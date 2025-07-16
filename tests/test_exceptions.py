"""Tests for exception classes."""

import pytest
from edx_downloader.exceptions import (
    EdxDownloaderError,
    AuthenticationError,
    InvalidCredentialsError,
    SessionExpiredError,
    TwoFactorRequiredError,
    CourseAccessError,
    CourseNotFoundError,
    EnrollmentRequiredError,
    CourseNotStartedError,
    CourseEndedError,
    NetworkError,
    ConnectionError,
    TimeoutError,
    RateLimitError,
    ServerError,
    ParseError,
    VideoNotFoundError,
    UnsupportedFormatError,
    DownloadError,
    DiskSpaceError,
    FilePermissionError,
    DownloadInterruptedError,
    ConfigurationError,
    ValidationError
)


class TestEdxDownloaderError:
    """Test base EdxDownloaderError."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = EdxDownloaderError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.details == {}

    def test_error_with_details(self):
        """Test error with details."""
        details = {"code": 500, "url": "https://example.com"}
        error = EdxDownloaderError("Test error", details)
        assert "code: 500" in str(error)
        assert "url: https://example.com" in str(error)
        assert error.details == details


class TestAuthenticationError:
    """Test AuthenticationError and subclasses."""

    def test_authentication_error(self):
        """Test basic AuthenticationError."""
        error = AuthenticationError("Login failed", username="testuser")
        assert str(error) == "Login failed"
        assert error.username == "testuser"
        assert isinstance(error, EdxDownloaderError)

    def test_invalid_credentials_error(self):
        """Test InvalidCredentialsError."""
        error = InvalidCredentialsError("Invalid username or password", username="testuser")
        assert isinstance(error, AuthenticationError)
        assert error.username == "testuser"

    def test_session_expired_error(self):
        """Test SessionExpiredError."""
        error = SessionExpiredError("Session has expired")
        assert isinstance(error, AuthenticationError)

    def test_two_factor_required_error(self):
        """Test TwoFactorRequiredError."""
        error = TwoFactorRequiredError("Two-factor authentication required")
        assert isinstance(error, AuthenticationError)


class TestCourseAccessError:
    """Test CourseAccessError and subclasses."""

    def test_course_access_error(self):
        """Test basic CourseAccessError."""
        error = CourseAccessError("Course not accessible", course_id="test-course")
        assert str(error) == "Course not accessible"
        assert error.course_id == "test-course"
        assert isinstance(error, EdxDownloaderError)

    def test_course_not_found_error(self):
        """Test CourseNotFoundError."""
        error = CourseNotFoundError("Course not found", course_id="missing-course")
        assert isinstance(error, CourseAccessError)
        assert error.course_id == "missing-course"

    def test_enrollment_required_error(self):
        """Test EnrollmentRequiredError."""
        error = EnrollmentRequiredError("Enrollment required")
        assert isinstance(error, CourseAccessError)

    def test_course_not_started_error(self):
        """Test CourseNotStartedError."""
        error = CourseNotStartedError("Course has not started")
        assert isinstance(error, CourseAccessError)

    def test_course_ended_error(self):
        """Test CourseEndedError."""
        error = CourseEndedError("Course has ended")
        assert isinstance(error, CourseAccessError)


class TestNetworkError:
    """Test NetworkError and subclasses."""

    def test_network_error(self):
        """Test basic NetworkError."""
        error = NetworkError("Connection failed", status_code=500, url="https://example.com")
        assert str(error) == "Connection failed"
        assert error.status_code == 500
        assert error.url == "https://example.com"
        assert isinstance(error, EdxDownloaderError)

    def test_connection_error(self):
        """Test ConnectionError."""
        error = ConnectionError("Failed to connect")
        assert isinstance(error, NetworkError)

    def test_timeout_error(self):
        """Test TimeoutError."""
        error = TimeoutError("Request timed out")
        assert isinstance(error, NetworkError)

    def test_rate_limit_error(self):
        """Test RateLimitError."""
        error = RateLimitError("Rate limit exceeded", status_code=429)
        assert isinstance(error, NetworkError)
        assert error.status_code == 429

    def test_server_error(self):
        """Test ServerError."""
        error = ServerError("Internal server error", status_code=500)
        assert isinstance(error, NetworkError)
        assert error.status_code == 500


class TestParseError:
    """Test ParseError and subclasses."""

    def test_parse_error(self):
        """Test basic ParseError."""
        error = ParseError("Failed to parse", content_type="text/html", url="https://example.com")
        assert str(error) == "Failed to parse"
        assert error.content_type == "text/html"
        assert error.url == "https://example.com"
        assert isinstance(error, EdxDownloaderError)

    def test_video_not_found_error(self):
        """Test VideoNotFoundError."""
        error = VideoNotFoundError("Video not found", url="https://example.com/video")
        assert isinstance(error, ParseError)
        assert error.url == "https://example.com/video"

    def test_unsupported_format_error(self):
        """Test UnsupportedFormatError."""
        error = UnsupportedFormatError("Unsupported video format", content_type="video/webm")
        assert isinstance(error, ParseError)
        assert error.content_type == "video/webm"


class TestDownloadError:
    """Test DownloadError and subclasses."""

    def test_download_error(self):
        """Test basic DownloadError."""
        error = DownloadError("Download failed", file_path="/path/to/file", video_id="video-123")
        assert str(error) == "Download failed"
        assert error.file_path == "/path/to/file"
        assert error.video_id == "video-123"
        assert isinstance(error, EdxDownloaderError)

    def test_disk_space_error(self):
        """Test DiskSpaceError."""
        error = DiskSpaceError("Insufficient disk space", file_path="/path/to/file")
        assert isinstance(error, DownloadError)
        assert error.file_path == "/path/to/file"

    def test_file_permission_error(self):
        """Test FilePermissionError."""
        error = FilePermissionError("Permission denied", file_path="/path/to/file")
        assert isinstance(error, DownloadError)
        assert error.file_path == "/path/to/file"

    def test_download_interrupted_error(self):
        """Test DownloadInterruptedError."""
        error = DownloadInterruptedError("Download interrupted", video_id="video-123")
        assert isinstance(error, DownloadError)
        assert error.video_id == "video-123"


class TestConfigurationError:
    """Test ConfigurationError."""

    def test_configuration_error(self):
        """Test ConfigurationError."""
        error = ConfigurationError("Invalid configuration", config_key="max_downloads")
        assert str(error) == "Invalid configuration"
        assert error.config_key == "max_downloads"
        assert isinstance(error, EdxDownloaderError)


class TestValidationError:
    """Test ValidationError."""

    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Invalid value", field_name="quality", field_value="invalid")
        assert str(error) == "Invalid value"
        assert error.field_name == "quality"
        assert error.field_value == "invalid"
        assert isinstance(error, EdxDownloaderError)