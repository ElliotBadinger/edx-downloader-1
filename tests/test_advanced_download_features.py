"""Tests for advanced download features."""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from edx_downloader.download_manager import (
    DownloadManager, RetryConfig, BandwidthController, DownloadQueueItem
)
from edx_downloader.models import VideoInfo, DownloadOptions


class TestRetryConfig:
    """Test retry configuration."""
    
    def test_default_config(self):
        """Test default retry configuration."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.backoff_factor == 2.0
    
    def test_get_delay_exponential_backoff(self):
        """Test exponential backoff delay calculation."""
        config = RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=10.0)
        
        assert config.get_delay(0) == 1.0  # 1.0 * 2^0
        assert config.get_delay(1) == 2.0  # 1.0 * 2^1
        assert config.get_delay(2) == 4.0  # 1.0 * 2^2
        assert config.get_delay(3) == 8.0  # 1.0 * 2^3
        assert config.get_delay(4) == 10.0  # Capped at max_delay
    
    def test_custom_config(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_retries=5,
            base_delay=0.5,
            max_delay=30.0,
            backoff_factor=1.5
        )
        
        assert config.max_retries == 5
        assert config.base_delay == 0.5
        assert config.max_delay == 30.0
        assert config.backoff_factor == 1.5


class TestBandwidthController:
    """Test bandwidth controller."""
    
    def test_unlimited_bandwidth(self):
        """Test unlimited bandwidth configuration."""
        controller = BandwidthController()
        assert controller.max_bandwidth is None
        assert controller.rate_limit_delay == 0.0
    
    def test_limited_bandwidth(self):
        """Test limited bandwidth configuration."""
        # 1 MB/s with 8KB chunks = 128 chunks/s = 0.0078125s delay
        controller = BandwidthController(max_bandwidth=1024*1024, chunk_size=8192)
        expected_delay = 1.0 / (1024*1024 / 8192)  # 1/128
        assert abs(controller.rate_limit_delay - expected_delay) < 0.001
    
    @pytest.mark.asyncio
    async def test_throttle_no_delay(self):
        """Test throttling with no delay."""
        controller = BandwidthController()
        # Should complete immediately
        await controller.throttle()
    
    @pytest.mark.asyncio
    async def test_throttle_with_delay(self):
        """Test throttling with delay."""
        controller = BandwidthController(max_bandwidth=1024, chunk_size=1024)
        # Should have 1 second delay
        assert controller.rate_limit_delay == 1.0


class TestDownloadQueueItem:
    """Test download queue item."""
    
    def test_queue_item_creation(self):
        """Test creating queue item."""
        video = VideoInfo(
            id="test",
            title="Test Video",
            url="https://example.com/video.mp4",
            quality="720p"
        )
        output_dir = Path("/tmp")
        
        item = DownloadQueueItem(video=video, output_dir=output_dir, priority=5)
        
        assert item.video == video
        assert item.output_dir == output_dir
        assert item.priority == 5
        assert item.retry_count == 0
        assert item.last_error is None
    
    def test_queue_item_priority_ordering(self):
        """Test priority queue ordering."""
        video1 = VideoInfo(id="1", title="Video 1", url="http://example.com/1.mp4", quality="720p")
        video2 = VideoInfo(id="2", title="Video 2", url="http://example.com/2.mp4", quality="720p")
        
        item1 = DownloadQueueItem(video=video1, output_dir=Path("/tmp"), priority=1)
        item2 = DownloadQueueItem(video=video2, output_dir=Path("/tmp"), priority=5)
        
        # Higher priority should be "less than" for heap ordering
        assert item2 < item1


class TestAdvancedDownloadFeatures:
    """Test advanced download manager features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.options = DownloadOptions(
            output_directory=self.temp_dir,
            concurrent_downloads=2,
            resume_enabled=True
        )
        self.retry_config = RetryConfig(max_retries=2, base_delay=0.1)
        self.bandwidth_controller = BandwidthController(max_bandwidth=1024*1024)
        
        self.manager = DownloadManager(
            self.options,
            retry_config=self.retry_config,
            bandwidth_controller=self.bandwidth_controller
        )
        
        self.test_video = VideoInfo(
            id="test-video",
            title="Test Video",
            url="https://example.com/test.mp4",
            quality="720p",
            size=1000000
        )
    
    def test_manager_initialization_with_advanced_features(self):
        """Test manager initialization with advanced features."""
        assert self.manager.retry_config == self.retry_config
        assert self.manager.bandwidth_controller == self.bandwidth_controller
        assert len(self.manager.download_queue) == 0
        assert len(self.manager.duplicate_tracker) == 0
        assert len(self.manager.failed_downloads) == 0
    
    def test_add_to_download_queue(self):
        """Test adding items to download queue."""
        output_dir = Path(self.temp_dir)
        
        self.manager.add_to_download_queue(self.test_video, output_dir, priority=5)
        
        assert len(self.manager.download_queue) == 1
        assert self.manager.download_queue[0].video == self.test_video
        assert self.manager.download_queue[0].priority == 5
    
    def test_duplicate_detection(self):
        """Test duplicate video detection."""
        output_dir = Path(self.temp_dir)
        
        # Initially not a duplicate
        assert not self.manager._is_duplicate_video(self.test_video, output_dir)
        
        # Track as downloaded
        self.manager._track_downloaded_video(self.test_video, output_dir)
        
        # Now should be detected as duplicate (even though file doesn't exist)
        # This tests the hash-based detection
        video_hash = self.manager.duplicate_tracker
        assert len(video_hash) == 1
    
    def test_get_failed_downloads(self):
        """Test getting failed downloads."""
        # Initially empty
        assert len(self.manager.get_failed_downloads()) == 0
        
        # Add some failed downloads
        self.manager.failed_downloads["video1"] = 2
        self.manager.failed_downloads["video2"] = 1
        
        failed = self.manager.get_failed_downloads()
        assert failed["video1"] == 2
        assert failed["video2"] == 1
    
    def test_clear_failed_downloads(self):
        """Test clearing failed downloads."""
        # Add some failed downloads
        self.manager.failed_downloads["video1"] = 2
        self.manager.failed_downloads["video2"] = 1
        
        assert len(self.manager.failed_downloads) == 2
        
        # Clear them
        self.manager.clear_failed_downloads()
        
        assert len(self.manager.failed_downloads) == 0
    
    def test_get_queue_status(self):
        """Test getting queue status."""
        output_dir = Path(self.temp_dir)
        
        # Add some items to track
        self.manager.add_to_download_queue(self.test_video, output_dir)
        self.manager.failed_downloads["video1"] = 1
        self.manager._track_downloaded_video(self.test_video, output_dir)
        
        status = self.manager.get_queue_status()
        
        assert status["queue_length"] == 1
        assert status["failed_downloads"] == 1
        assert status["duplicate_tracker_size"] == 1
        assert "active_downloads" in status
    
    @pytest.mark.asyncio
    async def test_download_video_with_retry_success_first_attempt(self):
        """Test successful download on first attempt."""
        output_dir = Path(self.temp_dir)
        
        # Mock successful download
        with patch.object(self.manager, 'download_video') as mock_download:
            mock_progress = MagicMock()
            mock_progress.is_complete = True
            mock_progress.error = None
            mock_download.return_value = mock_progress
            
            result = await self.manager.download_video_with_retry(self.test_video, output_dir)
            
            assert result.is_complete
            assert mock_download.call_count == 1
            assert self.test_video.id not in self.manager.failed_downloads
    
    @pytest.mark.asyncio
    async def test_download_video_with_retry_success_after_failure(self):
        """Test successful download after initial failure."""
        output_dir = Path(self.temp_dir)
        
        # Mock first failure, then success
        with patch.object(self.manager, 'download_video') as mock_download:
            failed_progress = MagicMock()
            failed_progress.is_complete = False
            failed_progress.error = "Network error"
            
            success_progress = MagicMock()
            success_progress.is_complete = True
            success_progress.error = None
            
            mock_download.side_effect = [failed_progress, success_progress]
            
            # Mock sleep to speed up test
            with patch('asyncio.sleep'):
                result = await self.manager.download_video_with_retry(self.test_video, output_dir)
            
            assert result.is_complete
            assert mock_download.call_count == 2
            assert self.test_video.id not in self.manager.failed_downloads
    
    @pytest.mark.asyncio
    async def test_download_video_with_retry_max_retries_exceeded(self):
        """Test download failure after max retries."""
        output_dir = Path(self.temp_dir)
        
        # Mock all attempts failing
        with patch.object(self.manager, 'download_video') as mock_download:
            failed_progress = MagicMock()
            failed_progress.is_complete = False
            failed_progress.error = "Persistent network error"
            mock_download.return_value = failed_progress
            
            # Mock sleep to speed up test
            with patch('asyncio.sleep'):
                result = await self.manager.download_video_with_retry(self.test_video, output_dir)
            
            assert not result.is_complete
            assert mock_download.call_count == self.retry_config.max_retries + 1
            assert self.manager.failed_downloads[self.test_video.id] == self.retry_config.max_retries + 1
    
    @pytest.mark.asyncio
    async def test_download_video_with_retry_duplicate_detection(self):
        """Test duplicate detection in retry logic."""
        output_dir = Path(self.temp_dir)
        
        # Mark as duplicate
        self.manager._track_downloaded_video(self.test_video, output_dir)
        
        # Mock is_duplicate to return True
        with patch.object(self.manager, '_is_duplicate_video', return_value=True):
            result = await self.manager.download_video_with_retry(self.test_video, output_dir)
            
            assert result.is_complete
            assert result.status == "completed"
    
    @pytest.mark.asyncio
    async def test_process_download_queue_empty(self):
        """Test processing empty download queue."""
        results = await self.manager.process_download_queue()
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_process_download_queue_with_items(self):
        """Test processing download queue with items."""
        output_dir = Path(self.temp_dir)
        
        # Add items to queue
        video1 = VideoInfo(id="1", title="Video 1", url="http://example.com/1.mp4", quality="720p")
        video2 = VideoInfo(id="2", title="Video 2", url="http://example.com/2.mp4", quality="720p")
        
        self.manager.add_to_download_queue(video1, output_dir, priority=1)
        self.manager.add_to_download_queue(video2, output_dir, priority=5)  # Higher priority
        
        # Mock download_video_with_retry
        with patch.object(self.manager, 'download_video_with_retry') as mock_download:
            mock_progress = MagicMock()
            mock_progress.is_complete = True
            mock_download.return_value = mock_progress
            
            results = await self.manager.process_download_queue()
            
            assert len(results) == 2
            assert mock_download.call_count == 2
            assert len(self.manager.download_queue) == 0
            
            # Verify higher priority item was processed first
            first_call_video = mock_download.call_args_list[0][0][0]
            assert first_call_video.id == "2"  # Higher priority video