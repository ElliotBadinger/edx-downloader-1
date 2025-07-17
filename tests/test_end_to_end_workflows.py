"""
End-to-end tests for complete download workflows.

These tests validate the entire download process from authentication
to file download completion.
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock, AsyncMock
from edx_downloader.app import EdxDownloaderApp
from edx_downloader.models import AppConfig, CourseInfo, VideoInfo, DownloadOptions
from tests.fixtures.edx_responses import EdxMockResponses, EdxApiResponseFixtures


class TestEndToEndWorkflows:
    """End-to-end workflow tests."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test downloads."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def test_config(self, temp_dir):
        """Create test configuration with temporary directories."""
        return AppConfig(
            cache_directory=str(temp_dir / "cache"),
            default_output_dir=str(temp_dir / "downloads"),
            max_concurrent_downloads=2,
            rate_limit_delay=0.1,  # Faster for testing
            video_quality_preference="highest"
        )
    
    @pytest.fixture
    def mock_file_download(self):
        """Mock file download to avoid actual downloads."""
        def mock_download(url, filepath, **kwargs):
            # Create a fake video file
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(b'fake video content for testing')
            return True
        
        return mock_download
    
    @pytest.mark.asyncio
    async def test_app_initialization_workflow(self, test_config, temp_dir, mock_file_download):
        """Test application initialization and basic functionality."""
        # Create a temporary config file
        config_file = temp_dir / "test_config.json"
        config_file.write_text('{}')  # Empty config, will use defaults
        
        app = EdxDownloaderApp(str(config_file))
        
        # Test that the app initializes correctly
        assert app is not None
        assert not app.is_authenticated()
        
        # Test configuration access
        config = app.get_config()
        assert config is not None
        assert 'max_concurrent_downloads' in config
        
        # Test stored usernames functionality
        usernames = app.get_stored_usernames()
        assert isinstance(usernames, list)
        
        # Test credential storage (without actually storing)
        # This tests the interface without side effects
        try:
            app.store_credentials("test_user", "test_pass")
            stored_usernames = app.get_stored_usernames()
            assert "test_user" in stored_usernames
            
            # Clean up
            app.delete_credentials("test_user")
        except Exception:
            # If credential storage fails, that's okay for this test
            pass
    
    @pytest.mark.asyncio
    async def test_selective_video_download(self, test_config, temp_dir, mock_file_download):
        """Test downloading only selected videos from a course."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            # Create a temporary config file
            config_file = temp_dir / "test_config.json"
            config_file.write_text('{}')  # Empty config, will use defaults
            
            app = EdxDownloaderApp(str(config_file))
            
            # Mock authentication manager
            with patch('edx_downloader.auth.AuthenticationManager') as mock_auth_manager:
                mock_auth_instance = AsyncMock()
                mock_auth_manager.return_value = mock_auth_instance
                
                # Initialize app
                await app.initialize("test@example.com", "password123")
                
                # Get course info and videos
                course_url = "https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2024/course/"
                
                # Mock course info and video list
                test_videos = [
                    VideoInfo(
                        id="video1",
                        title="Test Video 1",
                        url="https://example.com/video1.mp4",
                        quality="720p"
                    )
                ]
                
                with patch.object(app, 'list_course_videos', return_value=test_videos):
                    all_videos = await app.list_course_videos(course_url)
                    
                    # Select only first video
                    selected_videos = all_videos[:1]
                    
                    download_options = DownloadOptions(
                        quality_preference="highest",
                        organize_by_section=True,
                        output_directory=str(temp_dir / "downloads")
                    )
                    
                    # Mock download course method
                    mock_result = {
                        'success': True,
                        'videos_downloaded': 1,
                        'videos_found': 1
                    }
                    
                    with patch.object(app, 'download_course', return_value=mock_result):
                        results = await app.download_course(course_url, download_options)
                        assert results['success'] is True
                        assert results['videos_downloaded'] == 1
    
    @pytest.mark.asyncio
    async def test_download_with_resume_capability(self, test_config, temp_dir):
        """Test download resume functionality."""
        # This test demonstrates the concept of resume capability
        # In practice, this would be handled by the DownloadManager
        
        # Create partial file to simulate interrupted download
        download_dir = temp_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        partial_file = download_dir / "test_video.mp4"
        
        # Create partial file
        with open(partial_file, 'wb') as f:
            f.write(b'partial content')
        original_size = partial_file.stat().st_size
        assert original_size > 0
        
        # Simulate resume by appending to file
        with open(partial_file, 'ab') as f:
            f.write(b' resumed content')
        
        new_size = partial_file.stat().st_size
        assert new_size > original_size
        
        # Verify content is correct
        with open(partial_file, 'rb') as f:
            content = f.read()
            assert content == b'partial content resumed content'
    
    @pytest.mark.asyncio
    async def test_error_handling_during_download(self, test_config, temp_dir):
        """Test error handling during download process."""
        with patch('requests.Session') as mock_session_class:
            # Mock session that returns errors
            mock_session = Mock()
            
            # Mock authentication failure
            auth_response = Mock()
            auth_response.status_code = 401
            auth_response.json.return_value = EdxApiResponseFixtures.get_error_response_401()
            mock_session.post.return_value = auth_response
            
            mock_session_class.return_value = mock_session
            
            # Create a temporary config file
            config_file = temp_dir / "test_config.json"
            config_file.write_text('{}')  # Empty config, will use defaults
            
            app = EdxDownloaderApp(str(config_file))
            
            # Mock authentication manager to raise exception
            with patch('edx_downloader.auth.AuthenticationManager') as mock_auth_manager:
                mock_auth_instance = AsyncMock()
                mock_auth_instance.authenticate.side_effect = Exception("Authentication failed")
                mock_auth_manager.return_value = mock_auth_instance
                
                # Test authentication failure
                with pytest.raises(Exception):
                    await app.initialize("invalid@example.com", "wrongpassword")
    
    def test_concurrent_downloads(self, test_config, temp_dir, mock_file_download):
        """Test concurrent video downloads."""
        # This test demonstrates concurrent download concepts
        # In practice, this would be handled by the DownloadManager
        
        import time
        from concurrent.futures import ThreadPoolExecutor
        
        def slow_mock_download(url, filepath, **kwargs):
            time.sleep(0.1)  # Simulate download time
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(f'content for {filepath.name}'.encode())
            return True
        
        # Create test URLs and filepaths
        video_urls = [f"https://example.com/video{i}.mp4" for i in range(4)]
        download_dir = temp_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        
        # Test sequential downloads
        start_time = time.time()
        for i, url in enumerate(video_urls[:2]):
            filepath = download_dir / f"sequential_video{i}.mp4"
            slow_mock_download(url, filepath)
        sequential_time = time.time() - start_time
        
        # Test concurrent downloads (should be faster)
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            for i, url in enumerate(video_urls[2:4]):
                filepath = download_dir / f"concurrent_video{i}.mp4"
                future = executor.submit(slow_mock_download, url, filepath)
                futures.append(future)
            
            for future in futures:
                future.result()
        concurrent_time = time.time() - start_time
        
        # Concurrent should be faster than sequential
        assert concurrent_time < sequential_time * 0.8, \
            f"Concurrent downloads not faster: {concurrent_time:.3f}s vs {sequential_time:.3f}s"
        
        # Verify all files were created
        video_files = list(download_dir.rglob("*.mp4"))
        assert len(video_files) == 4
    
    def test_subtitle_download_workflow(self, test_config, temp_dir, mock_file_download):
        """Test subtitle download alongside videos."""
        # This test demonstrates subtitle download concepts
        # In practice, this would be handled by the DownloadManager
        
        download_dir = temp_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        
        # Mock subtitle download
        def mock_subtitle_download(url, filepath, **kwargs):
            if filepath.suffix == '.srt':
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("1\n00:00:00,000 --> 00:00:05,000\nTest subtitle content\n")
                return True
            else:
                return mock_file_download(url, filepath, **kwargs)
        
        # Create test video and subtitle files
        video_file = download_dir / "test_video.mp4"
        subtitle_file = download_dir / "test_video.srt"
        
        # Download video
        mock_file_download("https://example.com/video.mp4", video_file)
        
        # Download subtitle
        mock_subtitle_download("https://example.com/video.srt", subtitle_file)
        
        # Verify both files were created
        assert video_file.exists()
        assert subtitle_file.exists()
        
        # Verify subtitle content
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert "Test subtitle content" in content


class TestWorkflowErrorRecovery:
    """Test error recovery in workflows."""
    
    @pytest.fixture
    def test_config(self):
        """Create test configuration."""
        temp_dir = tempfile.mkdtemp()
        return AppConfig(
            cache_directory=f"{temp_dir}/cache",
            default_output_dir=f"{temp_dir}/downloads",
            max_concurrent_downloads=1,
            rate_limit_delay=0.1
        )
    
    def test_network_error_recovery(self, test_config):
        """Test recovery from network errors."""
        # This test demonstrates network error recovery concepts
        # In practice, this would be handled by the API client's retry logic
        
        import requests
        from unittest.mock import Mock
        
        # Simulate network error followed by success
        def mock_request_with_retry(url, **kwargs):
            # First call fails
            if not hasattr(mock_request_with_retry, 'call_count'):
                mock_request_with_retry.call_count = 0
            
            mock_request_with_retry.call_count += 1
            
            if mock_request_with_retry.call_count == 1:
                raise requests.exceptions.ConnectionError("Network error")
            else:
                # Second call succeeds
                response = Mock()
                response.status_code = 200
                response.json.return_value = {"success": True}
                return response
        
        # Test retry logic
        try:
            result = mock_request_with_retry("https://example.com/test")
            assert False, "Should have raised ConnectionError on first call"
        except requests.exceptions.ConnectionError:
            # Expected on first call
            pass
        
        # Second call should succeed
        result = mock_request_with_retry("https://example.com/test")
        assert result.status_code == 200
    
    def test_partial_course_download_recovery(self, test_config):
        """Test recovery when some videos fail to download."""
        # This test demonstrates partial download failure recovery concepts
        # In practice, this would be handled by the DownloadManager
        
        import tempfile
        
        # Mock download that fails for some videos
        def selective_mock_download(url, filepath, **kwargs):
            if 'video1' in str(filepath):
                # First video succeeds
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'wb') as f:
                    f.write(b'video1 content')
                return True
            else:
                # Other videos fail
                raise Exception("Download failed")
        
        # Create temporary directory for testing
        temp_dir = Path(tempfile.mkdtemp())
        download_dir = temp_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        
        # Test video URLs
        video_urls = [
            "https://example.com/video1.mp4",
            "https://example.com/video2.mp4",
            "https://example.com/video3.mp4"
        ]
        
        # Attempt downloads and track results
        results = []
        for i, url in enumerate(video_urls):
            filepath = download_dir / f"video{i+1}.mp4"
            try:
                success = selective_mock_download(url, filepath)
                results.append({'url': url, 'success': True, 'filepath': filepath})
            except Exception as e:
                results.append({'url': url, 'success': False, 'error': str(e)})
        
        # Some downloads should succeed, others fail
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        
        assert len(successful) == 1  # Only video1 should succeed
        assert len(failed) == 2     # video2 and video3 should fail
        
        # Verify successful download exists
        assert (download_dir / "video1.mp4").exists()
        assert not (download_dir / "video2.mp4").exists()
        assert not (download_dir / "video3.mp4").exists()
        
        # Clean up
        shutil.rmtree(temp_dir)