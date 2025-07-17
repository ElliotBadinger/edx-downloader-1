"""Unit tests for download manager."""

import pytest
import asyncio
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from edx_downloader.download_manager import (
    DownloadManager, DownloadProgress, CourseDownloadProgress
)
from edx_downloader.models import VideoInfo, CourseInfo, DownloadOptions
from edx_downloader.exceptions import (
    DownloadError, DiskSpaceError, FilePermissionError, DownloadInterruptedError
)


class TestDownloadProgress:
    """Test download progress functionality."""
    
    def test_progress_percent(self):
        """Test progress percentage calculation."""
        progress = DownloadProgress(
            video_id="test-video",
            filename="test.mp4",
            total_size=1000,
            downloaded_size=250
        )
        
        assert progress.progress_percent == 25.0
        
        # Test zero total size
        progress.total_size = 0
        assert progress.progress_percent == 0.0
    
    def test_is_complete(self):
        """Test completion status."""
        progress = DownloadProgress(
            video_id="test-video",
            filename="test.mp4",
            status="completed"
        )
        
        assert progress.is_complete is True
        
        progress.status = "downloading"
        assert progress.is_complete is False
    
    def test_is_failed(self):
        """Test failure status."""
        progress = DownloadProgress(
            video_id="test-video",
            filename="test.mp4",
            status="failed"
        )
        
        assert progress.is_failed is True
        
        progress.status = "completed"
        assert progress.is_failed is False


class TestCourseDownloadProgress:
    """Test course download progress functionality."""
    
    def test_progress_percent(self):
        """Test course progress percentage calculation."""
        progress = CourseDownloadProgress(
            course_id="test-course",
            course_title="Test Course",
            total_size=2000,
            downloaded_size=500
        )
        
        assert progress.progress_percent == 25.0
        
        # Test zero total size
        progress.total_size = 0
        assert progress.progress_percent == 0.0
    
    def test_is_complete(self):
        """Test course completion status."""
        progress = CourseDownloadProgress(
            course_id="test-course",
            course_title="Test Course",
            total_videos=5,
            completed_videos=5
        )
        
        assert progress.is_complete is True
        
        progress.completed_videos = 3
        assert progress.is_complete is False
    
    def test_success_rate(self):
        """Test success rate calculation."""
        progress = CourseDownloadProgress(
            course_id="test-course",
            course_title="Test Course",
            total_videos=10,
            failed_videos=2
        )
        
        assert progress.success_rate == 80.0
        
        # Test zero total videos
        progress.total_videos = 0
        assert progress.success_rate == 0.0


class TestDownloadManager:
    """Test download manager functionality."""
    
    def setup_method(self):
        """Set up test download manager."""
        self.temp_dir = tempfile.mkdtemp()
        self.options = DownloadOptions(
            output_directory=self.temp_dir,
            concurrent_downloads=2,
            resume_enabled=True
        )
        self.progress_callback = Mock()
        
        self.course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        self.video_info = VideoInfo(
            id="test-video",
            title="Test Video",
            url="https://example.com/video.mp4",
            quality="720p",
            size=1000000,
            duration=300,
            format="mp4"
        )
    
    def test_init(self):
        """Test download manager initialization."""
        manager = DownloadManager(self.options, self.progress_callback)
        
        assert manager.options == self.options
        assert manager.progress_callback == self.progress_callback
        assert manager.download_semaphore._value == 2
        assert manager.output_path == Path(self.temp_dir)
        assert manager.output_path.exists()
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager functionality."""
        manager = DownloadManager(self.options)
        
        async with manager:
            assert manager.session is not None
        
        # Session should be closed after exit
        assert manager.session.closed
    
    def test_create_safe_filename(self):
        """Test safe filename creation."""
        manager = DownloadManager(self.options)
        
        # Test normal filename
        video = VideoInfo(
            id="test",
            title="Normal Video",
            url="https://example.com/video.mp4",
            quality="720p",
            format="mp4"
        )
        filename = manager._create_safe_filename(video)
        assert filename == "Normal Video.mp4"
        
        # Test filename with invalid characters
        video.title = 'Video with <invalid> chars: "test"'
        filename = manager._create_safe_filename(video)
        assert filename == "Video with _invalid_ chars_ _test_.mp4"
        
        # Test very long filename
        video.title = "A" * 250
        filename = manager._create_safe_filename(video)
        assert len(filename) <= 204  # 200 + ".mp4"
    
    def test_sanitize_filename(self):
        """Test filename sanitization."""
        manager = DownloadManager(self.options)
        
        # Test invalid characters
        result = manager._sanitize_filename('file<>:"/\\|?*name')
        assert result == "file_________name"
        
        # Test leading/trailing spaces and dots
        result = manager._sanitize_filename("  .filename.  ")
        assert result == "filename"
        
        # Test empty result
        result = manager._sanitize_filename("   ")
        assert result == "video"
    
    def test_create_course_directory(self):
        """Test course directory creation."""
        manager = DownloadManager(self.options)
        
        course_dir = manager._create_course_directory(self.course_info)
        
        assert course_dir.exists()
        assert course_dir.name == "Test Course"
        assert course_dir.parent == Path(self.temp_dir)
    
    def test_filter_existing_videos(self):
        """Test filtering of existing videos."""
        manager = DownloadManager(self.options)
        
        videos = [
            VideoInfo(id="1", title="Video 1", url="https://example.com/1.mp4", 
                     quality="720p", format="mp4"),
            VideoInfo(id="2", title="Video 2", url="https://example.com/2.mp4", 
                     quality="720p", format="mp4"),
        ]
        
        output_dir = Path(self.temp_dir)
        
        # Create one existing file
        existing_file = output_dir / "Video 1.mp4"
        existing_file.write_text("existing content")
        
        filtered = manager._filter_existing_videos(videos, output_dir)
        
        # Should only return the non-existing video
        assert len(filtered) == 1
        assert filtered[0].id == "2"
    
    def test_filter_existing_videos_resume_disabled(self):
        """Test filtering when resume is disabled."""
        options = DownloadOptions(
            output_directory=self.temp_dir,
            resume_enabled=False
        )
        manager = DownloadManager(options)
        
        videos = [
            VideoInfo(id="1", title="Video 1", url="https://example.com/1.mp4", 
                     quality="720p", format="mp4"),
        ]
        
        # Should return all videos when resume is disabled
        filtered = manager._filter_existing_videos(videos, Path(self.temp_dir))
        assert len(filtered) == 1
    
    @pytest.mark.asyncio
    async def test_get_content_size(self):
        """Test getting content size from URL."""
        manager = DownloadManager(self.options)
        
        # Mock session
        mock_response = AsyncMock()
        mock_response.headers = {'content-length': '1000000'}
        
        mock_session = AsyncMock()
        mock_session.head.return_value.__aenter__.return_value = mock_response
        
        manager.session = mock_session
        
        size = await manager._get_content_size("https://example.com/video.mp4")
        assert size == 1000000
    
    @pytest.mark.asyncio
    async def test_get_content_size_fallback(self):
        """Test content size fallback method."""
        manager = DownloadManager(self.options)
        
        # Mock HEAD request failure, GET request success
        mock_head_response = AsyncMock()
        mock_head_response.headers = {}
        
        mock_get_response = AsyncMock()
        mock_get_response.headers = {'content-range': 'bytes 0-0/1000000'}
        
        mock_session = AsyncMock()
        mock_session.head.return_value.__aenter__.return_value = mock_head_response
        mock_session.get.return_value.__aenter__.return_value = mock_get_response
        
        manager.session = mock_session
        
        size = await manager._get_content_size("https://example.com/video.mp4")
        assert size == 1000000
    
    @pytest.mark.asyncio
    async def test_get_video_sizes(self):
        """Test getting sizes for multiple videos."""
        manager = DownloadManager(self.options)
        
        videos = [
            VideoInfo(id="1", title="Video 1", url="https://example.com/1.mp4", 
                     quality="720p", format="mp4"),
            VideoInfo(id="2", title="Video 2", url="https://example.com/2.mp4", 
                     quality="720p", format="mp4", size=500000),  # Already has size
        ]
        
        with patch.object(manager, '_get_content_size', return_value=1000000):
            await manager._get_video_sizes(videos)
        
        assert videos[0].size == 1000000
        assert videos[1].size == 500000  # Should not change
    
    def test_check_disk_space_sufficient(self):
        """Test disk space check with sufficient space."""
        manager = DownloadManager(self.options)
        
        with patch('shutil.disk_usage') as mock_disk_usage:
            mock_disk_usage.return_value = Mock(free=10 * 1024**3)  # 10 GB free
            
            # Should not raise exception
            manager._check_disk_space(Path(self.temp_dir), 1024**3)  # 1 GB required
    
    def test_check_disk_space_insufficient(self):
        """Test disk space check with insufficient space."""
        manager = DownloadManager(self.options)
        
        with patch('shutil.disk_usage') as mock_disk_usage:
            mock_disk_usage.return_value = Mock(free=500 * 1024**2)  # 500 MB free
            
            with pytest.raises(DiskSpaceError, match="Insufficient disk space"):
                manager._check_disk_space(Path(self.temp_dir), 2 * 1024**3)  # 2 GB required
    
    def test_load_resume_data_no_file(self):
        """Test loading resume data when file doesn't exist."""
        manager = DownloadManager(self.options)
        
        # Resume file shouldn't exist initially
        resume_data = manager._load_resume_data()
        assert resume_data == {}
    
    def test_load_resume_data_with_file(self):
        """Test loading resume data from existing file."""
        manager = DownloadManager(self.options)
        
        # Create resume data file
        resume_data = {'test': 'data'}
        with open(manager.resume_data_file, 'w') as f:
            json.dump(resume_data, f)
        
        loaded_data = manager._load_resume_data()
        assert loaded_data == resume_data
    
    def test_save_resume_data(self):
        """Test saving resume data."""
        manager = DownloadManager(self.options)
        
        # Add some active downloads
        manager.active_downloads['video1'] = DownloadProgress(
            video_id='video1',
            filename='test.mp4',
            total_size=1000,
            downloaded_size=500,
            status='downloading'
        )
        
        manager._save_resume_data()
        
        # Check file was created and contains data
        assert manager.resume_data_file.exists()
        
        with open(manager.resume_data_file, 'r') as f:
            data = json.load(f)
        
        assert 'active_downloads' in data
        assert 'video1' in data['active_downloads']
        assert data['active_downloads']['video1']['downloaded_size'] == 500
    
    def test_get_download_statistics(self):
        """Test download statistics calculation."""
        manager = DownloadManager(self.options)
        
        # Add some download progress
        manager.active_downloads['video1'] = DownloadProgress(
            video_id='video1',
            filename='test1.mp4',
            total_size=1000,
            downloaded_size=1000,
            status='completed'
        )
        
        manager.active_downloads['video2'] = DownloadProgress(
            video_id='video2',
            filename='test2.mp4',
            total_size=2000,
            downloaded_size=500,
            status='downloading'
        )
        
        manager.active_downloads['video3'] = DownloadProgress(
            video_id='video3',
            filename='test3.mp4',
            total_size=1000,
            downloaded_size=0,
            status='failed'
        )
        
        stats = manager.get_download_statistics()
        
        assert stats['total_downloads'] == 3
        assert stats['completed'] == 1
        assert stats['failed'] == 1
        assert stats['success_rate'] == pytest.approx(33.33, rel=1e-2)
        assert stats['progress_percent'] == 37.5  # 1500/4000 * 100
    
    @pytest.mark.asyncio
    async def test_download_video_success(self):
        """Test successful video download."""
        manager = DownloadManager(self.options)
        
        # Mock the download process
        with patch.object(manager, '_get_content_size', return_value=1000), \
             patch.object(manager, '_download_file') as mock_download:
            
            async with manager:
                progress = await manager.download_video(self.video_info, Path(self.temp_dir))
            
            assert progress.status == "completed"
            assert progress.video_id == "test-video"
            mock_download.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_download_video_already_exists(self):
        """Test download when file already exists."""
        options = DownloadOptions(
            output_directory=self.temp_dir,
            resume_enabled=False
        )
        manager = DownloadManager(options)
        
        # Create existing file
        existing_file = Path(self.temp_dir) / "Test Video.mp4"
        existing_file.write_text("existing content")
        
        async with manager:
            progress = await manager.download_video(self.video_info, Path(self.temp_dir))
        
        assert progress.status == "completed"
        assert progress.downloaded_size == len("existing content")
    
    @pytest.mark.asyncio
    async def test_download_video_failure(self):
        """Test video download failure."""
        manager = DownloadManager(self.options)
        
        # Mock download failure
        with patch.object(manager, '_get_content_size', return_value=1000), \
             patch.object(manager, '_download_file', side_effect=DownloadError("Network error")):
            
            async with manager:
                progress = await manager.download_video(self.video_info, Path(self.temp_dir))
            
            assert progress.status == "failed"
            assert "Network error" in progress.error
    
    @pytest.mark.asyncio
    async def test_download_course(self):
        """Test downloading entire course."""
        manager = DownloadManager(self.options)
        
        videos = [
            VideoInfo(id="1", title="Video 1", url="https://example.com/1.mp4", 
                     quality="720p", size=1000, format="mp4"),
            VideoInfo(id="2", title="Video 2", url="https://example.com/2.mp4", 
                     quality="720p", size=2000, format="mp4"),
        ]
        
        # Mock successful downloads
        with patch.object(manager, '_download_file'):
            async with manager:
                course_progress = await manager.download_course(self.course_info, videos)
        
        assert course_progress.course_id == "test-course"
        assert course_progress.total_videos == 2
        assert course_progress.total_size == 3000
        assert course_progress.is_complete
    
    @pytest.mark.asyncio
    async def test_download_course_with_failures(self):
        """Test course download with some failures."""
        manager = DownloadManager(self.options)
        
        videos = [
            VideoInfo(id="1", title="Video 1", url="https://example.com/1.mp4", 
                     quality="720p", size=1000, format="mp4"),
            VideoInfo(id="2", title="Video 2", url="https://example.com/2.mp4", 
                     quality="720p", size=2000, format="mp4"),
        ]
        
        # Mock one success, one failure
        def mock_download_side_effect(url, filepath, progress):
            if "1.mp4" in url:
                return  # Success
            else:
                raise DownloadError("Network error")
        
        with patch.object(manager, '_download_file', side_effect=mock_download_side_effect):
            async with manager:
                course_progress = await manager.download_course(self.course_info, videos)
        
        assert course_progress.completed_videos == 1
        assert course_progress.failed_videos == 1
        assert course_progress.success_rate == 50.0
    
    @pytest.mark.asyncio
    async def test_download_course_all_existing(self):
        """Test course download when all videos already exist."""
        manager = DownloadManager(self.options)
        
        videos = [
            VideoInfo(id="1", title="Video 1", url="https://example.com/1.mp4", 
                     quality="720p", format="mp4"),
        ]
        
        # Create course directory and existing file
        course_dir = manager._create_course_directory(self.course_info)
        existing_file = course_dir / "Video 1.mp4"
        existing_file.write_text("existing content")
        
        async with manager:
            course_progress = await manager.download_course(self.course_info, videos)
        
        assert course_progress.completed_videos == 1
        assert course_progress.is_complete
    
    @pytest.mark.asyncio
    async def test_write_chunks_with_progress(self):
        """Test writing chunks with progress tracking."""
        manager = DownloadManager(self.options)
        
        progress = DownloadProgress(
            video_id="test",
            filename="test.mp4",
            total_size=1000
        )
        
        # Mock response with chunks
        async def async_chunks():
            for chunk in [b"chunk1", b"chunk2", b"chunk3"]:
                yield chunk
        
        mock_response = AsyncMock()
        mock_response.content.iter_chunked.return_value = async_chunks()
        
        # Mock file
        mock_file = AsyncMock()
        
        await manager._write_chunks(mock_response, mock_file, progress)
        
        assert progress.downloaded_size == 18  # len("chunk1chunk2chunk3")
        assert mock_file.write.call_count == 3
    
    @pytest.mark.asyncio
    async def test_download_with_resume(self):
        """Test download with resume functionality."""
        manager = DownloadManager(self.options)
        
        # Create partial file
        filepath = Path(self.temp_dir) / "test.mp4"
        filepath.write_bytes(b"partial content")
        
        progress = DownloadProgress(
            video_id="test",
            filename="test.mp4",
            total_size=1000
        )
        
        # Mock session and response
        mock_response = AsyncMock()
        mock_response.status = 206  # Partial content
        mock_response.headers = {}
        async def async_chunks():
            yield b"more content"
        
        mock_response.content.iter_chunked.return_value = async_chunks()
        
        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response
        manager.session = mock_session
        
        await manager._download_file("https://example.com/test.mp4", filepath, progress)
        
        # Check that Range header was used
        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert 'Range' in call_args[1]['headers']
        assert call_args[1]['headers']['Range'] == 'bytes=15-'  # len("partial content")


class TestDownloadManagerIntegration:
    """Integration tests for download manager."""
    
    @pytest.mark.asyncio
    async def test_full_download_workflow(self):
        """Test complete download workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            options = DownloadOptions(
                output_directory=temp_dir,
                concurrent_downloads=1,
                resume_enabled=True
            )
            
            course_info = CourseInfo(
                id="integration-test",
                title="Integration Test Course",
                url="https://example.com/course",
                enrollment_status="enrolled",
                access_level="full"
            )
            
            videos = [
                VideoInfo(
                    id="video1",
                    title="Test Video 1",
                    url="https://httpbin.org/bytes/1000",  # Returns 1000 bytes
                    quality="720p",
                    format="mp4"
                )
            ]
            
            progress_updates = []
            
            def progress_callback(course_progress):
                progress_updates.append(course_progress)
            
            manager = DownloadManager(options, progress_callback)
            
            # Note: This test would require actual HTTP requests
            # In a real scenario, you'd mock the HTTP responses
            with patch.object(manager, '_download_file') as mock_download:
                async with manager:
                    course_progress = await manager.download_course(course_info, videos)
                
                assert course_progress.total_videos == 1
                assert len(progress_updates) >= 1
                mock_download.assert_called_once()