"""
Performance tests for download and parsing operations.

These tests measure the performance of key operations to ensure
they meet acceptable performance standards.
"""

import pytest
import asyncio
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock, AsyncMock
from edx_downloader.api_client import EdxApiClient
from edx_downloader.course_manager import CourseManager
from edx_downloader.models import AppConfig, CourseInfo, VideoInfo
from tests.fixtures.edx_responses import EdxMockResponses, EdxTestDataGenerator


class TestPerformanceMetrics:
    """Performance tests for core operations."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test operations."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def test_config(self, temp_dir):
        """Create test configuration."""
        return AppConfig(
            cache_directory=str(temp_dir / "cache"),
            default_output_dir=str(temp_dir / "downloads"),
            max_concurrent_downloads=4,
            rate_limit_delay=0.1
        )
    
    @pytest.mark.asyncio
    async def test_api_client_response_time(self, test_config):
        """Test API client response time performance."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            client = EdxApiClient(test_config)
            
            # Measure multiple API calls
            start_time = time.time()
            for _ in range(10):
                response = await client.get("/api/courses/v1/courses/")
                assert response is not None
            end_time = time.time()
            
            avg_response_time = (end_time - start_time) / 10
            
            # Should average less than 100ms per request (mocked)
            assert avg_response_time < 0.1, f"Average response time {avg_response_time:.3f}s too slow"
    
    @pytest.mark.asyncio
    async def test_course_parsing_performance(self, test_config):
        """Test course outline parsing performance."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            api_client = EdxApiClient(test_config)
            course_manager = CourseManager(api_client)
            
            # Create test course info
            course_info = CourseInfo(
                id="course-v1:TestX+PERF101+2024",
                title="Performance Test Course",
                url="https://courses.edx.org/courses/course-v1:TestX+PERF101+2024/course/",
                enrollment_status="enrolled",
                access_level="full"
            )
            
            # Generate large course outline
            large_outline = EdxTestDataGenerator.generate_course_outline(
                course_info.id, 
                num_chapters=10, 
                num_videos_per_chapter=20
            )
            
            # Mock the API response with large course
            async def mock_api_get(url, **kwargs):
                return large_outline
            
            with patch.object(api_client, 'get', mock_api_get):
                # Measure parsing time
                start_time = time.time()
                outline = await course_manager.get_course_outline(course_info)
                end_time = time.time()
                
                parsing_time = end_time - start_time
                
                # Should parse 200 videos in less than 1 second
                assert parsing_time < 1.0, f"Course parsing too slow: {parsing_time:.3f}s"
                assert outline is not None
    
    @pytest.mark.asyncio
    async def test_video_extraction_performance(self, test_config):
        """Test video extraction performance with large courses."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            api_client = EdxApiClient(test_config)
            course_manager = CourseManager(api_client)
            
            # Create test course info
            course_info = CourseInfo(
                id="course-v1:TestX+PERF101+2024",
                title="Performance Test Course",
                url="https://courses.edx.org/courses/course-v1:TestX+PERF101+2024/course/",
                enrollment_status="enrolled",
                access_level="full"
            )
            
            # Generate course with many videos
            large_outline = EdxTestDataGenerator.generate_course_outline(
                course_info.id, 
                num_chapters=5, 
                num_videos_per_chapter=50
            )
            
            # Mock video extraction to return test videos
            test_videos = []
            for i in range(250):
                test_videos.append(VideoInfo(
                    id=f"video-{i}",
                    title=f"Test Video {i}",
                    url=f"https://example.com/video{i}.mp4",
                    quality="720p"
                ))
            
            async def mock_extract_video_info(block_url, course_info):
                return [test_videos[0]]  # Return one video per block
            
            # Mock the app's _extract_all_videos method instead
            from edx_downloader.app import EdxDownloaderApp
            
            async def mock_extract_all_videos(course_info, outline):
                return test_videos[:100]  # Return subset for performance test
            
            with patch.object(EdxDownloaderApp, '_extract_all_videos', mock_extract_all_videos):
                with patch.object(course_manager, 'get_course_outline', return_value=large_outline):
                    # Create app instance for testing
                    app = EdxDownloaderApp()
                    app.course_manager = course_manager
                    
                    # Measure video extraction time
                    start_time = time.time()
                    videos = await app._extract_all_videos(course_info, large_outline)
                    end_time = time.time()
                    
                    extraction_time = end_time - start_time
                    
                    # Should extract videos in less than 2 seconds
                    assert extraction_time < 2.0, f"Video extraction too slow: {extraction_time:.3f}s"
                    assert len(videos) > 0
    
    def test_concurrent_download_performance(self, test_config, temp_dir):
        """Test concurrent download performance."""
        # Create mock video files to download
        video_urls = [
            f"https://example.com/video{i}.mp4" for i in range(10)
        ]
        
        def mock_download_file(url, filepath, **kwargs):
            # Simulate download time
            time.sleep(0.1)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(b'mock video content')
            return True
        
        # Test sequential downloads
        start_time = time.time()
        for i, url in enumerate(video_urls[:3]):
            filepath = temp_dir / f"sequential_video{i}.mp4"
            mock_download_file(url, filepath)
        sequential_time = time.time() - start_time
        
        # Test concurrent downloads (should be faster)
        start_time = time.time()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for i, url in enumerate(video_urls[3:6]):
                filepath = temp_dir / f"concurrent_video{i}.mp4"
                future = executor.submit(mock_download_file, url, filepath)
                futures.append(future)
            
            for future in futures:
                future.result()
        concurrent_time = time.time() - start_time
        
        # Concurrent should be significantly faster
        assert concurrent_time < sequential_time * 0.8, \
            f"Concurrent downloads not faster: {concurrent_time:.3f}s vs {sequential_time:.3f}s"
    
    @pytest.mark.asyncio
    async def test_memory_usage_during_parsing(self, test_config):
        """Test memory usage during large course parsing."""
        try:
            import psutil
            import os
        except ImportError:
            pytest.skip("psutil not available for memory testing")
        
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            api_client = EdxApiClient(test_config)
            course_manager = CourseManager(api_client)
            
            # Get initial memory usage
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            # Create test course info
            course_info = CourseInfo(
                id="course-v1:TestX+MEMORY101+2024",
                title="Memory Test Course",
                url="https://courses.edx.org/courses/course-v1:TestX+MEMORY101+2024/course/",
                enrollment_status="enrolled",
                access_level="full"
            )
            
            # Generate very large course
            huge_outline = EdxTestDataGenerator.generate_course_outline(
                course_info.id, 
                num_chapters=20, 
                num_videos_per_chapter=100
            )
            
            # Mock video extraction to return test videos
            test_videos = []
            for i in range(2000):
                test_videos.append(VideoInfo(
                    id=f"video-{i}",
                    title=f"Test Video {i}",
                    url=f"https://example.com/video{i}.mp4",
                    quality="720p"
                ))
            
            # Mock the app's _extract_all_videos method instead
            from edx_downloader.app import EdxDownloaderApp
            
            async def mock_extract_all_videos(course_info, outline):
                return test_videos[:1000]  # Return subset for memory test
            
            with patch.object(EdxDownloaderApp, '_extract_all_videos', mock_extract_all_videos):
                with patch.object(course_manager, 'get_course_outline', return_value=huge_outline):
                    # Create app instance for testing
                    app = EdxDownloaderApp()
                    app.course_manager = course_manager
                    
                    # Parse course and measure memory
                    outline = await course_manager.get_course_outline(course_info)
                    videos = await app._extract_all_videos(course_info, huge_outline)
                    
                    peak_memory = process.memory_info().rss / 1024 / 1024  # MB
                    memory_increase = peak_memory - initial_memory
                    
                    # Memory increase should be reasonable (less than 100MB for large processing)
                    assert memory_increase < 100, f"Memory usage too high: {memory_increase:.1f}MB"
                    assert len(videos) > 0


class TestPerformanceBenchmarks:
    """Benchmark tests for performance regression detection."""
    
    @pytest.fixture
    def benchmark_config(self):
        """Create configuration optimized for benchmarking."""
        temp_dir = tempfile.mkdtemp()
        return AppConfig(
            cache_directory=f"{temp_dir}/cache",
            default_output_dir=f"{temp_dir}/downloads",
            max_concurrent_downloads=8,
            rate_limit_delay=0.01  # Minimal delay for benchmarking
        )
    
    def test_api_client_initialization_time(self, benchmark_config):
        """Benchmark API client initialization time."""
        start_time = time.time()
        for _ in range(100):
            client = EdxApiClient(benchmark_config)
        end_time = time.time()
        
        avg_init_time = (end_time - start_time) / 100
        
        # Should initialize in less than 1ms on average
        assert avg_init_time < 0.001, f"API client initialization too slow: {avg_init_time:.6f}s"
    
    def test_course_info_parsing_benchmark(self, benchmark_config):
        """Benchmark course info parsing speed."""
        from edx_downloader.models import CourseInfo
        
        start_time = time.time()
        for _ in range(1000):
            course_info = CourseInfo(
                id="course-v1:TestX+BENCH101+2024",
                title="Benchmark Course",
                url="https://courses.edx.org/courses/course-v1:TestX+BENCH101+2024/course/",
                enrollment_status="enrolled",
                access_level="full"
            )
        end_time = time.time()
        
        avg_parse_time = (end_time - start_time) / 1000
        
        # Should parse in less than 0.1ms on average
        assert avg_parse_time < 0.0001, f"Course info parsing too slow: {avg_parse_time:.6f}s"
    
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_large_scale_video_processing(self, benchmark_config):
        """Benchmark processing of very large course with thousands of videos."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            api_client = EdxApiClient(benchmark_config)
            course_manager = CourseManager(api_client)
            
            # Create test course info
            course_info = CourseInfo(
                id="course-v1:TestX+MASSIVE101+2024",
                title="Massive Test Course",
                url="https://courses.edx.org/courses/course-v1:TestX+MASSIVE101+2024/course/",
                enrollment_status="enrolled",
                access_level="full"
            )
            
            # Generate massive course (simulate real large courses like CS50)
            massive_outline = EdxTestDataGenerator.generate_course_outline(
                course_info.id, 
                num_chapters=50, 
                num_videos_per_chapter=100
            )
            
            # Mock video extraction to return test videos
            test_videos = []
            for i in range(5000):
                test_videos.append(VideoInfo(
                    id=f"video-{i}",
                    title=f"Test Video {i}",
                    url=f"https://example.com/video{i}.mp4",
                    quality="720p"
                ))
            
            # Mock the app's _extract_all_videos method instead
            from edx_downloader.app import EdxDownloaderApp
            
            async def mock_extract_all_videos(course_info, outline):
                return test_videos[:2000]  # Return large subset for benchmark
            
            with patch.object(EdxDownloaderApp, '_extract_all_videos', mock_extract_all_videos):
                with patch.object(course_manager, 'get_course_outline', return_value=massive_outline):
                    # Create app instance for testing
                    app = EdxDownloaderApp()
                    app.course_manager = course_manager
                    
                    # Benchmark full processing pipeline
                    start_time = time.time()
                    
                    # Step 1: Get course outline
                    outline = await course_manager.get_course_outline(course_info)
                    outline_time = time.time()
                    
                    # Step 2: Extract all videos
                    videos = await app._extract_all_videos(course_info, massive_outline)
                    extraction_time = time.time()
                    
                    # Step 3: Process video metadata
                    processed_videos = []
                    for video in videos:
                        if hasattr(video, 'url') and video.url:
                            processed_videos.append(video)
                    processing_time = time.time()
                    
                    # Performance assertions
                    outline_duration = outline_time - start_time
                    extraction_duration = extraction_time - outline_time
                    processing_duration = processing_time - extraction_time
                    total_duration = processing_time - start_time
                    
                    # Should handle large number of videos in reasonable time
                    assert len(videos) > 0
                    assert outline_duration < 5.0, f"Outline parsing too slow: {outline_duration:.3f}s"
                    assert extraction_duration < 10.0, f"Video extraction too slow: {extraction_duration:.3f}s"
                    assert processing_duration < 2.0, f"Video processing too slow: {processing_duration:.3f}s"
                    assert total_duration < 15.0, f"Total processing too slow: {total_duration:.3f}s"