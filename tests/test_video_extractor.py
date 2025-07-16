"""Unit tests for video extractor."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from bs4 import BeautifulSoup

from edx_downloader.video_extractor import VideoExtractor
from edx_downloader.api_client import EdxApiClient
from edx_downloader.models import VideoInfo, CourseInfo
from edx_downloader.exceptions import ParseError, VideoNotFoundError


class TestVideoExtractor:
    """Test video extractor functionality."""
    
    def setup_method(self):
        """Set up test video extractor."""
        self.api_client = Mock(spec=EdxApiClient)
        self.api_client.base_url = "https://courses.edx.org"
        self.extractor = VideoExtractor(self.api_client)
        
        self.course_info = CourseInfo(
            id="test-course",
            title="Test Course",
            url="https://example.com/course",
            enrollment_status="enrolled",
            access_level="full"
        )
    
    @pytest.mark.asyncio
    async def test_extract_videos_from_block_json(self):
        """Test extracting videos from JSON block response."""
        block_url = "https://example.com/block"
        
        json_response = {
            'video': {
                'id': 'video-123',
                'display_name': 'Introduction Video',
                'encoded_videos': {
                    '720p': 'https://example.com/video_720p.mp4',
                    '480p': 'https://example.com/video_480p.mp4'
                },
                'duration': 300
            }
        }
        
        self.api_client.get = AsyncMock(return_value=json_response)
        
        videos = await self.extractor.extract_videos_from_block(block_url, self.course_info)
        
        assert len(videos) == 1
        video = videos[0]
        assert video.id == 'video-123'
        assert video.title == 'Introduction Video'
        assert video.quality == '720p'
        assert video.duration == 300
        assert 'video_720p.mp4' in video.url
    
    @pytest.mark.asyncio
    async def test_extract_videos_from_block_html(self):
        """Test extracting videos from HTML block response."""
        block_url = "https://example.com/block"
        
        html_content = '''
        <html>
        <body>
            <video title="Course Introduction" width="1280" height="720">
                <source src="https://example.com/intro.mp4" type="video/mp4">
            </video>
            <div class="video-player" data-video-url="https://example.com/lesson1.mp4" data-title="Lesson 1">
            </div>
        </body>
        </html>
        '''
        
        self.api_client.get = AsyncMock(return_value=html_content)
        
        videos = await self.extractor.extract_videos_from_block(block_url, self.course_info)
        
        assert len(videos) >= 1
        titles = [v.title for v in videos]
        assert "Course Introduction" in titles
    
    @pytest.mark.asyncio
    async def test_extract_videos_no_videos_found(self):
        """Test extracting videos when none are found."""
        block_url = "https://example.com/block"
        
        html_content = '<html><body><p>No videos here</p></body></html>'
        self.api_client.get = AsyncMock(return_value=html_content)
        
        with pytest.raises(VideoNotFoundError, match="No videos found"):
            await self.extractor.extract_videos_from_block(block_url, self.course_info)
    
    def test_extract_html5_videos(self):
        """Test extracting HTML5 video elements."""
        html = '''
        <html>
        <body>
            <video title="Test Video" width="1920" height="1080">
                <source src="https://example.com/test.mp4" type="video/mp4">
            </video>
            <video src="https://example.com/direct.webm" title="Direct Video">
            </video>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        videos = self.extractor._extract_html5_videos(soup, self.course_info, "https://example.com/block")
        
        assert len(videos) == 2
        assert videos[0].title == "Test Video"
        assert videos[0].quality == "1080p"
        assert videos[1].title == "Direct Video"
        assert "test.mp4" in videos[0].url
        assert "direct.webm" in videos[1].url
    
    def test_extract_video_players(self):
        """Test extracting video player elements."""
        html = '''
        <html>
        <body>
            <div class="video-player" data-video-url="https://example.com/player1.mp4" data-title="Player Video 1">
            </div>
            <div class="xblock-video" data-src="https://example.com/player2.m3u8" title="Player Video 2">
            </div>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        videos = self.extractor._extract_video_players(soup, self.course_info, "https://example.com/block")
        
        assert len(videos) == 2
        assert videos[0].title == "Player Video 1"
        assert videos[1].title == "Player Video 2"
        assert "player1.mp4" in videos[0].url
        assert "player2.m3u8" in videos[1].url
    
    def test_extract_js_videos(self):
        """Test extracting videos from JavaScript content."""
        html = '''
        <html>
        <body>
            <script>
                var videoConfig = {
                    video_url: "https://example.com/js_video.mp4",
                    sources: ["https://example.com/source1.webm", "https://example.com/playlist.m3u8"]
                };
            </script>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        videos = self.extractor._extract_js_videos(soup, self.course_info, "https://example.com/block")
        
        assert len(videos) >= 1
        video_urls = [v.url for v in videos]
        assert any("js_video.mp4" in url for url in video_urls)
    
    def test_extract_video_links(self):
        """Test extracting direct video links."""
        html = '''
        <html>
        <body>
            <a href="https://example.com/download.mp4" title="Download Video">Download MP4</a>
            <a href="https://example.com/stream.m3u8">Stream Video</a>
            <a href="https://example.com/not-video.pdf">Not a video</a>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        videos = self.extractor._extract_video_links(soup, self.course_info, "https://example.com/block")
        
        assert len(videos) == 2
        video_urls = [v.url for v in videos]
        assert any("download.mp4" in url for url in video_urls)
        assert any("stream.m3u8" in url for url in video_urls)
        assert not any("not-video.pdf" in url for url in video_urls)
    
    def test_extract_embedded_videos(self):
        """Test extracting embedded videos (YouTube, Vimeo)."""
        html = '''
        <html>
        <body>
            <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" title="YouTube Video"></iframe>
            <iframe src="https://player.vimeo.com/video/123456789" title="Vimeo Video"></iframe>
        </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        
        videos = self.extractor._extract_embedded_videos(soup, self.course_info, "https://example.com/block")
        
        assert len(videos) == 2
        
        youtube_video = next(v for v in videos if v.format == 'youtube')
        vimeo_video = next(v for v in videos if v.format == 'vimeo')
        
        assert "dQw4w9WgXcQ" in youtube_video.url
        assert "123456789" in vimeo_video.url
    
    def test_parse_video_json(self):
        """Test parsing video information from JSON data."""
        video_data = {
            'id': 'test-video-123',
            'display_name': 'Advanced Python Concepts',
            'encoded_videos': {
                '1080p': 'https://example.com/python_1080p.mp4',
                '720p': 'https://example.com/python_720p.mp4',
                '480p': 'https://example.com/python_480p.mp4'
            },
            'duration': 1800,
            'file_size': 524288000
        }
        
        video_info = self.extractor._parse_video_json(video_data, self.course_info, "https://example.com/block")
        
        assert video_info is not None
        assert video_info.id == 'test-video-123'
        assert video_info.title == 'Advanced Python Concepts'
        assert video_info.quality == '1080p'  # Should prefer highest quality
        assert video_info.duration == 1800
        assert video_info.size == 524288000
        assert 'python_1080p.mp4' in video_info.url
    
    def test_parse_encoded_videos(self):
        """Test parsing encoded videos data."""
        data = {
            'id': 'encoded-test',
            'display_name': 'Encoded Video Test',
            'encoded_videos': {
                '720p': 'https://example.com/encoded_720p.mp4',
                '480p': 'https://example.com/encoded_480p.mp4'
            },
            'duration': 600
        }
        
        video_info = self.extractor._parse_encoded_videos(data, self.course_info, "https://example.com/block")
        
        assert video_info is not None
        assert video_info.title == 'Encoded Video Test'
        assert video_info.quality == '720p'
        assert video_info.duration == 600
    
    def test_parse_youtube_embed(self):
        """Test parsing YouTube embed iframe."""
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?start=30" title="Rick Roll"></iframe>'
        soup = BeautifulSoup(html, 'html.parser')
        iframe = soup.find('iframe')
        
        video_info = self.extractor._parse_youtube_embed(iframe, self.course_info, "https://example.com/block")
        
        assert video_info is not None
        assert video_info.id == 'youtube-dQw4w9WgXcQ'
        assert video_info.title == 'Rick Roll'
        assert video_info.format == 'youtube'
        assert 'dQw4w9WgXcQ' in video_info.url
    
    def test_parse_vimeo_embed(self):
        """Test parsing Vimeo embed iframe."""
        html = '<iframe src="https://player.vimeo.com/video/123456789" title="Vimeo Test"></iframe>'
        soup = BeautifulSoup(html, 'html.parser')
        iframe = soup.find('iframe')
        
        video_info = self.extractor._parse_vimeo_embed(iframe, self.course_info, "https://example.com/block")
        
        assert video_info is not None
        assert video_info.id == 'vimeo-123456789'
        assert video_info.title == 'Vimeo Test'
        assert video_info.format == 'vimeo'
        assert '123456789' in video_info.url
    
    def test_create_video_from_url(self):
        """Test creating video info from URL."""
        url = "https://example.com/videos/lecture_720p.mp4"
        title = "Lecture Video"
        
        video_info = self.extractor._create_video_from_url(url, self.course_info, "https://example.com/block", title)
        
        assert video_info is not None
        assert video_info.title == title
        assert video_info.url == url
        assert video_info.quality == '720p'
        assert video_info.format == 'mp4'
    
    def test_extract_urls_from_json(self):
        """Test extracting video URLs from JSON data."""
        data = {
            'video_url': 'https://example.com/main.mp4',
            'sources': [
                'https://example.com/source1.webm',
                'https://example.com/source2.m3u8'
            ],
            'nested': {
                'src': 'https://example.com/nested.mp4',
                'other': 'not a video url'
            }
        }
        
        urls = self.extractor._extract_urls_from_json(data)
        
        assert len(urls) >= 3
        assert 'https://example.com/main.mp4' in urls
        assert 'https://example.com/source1.webm' in urls
        assert 'https://example.com/nested.mp4' in urls
    
    def test_extract_urls_from_script(self):
        """Test extracting video URLs from JavaScript content."""
        script_content = '''
        var config = {
            video_url: "https://example.com/script_video.mp4",
            src: "https://example.com/script_source.webm",
            playlist: "https://example.com/playlist.m3u8"
        };
        var otherUrl = "https://example.com/other.mp4";
        '''
        
        urls = self.extractor._extract_urls_from_script(script_content)
        
        assert len(urls) >= 3
        assert 'https://example.com/script_video.mp4' in urls
        assert 'https://example.com/script_source.webm' in urls
        assert 'https://example.com/playlist.m3u8' in urls
    
    def test_is_video_url(self):
        """Test video URL detection."""
        # Video file URLs
        assert self.extractor._is_video_url('https://example.com/video.mp4')
        assert self.extractor._is_video_url('https://example.com/stream.m3u8')
        assert self.extractor._is_video_url('https://example.com/content.webm')
        
        # Video service URLs
        assert self.extractor._is_video_url('https://www.youtube.com/watch?v=123')
        assert self.extractor._is_video_url('https://vimeo.com/123456')
        
        # Video-related URLs (these should NOT be detected as videos without clear indicators)
        assert not self.extractor._is_video_url('https://example.com/video/player')
        assert not self.extractor._is_video_url('https://example.com/media/stream')
        
        # Non-video URLs
        assert not self.extractor._is_video_url('https://example.com/document.pdf')
        assert not self.extractor._is_video_url('https://example.com/image.jpg')
        assert not self.extractor._is_video_url('https://example.com/page.html')
        assert not self.extractor._is_video_url('')
    
    def test_determine_video_quality(self):
        """Test video quality determination."""
        # URL-based quality detection
        assert self.extractor._determine_video_quality('https://example.com/video_1080p.mp4') == '1080p'
        assert self.extractor._determine_video_quality('https://example.com/hd_video.mp4') == '720p'
        assert self.extractor._determine_video_quality('https://example.com/4k_video.mp4') == '2160p'
        
        # Element-based quality detection
        html = '<video width="1920" height="1080"></video>'
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.find('video')
        
        quality = self.extractor._determine_video_quality('https://example.com/video.mp4', element)
        assert quality == '1080p'
        
        # Unknown quality
        assert self.extractor._determine_video_quality('https://example.com/video.mp4') == 'unknown'
    
    def test_get_video_format(self):
        """Test video format detection."""
        assert self.extractor._get_video_format('https://example.com/video.mp4') == 'mp4'
        assert self.extractor._get_video_format('https://example.com/video.webm') == 'webm'
        assert self.extractor._get_video_format('https://example.com/stream.m3u8') == 'hls'
        assert self.extractor._get_video_format('https://example.com/manifest.mpd') == 'dash'
        assert self.extractor._get_video_format('https://youtube.com/watch?v=123') == 'youtube'
        assert self.extractor._get_video_format('https://vimeo.com/123') == 'vimeo'
        assert self.extractor._get_video_format('https://example.com/unknown') == 'unknown'
    
    def test_parse_duration(self):
        """Test duration parsing."""
        # Direct seconds
        assert self.extractor._parse_duration('300') == 300
        assert self.extractor._parse_duration('90.5') == 90
        
        # MM:SS format
        assert self.extractor._parse_duration('5:30') == 330
        assert self.extractor._parse_duration('1:45') == 105
        
        # HH:MM:SS format
        assert self.extractor._parse_duration('1:30:45') == 5445
        assert self.extractor._parse_duration('0:05:30') == 330
        
        # Text format
        assert self.extractor._parse_duration('1h30m45s') == 5445
        assert self.extractor._parse_duration('30m') == 1800
        assert self.extractor._parse_duration('45s') == 45
        
        # Invalid/empty
        assert self.extractor._parse_duration('') == 0
        assert self.extractor._parse_duration(None) == 0
        assert self.extractor._parse_duration('invalid') == 0
    
    @pytest.mark.asyncio
    async def test_get_video_metadata(self):
        """Test getting video metadata."""
        video_info = VideoInfo(
            id='test-video',
            title='Test Video',
            url='https://example.com/test.mp4',
            quality='720p',
            duration=300,
            size=0,
            format='mp4'
        )
        
        result = await self.extractor.get_video_metadata(video_info)
        
        # For now, should return the same object
        assert result == video_info
    
    def test_filter_videos_by_quality(self):
        """Test filtering videos by quality preference."""
        videos = [
            VideoInfo(id='video-1', title='Video 1', url='https://example.com/1_480p.mp4', 
                     quality='480p', duration=0, size=0, format='mp4'),
            VideoInfo(id='video-1', title='Video 1', url='https://example.com/1_720p.mp4', 
                     quality='720p', duration=0, size=0, format='mp4'),
            VideoInfo(id='video-2', title='Video 2', url='https://example.com/2_1080p.mp4', 
                     quality='1080p', duration=0, size=0, format='mp4'),
        ]
        
        # Prefer 720p
        filtered = self.extractor.filter_videos_by_quality(videos, ['720p', '480p'])
        
        assert len(filtered) == 2
        qualities = [v.quality for v in filtered]
        assert '720p' in qualities  # Should pick 720p for video-1
        assert '1080p' in qualities  # Should pick 1080p for video-2 (highest available)
    
    def test_select_best_quality(self):
        """Test selecting best quality from video group."""
        videos = [
            VideoInfo(id='video-1', title='Video 1', url='https://example.com/1_480p.mp4', 
                     quality='480p', duration=0, size=0, format='mp4'),
            VideoInfo(id='video-1', title='Video 1', url='https://example.com/1_720p.mp4', 
                     quality='720p', duration=0, size=0, format='mp4'),
            VideoInfo(id='video-1', title='Video 1', url='https://example.com/1_1080p.mp4', 
                     quality='1080p', duration=0, size=0, format='mp4'),
        ]
        
        # Prefer 720p
        best = self.extractor._select_best_quality(videos, ['720p', '480p'])
        assert best.quality == '720p'
        
        # No preference - should pick highest
        best = self.extractor._select_best_quality(videos, [])
        assert best.quality == '1080p'
        
        # Single video
        best = self.extractor._select_best_quality([videos[0]], ['720p'])
        assert best.quality == '480p'
        
        # Empty list
        best = self.extractor._select_best_quality([], ['720p'])
        assert best is None