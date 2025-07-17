"""Download management system for EDX course videos."""

import os
import asyncio
import aiohttp
import aiofiles
import logging
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import heapq
from collections import defaultdict

from .models import VideoInfo, CourseInfo, DownloadOptions
from .exceptions import DownloadError, DiskSpaceError, FilePermissionError, DownloadInterruptedError
from .logging_config import get_logger, log_with_context, performance_timer

logger = get_logger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_factor: float = 2.0
    
    def get_delay(self, attempt: int) -> float:
        """Get delay for retry attempt with exponential backoff."""
        delay = self.base_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)


@dataclass
class BandwidthController:
    """Controls download bandwidth and rate limiting."""
    
    max_bandwidth: Optional[int] = None  # bytes per second, None for unlimited
    chunk_size: int = 8192
    rate_limit_delay: float = 0.0  # seconds between chunks
    
    def __post_init__(self):
        """Calculate rate limiting parameters."""
        if self.max_bandwidth:
            # Calculate delay needed between chunks to maintain bandwidth limit
            chunks_per_second = self.max_bandwidth / self.chunk_size
            self.rate_limit_delay = 1.0 / chunks_per_second if chunks_per_second > 0 else 0.0
    
    async def throttle(self) -> None:
        """Apply rate limiting delay."""
        if self.rate_limit_delay > 0:
            await asyncio.sleep(self.rate_limit_delay)


@dataclass
class DownloadQueueItem:
    """Item in the download queue."""
    
    video: VideoInfo
    output_dir: Path
    priority: int = 0  # Higher number = higher priority
    retry_count: int = 0
    last_error: Optional[str] = None
    
    def __lt__(self, other):
        """Compare items for priority queue ordering."""
        return self.priority > other.priority  # Higher priority first


@dataclass
class DownloadProgress:
    """Progress information for a download."""
    
    video_id: str
    filename: str
    total_size: int = 0
    downloaded_size: int = 0
    speed: float = 0.0  # bytes per second
    eta: Optional[int] = None  # seconds
    status: str = "pending"  # pending, downloading, completed, failed, paused
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def progress_percent(self) -> float:
        """Get download progress as percentage."""
        if self.total_size == 0:
            return 0.0
        return (self.downloaded_size / self.total_size) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if download is complete."""
        return self.status == "completed"
    
    @property
    def is_failed(self) -> bool:
        """Check if download failed."""
        return self.status == "failed"


@dataclass
class CourseDownloadProgress:
    """Progress information for entire course download."""
    
    course_id: str
    course_title: str
    total_videos: int = 0
    completed_videos: int = 0
    failed_videos: int = 0
    total_size: int = 0
    downloaded_size: int = 0
    video_progress: Dict[str, DownloadProgress] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def progress_percent(self) -> float:
        """Get overall course download progress as percentage."""
        if self.total_size == 0:
            return 0.0
        return (self.downloaded_size / self.total_size) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if course download is complete."""
        return self.completed_videos == self.total_videos
    
    @property
    def success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_videos == 0:
            return 0.0
        return ((self.total_videos - self.failed_videos) / self.total_videos) * 100


class DownloadManager:
    """Manages concurrent video downloads with progress tracking and resume functionality."""
    
    def __init__(self, options: DownloadOptions, progress_callback: Optional[Callable] = None,
                 retry_config: Optional[RetryConfig] = None, bandwidth_controller: Optional[BandwidthController] = None):
        """Initialize download manager.
        
        Args:
            options: Download configuration options.
            progress_callback: Optional callback for progress updates.
            retry_config: Configuration for retry logic.
            bandwidth_controller: Bandwidth control configuration.
        """
        self.options = options
        self.progress_callback = progress_callback
        self.session: Optional[aiohttp.ClientSession] = None
        self.download_semaphore = asyncio.Semaphore(options.concurrent_downloads)
        self.active_downloads: Dict[str, DownloadProgress] = {}
        self.course_progress: Dict[str, CourseDownloadProgress] = {}
        self.resume_data_file = Path(options.output_directory) / ".edx_resume_data.json"
        
        # Advanced features
        self.retry_config = retry_config or RetryConfig()
        self.bandwidth_controller = bandwidth_controller or BandwidthController()
        self.download_queue: List[DownloadQueueItem] = []
        self.duplicate_tracker: Dict[str, str] = {}  # hash -> filepath
        self.failed_downloads: Dict[str, int] = defaultdict(int)  # video_id -> retry_count
        
        # Create output directory
        self.output_path = Path(options.output_directory)
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        # Load resume data
        self.resume_data = self._load_resume_data()
    
    async def __aenter__(self):
        """Async context manager entry."""
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=300, connect=30)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
        self._save_resume_data()
    
    async def download_course(self, course_info: CourseInfo, videos: List[VideoInfo]) -> CourseDownloadProgress:
        """Download all videos for a course.
        
        Args:
            course_info: Course information.
            videos: List of videos to download.
            
        Returns:
            Course download progress information.
        """
        with performance_timer("download_course", logger):
            log_with_context(logger, logging.INFO, "Starting course download", {
                'course_id': course_info.id,
                'course_title': course_info.title,
                'total_videos': len(videos),
                'concurrent_downloads': self.options.concurrent_downloads
            })
            
            # Initialize course progress
            course_progress = CourseDownloadProgress(
                course_id=course_info.id,
                course_title=course_info.title,
                total_videos=len(videos),
                start_time=datetime.now()
            )
            self.course_progress[course_info.id] = course_progress
            
            # Create course directory
            with performance_timer("create_course_directory", logger):
                course_dir = self._create_course_directory(course_info)
                log_with_context(logger, logging.DEBUG, "Created course directory", {
                    'course_dir': str(course_dir),
                    'organize_by_section': self.options.organize_by_section
                })
            
            # Filter out already downloaded videos if not resuming
            with performance_timer("filter_existing_videos", logger):
                videos_to_download = self._filter_existing_videos(videos, course_dir)
                log_with_context(logger, logging.INFO, "Filtered videos for download", {
                    'total_videos': len(videos),
                    'videos_to_download': len(videos_to_download),
                    'already_downloaded': len(videos) - len(videos_to_download),
                    'resume_enabled': self.options.resume_enabled
                })
            
            if not videos_to_download:
                log_with_context(logger, logging.INFO, "All videos already downloaded", {
                    'course_id': course_info.id,
                    'total_videos': len(videos)
                })
                course_progress.completed_videos = len(videos)
                course_progress.end_time = datetime.now()
                return course_progress
            
            # Get video sizes for progress tracking
            with performance_timer("get_video_sizes", logger):
                await self._get_video_sizes(videos_to_download)
                course_progress.total_size = sum(v.size or 0 for v in videos)
                log_with_context(logger, logging.DEBUG, "Retrieved video sizes", {
                    'total_size_gb': course_progress.total_size / (1024**3),
                    'videos_with_size': sum(1 for v in videos_to_download if v.size),
                    'videos_without_size': sum(1 for v in videos_to_download if not v.size)
                })
            
            # Create download tasks
            download_tasks = []
            for video in videos_to_download:
                task = asyncio.create_task(
                    self._download_video_with_semaphore(video, course_dir, course_progress)
                )
                download_tasks.append(task)
            
            log_with_context(logger, logging.INFO, "Starting concurrent downloads", {
                'download_tasks': len(download_tasks),
                'concurrent_limit': self.options.concurrent_downloads
            })
            
            # Wait for all downloads to complete
            try:
                with performance_timer("concurrent_downloads", logger):
                    await asyncio.gather(*download_tasks, return_exceptions=True)
            except Exception as e:
                log_with_context(logger, logging.ERROR, "Error during course download", {
                    'course_id': course_info.id,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
            
            course_progress.end_time = datetime.now()
            duration = (course_progress.end_time - course_progress.start_time).total_seconds()
            
            log_with_context(logger, logging.INFO, "Course download completed", {
                'course_id': course_info.id,
                'course_title': course_info.title,
                'total_videos': course_progress.total_videos,
                'completed_videos': course_progress.completed_videos,
                'failed_videos': course_progress.failed_videos,
                'success_rate': course_progress.success_rate,
                'total_size_gb': course_progress.total_size / (1024**3),
                'downloaded_size_gb': course_progress.downloaded_size / (1024**3),
                'duration_seconds': duration,
                'average_speed_mbps': (course_progress.downloaded_size / (1024**2)) / duration if duration > 0 else 0
            })
            
            return course_progress
    
    async def download_video(self, video: VideoInfo, output_dir: Path) -> DownloadProgress:
        """Download a single video.
        
        Args:
            video: Video information.
            output_dir: Output directory.
            
        Returns:
            Download progress information.
        """
        progress = DownloadProgress(
            video_id=video.id,
            filename=video.filename,
            start_time=datetime.now()
        )
        
        try:
            # Create safe filename
            filename = self._create_safe_filename(video)
            filepath = output_dir / filename
            
            # Check if file already exists and is complete
            if filepath.exists() and not self.options.resume_enabled:
                logger.info(f"File already exists: {filename}")
                progress.status = "completed"
                progress.total_size = filepath.stat().st_size
                progress.downloaded_size = progress.total_size
                progress.end_time = datetime.now()
                return progress
            
            # Get video size
            if not video.size:
                video.size = await self._get_content_size(video.url)
            
            progress.total_size = video.size or 0
            
            # Download the video
            await self._download_file(video.url, filepath, progress)
            
            progress.status = "completed"
            progress.end_time = datetime.now()
            logger.info(f"Successfully downloaded: {filename}")
            
        except Exception as e:
            progress.status = "failed"
            progress.error = str(e)
            progress.end_time = datetime.now()
            logger.error(f"Failed to download {video.filename}: {e}")
            
            if isinstance(e, (DiskSpaceError, FilePermissionError)):
                raise
        
        return progress
    
    async def _download_video_with_semaphore(self, video: VideoInfo, output_dir: Path, 
                                           course_progress: CourseDownloadProgress) -> None:
        """Download video with semaphore control.
        
        Args:
            video: Video information.
            output_dir: Output directory.
            course_progress: Course progress tracker.
        """
        async with self.download_semaphore:
            progress = await self.download_video(video, output_dir)
            
            # Update course progress
            course_progress.video_progress[video.id] = progress
            
            if progress.is_complete:
                course_progress.completed_videos += 1
                course_progress.downloaded_size += progress.downloaded_size
            elif progress.is_failed:
                course_progress.failed_videos += 1
            
            # Call progress callback if provided
            if self.progress_callback:
                self.progress_callback(course_progress)
    
    async def _download_file(self, url: str, filepath: Path, progress: DownloadProgress) -> None:
        """Download file with resume support and progress tracking.
        
        Args:
            url: Download URL.
            filepath: Output file path.
            progress: Progress tracker.
        """
        if not self.session:
            raise DownloadError("Download session not initialized")
        
        # Check available disk space
        self._check_disk_space(filepath.parent, progress.total_size)
        
        # Determine resume position
        resume_pos = 0
        if self.options.resume_enabled and filepath.exists():
            resume_pos = filepath.stat().st_size
            progress.downloaded_size = resume_pos
            
            # If file is already complete, skip download
            if resume_pos >= progress.total_size > 0:
                logger.info(f"File already complete: {filepath.name}")
                return
        
        # Set up headers for resume
        headers = {}
        if resume_pos > 0:
            headers['Range'] = f'bytes={resume_pos}-'
            logger.info(f"Resuming download from byte {resume_pos}")
        
        progress.status = "downloading"
        
        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status not in (200, 206):
                    raise DownloadError(f"HTTP {response.status}: {response.reason}")
                
                # Update total size if not known
                if progress.total_size == 0:
                    content_length = response.headers.get('content-length')
                    if content_length:
                        progress.total_size = int(content_length) + resume_pos
                
                # Open file for writing
                mode = 'ab' if resume_pos > 0 else 'wb'
                async with aiofiles.open(filepath, mode) as f:
                    await self._write_chunks_with_bandwidth_control(response, f, progress)
                
        except asyncio.CancelledError:
            progress.status = "paused"
            raise DownloadInterruptedError("Download was cancelled")
        except Exception as e:
            progress.status = "failed"
            # Clean up partial file if not resuming
            if not self.options.resume_enabled and filepath.exists():
                filepath.unlink()
            raise DownloadError(f"Download failed: {e}")
    
    async def _write_chunks_with_bandwidth_control(self, response: aiohttp.ClientResponse, file, progress: DownloadProgress) -> None:
        """Write response chunks to file with bandwidth control and progress tracking.
        
        Args:
            response: HTTP response.
            file: Output file handle.
            progress: Progress tracker.
        """
        chunk_size = self.bandwidth_controller.chunk_size
        last_update = datetime.now()
        bytes_since_update = 0
        
        async for chunk in response.content.iter_chunked(chunk_size):
            await file.write(chunk)
            chunk_len = len(chunk)
            progress.downloaded_size += chunk_len
            bytes_since_update += chunk_len
            
            # Apply bandwidth throttling
            await self.bandwidth_controller.throttle()
            
            # Update speed calculation every second
            now = datetime.now()
            time_diff = (now - last_update).total_seconds()
            
            if time_diff >= 1.0:
                progress.speed = bytes_since_update / time_diff
                
                # Calculate ETA
                if progress.speed > 0 and progress.total_size > 0:
                    remaining_bytes = progress.total_size - progress.downloaded_size
                    progress.eta = int(remaining_bytes / progress.speed)
                
                last_update = now
                bytes_since_update = 0

    async def _write_chunks(self, response: aiohttp.ClientResponse, file, progress: DownloadProgress) -> None:
        """Write response chunks to file with progress tracking.
        
        Args:
            response: HTTP response.
            file: Output file handle.
            progress: Progress tracker.
        """
        chunk_size = 8192
        last_update = datetime.now()
        bytes_since_update = 0
        
        async for chunk in response.content.iter_chunked(chunk_size):
            await file.write(chunk)
            chunk_len = len(chunk)
            progress.downloaded_size += chunk_len
            bytes_since_update += chunk_len
            
            # Update speed calculation every second
            now = datetime.now()
            time_diff = (now - last_update).total_seconds()
            
            if time_diff >= 1.0:
                progress.speed = bytes_since_update / time_diff
                
                # Calculate ETA
                if progress.speed > 0 and progress.total_size > 0:
                    remaining_bytes = progress.total_size - progress.downloaded_size
                    progress.eta = int(remaining_bytes / progress.speed)
                
                last_update = now
                bytes_since_update = 0
    
    async def _get_video_sizes(self, videos: List[VideoInfo]) -> None:
        """Get sizes for videos that don't have size information.
        
        Args:
            videos: List of videos to check.
        """
        tasks = []
        for video in videos:
            if not video.size:
                task = asyncio.create_task(self._get_content_size_for_video(video))
                tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _get_content_size_for_video(self, video: VideoInfo) -> None:
        """Get content size for a video.
        
        Args:
            video: Video information.
        """
        try:
            video.size = await self._get_content_size(video.url)
        except Exception as e:
            logger.warning(f"Could not get size for {video.filename}: {e}")
            video.size = 0
    
    async def _get_content_size(self, url: str) -> int:
        """Get content size from URL.
        
        Args:
            url: Content URL.
            
        Returns:
            Content size in bytes.
        """
        if not self.session:
            raise DownloadError("Download session not initialized")
        
        try:
            async with self.session.head(url) as response:
                content_length = response.headers.get('content-length')
                return int(content_length) if content_length else 0
        except Exception:
            # Fallback to GET request with range
            try:
                headers = {'Range': 'bytes=0-0'}
                async with self.session.get(url, headers=headers) as response:
                    content_range = response.headers.get('content-range')
                    if content_range:
                        # Parse "bytes 0-0/total_size"
                        total_size = content_range.split('/')[-1]
                        return int(total_size)
            except Exception:
                pass
        
        return 0
    
    def _create_course_directory(self, course_info: CourseInfo) -> Path:
        """Create directory structure for course.
        
        Args:
            course_info: Course information.
            
        Returns:
            Course directory path.
        """
        # Create safe directory name
        safe_title = self._sanitize_filename(course_info.title)
        course_dir = self.output_path / safe_title
        
        if self.options.organize_by_section:
            # Create subdirectories for sections if needed
            course_dir.mkdir(parents=True, exist_ok=True)
        else:
            course_dir.mkdir(parents=True, exist_ok=True)
        
        return course_dir
    
    def _filter_existing_videos(self, videos: List[VideoInfo], output_dir: Path) -> List[VideoInfo]:
        """Filter out videos that are already downloaded.
        
        Args:
            videos: List of all videos.
            output_dir: Output directory.
            
        Returns:
            List of videos that need to be downloaded.
        """
        if not self.options.resume_enabled:
            return videos
        
        videos_to_download = []
        for video in videos:
            filename = self._create_safe_filename(video)
            filepath = output_dir / filename
            
            if not filepath.exists():
                videos_to_download.append(video)
            elif video.size and filepath.stat().st_size < video.size:
                # Partial file - can be resumed
                videos_to_download.append(video)
            else:
                logger.info(f"Skipping already downloaded: {filename}")
        
        return videos_to_download
    
    def _create_safe_filename(self, video: VideoInfo) -> str:
        """Create safe filename for video.
        
        Args:
            video: Video information.
            
        Returns:
            Safe filename.
        """
        # Use video's filename property if available, otherwise create one
        if hasattr(video, 'filename') and video.filename:
            return self._sanitize_filename(video.filename)
        
        # Create filename from title and format
        safe_title = self._sanitize_filename(video.title)
        extension = video.format if video.format != 'unknown' else 'mp4'
        return f"{safe_title}.{extension}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem compatibility.
        
        Args:
            filename: Original filename.
            
        Returns:
            Sanitized filename.
        """
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limit length
        if len(filename) > 200:
            filename = filename[:200]
        
        # Remove leading/trailing spaces and dots
        filename = filename.strip(' .')
        
        return filename or "video"
    
    def _check_disk_space(self, directory: Path, required_size: int) -> None:
        """Check if there's enough disk space.
        
        Args:
            directory: Target directory.
            required_size: Required space in bytes.
            
        Raises:
            DiskSpaceError: If insufficient disk space.
        """
        try:
            stat = os.statvfs(directory)
            available_space = stat.f_bavail * stat.f_frsize
            
            if required_size > available_space:
                raise DiskSpaceError(
                    f"Insufficient disk space. Required: {required_size / (1024**3):.2f} GB, "
                    f"Available: {available_space / (1024**3):.2f} GB"
                )
        except AttributeError:
            # Windows doesn't have statvfs, use shutil
            import shutil
            available_space = shutil.disk_usage(directory).free
            
            if required_size > available_space:
                raise DiskSpaceError(
                    f"Insufficient disk space. Required: {required_size / (1024**3):.2f} GB, "
                    f"Available: {available_space / (1024**3):.2f} GB"
                )
    
    def _load_resume_data(self) -> Dict[str, Any]:
        """Load resume data from file.
        
        Returns:
            Resume data dictionary.
        """
        if not self.resume_data_file.exists():
            return {}
        
        try:
            with open(self.resume_data_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load resume data: {e}")
            return {}
    
    def _save_resume_data(self) -> None:
        """Save resume data to file."""
        try:
            resume_data = {
                'active_downloads': {
                    vid: {
                        'filename': prog.filename,
                        'downloaded_size': prog.downloaded_size,
                        'total_size': prog.total_size,
                        'status': prog.status
                    }
                    for vid, prog in self.active_downloads.items()
                },
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.resume_data_file, 'w') as f:
                json.dump(resume_data, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Could not save resume data: {e}")
    
    def get_download_statistics(self) -> Dict[str, Any]:
        """Get download statistics.
        
        Returns:
            Statistics dictionary.
        """
        total_downloads = len(self.active_downloads)
        completed = sum(1 for p in self.active_downloads.values() if p.is_complete)
        failed = sum(1 for p in self.active_downloads.values() if p.is_failed)
        
        total_size = sum(p.total_size for p in self.active_downloads.values())
        downloaded_size = sum(p.downloaded_size for p in self.active_downloads.values())
        
        return {
            'total_downloads': total_downloads,
            'completed': completed,
            'failed': failed,
            'success_rate': (completed / total_downloads * 100) if total_downloads > 0 else 0,
            'total_size_gb': total_size / (1024**3),
            'downloaded_size_gb': downloaded_size / (1024**3),
            'progress_percent': (downloaded_size / total_size * 100) if total_size > 0 else 0
        }
    
    # Advanced download features
    
    async def download_video_with_retry(self, video: VideoInfo, output_dir: Path) -> DownloadProgress:
        """Download a video with retry logic and exponential backoff.
        
        Args:
            video: Video information.
            output_dir: Output directory.
            
        Returns:
            Download progress information.
        """
        last_error = None
        
        for attempt in range(self.retry_config.max_retries + 1):
            try:
                # Check if this is a duplicate
                if self._is_duplicate_video(video, output_dir):
                    logger.info(f"Skipping duplicate video: {video.title}")
                    progress = DownloadProgress(
                        video_id=video.id,
                        filename=video.filename,
                        status="completed"
                    )
                    return progress
                
                # Attempt download
                progress = await self.download_video(video, output_dir)
                
                if progress.is_complete:
                    # Reset retry count on success
                    self.failed_downloads.pop(video.id, None)
                    # Track successful download to prevent duplicates
                    self._track_downloaded_video(video, output_dir)
                    return progress
                
                # If download failed but we have retries left
                if attempt < self.retry_config.max_retries:
                    delay = self.retry_config.get_delay(attempt)
                    logger.warning(f"Download failed for {video.title}, retrying in {delay:.1f}s (attempt {attempt + 1}/{self.retry_config.max_retries})")
                    await asyncio.sleep(delay)
                    last_error = progress.error
                else:
                    # Max retries reached
                    self.failed_downloads[video.id] = attempt + 1
                    logger.error(f"Download failed permanently for {video.title} after {attempt + 1} attempts")
                    return progress
                    
            except Exception as e:
                last_error = str(e)
                if attempt < self.retry_config.max_retries:
                    delay = self.retry_config.get_delay(attempt)
                    logger.warning(f"Download error for {video.title}: {e}, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Download failed permanently for {video.title}: {e}")
                    progress = DownloadProgress(
                        video_id=video.id,
                        filename=video.filename,
                        status="failed",
                        error=last_error
                    )
                    self.failed_downloads[video.id] = attempt + 1
                    return progress
        
        # Should not reach here, but just in case
        progress = DownloadProgress(
            video_id=video.id,
            filename=video.filename,
            status="failed",
            error=last_error or "Unknown error"
        )
        return progress
    
    def add_to_download_queue(self, video: VideoInfo, output_dir: Path, priority: int = 0) -> None:
        """Add video to download queue with priority.
        
        Args:
            video: Video information.
            output_dir: Output directory.
            priority: Download priority (higher = more important).
        """
        queue_item = DownloadQueueItem(
            video=video,
            output_dir=output_dir,
            priority=priority
        )
        heapq.heappush(self.download_queue, queue_item)
        logger.debug(f"Added {video.title} to download queue with priority {priority}")
    
    async def process_download_queue(self) -> List[DownloadProgress]:
        """Process all items in the download queue.
        
        Returns:
            List of download progress results.
        """
        results = []
        
        while self.download_queue:
            # Get highest priority item
            queue_item = heapq.heappop(self.download_queue)
            
            # Download with retry logic
            async with self.download_semaphore:
                progress = await self.download_video_with_retry(
                    queue_item.video, 
                    queue_item.output_dir
                )
                results.append(progress)
                
                # Update queue item with results
                queue_item.retry_count = self.failed_downloads.get(queue_item.video.id, 0)
                queue_item.last_error = progress.error
        
        return results
    
    def _is_duplicate_video(self, video: VideoInfo, output_dir: Path) -> bool:
        """Check if video is a duplicate of already downloaded content.
        
        Args:
            video: Video information.
            output_dir: Output directory.
            
        Returns:
            True if video is a duplicate.
        """
        # Create a hash based on video URL and title for duplicate detection
        video_hash = hashlib.md5(f"{video.url}:{video.title}".encode()).hexdigest()
        
        # Check if we've already downloaded this hash
        if video_hash in self.duplicate_tracker:
            existing_path = self.duplicate_tracker[video_hash]
            if Path(existing_path).exists():
                logger.debug(f"Found duplicate: {video.title} -> {existing_path}")
                return True
            else:
                # File was deleted, remove from tracker
                del self.duplicate_tracker[video_hash]
        
        return False
    
    def _track_downloaded_video(self, video: VideoInfo, output_dir: Path) -> None:
        """Track successfully downloaded video to prevent duplicates.
        
        Args:
            video: Video information.
            output_dir: Output directory.
        """
        video_hash = hashlib.md5(f"{video.url}:{video.title}".encode()).hexdigest()
        filename = self._create_safe_filename(video)
        filepath = output_dir / filename
        
        self.duplicate_tracker[video_hash] = str(filepath)
        logger.debug(f"Tracking downloaded video: {video.title} -> {filepath}")
    
    async def _write_chunks_with_bandwidth_control(self, response: aiohttp.ClientResponse, 
                                                 file, progress: DownloadProgress) -> None:
        """Write response chunks to file with bandwidth control and progress tracking.
        
        Args:
            response: HTTP response.
            file: Output file handle.
            progress: Progress tracker.
        """
        chunk_size = self.bandwidth_controller.chunk_size
        last_update = datetime.now()
        bytes_since_update = 0
        
        async for chunk in response.content.iter_chunked(chunk_size):
            await file.write(chunk)
            chunk_len = len(chunk)
            progress.downloaded_size += chunk_len
            bytes_since_update += chunk_len
            
            # Apply bandwidth throttling
            await self.bandwidth_controller.throttle()
            
            # Update speed calculation every second
            now = datetime.now()
            time_diff = (now - last_update).total_seconds()
            
            if time_diff >= 1.0:
                progress.speed = bytes_since_update / time_diff
                
                # Calculate ETA
                if progress.speed > 0 and progress.total_size > 0:
                    remaining_bytes = progress.total_size - progress.downloaded_size
                    progress.eta = int(remaining_bytes / progress.speed)
                
                last_update = now
                bytes_since_update = 0
    
    def get_failed_downloads(self) -> Dict[str, int]:
        """Get list of failed downloads with retry counts.
        
        Returns:
            Dictionary mapping video_id to retry count.
        """
        return dict(self.failed_downloads)
    
    def clear_failed_downloads(self) -> None:
        """Clear the failed downloads tracking."""
        self.failed_downloads.clear()
        logger.info("Cleared failed downloads tracking")
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get download queue status.
        
        Returns:
            Queue status information.
        """
        return {
            'queue_length': len(self.download_queue),
            'active_downloads': len(self.active_downloads),
            'failed_downloads': len(self.failed_downloads),
            'duplicate_tracker_size': len(self.duplicate_tracker)
        }