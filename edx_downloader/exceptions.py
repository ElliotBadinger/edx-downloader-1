"""Exception classes for EDX downloader."""

from typing import Optional, Dict, Any


class EdxDownloaderError(Exception):
    """Base exception for all EDX downloader errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join([f"{k}: {v}" for k, v in self.details.items()])
            return f"{self.message} ({details_str})"
        return self.message


class AuthenticationError(EdxDownloaderError):
    """Authentication-related errors."""

    def __init__(self, message: str, username: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.username = username


class InvalidCredentialsError(AuthenticationError):
    """Invalid username or password."""
    pass


class SessionExpiredError(AuthenticationError):
    """Authentication session has expired."""
    pass


class TwoFactorRequiredError(AuthenticationError):
    """Two-factor authentication is required."""
    pass


class CourseAccessError(EdxDownloaderError):
    """Course access and enrollment errors."""

    def __init__(self, message: str, course_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.course_id = course_id


class CourseNotFoundError(CourseAccessError):
    """Course does not exist or is not accessible."""
    pass


class EnrollmentRequiredError(CourseAccessError):
    """User must be enrolled to access course content."""
    pass


class CourseNotStartedError(CourseAccessError):
    """Course has not started yet."""
    pass


class CourseEndedError(CourseAccessError):
    """Course has ended and content is no longer available."""
    pass


class NetworkError(EdxDownloaderError):
    """Network and API communication errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, url: Optional[str] = None, 
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.status_code = status_code
        self.url = url


class ConnectionError(NetworkError):
    """Failed to establish network connection."""
    pass


class TimeoutError(NetworkError):
    """Network request timed out."""
    pass


class RateLimitError(NetworkError):
    """Rate limit exceeded."""
    pass


class ServerError(NetworkError):
    """Server returned an error response."""
    pass


class ParseError(EdxDownloaderError):
    """Content parsing and data extraction errors."""

    def __init__(self, message: str, content_type: Optional[str] = None, url: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.content_type = content_type
        self.url = url


class VideoNotFoundError(ParseError):
    """Video content could not be found or extracted."""
    pass


class UnsupportedFormatError(ParseError):
    """Video format is not supported."""
    pass


class DownloadError(EdxDownloaderError):
    """Video download and file system errors."""

    def __init__(self, message: str, file_path: Optional[str] = None, video_id: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.file_path = file_path
        self.video_id = video_id


class DiskSpaceError(DownloadError):
    """Insufficient disk space for download."""
    pass


class FilePermissionError(DownloadError):
    """Insufficient permissions to write file."""
    pass


class DownloadInterruptedError(DownloadError):
    """Download was interrupted."""
    pass


class ConfigurationError(EdxDownloaderError):
    """Configuration and setup errors."""

    def __init__(self, message: str, config_key: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.config_key = config_key


class ValidationError(EdxDownloaderError):
    """Data validation errors."""

    def __init__(self, message: str, field_name: Optional[str] = None, field_value: Optional[Any] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.field_name = field_name
        self.field_value = field_value
