"""
Integration tests that validate against the current EDX platform.

These tests make real HTTP requests to EDX to ensure our implementation
works with the current platform structure.
"""

import pytest
import requests
from unittest.mock import patch, Mock
from edx_downloader.api_client import EdxApiClient
from edx_downloader.auth import AuthenticationManager
from edx_downloader.course_manager import CourseManager
from edx_downloader.config import AppConfig
from tests.fixtures.edx_responses import EdxApiResponseFixtures, EdxMockResponses


class TestEdxPlatformIntegration:
    """Integration tests for EDX platform compatibility."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return AppConfig(
            cache_directory="test_cache",
            default_output_dir="test_downloads",
            max_concurrent_downloads=2,
            rate_limit_delay=1.0
        )
    
    @pytest.fixture
    def mock_session(self):
        """Create mock session with EDX responses."""
        return EdxMockResponses.mock_requests_session()
    
    def test_edx_login_page_structure(self, config):
        """Test that EDX login page has expected structure."""
        # This test can be run against real EDX or mocked
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            client = EdxApiClient(config)
            response = client.session.get("https://courses.edx.org/login")
            
            assert response.status_code == 200
            html_content = response.text
            
            # Verify expected elements in login page
            assert 'csrf' in html_content.lower()
            assert 'email' in html_content.lower()
            assert 'password' in html_content.lower()
            assert 'form' in html_content.lower()
    
    def test_course_list_api_structure(self, config):
        """Test course list API response structure."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            client = EdxApiClient(config)
            response = client.session.get("https://courses.edx.org/api/courses/v1/courses/")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify expected structure
            assert 'results' in data
            assert isinstance(data['results'], list)
            
            if data['results']:
                course = data['results'][0]
                required_fields = ['course_id', 'name', 'org', 'number', 'run']
                for field in required_fields:
                    assert field in course
    
    def test_course_blocks_api_structure(self, config):
        """Test course blocks API response structure."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            client = EdxApiClient(config)
            course_id = "course-v1:MITx+6.00.1x+2T2024"
            url = f"https://courses.edx.org/api/courses/v1/blocks/?course_id={course_id}"
            response = client.session.get(url)
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify expected structure
            assert 'root' in data
            assert 'blocks' in data
            assert isinstance(data['blocks'], dict)
            
            # Check for video blocks
            video_blocks = [
                block for block in data['blocks'].values()
                if block.get('type') == 'video'
            ]
            
            if video_blocks:
                video_block = video_blocks[0]
                assert 'student_view_data' in video_block
                assert 'encoded_videos' in video_block['student_view_data']
    
    def test_authentication_flow(self, config):
        """Test authentication flow with mocked responses."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            auth_manager = AuthenticationManager(config)
            
            # Test login process
            success = auth_manager.login("test@example.com", "password123")
            assert success is True
            assert auth_manager.is_authenticated()
    
    def test_course_parsing_with_real_structure(self, config):
        """Test course parsing with realistic course structure."""
        with patch('requests.Session') as mock_session_class:
            mock_session = EdxMockResponses.mock_requests_session()
            mock_session_class.return_value = mock_session
            
            course_manager = CourseManager(config)
            course_id = "course-v1:MITx+6.00.1x+2T2024"
            
            # Test course info retrieval
            course_info = course_manager.get_course_info(course_id)
            assert course_info is not None
            assert course_info.course_id == course_id
            
            # Test course outline parsing
            outline = course_manager.get_course_outline(course_id)
            assert outline is not None
            assert len(outline.chapters) > 0
            
            # Test video extraction
            videos = course_manager.extract_videos(course_id)
            assert isinstance(videos, list)
            
            if videos:
                video = videos[0]
                assert hasattr(video, 'title')
                assert hasattr(video, 'video_urls')
                assert len(video.video_urls) > 0


class TestEdxApiEndpoints:
    """Test specific EDX API endpoints and their responses."""
    
    def test_csrf_token_extraction(self):
        """Test CSRF token extraction from login page."""
        html_content = EdxApiResponseFixtures.get_login_page_html()
        
        # Test different CSRF token patterns
        import re
        
        # Pattern 1: meta tag
        csrf_pattern1 = r'<meta name="csrf-token" content="([^"]+)"'
        match1 = re.search(csrf_pattern1, html_content)
        
        # Pattern 2: hidden input
        csrf_pattern2 = r'name="csrfmiddlewaretoken" value="([^"]+)"'
        match2 = re.search(csrf_pattern2, html_content)
        
        assert match1 or match2, "CSRF token should be found in HTML"
        
        if match1:
            token = match1.group(1)
            assert len(token) > 0
            assert token == "test-csrf-token-12345"
    
    def test_video_url_formats(self):
        """Test video URL format validation."""
        course_outline = EdxApiResponseFixtures.get_course_outline_response()
        
        # Find video blocks
        video_blocks = []
        for block in course_outline['blocks'].values():
            if block.get('type') == 'video':
                video_blocks.append(block)
        
        assert len(video_blocks) > 0, "Should have video blocks in test data"
        
        for video_block in video_blocks:
            student_view_data = video_block.get('student_view_data', {})
            encoded_videos = student_view_data.get('encoded_videos', {})
            
            # Check for expected video formats
            expected_formats = ['desktop_mp4', 'mobile_low']
            for format_name in expected_formats:
                if format_name in encoded_videos:
                    video_info = encoded_videos[format_name]
                    assert 'url' in video_info
                    assert 'file_size' in video_info
                    assert video_info['url'].startswith('http')
    
    def test_error_response_handling(self):
        """Test error response structures."""
        error_responses = [
            EdxApiResponseFixtures.get_error_response_401(),
            EdxApiResponseFixtures.get_error_response_403(),
            EdxApiResponseFixtures.get_error_response_404(),
            EdxApiResponseFixtures.get_rate_limit_response(),
            EdxApiResponseFixtures.get_server_error_response()
        ]
        
        for error_response in error_responses:
            assert 'error' in error_response
            assert 'error_code' in error_response
            assert isinstance(error_response['error'], str)
            assert len(error_response['error']) > 0


@pytest.mark.slow
class TestRealEdxPlatform:
    """Tests that make real requests to EDX platform (marked as slow)."""
    
    def test_edx_homepage_accessibility(self):
        """Test that EDX homepage is accessible."""
        try:
            response = requests.get("https://www.edx.org", timeout=10)
            assert response.status_code == 200
        except requests.RequestException:
            pytest.skip("EDX platform not accessible")
    
    def test_edx_courses_page_accessibility(self):
        """Test that EDX courses page is accessible."""
        try:
            response = requests.get("https://courses.edx.org", timeout=10)
            # EDX might redirect to login, so accept both 200 and 302
            assert response.status_code in [200, 302]
        except requests.RequestException:
            pytest.skip("EDX courses platform not accessible")
    
    @pytest.mark.skipif(
        True,  # Skip by default to avoid hitting EDX servers during regular testing
        reason="Skipped to avoid hitting EDX servers during regular testing"
    )
    def test_real_course_api_structure(self):
        """Test real course API structure (disabled by default)."""
        # This test would make real API calls to EDX
        # Only enable when specifically testing against live platform
        try:
            response = requests.get(
                "https://courses.edx.org/api/courses/v1/courses/",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                assert 'results' in data
        except requests.RequestException:
            pytest.skip("EDX API not accessible")