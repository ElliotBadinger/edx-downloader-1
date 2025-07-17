"""Main application flow for EDX downloader."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from .config import ConfigManager
from .auth import AuthenticationManager
from .api_client import EdxApiClient
from .course_manager import CourseManager
from .download_manager import DownloadManager
from .models import DownloadOptions, CourseInfo, VideoInfo
from .exceptions import (
    EdxDownloaderError, AuthenticationError, CourseAccessError,
    NetworkError, DownloadError, ConfigurationError
)
from .logging_config import get_logger, log_with_context, performance_timer

logger = get_logger(__name__)


class EdxDownloaderApp:
    """Main application class that orchestrates all components."""
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize the application.
        
        Args:
            config_file: Optional path to configuration file.
        """
        self.config_manager = ConfigManager(config_file)
        self.auth_manager: Optional[AuthenticationManager] = None
        self.api_client: Optional[EdxApiClient] = None
        self.course_manager: Optional[CourseManager] = None
        self.download_manager: Optional[DownloadManager] = None
        self.shutdown_requested = False
        
        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_requested = True
        
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except (AttributeError, ValueError):
            # Some signals might not be available on all platforms
            pass
    
    async def initialize(self, username: str, password: Optional[str] = None) -> None:
        """Initialize all components and authenticate.
        
        Args:
            username: EDX username or email.
            password: EDX password. If None, will try to retrieve from storage.
            
        Raises:
            AuthenticationError: If authentication fails.
            ConfigurationError: If configuration is invalid.
        """
        with performance_timer("app_initialization", logger):
            try:
                log_with_context(logger, logging.INFO, "Starting application initialization", {
                    'username': username,
                    'has_password': password is not None
                })
                
                # Initialize authentication manager
                with performance_timer("auth_manager_init", logger):
                    self.auth_manager = AuthenticationManager(
                        self.config_manager.credential_manager,
                        base_url="https://courses.edx.org"
                    )
                
                # Authenticate user
                with performance_timer("user_authentication", logger):
                    auth_session = self.auth_manager.authenticate(username, password)
                    log_with_context(logger, logging.INFO, "Authentication successful", {
                        'username': username,
                        'session_id': getattr(auth_session, 'session_id', 'unknown')
                    })
                
                # Initialize API client with configuration
                with performance_timer("api_client_init", logger):
                    self.api_client = EdxApiClient(self.config_manager.config)
                    self.api_client.set_auth_session(auth_session)
                
                # Initialize course manager
                with performance_timer("course_manager_init", logger):
                    self.course_manager = CourseManager(self.api_client)
                
                log_with_context(logger, logging.INFO, "Application initialization completed", {
                    'components_initialized': ['auth_manager', 'api_client', 'course_manager']
                })
                
            except Exception as e:
                log_with_context(logger, logging.ERROR, "Application initialization failed", {
                    'username': username,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                await self.cleanup()
                raise
    
    async def download_course(
        self, 
        course_url: str, 
        options: DownloadOptions,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """Download a complete course.
        
        Args:
            course_url: URL of the course to download.
            options: Download configuration options.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            Download results dictionary.
            
        Raises:
            CourseAccessError: If course cannot be accessed.
            DownloadError: If download fails.
        """
        if not self.course_manager:
            raise EdxDownloaderError("Application not initialized")
        
        try:
            # Get course information
            logger.info(f"Getting course information for: {course_url}")
            course_info = await self.course_manager.get_course_info(course_url)
            logger.info(f"Found course: {course_info.title}")
            
            # Validate course access
            logger.info("Validating course access...")
            await self.course_manager.validate_course_access(course_info)
            logger.info("Course access validated")
            
            # Get course outline
            logger.info("Getting course outline...")
            outline = await self.course_manager.get_course_outline(course_info)
            logger.info(f"Found {len(outline.get('blocks', {}))} course sections")
            
            # Extract videos from course
            logger.info("Extracting video information...")
            all_videos = await self._extract_all_videos(course_info, outline)
            logger.info(f"Found {len(all_videos)} videos to download")
            
            if not all_videos:
                return {
                    'success': True,
                    'course_info': course_info,
                    'videos_found': 0,
                    'videos_downloaded': 0,
                    'message': 'No videos found in course'
                }
            
            # Initialize download manager
            async with DownloadManager(options, progress_callback) as download_manager:
                self.download_manager = download_manager
                
                # Start download process
                logger.info(f"Starting download of {len(all_videos)} videos...")
                course_progress = await download_manager.download_course(course_info, all_videos)
                
                # Check for shutdown request
                if self.shutdown_requested:
                    logger.info("Shutdown requested, stopping downloads...")
                    return {
                        'success': False,
                        'course_info': course_info,
                        'videos_found': len(all_videos),
                        'videos_downloaded': course_progress.completed_videos,
                        'message': 'Download interrupted by user'
                    }
                
                # Return results
                return {
                    'success': course_progress.success_rate > 0,
                    'course_info': course_info,
                    'videos_found': len(all_videos),
                    'videos_downloaded': course_progress.completed_videos,
                    'videos_failed': course_progress.failed_videos,
                    'success_rate': course_progress.success_rate,
                    'total_size_gb': course_progress.total_size / (1024**3) if course_progress.total_size > 0 else 0,
                    'downloaded_size_gb': course_progress.downloaded_size / (1024**3) if course_progress.downloaded_size > 0 else 0,
                    'course_progress': course_progress
                }
                
        except Exception as e:
            logger.error(f"Course download failed: {e}")
            raise
    
    async def get_course_info(self, course_url: str) -> CourseInfo:
        """Get information about a course without downloading.
        
        Args:
            course_url: URL of the course.
            
        Returns:
            Course information.
        """
        if not self.course_manager:
            raise EdxDownloaderError("Application not initialized")
        
        return await self.course_manager.get_course_info(course_url)
    
    async def list_course_videos(self, course_url: str) -> List[VideoInfo]:
        """List all videos in a course without downloading.
        
        Args:
            course_url: URL of the course.
            
        Returns:
            List of video information.
        """
        if not self.course_manager:
            raise EdxDownloaderError("Application not initialized")
        
        # Get course info and outline
        course_info = await self.course_manager.get_course_info(course_url)
        outline = await self.course_manager.get_course_outline(course_info)
        
        # Extract all videos
        return await self._extract_all_videos(course_info, outline)
    
    async def _extract_all_videos(self, course_info: CourseInfo, outline: Dict[str, Any]) -> List[VideoInfo]:
        """Extract all videos from course outline.
        
        Args:
            course_info: Course information.
            outline: Course outline data.
            
        Returns:
            List of video information.
        """
        all_videos = []
        blocks = outline.get('blocks', {})
        
        for block_id, block_data in blocks.items():
            if self.shutdown_requested:
                break
                
            block_type = block_data.get('type', '')
            
            # Process video blocks and sequential blocks that might contain videos
            if block_type in ['video', 'sequential', 'vertical']:
                block_url = block_data.get('student_view_url', '')
                if block_url:
                    try:
                        videos = await self.course_manager.extract_video_info(block_url, course_info)
                        all_videos.extend(videos)
                        
                        # Add section information to videos
                        section_name = block_data.get('display_name', 'Unknown Section')
                        for video in videos:
                            if not video.course_section or video.course_section == course_info.title:
                                video.course_section = section_name
                                
                    except Exception as e:
                        logger.warning(f"Failed to extract videos from block {block_id}: {e}")
                        continue
        
        # Remove duplicates based on URL
        unique_videos = []
        seen_urls = set()
        
        for video in all_videos:
            if video.url not in seen_urls:
                unique_videos.append(video)
                seen_urls.add(video.url)
        
        return unique_videos
    
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated.
        
        Returns:
            True if authenticated.
        """
        return self.auth_manager is not None and self.auth_manager.is_authenticated()
    
    def get_stored_usernames(self) -> List[str]:
        """Get list of stored usernames.
        
        Returns:
            List of stored usernames.
        """
        return self.config_manager.list_stored_usernames()
    
    def store_credentials(self, username: str, password: str) -> None:
        """Store user credentials.
        
        Args:
            username: Username to store.
            password: Password to store.
        """
        self.config_manager.store_credentials(username, password)
    
    def delete_credentials(self, username: str) -> None:
        """Delete stored credentials.
        
        Args:
            username: Username to delete.
        """
        self.config_manager.delete_credentials(username)
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration.
        
        Returns:
            Configuration dictionary.
        """
        config = self.config_manager.config
        return {
            'default_output_dir': str(config.default_output_dir),
            'max_concurrent_downloads': config.max_concurrent_downloads,
            'video_quality_preference': config.video_quality_preference,
            'rate_limit_delay': config.rate_limit_delay,
            'retry_attempts': config.retry_attempts,
            'cache_directory': str(config.cache_directory),
            'credentials_file': str(config.credentials_file)
        }
    
    async def cleanup(self) -> None:
        """Clean up resources and close connections."""
        logger.info("Cleaning up application resources...")
        
        try:
            # Close download manager
            if self.download_manager:
                # Download manager cleanup is handled by its context manager
                pass
            
            # Close API client
            if self.api_client:
                self.api_client.close()
            
            # Logout authentication manager
            if self.auth_manager:
                try:
                    self.auth_manager.logout()
                except Exception as e:
                    logger.warning(f"Error during logout: {e}")
                finally:
                    self.auth_manager.close()
            
            logger.info("Application cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


@asynccontextmanager
async def create_app(config_file: Optional[str] = None):
    """Create and manage EDX downloader application.
    
    Args:
        config_file: Optional path to configuration file.
        
    Yields:
        EdxDownloaderApp instance.
    """
    app = EdxDownloaderApp(config_file)
    try:
        yield app
    finally:
        await app.cleanup()


async def download_course_simple(
    course_url: str,
    username: str,
    password: Optional[str] = None,
    output_dir: Optional[str] = None,
    quality: str = "highest",
    concurrent_downloads: int = 4,
    config_file: Optional[str] = None,
    progress_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """Simple function to download a course with minimal setup.
    
    Args:
        course_url: URL of the course to download.
        username: EDX username or email.
        password: EDX password. If None, will try to retrieve from storage.
        output_dir: Output directory for downloads.
        quality: Video quality preference.
        concurrent_downloads: Number of concurrent downloads.
        config_file: Optional path to configuration file.
        progress_callback: Optional callback for progress updates.
        
    Returns:
        Download results dictionary.
    """
    async with create_app(config_file) as app:
        # Initialize application
        await app.initialize(username, password)
        
        # Create download options
        options = DownloadOptions(
            output_directory=output_dir or str(Path.cwd() / "downloads"),
            quality_preference=quality,
            concurrent_downloads=concurrent_downloads,
            resume_enabled=True,
            organize_by_section=True
        )
        
        # Download course
        return await app.download_course(course_url, options, progress_callback)


async def get_course_info_simple(
    course_url: str,
    username: str,
    password: Optional[str] = None,
    config_file: Optional[str] = None
) -> CourseInfo:
    """Simple function to get course information.
    
    Args:
        course_url: URL of the course.
        username: EDX username or email.
        password: EDX password. If None, will try to retrieve from storage.
        config_file: Optional path to configuration file.
        
    Returns:
        Course information.
    """
    async with create_app(config_file) as app:
        await app.initialize(username, password)
        return await app.get_course_info(course_url)