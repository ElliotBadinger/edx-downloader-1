"""Video content extraction system for EDX courses."""

import re
import json
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup, Tag

from .models import VideoInfo, CourseInfo
from .api_client import EdxApiClient
from .exceptions import ParseError, VideoNotFoundError
from .logging_config import get_logger, log_with_context, performance_timer

logger = get_logger(__name__)


class VideoExtractor:
    """Extracts video content from EDX course blocks."""
    
    # Video quality patterns for URL-based detection
    QUALITY_PATTERNS = {
        '2160p': [r'2160p?', r'4k', r'uhd'],
        '1440p': [r'1440p?', r'2k'],
        '1080p': [r'1080p?', r'fullhd', r'fhd'],
        '720p': [r'720p?', r'hd'],
        '480p': [r'480p?', r'sd'],
        '360p': [r'360p?'],
        '240p': [r'240p?'],
        '144p': [r'144p?']
    }
    
    # Video file extensions
    VIDEO_EXTENSIONS = {'.mp4', '.webm', '.m4v', '.mov', '.avi', '.mkv', '.flv'}
    
    # Streaming formats
    STREAMING_FORMATS = {'.m3u8', '.mpd', '.f4m'}
    
    def __init__(self, api_client: EdxApiClient):
        """Initialize video extractor.
        
        Args:
            api_client: EDX API client instance.
        """
        self.api_client = api_client
        self.base_url = api_client.base_url
    
    async def extract_videos_from_block(self, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Extract all videos from a course block using multi-strategy approach.
        
        Args:
            block_url: URL of the course block.
            course_info: Course information.
            
        Returns:
            List of video information objects.
            
        Raises:
            ParseError: If block content cannot be parsed.
            VideoNotFoundError: If no videos found in block.
        """
        logger.debug(f"Extracting videos from block: {block_url}")
        
        # Multi-strategy extraction with fallbacks
        strategies = [
            self._extract_from_api_data,
            self._extract_from_html_parsing,
            self._extract_from_javascript,
            self._extract_from_video_elements
        ]
        
        for strategy in strategies:
            try:
                videos = await strategy(block_url, course_info)
                if videos:
                    logger.info(f"Strategy {strategy.__name__} found {len(videos)} videos")
                    return videos
            except Exception as e:
                logger.warning(f"Strategy {strategy.__name__} failed: {e}")
                continue
        
        logger.warning(f"All extraction strategies failed for block: {block_url}")
        raise VideoNotFoundError(f"No videos found in block: {block_url}")
    
    async def _extract_from_api_data(self, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Strategy 1: Extract from API data structures."""
        response = await self.api_client.get(block_url)
        
        if isinstance(response, dict):
            return await self._extract_from_json(response, course_info, block_url)
        return []
    
    async def _extract_from_html_parsing(self, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Strategy 2: Extract from HTML parsing."""
        response = await self.api_client.get(block_url)
        
        if not isinstance(response, dict):
            soup = BeautifulSoup(str(response), 'html.parser')
            return await self._extract_from_html(soup, course_info, block_url)
        elif 'content' in response and isinstance(response['content'], str):
            soup = BeautifulSoup(response['content'], 'html.parser')
            return await self._extract_from_html(soup, course_info, block_url)
        return []
    
    async def _extract_from_javascript(self, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Strategy 3: Extract from JavaScript content."""
        response = await self.api_client.get(block_url)
        videos = []
        
        if isinstance(response, dict) and 'content' in response:
            soup = BeautifulSoup(response['content'], 'html.parser')
        else:
            soup = BeautifulSoup(str(response), 'html.parser')
        
        videos.extend(self._extract_js_videos(soup, course_info, block_url))
        return videos
    
    async def _extract_from_video_elements(self, block_url: str, course_info: CourseInfo) -> List[VideoInfo]:
        """Strategy 4: Extract from direct video elements."""
        response = await self.api_client.get(block_url)
        videos = []
        
        if isinstance(response, dict) and 'content' in response:
            soup = BeautifulSoup(response['content'], 'html.parser')
        else:
            soup = BeautifulSoup(str(response), 'html.parser')
        
        videos.extend(self._extract_html5_videos(soup, course_info, block_url))
        videos.extend(self._extract_video_links(soup, course_info, block_url))
        videos.extend(self._extract_embedded_videos(soup, course_info, block_url))
        return videos
    
    async def _extract_from_json(self, data: Dict[str, Any], course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract videos from JSON data.
        
        Args:
            data: JSON response data.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        
        # Method 1: Direct video data
        if 'video' in data:
            video_info = self._parse_video_json(data['video'], course_info, block_url)
            if video_info:
                videos.append(video_info)
        
        # Method 2: Encoded videos
        if 'encoded_videos' in data:
            video_info = self._parse_encoded_videos(data, course_info, block_url)
            if video_info:
                videos.append(video_info)
        
        # Method 3: Video URLs in various fields
        video_urls = self._extract_urls_from_json(data)
        for url in video_urls:
            video_info = self._create_video_from_url(url, course_info, block_url)
            if video_info:
                videos.append(video_info)
        
        # Method 4: Nested content
        if 'content' in data and isinstance(data['content'], str):
            soup = BeautifulSoup(data['content'], 'html.parser')
            videos.extend(await self._extract_from_html(soup, course_info, block_url))
        
        return videos
    
    async def _extract_from_html(self, soup: BeautifulSoup, course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract videos from HTML content.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        
        # Method 1: HTML5 video elements
        videos.extend(self._extract_html5_videos(soup, course_info, block_url))
        
        # Method 2: Video player containers
        videos.extend(self._extract_video_players(soup, course_info, block_url))
        
        # Method 3: JavaScript embedded videos
        videos.extend(self._extract_js_videos(soup, course_info, block_url))
        
        # Method 4: Direct video links
        videos.extend(self._extract_video_links(soup, course_info, block_url))
        
        # Method 5: YouTube/Vimeo embeds
        videos.extend(self._extract_embedded_videos(soup, course_info, block_url))
        
        return videos
    
    def _extract_html5_videos(self, soup: BeautifulSoup, course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract HTML5 video elements.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        video_elements = soup.find_all('video')
        
        for i, element in enumerate(video_elements):
            video_info = self._parse_video_element(element, i, course_info, block_url)
            if video_info:
                videos.append(video_info)
        
        return videos
    
    def _extract_video_players(self, soup: BeautifulSoup, course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract videos from player containers.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        processed_elements = set()
        
        # Common video player selectors
        player_selectors = [
            '.video-player',
            '.video-content',
            '.xblock-video',
            '[data-video-url]',
            '[data-video-id]',
            '.video-wrapper'
        ]
        
        for selector in player_selectors:
            elements = soup.select(selector)
            for i, element in enumerate(elements):
                # Use element's position in DOM as unique identifier
                element_id = id(element)
                if element_id not in processed_elements:
                    processed_elements.add(element_id)
                    video_info = self._parse_player_element(element, i, course_info, block_url)
                    if video_info:
                        videos.append(video_info)
        
        return videos
    
    def _extract_js_videos(self, soup: BeautifulSoup, course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract videos from JavaScript content.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        script_tags = soup.find_all('script')
        
        for script in script_tags:
            if script.string:
                video_urls = self._extract_urls_from_script(script.string)
                for url in video_urls:
                    video_info = self._create_video_from_url(url, course_info, block_url)
                    if video_info:
                        videos.append(video_info)
        
        return videos
    
    def _extract_video_links(self, soup: BeautifulSoup, course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract direct video links.
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        
        # Find all links that might be videos
        links = soup.find_all('a', href=True)
        
        for link in links:
            href = link['href']
            if self._is_video_url(href):
                title = link.get_text(strip=True) or link.get('title', '')
                video_info = self._create_video_from_url(href, course_info, block_url, title)
                if video_info:
                    videos.append(video_info)
        
        return videos
    
    def _extract_embedded_videos(self, soup: BeautifulSoup, course_info: CourseInfo, block_url: str) -> List[VideoInfo]:
        """Extract embedded videos (YouTube, Vimeo, etc.).
        
        Args:
            soup: BeautifulSoup object.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            List of video information objects.
        """
        videos = []
        
        # YouTube embeds
        youtube_iframes = soup.find_all('iframe', src=re.compile(r'youtube\.com|youtu\.be'))
        for iframe in youtube_iframes:
            video_info = self._parse_youtube_embed(iframe, course_info, block_url)
            if video_info:
                videos.append(video_info)
        
        # Vimeo embeds
        vimeo_iframes = soup.find_all('iframe', src=re.compile(r'vimeo\.com'))
        for iframe in vimeo_iframes:
            video_info = self._parse_vimeo_embed(iframe, course_info, block_url)
            if video_info:
                videos.append(video_info)
        
        return videos
    
    def _parse_video_element(self, element: Tag, index: int, course_info: CourseInfo, block_url: str) -> Optional[VideoInfo]:
        """Parse HTML5 video element.
        
        Args:
            element: Video element.
            index: Element index.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            Video information object or None.
        """
        try:
            # Get video source
            video_url = None
            source = element.find('source')
            if source and source.get('src'):
                video_url = source['src']
            elif element.get('src'):
                video_url = element['src']
            
            if not video_url:
                return None
            
            # Make URL absolute
            if not video_url.startswith('http'):
                video_url = urljoin(self.base_url, video_url)
            
            # Extract metadata
            title = element.get('title') or element.get('data-title') or f"Video {index + 1}"
            duration = self._parse_duration(element.get('duration'))
            quality = self._determine_video_quality(video_url, element)
            
            return VideoInfo(
                id=f"video-{index}",
                title=title,
                url=video_url,
                quality=quality,
                duration=duration,
                size=0,  # Will be determined during download
                format=self._get_video_format(video_url)
            )
            
        except Exception as e:
            logger.warning(f"Error parsing video element: {e}")
            return None
    
    def _parse_player_element(self, element: Tag, index: int, course_info: CourseInfo, block_url: str) -> Optional[VideoInfo]:
        """Parse video player element.
        
        Args:
            element: Player element.
            index: Element index.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            Video information object or None.
        """
        try:
            # Try different attributes for video URL
            video_url = (
                element.get('data-video-url') or
                element.get('data-src') or
                element.get('src')
            )
            
            if not video_url:
                # Look for nested video elements
                video_elem = element.find('video')
                if video_elem:
                    return self._parse_video_element(video_elem, index, course_info, block_url)
                return None
            
            # Make URL absolute
            if not video_url.startswith('http'):
                video_url = urljoin(self.base_url, video_url)
            
            # Extract metadata
            title = (
                element.get('data-title') or
                element.get('title') or
                element.get_text(strip=True) or
                f"Video {index + 1}"
            )
            
            quality = self._determine_video_quality(video_url, element)
            duration = self._parse_duration(element.get('data-duration'))
            
            return VideoInfo(
                id=f"player-{index}",
                title=title,
                url=video_url,
                quality=quality,
                duration=duration,
                size=0,
                format=self._get_video_format(video_url)
            )
            
        except Exception as e:
            logger.warning(f"Error parsing player element: {e}")
            return None    

    def _parse_video_json(self, video_data: Dict[str, Any], course_info: CourseInfo, block_url: str) -> Optional[VideoInfo]:
        """Parse video information from JSON data.
        
        Args:
            video_data: Video data dictionary.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            Video information object or None.
        """
        try:
            video_id = video_data.get('id', video_data.get('video_id', 'unknown'))
            title = video_data.get('display_name', video_data.get('name', f"Video {video_id}"))
            
            # Get video URL from encoded videos
            video_url = None
            quality = 'unknown'
            
            if 'encoded_videos' in video_data:
                encoded = video_data['encoded_videos']
                # Prefer higher quality
                for q in ['1080p', '720p', '480p', '360p', '240p']:
                    if q in encoded:
                        video_url = encoded[q]
                        quality = q
                        break
                
                # If no standard quality found, take first available
                if not video_url and encoded:
                    quality, video_url = next(iter(encoded.items()))
            
            elif 'video_url' in video_data:
                video_url = video_data['video_url']
                quality = self._determine_video_quality(video_url)
            
            if not video_url:
                return None
            
            # Make URL absolute
            if not video_url.startswith('http'):
                video_url = urljoin(self.base_url, video_url)
            
            duration = self._parse_duration(video_data.get('duration'))
            
            return VideoInfo(
                id=str(video_id),
                title=title,
                url=video_url,
                quality=quality,
                duration=duration,
                size=video_data.get('file_size', 0),
                format=self._get_video_format(video_url)
            )
            
        except Exception as e:
            logger.warning(f"Error parsing video JSON: {e}")
            return None
    
    def _parse_encoded_videos(self, data: Dict[str, Any], course_info: CourseInfo, block_url: str) -> Optional[VideoInfo]:
        """Parse encoded videos data.
        
        Args:
            data: Data containing encoded videos.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            Video information object or None.
        """
        try:
            encoded_videos = data['encoded_videos']
            if not encoded_videos:
                return None
            
            # Get the best quality available
            video_url = None
            quality = 'unknown'
            
            for q in ['1080p', '720p', '480p', '360p', '240p']:
                if q in encoded_videos:
                    video_url = encoded_videos[q]
                    quality = q
                    break
            
            if not video_url and encoded_videos:
                quality, video_url = next(iter(encoded_videos.items()))
            
            if not video_url:
                return None
            
            # Make URL absolute
            if not video_url.startswith('http'):
                video_url = urljoin(self.base_url, video_url)
            
            title = data.get('display_name', data.get('name', 'Video'))
            duration = self._parse_duration(data.get('duration'))
            
            return VideoInfo(
                id=data.get('id', 'encoded-video'),
                title=title,
                url=video_url,
                quality=quality,
                duration=duration,
                size=0,
                format=self._get_video_format(video_url)
            )
            
        except Exception as e:
            logger.warning(f"Error parsing encoded videos: {e}")
            return None
    
    def _parse_youtube_embed(self, iframe: Tag, course_info: CourseInfo, block_url: str) -> Optional[VideoInfo]:
        """Parse YouTube embed iframe.
        
        Args:
            iframe: YouTube iframe element.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            Video information object or None.
        """
        try:
            src = iframe.get('src', '')
            if not src:
                return None
            
            # Extract video ID
            video_id = None
            if 'youtube.com/embed/' in src:
                video_id = src.split('/embed/')[-1].split('?')[0]
            elif 'youtu.be/' in src:
                video_id = src.split('youtu.be/')[-1].split('?')[0]
            
            if not video_id:
                return None
            
            title = iframe.get('title', f"YouTube Video {video_id}")
            
            return VideoInfo(
                id=f"youtube-{video_id}",
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                quality='youtube',
                duration=0,
                size=0,
                format='youtube'
            )
            
        except Exception as e:
            logger.warning(f"Error parsing YouTube embed: {e}")
            return None
    
    def _parse_vimeo_embed(self, iframe: Tag, course_info: CourseInfo, block_url: str) -> Optional[VideoInfo]:
        """Parse Vimeo embed iframe.
        
        Args:
            iframe: Vimeo iframe element.
            course_info: Course information.
            block_url: Block URL for context.
            
        Returns:
            Video information object or None.
        """
        try:
            src = iframe.get('src', '')
            if not src:
                return None
            
            # Extract video ID
            video_id = None
            if 'vimeo.com/video/' in src:
                video_id = src.split('/video/')[-1].split('?')[0]
            elif 'player.vimeo.com/video/' in src:
                video_id = src.split('/video/')[-1].split('?')[0]
            
            if not video_id:
                return None
            
            title = iframe.get('title', f"Vimeo Video {video_id}")
            
            return VideoInfo(
                id=f"vimeo-{video_id}",
                title=title,
                url=f"https://vimeo.com/{video_id}",
                quality='vimeo',
                duration=0,
                size=0,
                format='vimeo'
            )
            
        except Exception as e:
            logger.warning(f"Error parsing Vimeo embed: {e}")
            return None
    
    def _create_video_from_url(self, url: str, course_info: CourseInfo, block_url: str, title: str = '') -> Optional[VideoInfo]:
        """Create video info from URL.
        
        Args:
            url: Video URL.
            course_info: Course information.
            block_url: Block URL for context.
            title: Video title.
            
        Returns:
            Video information object or None.
        """
        try:
            if not self._is_video_url(url):
                return None
            
            # Make URL absolute
            if not url.startswith('http'):
                url = urljoin(self.base_url, url)
            
            if not title:
                # Extract title from URL
                parsed = urlparse(url)
                filename = parsed.path.split('/')[-1]
                title = filename.split('.')[0] if '.' in filename else 'Video'
            
            quality = self._determine_video_quality(url)
            
            return VideoInfo(
                id=f"url-{hash(url) % 10000}",
                title=title,
                url=url,
                quality=quality,
                duration=0,
                size=0,
                format=self._get_video_format(url)
            )
            
        except Exception as e:
            logger.warning(f"Error creating video from URL: {e}")
            return None
    
    def _extract_urls_from_json(self, data: Dict[str, Any]) -> Set[str]:
        """Extract video URLs from JSON data.
        
        Args:
            data: JSON data.
            
        Returns:
            Set of video URLs.
        """
        urls = set()
        
        def extract_recursive(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key.lower() in ['video_url', 'src', 'url', 'href'] and isinstance(value, str):
                        if self._is_video_url(value):
                            urls.add(value)
                    elif isinstance(value, (dict, list)):
                        extract_recursive(value)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, str) and self._is_video_url(item):
                        urls.add(item)
                    elif isinstance(item, (dict, list)):
                        extract_recursive(item)
        
        extract_recursive(data)
        return urls
    
    def _extract_urls_from_script(self, script_content: str) -> Set[str]:
        """Extract video URLs from JavaScript content.
        
        Args:
            script_content: JavaScript content.
            
        Returns:
            Set of video URLs.
        """
        urls = set()
        
        # Common patterns for video URLs in JavaScript
        patterns = [
            r'["\']([^"\']*\.(?:mp4|webm|m4v|mov|avi|mkv|flv|m3u8|mpd)(?:\?[^"\']*)?)["\']',
            r'video_url["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'src["\']?\s*[:=]\s*["\']([^"\']*\.(?:mp4|webm|m4v|mov|avi|mkv|flv|m3u8|mpd)(?:\?[^"\']*)?)["\']',
            r'url["\']?\s*[:=]\s*["\']([^"\']*\.(?:mp4|webm|m4v|mov|avi|mkv|flv|m3u8|mpd)(?:\?[^"\']*)?)["\']'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, script_content, re.IGNORECASE)
            for match in matches:
                if self._is_video_url(match):
                    urls.add(match)
        
        return urls
    
    def _is_video_url(self, url: str) -> bool:
        """Check if URL is a video URL.
        
        Args:
            url: URL to check.
            
        Returns:
            True if URL appears to be a video.
        """
        if not url:
            return False
        
        url_lower = url.lower()
        
        # Check file extensions
        parsed = urlparse(url_lower)
        path = parsed.path
        
        # Direct video files
        for ext in self.VIDEO_EXTENSIONS | self.STREAMING_FORMATS:
            if path.endswith(ext):
                return True
        
        # Video streaming services
        video_domains = [
            'youtube.com', 'youtu.be', 'vimeo.com',
            'wistia.com', 'brightcove.com', 'kaltura.com'
        ]
        
        for domain in video_domains:
            if domain in url_lower:
                return True
        
        return False
    
    def _determine_video_quality(self, url: str, element: Optional[Tag] = None) -> str:
        """Determine video quality from URL and element attributes.
        
        Args:
            url: Video URL.
            element: HTML element (optional).
            
        Returns:
            Video quality string.
        """
        # Check URL for quality indicators
        url_lower = url.lower()
        for quality, patterns in self.QUALITY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    return quality
        
        # Check element attributes if available
        if element:
            width = element.get('width')
            height = element.get('height')
            
            if height:
                try:
                    h = int(height)
                    if h >= 2160:
                        return '2160p'
                    elif h >= 1440:
                        return '1440p'
                    elif h >= 1080:
                        return '1080p'
                    elif h >= 720:
                        return '720p'
                    elif h >= 480:
                        return '480p'
                    elif h >= 360:
                        return '360p'
                    elif h >= 240:
                        return '240p'
                    else:
                        return '144p'
                except ValueError:
                    pass
        
        return 'unknown'
    
    def _get_video_format(self, url: str) -> str:
        """Get video format from URL.
        
        Args:
            url: Video URL.
            
        Returns:
            Video format string.
        """
        parsed = urlparse(url.lower())
        path = parsed.path
        
        if path.endswith('.mp4'):
            return 'mp4'
        elif path.endswith('.webm'):
            return 'webm'
        elif path.endswith('.m4v'):
            return 'm4v'
        elif path.endswith('.mov'):
            return 'mov'
        elif path.endswith('.avi'):
            return 'avi'
        elif path.endswith('.mkv'):
            return 'mkv'
        elif path.endswith('.flv'):
            return 'flv'
        elif path.endswith('.m3u8'):
            return 'hls'
        elif path.endswith('.mpd'):
            return 'dash'
        elif 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'vimeo.com' in url:
            return 'vimeo'
        else:
            return 'unknown'
    
    def _parse_duration(self, duration_str: Optional[str]) -> int:
        """Parse duration string to seconds.
        
        Args:
            duration_str: Duration string (e.g., "1:30", "90", "1h30m").
            
        Returns:
            Duration in seconds.
        """
        if not duration_str:
            return 0
        
        try:
            # Try direct integer conversion
            return int(float(duration_str))
        except ValueError:
            pass
        
        # Parse time formats
        duration_str = str(duration_str).strip()
        
        # Format: "1:30:45" or "30:45"
        if ':' in duration_str:
            parts = duration_str.split(':')
            if len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        
        # Format: "1h30m45s"
        time_pattern = r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
        match = re.match(time_pattern, duration_str.lower())
        if match:
            hours, minutes, seconds = match.groups()
            total = 0
            if hours:
                total += int(hours) * 3600
            if minutes:
                total += int(minutes) * 60
            if seconds:
                total += int(seconds)
            return total
        
        return 0
    
    async def get_video_metadata(self, video_info: VideoInfo) -> VideoInfo:
        """Get additional metadata for a video.
        
        Args:
            video_info: Video information object.
            
        Returns:
            Updated video information with metadata.
        """
        try:
            # For now, just return the original info
            # In the future, this could fetch additional metadata
            # like file size, actual duration, etc.
            return video_info
            
        except Exception as e:
            logger.warning(f"Error getting video metadata: {e}")
            return video_info
    
    def filter_videos_by_quality(self, videos: List[VideoInfo], preferred_qualities: List[str]) -> List[VideoInfo]:
        """Filter videos by quality preference.
        
        Args:
            videos: List of video information objects.
            preferred_qualities: List of preferred qualities in order.
            
        Returns:
            Filtered list of videos.
        """
        if not preferred_qualities:
            return videos
        
        # Group videos by ID (same video, different qualities)
        video_groups = {}
        for video in videos:
            base_id = video.id.split('-quality-')[0]  # Remove quality suffix if present
            if base_id not in video_groups:
                video_groups[base_id] = []
            video_groups[base_id].append(video)
        
        # Select best quality for each group
        filtered_videos = []
        for group in video_groups.values():
            best_video = self._select_best_quality(group, preferred_qualities)
            if best_video:
                filtered_videos.append(best_video)
        
        return filtered_videos
    
    def _select_best_quality(self, videos: List[VideoInfo], preferred_qualities: List[str]) -> Optional[VideoInfo]:
        """Select the best quality video from a group.
        
        Args:
            videos: List of video variants.
            preferred_qualities: List of preferred qualities.
            
        Returns:
            Best quality video or None.
        """
        if not videos:
            return None
        
        if len(videos) == 1:
            return videos[0]
        
        # Try to find preferred quality
        for quality in preferred_qualities:
            for video in videos:
                if video.quality == quality:
                    return video
        
        # If no preferred quality found, return highest available
        quality_order = ['2160p', '1440p', '1080p', '720p', '480p', '360p', '240p', '144p']
        for quality in quality_order:
            for video in videos:
                if video.quality == quality:
                    return video
        
        # Return first video as fallback
        return videos[0]