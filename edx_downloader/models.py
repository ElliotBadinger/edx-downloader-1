"""Data models for EDX downloader."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse
import re


@dataclass
class CourseInfo:
    """Information about an EDX course."""

    id: str
    title: str
    url: str
    enrollment_status: str
    access_level: str
    
    def __post_init__(self):
        """Validate course information after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate course information."""
        if not self.id or not isinstance(self.id, str):
            raise ValueError("Course ID must be a non-empty string")
        
        if not self.title or not isinstance(self.title, str):
            raise ValueError("Course title must be a non-empty string")
        
        if not self.url or not isinstance(self.url, str):
            raise ValueError("Course URL must be a non-empty string")
        
        # Validate URL format
        parsed = urlparse(self.url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Course URL must be a valid URL")
        
        # Validate enrollment status
        valid_statuses = ["enrolled", "not_enrolled", "audit", "verified", "honor"]
        if self.enrollment_status not in valid_statuses:
            raise ValueError(f"Invalid enrollment status: {self.enrollment_status}")
        
        # Validate access level
        valid_access = ["full", "audit", "limited", "none"]
        if self.access_level not in valid_access:
            raise ValueError(f"Invalid access level: {self.access_level}")
    
    @property
    def is_accessible(self) -> bool:
        """Check if course content is accessible."""
        return self.access_level in ["full", "audit"]
    
    @property
    def course_key(self) -> str:
        """Extract course key from URL or ID."""
        # Try to extract from URL first
        if "/courses/" in self.url:
            # Extract from URL like: /courses/course-v1:MITx+6.00.1x+2T2017/course/
            parts = self.url.split("/courses/")[1].split("/")
            if parts:
                return parts[0]
        elif "/course/" in self.url:
            # Extract from URL like: /course/course-v1:MITx+6.00.1x+2T2017/
            parts = self.url.split("/course/")[1].split("/")
            if parts:
                return parts[0]
        return self.id


@dataclass
class VideoInfo:
    """Information about a course video."""

    id: str
    title: str
    url: str
    quality: str
    size: Optional[int] = None
    duration: Optional[int] = None
    course_section: str = ""
    format: str = "mp4"
    
    def __post_init__(self):
        """Validate video information after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate video information."""
        if not self.id or not isinstance(self.id, str):
            raise ValueError("Video ID must be a non-empty string")
        
        if not self.title or not isinstance(self.title, str):
            raise ValueError("Video title must be a non-empty string")
        
        if not self.url or not isinstance(self.url, str):
            raise ValueError("Video URL must be a non-empty string")
        
        # Validate URL format
        parsed = urlparse(self.url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Video URL must be a valid URL")
        
        # Validate quality
        valid_qualities = [
            "highest", "high", "medium", "low", 
            "2160p", "1440p", "1080p", "720p", "480p", "360p", "240p", "144p",
            "youtube", "vimeo", "unknown"
        ]
        if self.quality not in valid_qualities:
            raise ValueError(f"Invalid quality: {self.quality}")
        
        # Validate size if provided
        if self.size is not None and (not isinstance(self.size, int) or self.size < 0):
            raise ValueError("Video size must be a non-negative integer")
        
        # Validate duration if provided
        if self.duration is not None and (not isinstance(self.duration, int) or self.duration < 0):
            raise ValueError("Video duration must be a non-negative integer")
    
    @property
    def filename(self) -> str:
        """Generate safe filename for the video."""
        # Remove invalid characters for filenames
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', self.title)
        return f"{safe_title}.{self.format}"
    
    @property
    def size_mb(self) -> Optional[float]:
        """Get video size in MB."""
        if self.size is None:
            return None
        return round(self.size / (1024 * 1024), 2)
    
    @property
    def duration_formatted(self) -> Optional[str]:
        """Get formatted duration string."""
        if self.duration is None:
            return None
        
        hours = self.duration // 3600
        minutes = (self.duration % 3600) // 60
        seconds = self.duration % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"


@dataclass
class DownloadOptions:
    """Configuration options for downloads."""

    output_directory: str = "./downloads"
    quality_preference: str = "highest"
    concurrent_downloads: int = 3
    resume_enabled: bool = True
    organize_by_section: bool = True
    
    def __post_init__(self):
        """Validate download options after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate download options."""
        if not self.output_directory or not isinstance(self.output_directory, str):
            raise ValueError("Output directory must be a non-empty string")
        
        # Validate quality preference
        valid_qualities = ["highest", "high", "medium", "low", "720p", "480p", "360p", "240p"]
        if self.quality_preference not in valid_qualities:
            raise ValueError(f"Invalid quality preference: {self.quality_preference}")
        
        # Validate concurrent downloads
        if not isinstance(self.concurrent_downloads, int) or self.concurrent_downloads < 1:
            raise ValueError("Concurrent downloads must be a positive integer")
        
        if self.concurrent_downloads > 10:
            raise ValueError("Concurrent downloads should not exceed 10 to avoid server overload")
        
        # Validate boolean fields
        if not isinstance(self.resume_enabled, bool):
            raise ValueError("Resume enabled must be a boolean")
        
        if not isinstance(self.organize_by_section, bool):
            raise ValueError("Organize by section must be a boolean")
    
    @property
    def output_path(self) -> Path:
        """Get output directory as Path object."""
        return Path(self.output_directory).expanduser().resolve()
    
    def create_output_directory(self) -> None:
        """Create output directory if it doesn't exist."""
        self.output_path.mkdir(parents=True, exist_ok=True)


@dataclass
class AuthSession:
    """Authentication session information."""

    csrf_token: str
    session_cookies: Dict[str, str]
    expires_at: datetime
    user_id: str
    
    def __post_init__(self):
        """Validate authentication session after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate authentication session."""
        if not self.csrf_token or not isinstance(self.csrf_token, str):
            raise ValueError("CSRF token must be a non-empty string")
        
        if not isinstance(self.session_cookies, dict):
            raise ValueError("Session cookies must be a dictionary")
        
        if not self.user_id or not isinstance(self.user_id, str):
            raise ValueError("User ID must be a non-empty string")
        
        if not isinstance(self.expires_at, datetime):
            raise ValueError("Expires at must be a datetime object")
    
    @property
    def is_expired(self) -> bool:
        """Check if the session has expired."""
        return datetime.now() >= self.expires_at
    
    @property
    def time_until_expiry(self) -> int:
        """Get seconds until session expires."""
        if self.is_expired:
            return 0
        return int((self.expires_at - datetime.now()).total_seconds())
    
    def get_cookie_header(self) -> str:
        """Get cookies formatted for HTTP header."""
        return "; ".join([f"{k}={v}" for k, v in self.session_cookies.items()])


@dataclass
class AppConfig:
    """Application configuration."""

    credentials_file: str = "~/.edxauth"
    cache_directory: str = "~/.cache/edx-downloader"
    default_output_dir: str = "./downloads"
    max_concurrent_downloads: int = 3
    rate_limit_delay: float = 1.0
    retry_attempts: int = 3
    video_quality_preference: str = "highest"
    
    # NEW: API endpoint configuration for different EDX instances
    api_endpoints: Dict[str, str] = field(default_factory=lambda: {
        'course_blocks': '/api/courses/v1/blocks/',
        'course_info': '/api/courses/v1/courses/{course_id}/',
        'enrollment': '/api/enrollment/v1/enrollment',
        'oauth_token': '/oauth2/access_token',
        'user_info': '/api/user/v1/me',
        'video_analytics': '/api/v0/courses/{course_id}/videos/'
    })
    
    def __post_init__(self):
        """Validate application configuration after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate application configuration."""
        if not self.credentials_file or not isinstance(self.credentials_file, str):
            raise ValueError("Credentials file must be a non-empty string")
        
        if not self.cache_directory or not isinstance(self.cache_directory, str):
            raise ValueError("Cache directory must be a non-empty string")
        
        if not self.default_output_dir or not isinstance(self.default_output_dir, str):
            raise ValueError("Default output directory must be a non-empty string")
        
        # Validate max concurrent downloads
        if not isinstance(self.max_concurrent_downloads, int) or self.max_concurrent_downloads < 1:
            raise ValueError("Max concurrent downloads must be a positive integer")
        
        if self.max_concurrent_downloads > 20:
            raise ValueError("Max concurrent downloads should not exceed 20")
        
        # Validate rate limit delay
        if not isinstance(self.rate_limit_delay, (int, float)) or self.rate_limit_delay < 0:
            raise ValueError("Rate limit delay must be a non-negative number")
        
        # Validate retry attempts
        if not isinstance(self.retry_attempts, int) or self.retry_attempts < 0:
            raise ValueError("Retry attempts must be a non-negative integer")
        
        if self.retry_attempts > 10:
            raise ValueError("Retry attempts should not exceed 10")
        
        # Validate video quality preference
        valid_qualities = ["highest", "high", "medium", "low", "720p", "480p", "360p", "240p"]
        if self.video_quality_preference not in valid_qualities:
            raise ValueError(f"Invalid video quality preference: {self.video_quality_preference}")
    
    @property
    def credentials_path(self) -> Path:
        """Get credentials file path as Path object."""
        return Path(self.credentials_file).expanduser().resolve()
    
    @property
    def cache_path(self) -> Path:
        """Get cache directory path as Path object."""
        return Path(self.cache_directory).expanduser().resolve()
    
    @property
    def output_path(self) -> Path:
        """Get default output directory path as Path object."""
        return Path(self.default_output_dir).expanduser().resolve()
    
    def create_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.output_path.mkdir(parents=True, exist_ok=True)
