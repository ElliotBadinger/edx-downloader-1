"""
EDX Downloader - Modern CLI tool for downloading EDX course videos.

A modernized version of the EDX downloader with updated APIs,
improved error handling, and better maintainability.
"""

__version__ = "2.0.0"
__author__ = "Siyabonga Buthelezi"
__email__ = "brainstein@protonmail.com"

from .exceptions import (
    EdxDownloaderError,
    AuthenticationError,
    CourseAccessError,
    NetworkError,
    ParseError,
    DownloadError,
    MigrationError,
)

from .models import (
    CourseInfo,
    VideoInfo,
    DownloadOptions,
    AuthSession,
    AppConfig
)

from .config import ConfigManager
from .auth import AuthenticationManager
from .api_client import EdxApiClient
from .course_manager import CourseManager
from .download_manager import DownloadManager
from .logging_config import setup_logging, get_logger

__all__ = [
    "EdxDownloaderError",
    "AuthenticationError",
    "CourseAccessError",
    "NetworkError",
    "ParseError",
    "DownloadError",
    "CourseInfo",
    "VideoInfo",
    "DownloadOptions",
    "AuthSession",
    "AppConfig",
    "ConfigManager",
    "AuthenticationManager",
    "EdxApiClient",
    "CourseManager",
    "DownloadManager",
    "setup_logging",
    "get_logger",
]
