"""Course discovery and parsing system for EDX downloader."""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup, Tag

from edx_downloader.models import CourseInfo, VideoInfo
from edx_downloader.api_client import EdxApiClient
from edx_downloader.video_extractor import VideoExtractor
from edx_downloader.exceptions import (
    CourseAccessError, CourseNotFoundError, EnrollmentRequiredError,
    CourseNotStartedError, CourseEndedError, ParseError, NetworkError
)
from edx_downloader.logging_config import get_logger, log_with_context, performance_timer

logger = get_logger(__name__)


class CourseManager:
    """Manages course discovery, parsing, and content extraction."""
    
    def __init__(self, api_client: EdxApiClient):
        """Initialize course manager.
        
        Args:
            api_client: EDX API client for making requests.
        """
        self.api_client = api_client
        self.base_url = api_client.base_url
        self.video_extractor = VideoExtractor(api_client)
    
    async def parse_course_url(self, course_url: str) -> str:
        """Parse course URL and extract course ID.
        
        Args:
            course_url: Course URL to parse.
            
        Returns:
            Course ID extracted from URL.
            
        Raises:
            CourseNotFoundError: If course URL is invalid.
        """
        try:
            parsed_url = urlparse(course_url)
            
            # Handle different URL formats
            if '/courses/' in parsed_url.path:
                # Format: /courses/course-v1:MITx+6.00.1x+2T2017/course/
                path_parts = parsed_url.path.split('/courses/')
                if len(path_parts) > 1:
                    course_part = path_parts[1].split('/')[0]
                    if course_part:
                        return course_part
            
            elif '/course/' in parsed_url.path:
                # Format: /course/course-v1:MITx+6.00.1x+2T2017/
                path_parts = parsed_url.path.split('/course/')
                if len(path_parts) > 1:
                    course_part = path_parts[1].split('/')[0]
                    if course_part:
                        return course_part
            
            # Try to extract from query parameters
            query_params = parse_qs(parsed_url.query)
            if 'course_id' in query_params:
                return query_params['course_id'][0]
            
            raise CourseNotFoundError(f"Could not extract course ID from URL: {course_url}")
            
        except Exception as e:
            raise CourseNotFoundError(f"Invalid course URL format: {course_url}", details={'error': str(e)})
    
    async def get_course_info(self, course_url: str) -> CourseInfo:
        """Get course information from URL.
        
        Args:
            course_url: Course URL.
            
        Returns:
            Course information.
            
        Raises:
            CourseNotFoundError: If course is not found.
            CourseAccessError: If course access is restricted.
        """
        with performance_timer("get_course_info", logger):
            log_with_context(logger, logging.INFO, "Getting course information", {
                'course_url': course_url
            })
            
            course_id = await self.parse_course_url(course_url)
            
            log_with_context(logger, logging.DEBUG, "Parsed course ID", {
                'course_url': course_url,
                'course_id': course_id
            })
            
            try:
                # Get course info from API
                course_info_url = f"/api/courses/v1/courses/{course_id}/"
                
                with performance_timer("api_get_course_info", logger):
                    course_data = await self.api_client.get(course_info_url, require_auth=False)
                
                if 'content' in course_data and course_data.get('content_type') == 'html':
                    # Parse HTML response
                    log_with_context(logger, logging.DEBUG, "Parsing course info from HTML", {
                        'course_id': course_id,
                        'content_length': len(course_data['content'])
                    })
                    return await self._parse_course_info_from_html(course_data['content'], course_url, course_id)
                else:
                    # Parse JSON response
                    log_with_context(logger, logging.DEBUG, "Parsing course info from JSON", {
                        'course_id': course_id,
                        'data_keys': list(course_data.keys()) if isinstance(course_data, dict) else None
                    })
                    return self._parse_course_info_from_json(course_data, course_url, course_id)
                    
            except NetworkError as e:
                log_with_context(logger, logging.ERROR, "Failed to get course info", {
                    'course_url': course_url,
                    'course_id': course_id,
                    'status_code': getattr(e, 'status_code', None),
                    'error_message': str(e)
                })
                
                if e.status_code == 404:
                    raise CourseNotFoundError(f"Course not found: {course_id}")
                elif e.status_code == 403:
                    raise CourseAccessError(f"Access denied to course: {course_id}")
                else:
                    raise CourseAccessError(f"Failed to get course info: {str(e)}", course_id=course_id)
    
    def _parse_course_info_from_json(self, course_data: Dict[str, Any], course_url: str, course_id: str) -> CourseInfo:
        """Parse course information from JSON API response.
        
        Args:
            course_data: Course data from API.
            course_url: Original course URL.
            course_id: Course ID.
            
        Returns:
            Course information.
        """
        try:
            title = course_data.get('name', course_data.get('display_name', 'Unknown Course'))
            enrollment_status = self._determine_enrollment_status(course_data)
            access_level = self._determine_access_level(course_data)
            
            return CourseInfo(
                id=course_id,
                title=title,
                url=course_url,
                enrollment_status=enrollment_status,
                access_level=access_level
            )
            
        except Exception as e:
            raise ParseError(f"Failed to parse course info from JSON: {str(e)}", content_type='json', url=course_url)
    
    async def _parse_course_info_from_html(self, html_content: str, course_url: str, course_id: str) -> CourseInfo:
        """Parse course information from HTML response.
        
        Args:
            html_content: HTML content.
            course_url: Original course URL.
            course_id: Course ID.
            
        Returns:
            Course information.
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract course title
            title = self._extract_course_title(soup)
            
            # Determine enrollment and access status
            enrollment_status = self._extract_enrollment_status(soup)
            access_level = self._extract_access_level(soup)
            
            return CourseInfo(
                id=course_id,
                title=title,
                url=course_url,
                enrollment_status=enrollment_status,
                access_level=access_level
            )
            
        except Exception as e:
            raise ParseError(f"Failed to parse course info from HTML: {str(e)}", content_type='html', url=course_url)
    
    def _extract_course_title(self, soup: BeautifulSoup) -> str:
        """Extract course title from HTML.
        
        Args:
            soup: BeautifulSoup object.
            
        Returns:
            Course title.
        """
        # Try different selectors for course title
        title_selectors = [
            'h1.course-title',
            '.course-title',
            'h1.page-title',
            '.page-title',
            'h1',
            'title'
        ]
        
        for selector in title_selectors:
            element = soup.select_one(selector)
            if element and element.get_text(strip=True):
                title = element.get_text(strip=True)
                # Clean up title
                title = re.sub(r'\s+', ' ', title)
                if len(title) > 5:  # Avoid very short titles
                    return title
        
        return "Unknown Course"
    
    def _extract_enrollment_status(self, soup: BeautifulSoup) -> str:
        """Extract enrollment status from HTML.
        
        Args:
            soup: BeautifulSoup object.
            
        Returns:
            Enrollment status.
        """
        # Look for enrollment indicators
        enrollment_indicators = [
            ('.enrollment-status', 'data-status'),
            ('.enroll-btn', None),
            ('.unenroll-btn', None),
            ('.enrollment-info', None)
        ]
        
        for selector, attr in enrollment_indicators:
            element = soup.select_one(selector)
            if element:
                if attr and element.get(attr):
                    return element.get(attr)
                elif 'enroll' in element.get_text().lower():
                    return 'not_enrolled'
                elif 'unenroll' in element.get_text().lower():
                    return 'enrolled'
        
        # Check for enrollment-related text
        page_text = soup.get_text().lower()
        if 'you are enrolled' in page_text:
            return 'enrolled'
        elif 'enroll now' in page_text:
            return 'not_enrolled'
        elif 'audit' in page_text:
            return 'audit'
        elif 'verified' in page_text:
            return 'verified'
        
        return 'not_enrolled'
    
    def _extract_access_level(self, soup: BeautifulSoup) -> str:
        """Extract access level from HTML.
        
        Args:
            soup: BeautifulSoup object.
            
        Returns:
            Access level.
        """
        page_text = soup.get_text().lower()
        
        # Check for access restrictions
        if 'access denied' in page_text or 'not authorized' in page_text:
            return 'none'
        elif 'enrollment required' in page_text:
            return 'limited'
        elif 'audit' in page_text:
            return 'audit'
        else:
            return 'full'
    
    def _determine_enrollment_status(self, course_data: Dict[str, Any]) -> str:
        """Determine enrollment status from course data.
        
        Args:
            course_data: Course data dictionary.
            
        Returns:
            Enrollment status.
        """
        # Check various fields that might indicate enrollment
        if course_data.get('enrollment', {}).get('is_active'):
            mode = course_data.get('enrollment', {}).get('mode', 'audit')
            return mode if mode in ['audit', 'verified', 'honor'] else 'enrolled'
        
        if course_data.get('is_enrolled'):
            return 'enrolled'
        
        return 'not_enrolled'
    
    def _determine_access_level(self, course_data: Dict[str, Any]) -> str:
        """Determine access level from course data.
        
        Args:
            course_data: Course data dictionary.
            
        Returns:
            Access level.
        """
        # Check access permissions
        if course_data.get('can_access_course', True):
            if course_data.get('enrollment', {}).get('mode') == 'audit':
                return 'audit'
            else:
                return 'full'
        else:
            return 'limited'
    
    async def get_course_outline(self, course_info: CourseInfo) -> Dict[str, Any]:
        """Get course outline and structure.
        
        Args:
            course_info: Course information.
            
        Returns:
            Course outline data.
            
        Raises:
            CourseAccessError: If course outline cannot be accessed.
        """
        try:
            # FIXED: Correct API endpoint format - course_id as parameter, not in URL
            outline_url = f"/api/courses/v1/blocks/"
            params = {
                'course_id': course_info.course_key,  # Pass as parameter, not in URL
                'depth': 'all',
                'requested_fields': 'children,display_name,type,student_view_url'
            }
            
            outline_data = await self._make_api_request_with_fallback(
                outline_url, 
                params, 
                lambda: self._get_outline_from_course_page(course_info)
            )
            
            if 'blocks' in outline_data:
                return outline_data
            
            # If API didn't return blocks, use fallback
            return await self._get_outline_from_course_page(course_info)
            
        except NetworkError as e:
            if e.status_code == 403:
                raise EnrollmentRequiredError(
                    "Enrollment required to access course outline",
                    course_id=course_info.id
                )
            else:
                raise CourseAccessError(
                    f"Failed to get course outline: {str(e)}",
                    course_id=course_info.id
                )
    
    async def _make_api_request_with_fallback(self, endpoint: str, params: Dict[str, Any], fallback_method):
        """Make API request with fallback method if it fails.
        
        Args:
            endpoint: API endpoint to call.
            params: Parameters for the API call.
            fallback_method: Fallback method to call if API fails.
            
        Returns:
            API response or fallback result.
        """
        try:
            return await self.api_client.get(endpoint, params=params)
        except NetworkError as e:
            if e.status_code == 403:
                # Don't use fallback for 403 errors, re-raise as enrollment required
                raise EnrollmentRequiredError(
                    "Enrollment required to access course outline",
                    course_id=params.get('course_id', 'unknown')
                )
            logger.warning(f"API request failed: {e}, falling back to alternative method")
            return await fallback_method()
        except CourseAccessError as e:
            logger.warning(f"API request failed: {e}, falling back to alternative method")
            return await fallback_method()
    
    async def _get_outline_from_course_page(self, course_info: CourseInfo) -> Dict[str, Any]:
        """Get course outline by parsing course page.
        
        Args:
            course_info: Course information.
            
        Returns:
            Course outline data.
        """
        try:
            course_page = await self.api_client.get(course_info.url, use_cache=False)
            
            if course_page.get('content_type') != 'html':
                raise ParseError("Expected HTML content for course page")
            
            soup = BeautifulSoup(course_page['content'], 'html.parser')
            
            # Extract course structure from navigation or content
            outline = self._parse_course_structure(soup, course_info)
            
            return {
                'blocks': outline,
                'root': course_info.course_key
            }
            
        except Exception as e:
            raise ParseError(f"Failed to parse course outline: {str(e)}", url=course_info.url)
    
    def _parse_course_structure(self, soup: BeautifulSoup, course_info: CourseInfo) -> Dict[str, Any]:
        """Parse course structure from HTML.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            
        Returns:
            Course structure data.
        """
        blocks = {}
        
        # Look for course navigation or outline
        nav_selectors = [
            '.course-navigation',
            '.course-outline',
            '.course-tabs',
            '.sequence-nav',
            '.chapter-nav'
        ]
        
        for selector in nav_selectors:
            nav_element = soup.select_one(selector)
            if nav_element:
                blocks.update(self._extract_blocks_from_nav(nav_element, course_info))
                break
        
        # If no navigation found, look for video links directly
        if not blocks:
            blocks.update(self._extract_video_blocks(soup, course_info))
        
        return blocks
    
    def _extract_blocks_from_nav(self, nav_element: Tag, course_info: CourseInfo) -> Dict[str, Any]:
        """Extract blocks from navigation element.
        
        Args:
            nav_element: Navigation element.
            course_info: Course information.
            
        Returns:
            Blocks dictionary.
        """
        blocks = {}
        
        # Find all links in navigation
        links = nav_element.find_all('a', href=True)
        
        for i, link in enumerate(links):
            href = link['href']
            title = link.get_text(strip=True)
            
            if not title:
                title = f"Section {i + 1}"
            
            # Create block ID
            block_id = f"block-{i}"
            
            blocks[block_id] = {
                'id': block_id,
                'type': 'sequential',
                'display_name': title,
                'student_view_url': urljoin(self.base_url, href) if not href.startswith('http') else href,
                'children': []
            }
        
        return blocks
    
    def _extract_video_blocks(self, soup: BeautifulSoup, course_info: CourseInfo) -> Dict[str, Any]:
        """Extract video blocks directly from page.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            
        Returns:
            Video blocks dictionary.
        """
        blocks = {}
        
        # Look for video elements or links
        video_selectors = [
            'video',
            '.video-player',
            '.video-content',
            'a[href*="video"]',
            'a[href*=".mp4"]',
            'a[href*=".m3u8"]'
        ]
        
        for i, selector in enumerate(video_selectors):
            elements = soup.select(selector)
            
            for j, element in enumerate(elements):
                block_id = f"video-{i}-{j}"
                title = element.get('title', element.get_text(strip=True)) or f"Video {j + 1}"
                
                # Get video URL
                video_url = None
                if element.name == 'video':
                    source = element.find('source')
                    if source and source.get('src'):
                        video_url = source['src']
                elif element.get('href'):
                    video_url = element['href']
                
                if video_url:
                    blocks[block_id] = {
                        'id': block_id,
                        'type': 'video',
                        'display_name': title,
                        'student_view_url': urljoin(self.base_url, video_url) if not video_url.startswith('http') else video_url,
                        'children': []
                    }
        
        return blocks
    
    async def validate_course_access(self, course_info: CourseInfo) -> bool:
        """Validate that course content is accessible.
        
        Args:
            course_info: Course information.
            
        Returns:
            True if course is accessible.
            
        Raises:
            EnrollmentRequiredError: If enrollment is required.
            CourseNotStartedError: If course hasn't started.
            CourseEndedError: If course has ended.
        """
        if not course_info.is_accessible:
            if course_info.enrollment_status == 'not_enrolled':
                raise EnrollmentRequiredError(
                    "Enrollment required to access course content",
                    course_id=course_info.id
                )
            else:
                raise CourseAccessError(
                    "Course content is not accessible",
                    course_id=course_info.id
                )
        
        # Try to access course outline to verify access
        try:
            await self.get_course_outline(course_info)
            return True
        except EnrollmentRequiredError:
            raise
        except CourseAccessError:
            return False
    
    async def extract_video_info(self, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Extract video information from a course block.
        
        Args:
            block_url: URL of the course block.
            course_info: Course information.
            
        Returns:
            List of video information.
        """
        return await self.video_extractor.extract_videos_from_block(block_url, course_info)
    
    async def _extract_videos_from_html(self, html_content: str, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Extract video information from HTML content.
        
        Args:
            html_content: HTML content.
            block_url: Block URL.
            course_info: Course information.
            
        Returns:
            List of video information.
        """
        videos = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for video elements and data
        video_elements = soup.find_all(['video', 'source']) + soup.select('[data-video-url]')
        
        for i, element in enumerate(video_elements):
            try:
                video_info = self._parse_video_element(element, i, course_info)
                if video_info:
                    videos.append(video_info)
            except Exception as e:
                continue  # Skip invalid video elements
        
        # Look for video URLs in JavaScript or data attributes
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                video_urls = self._extract_video_urls_from_script(script.string)
                for j, url in enumerate(video_urls):
                    try:
                        video_info = VideoInfo(
                            id=f"script-video-{j}",
                            title=f"Video {len(videos) + j + 1}",
                            url=url,
                            quality="unknown",
                            course_section=course_info.title
                        )
                        videos.append(video_info)
                    except Exception:
                        continue
        
        return videos
    
    def _extract_videos_from_json(self, json_data: Dict[str, Any], block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Extract video information from JSON data.
        
        Args:
            json_data: JSON data.
            block_url: Block URL.
            course_info: Course information.
            
        Returns:
            List of video information.
        """
        videos = []
        
        # Look for video data in various JSON structures
        if 'video' in json_data:
            video_data = json_data['video']
            if isinstance(video_data, dict):
                video_info = self._parse_video_json(video_data, course_info)
                if video_info:
                    videos.append(video_info)
        
        # Look for encoded videos or sources
        if 'encoded_videos' in json_data:
            for quality, url in json_data['encoded_videos'].items():
                try:
                    video_info = VideoInfo(
                        id=f"encoded-{quality}",
                        title=json_data.get('display_name', 'Video'),
                        url=url,
                        quality=quality,
                        course_section=course_info.title
                    )
                    videos.append(video_info)
                except Exception:
                    continue
        
        return videos
    
    def _parse_video_element(self, element: Tag, index: int, course_info: CourseInfo) -> Optional[VideoInfo]:
        """Parse video information from HTML element.
        
        Args:
            element: HTML element.
            index: Element index.
            course_info: Course information.
            
        Returns:
            Video information or None.
        """
        try:
            # Get video URL
            video_url = None
            if element.name == 'video':
                # Check for source element first
                source = element.find('source')
                if source and source.get('src'):
                    video_url = source['src']
                # Check for direct src attribute on video element
                elif element.get('src'):
                    video_url = element['src']
            elif element.name == 'source' and element.get('src'):
                video_url = element['src']
            elif element.get('data-video-url'):
                video_url = element['data-video-url']
            
            if not video_url:
                return None
            
            # Get title
            title = (element.get('title') or 
                    element.get('data-title') or 
                    element.get_text(strip=True) or 
                    f"Video {index + 1}")
            
            # Determine quality
            quality = self._determine_video_quality(video_url, element)
            
            return VideoInfo(
                id=f"video-{index}",
                title=title,
                url=video_url,
                quality=quality,
                course_section=course_info.title
            )
            
        except Exception:
            return None
    
    def _parse_video_json(self, video_data: Dict[str, Any], course_info: CourseInfo) -> Optional[VideoInfo]:
        """Parse video information from JSON data.
        
        Args:
            video_data: Video data dictionary.
            course_info: Course information.
            
        Returns:
            Video information or None.
        """
        try:
            # Get best quality video URL
            video_url = None
            quality = "unknown"
            
            if 'encoded_videos' in video_data:
                # Choose highest quality available
                qualities = ['1080p', '720p', '480p', '360p', '240p']
                for q in qualities:
                    if q in video_data['encoded_videos']:
                        video_url = video_data['encoded_videos'][q]
                        quality = q
                        break
            
            if not video_url and 'video_url' in video_data:
                video_url = video_data['video_url']
            
            if not video_url:
                return None
            
            return VideoInfo(
                id=video_data.get('id', 'unknown'),
                title=video_data.get('display_name', 'Video'),
                url=video_url,
                quality=quality,
                duration=video_data.get('duration'),
                course_section=course_info.title
            )
            
        except Exception:
            return None
    
    def _extract_video_urls_from_script(self, script_content: str) -> List[str]:
        """Extract video URLs from JavaScript content.
        
        Args:
            script_content: JavaScript content.
            
        Returns:
            List of video URLs.
        """
        urls = []
        
        # Common video URL patterns
        patterns = [
            r'["\']https?://[^"\']*\.mp4["\']',
            r'["\']https?://[^"\']*\.m3u8["\']',
            r'["\']https?://[^"\']*\.webm["\']',
            r'video_url["\']?\s*:\s*["\']([^"\']+)["\']',
            r'src["\']?\s*:\s*["\']([^"\']+\.mp4)["\']'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, script_content, re.IGNORECASE)
            for match in matches:
                url = match.strip('\'"')
                if url.startswith('http') and url not in urls:
                    urls.append(url)
        
        return urls
    
    def _determine_video_quality(self, video_url: str, element: Tag) -> str:
        """Determine video quality from URL or element attributes.
        
        Args:
            video_url: Video URL.
            element: HTML element.
            
        Returns:
            Video quality string.
        """
        # Check URL for quality indicators
        quality_patterns = {
            '1080p': r'1080p?',
            '720p': r'720p?',
            '480p': r'480p?',
            '360p': r'360p?',
            '240p': r'240p?'
        }
        
        for quality, pattern in quality_patterns.items():
            if re.search(pattern, video_url, re.IGNORECASE):
                return quality
        
        # Check element attributes
        if element.get('data-quality'):
            return element['data-quality']
        
        # Check resolution attributes
        width = element.get('width')
        height = element.get('height')
        if width and height:
            try:
                h = int(height)
                if h >= 1080:
                    return '1080p'
                elif h >= 720:
                    return '720p'
                elif h >= 480:
                    return '480p'
                elif h >= 360:
                    return '360p'
                else:
                    return '240p'
            except ValueError:
                pass
        
        return 'unknown'