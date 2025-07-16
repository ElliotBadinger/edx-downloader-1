"""
EDX Downloader - Modern CLI tool for downloading EDX course videos.

A modernized version of the EDX downloader with updated APIs,
improved error handling, and better maintainability.
"""

__version__ = "2.0.0"
__author__ = "Rehmat Alam"
__email__ = "contact@rehmat.works"

from .exceptions import (
    EdxDownloaderError,
    AuthenticationError,
    CourseAccessError,
    NetworkError,
    ParseError,
    DownloadError,
)

__all__ = [
    "EdxDownloaderError",
    "AuthenticationError",
    "CourseAccessError",
    "NetworkError",
    "ParseError",
    "DownloadError",
]
