"""Unit tests for EDX downloader data models."""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from edx_downloader.models import (
    CourseInfo, VideoInfo, DownloadOptions, AuthSession, AppConfig
)


class TestCourseInfo:
    """Test CourseInfo model."""
    
    def test_valid_course_info(self):
        """Test creating valid course info."""
        course = CourseInfo(
            id="course-v1:MITx+6.00.1x+2T2017",
            title="Introduction to Computer Science",
            url="https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        assert course.id == "course-v1:MITx+6.00.1x+2T2017"
        assert course.title == "Introduction to Computer Science"
        assert course.is_accessible is True
        assert course.course_key == "course-v1:MITx+6.00.1x+2T2017"
    
    def test_invalid_course_id(self):
        """Test validation with invalid course ID."""
        with pytest.raises(ValueError, match="Course ID must be a non-empty string"):
            CourseInfo(
                id="",
                title="Test Course",
                url="https://courses.edx.org/test",
                enrollment_status="enrolled",
                access_level="full"
            )
    
    def test_invalid_url(self):
        """Test validation with invalid URL."""
        with pytest.raises(ValueError, match="Course URL must be a valid URL"):
            CourseInfo(
                id="test-course",
                title="Test Course",
                url="not-a-url",
                enrollment_status="enrolled",
                access_level="full"
            )
    
    def test_invalid_enrollment_status(self):
        """Test validation with invalid enrollment status."""
        with pytest.raises(ValueError, match="Invalid enrollment status"):
            CourseInfo(
                id="test-course",
                title="Test Course",
                url="https://courses.edx.org/test",
                enrollment_status="invalid",
                access_level="full"
            )
    
    def test_invalid_access_level(self):
        """Test validation with invalid access level."""
        with pytest.raises(ValueError, match="Invalid access level"):
            CourseInfo(
                id="test-course",
                title="Test Course",
                url="https://courses.edx.org/test",
                enrollment_status="enrolled",
                access_level="invalid"
            )
    
    def test_course_key_extraction(self):
        """Test course key extraction from different URL formats."""
        # Test /courses/ format
        course1 = CourseInfo(
            id="test-id",
            title="Test Course",
            url="https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/",
            enrollment_status="enrolled",
            access_level="full"
        )
        assert course1.course_key == "course-v1:MITx+6.00.1x+2T2017"
        
        # Test /course/ format
        course2 = CourseInfo(
            id="test-id",
            title="Test Course",
            url="https://courses.edx.org/course/course-v1:MITx+6.00.1x+2T2017/",
            enrollment_status="enrolled",
            access_level="full"
        )
        assert course2.course_key == "course-v1:MITx+6.00.1x+2T2017"
        
        # Test fallback to ID
        course3 = CourseInfo(
            id="fallback-id",
            title="Test Course",
            url="https://courses.edx.org/other/path/",
            enrollment_status="enrolled",
            access_level="full"
        )
        assert course3.course_key == "fallback-id"


class TestVideoInfo:
    """Test VideoInfo model."""
    
    def test_valid_video_info(self):
        """Test creating valid video info."""
        video = VideoInfo(
            id="video-123",
            title="Introduction Video",
            url="https://example.com/video.mp4",
            quality="720p",
            size=1024000,
            duration=300,
            course_section="Week 1"
        )
        
        assert video.id == "video-123"
        assert video.filename == "Introduction Video.mp4"
        assert video.size_mb == 0.98  # 1024000 bytes = ~0.98 MB
        assert video.duration_formatted == "05:00"
    
    def test_invalid_video_id(self):
        """Test validation with invalid video ID."""
        with pytest.raises(ValueError, match="Video ID must be a non-empty string"):
            VideoInfo(
                id="",
                title="Test Video",
                url="https://example.com/video.mp4",
                quality="720p"
            )
    
    def test_invalid_quality(self):
        """Test validation with invalid quality."""
        with pytest.raises(ValueError, match="Invalid quality"):
            VideoInfo(
                id="video-123",
                title="Test Video",
                url="https://example.com/video.mp4",
                quality="invalid"
            )
    
    def test_filename_sanitization(self):
        """Test filename sanitization."""
        video = VideoInfo(
            id="video-123",
            title="Video: With <Special> Characters/\\|?*",
            url="https://example.com/video.mp4",
            quality="720p"
        )
        assert video.filename == "Video_ With _Special_ Characters_____.mp4"
    
    def test_duration_formatting(self):
        """Test duration formatting."""
        # Test with hours
        video1 = VideoInfo(
            id="video-1",
            title="Long Video",
            url="https://example.com/video.mp4",
            quality="720p",
            duration=3661  # 1 hour, 1 minute, 1 second
        )
        assert video1.duration_formatted == "01:01:01"
        
        # Test without hours
        video2 = VideoInfo(
            id="video-2",
            title="Short Video",
            url="https://example.com/video.mp4",
            quality="720p",
            duration=61  # 1 minute, 1 second
        )
        assert video2.duration_formatted == "01:01"
        
        # Test None duration
        video3 = VideoInfo(
            id="video-3",
            title="Unknown Duration",
            url="https://example.com/video.mp4",
            quality="720p"
        )
        assert video3.duration_formatted is None


class TestDownloadOptions:
    """Test DownloadOptions model."""
    
    def test_valid_download_options(self):
        """Test creating valid download options."""
        options = DownloadOptions(
            output_directory="./downloads",
            quality_preference="720p",
            concurrent_downloads=5,
            resume_enabled=True,
            organize_by_section=True
        )
        
        assert options.output_directory == "./downloads"
        assert options.quality_preference == "720p"
        assert options.concurrent_downloads == 5
        assert isinstance(options.output_path, Path)
    
    def test_invalid_concurrent_downloads(self):
        """Test validation with invalid concurrent downloads."""
        with pytest.raises(ValueError, match="Concurrent downloads must be a positive integer"):
            DownloadOptions(concurrent_downloads=0)
        
        with pytest.raises(ValueError, match="Concurrent downloads should not exceed 10"):
            DownloadOptions(concurrent_downloads=15)
    
    def test_invalid_quality_preference(self):
        """Test validation with invalid quality preference."""
        with pytest.raises(ValueError, match="Invalid quality preference"):
            DownloadOptions(quality_preference="invalid")
    
    def test_create_output_directory(self, tmp_path):
        """Test output directory creation."""
        test_dir = tmp_path / "test_downloads"
        options = DownloadOptions(output_directory=str(test_dir))
        
        assert not test_dir.exists()
        options.create_output_directory()
        assert test_dir.exists()


class TestAuthSession:
    """Test AuthSession model."""
    
    def test_valid_auth_session(self):
        """Test creating valid auth session."""
        expires_at = datetime.now() + timedelta(hours=1)
        session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=expires_at,
            user_id="test-user"
        )
        
        assert session.csrf_token == "test-csrf-token"
        assert session.user_id == "test-user"
        assert not session.is_expired
        assert session.time_until_expiry > 0
        assert session.get_cookie_header() == "sessionid=test-session"
    
    def test_expired_session(self):
        """Test expired auth session."""
        expires_at = datetime.now() - timedelta(hours=1)
        session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=expires_at,
            user_id="test-user"
        )
        
        assert session.is_expired
        assert session.time_until_expiry == 0
    
    def test_invalid_csrf_token(self):
        """Test validation with invalid CSRF token."""
        with pytest.raises(ValueError, match="CSRF token must be a non-empty string"):
            AuthSession(
                csrf_token="",
                session_cookies={"sessionid": "test-session"},
                expires_at=datetime.now() + timedelta(hours=1),
                user_id="test-user"
            )
    
    def test_invalid_session_cookies(self):
        """Test validation with invalid session cookies."""
        with pytest.raises(ValueError, match="Session cookies must be a dictionary"):
            AuthSession(
                csrf_token="test-csrf-token",
                session_cookies="not-a-dict",
                expires_at=datetime.now() + timedelta(hours=1),
                user_id="test-user"
            )
    
    def test_cookie_header_multiple_cookies(self):
        """Test cookie header with multiple cookies."""
        session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={
                "sessionid": "test-session",
                "csrftoken": "test-csrf",
                "other": "value"
            },
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        
        cookie_header = session.get_cookie_header()
        assert "sessionid=test-session" in cookie_header
        assert "csrftoken=test-csrf" in cookie_header
        assert "other=value" in cookie_header


class TestAppConfig:
    """Test AppConfig model."""
    
    def test_valid_app_config(self):
        """Test creating valid app config."""
        config = AppConfig(
            credentials_file="~/.edxauth",
            cache_directory="~/.cache/edx-downloader",
            default_output_dir="./downloads",
            max_concurrent_downloads=5,
            rate_limit_delay=1.5,
            retry_attempts=3,
            video_quality_preference="720p"
        )
        
        assert config.credentials_file == "~/.edxauth"
        assert config.max_concurrent_downloads == 5
        assert config.rate_limit_delay == 1.5
        assert isinstance(config.credentials_path, Path)
        assert isinstance(config.cache_path, Path)
        assert isinstance(config.output_path, Path)
    
    def test_invalid_max_concurrent_downloads(self):
        """Test validation with invalid max concurrent downloads."""
        with pytest.raises(ValueError, match="Max concurrent downloads must be a positive integer"):
            AppConfig(max_concurrent_downloads=0)
        
        with pytest.raises(ValueError, match="Max concurrent downloads should not exceed 20"):
            AppConfig(max_concurrent_downloads=25)
    
    def test_invalid_rate_limit_delay(self):
        """Test validation with invalid rate limit delay."""
        with pytest.raises(ValueError, match="Rate limit delay must be a non-negative number"):
            AppConfig(rate_limit_delay=-1.0)
    
    def test_invalid_retry_attempts(self):
        """Test validation with invalid retry attempts."""
        with pytest.raises(ValueError, match="Retry attempts must be a non-negative integer"):
            AppConfig(retry_attempts=-1)
        
        with pytest.raises(ValueError, match="Retry attempts should not exceed 10"):
            AppConfig(retry_attempts=15)
    
    def test_invalid_video_quality_preference(self):
        """Test validation with invalid video quality preference."""
        with pytest.raises(ValueError, match="Invalid video quality preference"):
            AppConfig(video_quality_preference="invalid")
    
    def test_create_directories(self, tmp_path):
        """Test directory creation."""
        cache_dir = tmp_path / "cache"
        output_dir = tmp_path / "output"
        
        config = AppConfig(
            cache_directory=str(cache_dir),
            default_output_dir=str(output_dir)
        )
        
        assert not cache_dir.exists()
        assert not output_dir.exists()
        
        config.create_directories()
        
        assert cache_dir.exists()
        assert output_dir.exists()