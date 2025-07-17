"""
Test utilities for mocking EDX responses and file operations.

This module provides utilities for creating mock responses, test data,
and helper functions for testing the EDX downloader.
"""

import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, MagicMock
from edx_downloader.models import CourseInfo, VideoInfo, AppConfig


class TestFileManager:
    """Utility for managing test files and directories."""
    
    def __init__(self):
        """Initialize test file manager."""
        self.temp_dirs = []
        self.temp_files = []
    
    def create_temp_dir(self) -> Path:
        """Create a temporary directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        self.temp_dirs.append(temp_dir)
        return temp_dir
    
    def create_temp_file(self, content: str = "", suffix: str = ".txt") -> Path:
        """Create a temporary file with content."""
        temp_file = Path(tempfile.mktemp(suffix=suffix))
        temp_file.write_text(content)
        self.temp_files.append(temp_file)
        return temp_file
    
    def create_mock_video_file(self, filepath: Path, size_mb: int = 1) -> Path:
        """Create a mock video file of specified size."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file with specified size
        content = b'0' * (size_mb * 1024 * 1024)
        with open(filepath, 'wb') as f:
            f.write(content)
        
        self.temp_files.append(filepath)
        return filepath
    
    def cleanup(self):
        """Clean up all temporary files and directories."""
        for temp_file in self.temp_files:
            if temp_file.exists():
                temp_file.unlink()
        
        for temp_dir in self.temp_dirs:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        
        self.temp_dirs.clear()
        self.temp_files.clear()


class MockHttpResponse:
    """Mock HTTP response for testing."""
    
    def __init__(self, status_code: int = 200, json_data: Optional[Dict] = None, 
                 text_data: str = "", headers: Optional[Dict] = None):
        """Initialize mock response."""
        self.status_code = status_code
        self._json_data = json_data
        self.text = text_data
        self.headers = headers or {}
        self.content = text_data.encode() if text_data else b''
    
    def json(self):
        """Return JSON data."""
        if self._json_data is None:
            raise ValueError("No JSON data available")
        return self._json_data
    
    def raise_for_status(self):
        """Raise exception for bad status codes."""
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code} Error")


class MockEdxSession:
    """Mock EDX session for testing API interactions."""
    
    def __init__(self):
        """Initialize mock session."""
        self.responses = {}
        self.request_history = []
        self.cookies = {}
        self.headers = {}
    
    def add_response(self, url_pattern: str, response: MockHttpResponse):
        """Add a response for a URL pattern."""
        self.responses[url_pattern] = response
    
    def get(self, url: str, **kwargs) -> MockHttpResponse:
        """Mock GET request."""
        self.request_history.append(('GET', url, kwargs))
        
        # Find matching response
        for pattern, response in self.responses.items():
            if pattern in url:
                return response
        
        # Default 404 response
        return MockHttpResponse(404, {"error": "Not found"})
    
    def post(self, url: str, **kwargs) -> MockHttpResponse:
        """Mock POST request."""
        self.request_history.append(('POST', url, kwargs))
        
        # Find matching response
        for pattern, response in self.responses.items():
            if pattern in url:
                return response
        
        # Default 404 response
        return MockHttpResponse(404, {"error": "Not found"})


class TestDataBuilder:
    """Builder for creating test data objects."""
    
    @staticmethod
    def create_course_info(course_id: str = "course-v1:TestX+TEST101+2024",
                          name: str = "Test Course") -> CourseInfo:
        """Create a test CourseInfo object."""
        return CourseInfo(
            course_id=course_id,
            name=name,
            org="TestX",
            number="TEST101",
            run="2024",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-12-31T23:59:59Z"
        )
    
    @staticmethod
    def create_video_info(video_id: str = "video1", title: str = "Test Video") -> VideoInfo:
        """Create a test VideoInfo object."""
        return VideoInfo(
            video_id=video_id,
            title=title,
            duration=600,
            video_urls={
                "desktop_mp4": "https://example.com/video1.mp4",
                "mobile_low": "https://example.com/video1_mobile.mp4"
            },
            transcript_url="https://example.com/video1_transcript.srt"
        )
    
    @staticmethod
    def create_test_config(temp_dir: Optional[Path] = None) -> AppConfig:
        """Create a test AppConfig object."""
        if temp_dir is None:
            temp_dir = Path(tempfile.mkdtemp())
        
        return AppConfig(
            cache_directory=str(temp_dir / "cache"),
            default_output_dir=str(temp_dir / "downloads"),
            max_concurrent_downloads=2,
            rate_limit_delay=0.1
        )


class MockDownloadManager:
    """Mock download manager for testing."""
    
    def __init__(self):
        """Initialize mock download manager."""
        self.downloaded_files = []
        self.download_failures = []
        self.download_delay = 0.0
    
    def set_download_delay(self, delay: float):
        """Set artificial delay for downloads."""
        self.download_delay = delay
    
    def add_download_failure(self, url: str):
        """Add a URL that should fail to download."""
        self.download_failures.append(url)
    
    def mock_download_file(self, url: str, filepath: Path, **kwargs) -> bool:
        """Mock file download."""
        import time
        
        if self.download_delay > 0:
            time.sleep(self.download_delay)
        
        if url in self.download_failures:
            raise Exception(f"Download failed for {url}")
        
        # Create mock file
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(f"Mock content for {url}".encode())
        
        self.downloaded_files.append(str(filepath))
        return True


class TestAssertions:
    """Custom assertions for testing EDX downloader."""
    
    @staticmethod
    def assert_video_file_exists(filepath: Path, min_size: int = 0):
        """Assert that a video file exists and has minimum size."""
        assert filepath.exists(), f"Video file does not exist: {filepath}"
        assert filepath.stat().st_size >= min_size, \
            f"Video file too small: {filepath.stat().st_size} bytes"
    
    @staticmethod
    def assert_course_structure(download_dir: Path, expected_chapters: int):
        """Assert that course directory structure is correct."""
        assert download_dir.exists(), f"Download directory does not exist: {download_dir}"
        
        # Count chapter directories
        chapter_dirs = [d for d in download_dir.iterdir() if d.is_dir()]
        assert len(chapter_dirs) >= expected_chapters, \
            f"Expected at least {expected_chapters} chapters, found {len(chapter_dirs)}"
    
    @staticmethod
    def assert_api_calls_made(mock_session: MockEdxSession, expected_calls: List[str]):
        """Assert that expected API calls were made."""
        made_calls = [call[1] for call in mock_session.request_history]
        
        for expected_call in expected_calls:
            matching_calls = [call for call in made_calls if expected_call in call]
            assert len(matching_calls) > 0, \
                f"Expected API call not made: {expected_call}"
    
    @staticmethod
    def assert_performance_within_limits(duration: float, max_duration: float, 
                                       operation: str):
        """Assert that operation completed within time limits."""
        assert duration <= max_duration, \
            f"{operation} took too long: {duration:.3f}s (max: {max_duration:.3f}s)"


class TestScenarios:
    """Pre-built test scenarios for common testing patterns."""
    
    @staticmethod
    def setup_successful_download_scenario(mock_session: MockEdxSession):
        """Set up a scenario where all downloads succeed."""
        from tests.fixtures.edx_responses import EdxApiResponseFixtures
        
        # Login page
        mock_session.add_response(
            "login",
            MockHttpResponse(200, text_data=EdxApiResponseFixtures.get_login_page_html())
        )
        
        # Successful login
        mock_session.add_response(
            "login_session",
            MockHttpResponse(200, EdxApiResponseFixtures.get_login_success_response())
        )
        
        # Course list
        mock_session.add_response(
            "courses",
            MockHttpResponse(200, EdxApiResponseFixtures.get_course_list_response())
        )
        
        # Course outline
        mock_session.add_response(
            "blocks",
            MockHttpResponse(200, EdxApiResponseFixtures.get_course_outline_response())
        )
    
    @staticmethod
    def setup_authentication_failure_scenario(mock_session: MockEdxSession):
        """Set up a scenario where authentication fails."""
        from tests.fixtures.edx_responses import EdxApiResponseFixtures
        
        # Login page
        mock_session.add_response(
            "login",
            MockHttpResponse(200, text_data=EdxApiResponseFixtures.get_login_page_html())
        )
        
        # Failed login
        mock_session.add_response(
            "login_session",
            MockHttpResponse(401, EdxApiResponseFixtures.get_error_response_401())
        )
    
    @staticmethod
    def setup_network_error_scenario(mock_session: MockEdxSession):
        """Set up a scenario with network errors."""
        # All requests fail with network error
        error_response = MockHttpResponse(500, {"error": "Network error"})
        mock_session.add_response("", error_response)


class PerformanceProfiler:
    """Utility for profiling performance during tests."""
    
    def __init__(self):
        """Initialize profiler."""
        self.measurements = {}
        self.start_times = {}
    
    def start_measurement(self, operation: str):
        """Start measuring an operation."""
        import time
        self.start_times[operation] = time.time()
    
    def end_measurement(self, operation: str) -> float:
        """End measuring an operation and return duration."""
        import time
        
        if operation not in self.start_times:
            raise ValueError(f"No start time recorded for operation: {operation}")
        
        duration = time.time() - self.start_times[operation]
        self.measurements[operation] = duration
        del self.start_times[operation]
        
        return duration
    
    def get_measurement(self, operation: str) -> float:
        """Get measurement for an operation."""
        return self.measurements.get(operation, 0.0)
    
    def get_all_measurements(self) -> Dict[str, float]:
        """Get all measurements."""
        return self.measurements.copy()
    
    def assert_performance_targets(self, targets: Dict[str, float]):
        """Assert that all operations meet performance targets."""
        for operation, max_duration in targets.items():
            actual_duration = self.measurements.get(operation, float('inf'))
            assert actual_duration <= max_duration, \
                f"{operation} exceeded target: {actual_duration:.3f}s > {max_duration:.3f}s"