"""Unit tests for course manager."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from bs4 import BeautifulSoup

from edx_downloader.course_manager import CourseManager
from edx_downloader.api_client import EdxApiClient
from edx_downloader.models import CourseInfo, VideoInfo, AppConfig
from edx_downloader.exceptions import (
    CourseNotFoundError, CourseAccessError, EnrollmentRequiredError,
    ParseError, NetworkError
)


class TestCourseManager:
    """Test course manager functionality."""
    
    def setup_method(self):
        """Set up test course manager."""
        self.config = AppConfig()
        self.api_client = Mock(spec=EdxApiClient)
        self.api_client.base_url = "https://courses.edx.org"
        self.course_manager = CourseManager(self.api_client)
    
    @pytest.mark.asyncio
    async def test_parse_course_url_courses_format(self):
        """Test parsing course URL in /courses/ format."""
        url = "https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/"
        course_id = await self.course_manager.parse_course_url(url)
        assert course_id == "course-v1:MITx+6.00.1x+2T2017"
    
    @pytest.mark.asyncio
    async def test_parse_course_url_course_format(self):
        """Test parsing course URL in /course/ format."""
        url = "https://courses.edx.org/course/course-v1:MITx+6.00.1x+2T2017/"
        course_id = await self.course_manager.parse_course_url(url)
        assert course_id == "course-v1:MITx+6.00.1x+2T2017"
    
    @pytest.mark.asyncio
    async def test_parse_course_url_query_param(self):
        """Test parsing course URL with query parameter."""
        url = "https://courses.edx.org/dashboard?course_id=course-v1:MITx+6.00.1x+2T2017"
        course_id = await self.course_manager.parse_course_url(url)
        assert course_id == "course-v1:MITx 6.00.1x 2T2017"
    
    @pytest.mark.asyncio
    async def test_parse_course_url_invalid(self):
        """Test parsing invalid course URL."""
        url = "https://courses.edx.org/invalid/path"
        with pytest.raises(CourseNotFoundError, match="Could not extract course ID"):
            await self.course_manager.parse_course_url(url)
    
    @pytest.mark.asyncio
    async def test_get_course_info_json_response(self):
        """Test getting course info from JSON API response."""
        course_url = "https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/"
        
        # Mock API response
        api_response = {
            'name': 'Introduction to Computer Science',
            'enrollment': {'is_active': True, 'mode': 'verified'},
            'can_access_course': True
        }
        self.api_client.get = AsyncMock(return_value=api_response)
        
        course_info = await self.course_manager.get_course_info(course_url)
        
        assert course_info.id == "course-v1:MITx+6.00.1x+2T2017"
        assert course_info.title == "Introduction to Computer Science"
        assert course_info.enrollment_status == "verified"
        assert course_info.access_level == "full"
    
    @pytest.mark.asyncio
    async def test_get_course_info_html_response(self):
        """Test getting course info from HTML response."""
        course_url = "https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/"
        
        html_content = '''
        <html>
        <head><title>Introduction to Computer Science</title></head>
        <body>
            <h1 class="course-title">Introduction to Computer Science</h1>
            <div class="enrollment-info">You are enrolled</div>
        </body>
        </html>
        '''
        
        api_response = {
            'content': html_content,
            'content_type': 'html'
        }
        self.api_client.get = AsyncMock(return_value=api_response)
        
        course_info = await self.course_manager.get_course_info(course_url)
        
        assert course_info.id == "course-v1:MITx+6.00.1x+2T2017"
        assert course_info.title == "Introduction to Computer Science"
        assert course_info.enrollment_status == "not_enrolled"  # Default when no clear enrollment indicator
    
    @pytest.mark.asyncio
    async def test_get_course_info_not_found(self):
        """Test getting course info when course is not found."""
        course_url = "https://courses.edx.org/courses/course-v1:NotFound+Course+2023/course/"
        
        # Mock 404 response
        self.api_client.get = AsyncMock(side_effect=NetworkError("Not found", status_code=404))
        
        with pytest.raises(CourseNotFoundError, match="Course not found"):
            await self.course_manager.get_course_info(course_url)
    
    @pytest.mark.asyncio
    async def test_get_course_info_access_denied(self):
        """Test getting course info when access is denied."""
        course_url = "https://courses.edx.org/courses/course-v1:Private+Course+2023/course/"
        
        # Mock 403 response
        self.api_client.get = AsyncMock(side_effect=NetworkError("Forbidden", status_code=403))
        
        with pytest.raises(CourseAccessError, match="Access denied"):
            await self.course_manager.get_course_info(course_url)
    
    def test_parse_course_info_from_json(self):
        """Test parsing course info from JSON data."""
        course_data = {
            'name': 'Test Course',
            'display_name': 'Test Course Display',
            'enrollment': {'is_active': True, 'mode': 'audit'},
            'can_access_course': True
        }
        
        course_info = self.course_manager._parse_course_info_from_json(
            course_data, 
            "https://example.com/course", 
            "test-course-id"
        )
        
        assert course_info.title == "Test Course"
        assert course_info.enrollment_status == "audit"
        assert course_info.access_level == "audit"
    
    def test_extract_course_title(self):
        """Test extracting course title from HTML."""
        html = '''
        <html>
        <body>
            <h1 class="course-title">Advanced Python Programming</h1>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        title = self.course_manager._extract_course_title(soup)
        assert title == "Advanced Python Programming"
    
    def test_extract_course_title_fallback(self):
        """Test extracting course title with fallback selectors."""
        html = '''
        <html>
        <head><title>Machine Learning Course - EdX</title></head>
        <body>
            <h1>Machine Learning Course</h1>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        title = self.course_manager._extract_course_title(soup)
        assert title == "Machine Learning Course"
    
    def test_extract_enrollment_status(self):
        """Test extracting enrollment status from HTML."""
        html = '''
        <html>
        <body>
            <div class="enrollment-status" data-status="enrolled">
                You are enrolled in this course
            </div>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        status = self.course_manager._extract_enrollment_status(soup)
        assert status == "enrolled"
    
    def test_extract_enrollment_status_text_based(self):
        """Test extracting enrollment status from text content."""
        html = '''
        <html>
        <body>
            <p>You are enrolled in this course with verified certificate.</p>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        status = self.course_manager._extract_enrollment_status(soup)
        assert status == "enrolled"
    
    def test_extract_access_level(self):
        """Test extracting access level from HTML."""
        html = '''
        <html>
        <body>
            <p>This is an audit track course with limited access.</p>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        access_level = self.course_manager._extract_access_level(soup)
        assert access_level == "audit"
    
    def test_determine_enrollment_status(self):
        """Test determining enrollment status from course data."""
        # Test active enrollment
        data1 = {'enrollment': {'is_active': True, 'mode': 'verified'}}
        status1 = self.course_manager._determine_enrollment_status(data1)
        assert status1 == "verified"
        
        # Test is_enrolled flag
        data2 = {'is_enrolled': True}
        status2 = self.course_manager._determine_enrollment_status(data2)
        assert status2 == "enrolled"
        
        # Test not enrolled
        data3 = {}
        status3 = self.course_manager._determine_enrollment_status(data3)
        assert status3 == "not_enrolled"
    
    def test_determine_access_level(self):
        """Test determining access level from course data."""
        # Test full access
        data1 = {'can_access_course': True, 'enrollment': {'mode': 'verified'}}
        level1 = self.course_manager._determine_access_level(data1)
        assert level1 == "full"
        
        # Test audit access
        data2 = {'can_access_course': True, 'enrollment': {'mode': 'audit'}}
        level2 = self.course_manager._determine_access_level(data2)
        assert level2 == "audit"
        
        # Test limited access
        data3 = {'can_access_course': False}
        level3 = self.course_manager._determine_access_level(data3)
        assert level3 == "limited"
    
    @pytest.mark.asyncio
    async def test_get_course_outline_api(self):
        """Test getting course outline from API."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        outline_data = {
            'blocks': {
                'block-1': {
                    'id': 'block-1',
                    'type': 'sequential',
                    'display_name': 'Week 1',
                    'children': []
                }
            }
        }
        
        self.api_client.get = AsyncMock(return_value=outline_data)
        
        result = await self.course_manager.get_course_outline(course_info)
        assert 'blocks' in result
        assert 'block-1' in result['blocks']
    
    @pytest.mark.asyncio
    async def test_get_course_outline_enrollment_required(self):
        """Test getting course outline when enrollment is required."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="not_enrolled",
            access_level="limited"
        )
        
        self.api_client.get = AsyncMock(side_effect=NetworkError("Forbidden", status_code=403))
        
        with pytest.raises(EnrollmentRequiredError, match="Enrollment required"):
            await self.course_manager.get_course_outline(course_info)
    
    @pytest.mark.asyncio
    async def test_validate_course_access_success(self):
        """Test successful course access validation."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        # Mock successful outline retrieval
        self.api_client.get = AsyncMock(return_value={'blocks': {}})
        
        result = await self.course_manager.validate_course_access(course_info)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_validate_course_access_enrollment_required(self):
        """Test course access validation when enrollment is required."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="not_enrolled",
            access_level="none"
        )
        
        with pytest.raises(EnrollmentRequiredError, match="Enrollment required"):
            await self.course_manager.validate_course_access(course_info)
    
    @pytest.mark.asyncio
    async def test_extract_video_info_html(self):
        """Test extracting video info from HTML content."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        html_content = '''
        <html>
        <body>
            <video title="Introduction Video">
                <source src="https://example.com/video1.mp4" type="video/mp4">
            </video>
            <div data-video-url="https://example.com/video2.mp4" data-title="Lesson 1"></div>
        </body>
        </html>
        '''
        
        api_response = {
            'content': html_content,
            'content_type': 'html'
        }
        self.api_client.get = AsyncMock(return_value=api_response)
        
        videos = await self.course_manager.extract_video_info("https://example.com/block", course_info)
        
        assert len(videos) >= 1
        assert any(video.title == "Introduction Video" for video in videos)
        assert any("video1.mp4" in video.url for video in videos)
    
    @pytest.mark.asyncio
    async def test_extract_video_info_json(self):
        """Test extracting video info from JSON data."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        json_data = {
            'encoded_videos': {
                '720p': 'https://example.com/video_720p.mp4',
                '480p': 'https://example.com/video_480p.mp4'
            },
            'display_name': 'Course Introduction'
        }
        
        self.api_client.get = AsyncMock(return_value=json_data)
        
        videos = await self.course_manager.extract_video_info("https://example.com/block", course_info)
        
        assert len(videos) >= 1
        assert any(video.quality == "720p" for video in videos)
    
    def test_parse_video_element(self):
        """Test parsing video element from HTML."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        html = '<video title="Test Video"><source src="https://example.com/test.mp4"></video>'
        soup = BeautifulSoup(html, 'html.parser')
        video_element = soup.find('video')
        
        video_info = self.course_manager._parse_video_element(video_element, 0, course_info)
        
        assert video_info is not None
        assert video_info.title == "Test Video"
        assert "test.mp4" in video_info.url
    
    def test_parse_video_json(self):
        """Test parsing video info from JSON data."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        video_data = {
            'id': 'video-123',
            'display_name': 'Introduction to Python',
            'encoded_videos': {
                '720p': 'https://example.com/python_intro_720p.mp4'
            },
            'duration': 300
        }
        
        video_info = self.course_manager._parse_video_json(video_data, course_info)
        
        assert video_info is not None
        assert video_info.id == "video-123"
        assert video_info.title == "Introduction to Python"
        assert video_info.quality == "720p"
        assert video_info.duration == 300
    
    def test_extract_video_urls_from_script(self):
        """Test extracting video URLs from JavaScript content."""
        script_content = '''
        var videoConfig = {
            video_url: "https://example.com/video1.mp4",
            sources: [
                "https://example.com/video2.mp4",
                "https://example.com/playlist.m3u8"
            ]
        };
        '''
        
        urls = self.course_manager._extract_video_urls_from_script(script_content)
        
        assert len(urls) >= 1
        assert any("video1.mp4" in url for url in urls)
        assert any("video2.mp4" in url for url in urls)
        assert any("playlist.m3u8" in url for url in urls)
    
    def test_determine_video_quality(self):
        """Test determining video quality from URL and attributes."""
        html = '<video width="1280" height="720"></video>'
        soup = BeautifulSoup(html, 'html.parser')
        video_element = soup.find('video')
        
        # Test URL-based quality detection
        quality1 = self.course_manager._determine_video_quality(
            "https://example.com/video_720p.mp4", 
            video_element
        )
        assert quality1 == "720p"
        
        # Test attribute-based quality detection
        quality2 = self.course_manager._determine_video_quality(
            "https://example.com/video.mp4", 
            video_element
        )
        assert quality2 == "720p"  # Based on height=720
        
        # Test unknown quality
        html_unknown = '<video></video>'
        soup_unknown = BeautifulSoup(html_unknown, 'html.parser')
        element_unknown = soup_unknown.find('video')
        
        quality3 = self.course_manager._determine_video_quality(
            "https://example.com/video.mp4", 
            element_unknown
        )
        assert quality3 == "unknown"
    
    def test_parse_course_structure(self):
        """Test parsing course structure from HTML."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        html = '''
        <html>
        <body>
            <nav class="course-navigation">
                <a href="/week1">Week 1: Introduction</a>
                <a href="/week2">Week 2: Advanced Topics</a>
            </nav>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        blocks = self.course_manager._parse_course_structure(soup, course_info)
        
        assert len(blocks) == 2
        assert any("Week 1" in block['display_name'] for block in blocks.values())
        assert any("Week 2" in block['display_name'] for block in blocks.values())
    
    def test_extract_blocks_from_nav(self):
        """Test extracting blocks from navigation element."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        html = '''
        <nav>
            <a href="/section1">Section 1</a>
            <a href="/section2">Section 2</a>
        </nav>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        nav_element = soup.find('nav')
        
        blocks = self.course_manager._extract_blocks_from_nav(nav_element, course_info)
        
        assert len(blocks) == 2
        block_names = [block['display_name'] for block in blocks.values()]
        assert "Section 1" in block_names
        assert "Section 2" in block_names
    
    def test_extract_video_blocks(self):
        """Test extracting video blocks from HTML."""
        course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
        
        html = '''
        <html>
        <body>
            <video>
                <source src="https://example.com/video1.mp4">
            </video>
            <a href="https://example.com/video2.mp4">Video 2</a>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        blocks = self.course_manager._extract_video_blocks(soup, course_info)
        
        assert len(blocks) >= 1
        video_urls = [block['student_view_url'] for block in blocks.values()]
        assert any("video1.mp4" in url for url in video_urls)
        assert any("video2.mp4" in url for url in video_urls)