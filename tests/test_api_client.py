"""Unit tests for EDX API client."""

import asyncio
import json
import pickle
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
import requests

from edx_downloader.api_client import EdxApiClient, RateLimiter, ResponseCache
from edx_downloader.models import AppConfig, AuthSession
from edx_downloader.exceptions import (
    NetworkError, ConnectionError, TimeoutError, RateLimitError,
    ServerError, AuthenticationError, SessionExpiredError
)


class TestRateLimiter:
    """Test rate limiting functionality."""
    
    def test_init(self):
        """Test rate limiter initialization."""
        limiter = RateLimiter(delay=2.0, max_delay=30.0, backoff_factor=1.5)
        assert limiter.base_delay == 2.0
        assert limiter.current_delay == 2.0
        assert limiter.max_delay == 30.0
        assert limiter.backoff_factor == 1.5
        assert limiter.consecutive_rate_limits == 0
    
    @pytest.mark.asyncio
    async def test_wait_no_previous_request(self):
        """Test waiting when no previous request was made."""
        limiter = RateLimiter(delay=0.1)
        start_time = time.time()
        await limiter.wait()
        elapsed = time.time() - start_time
        # Should not wait if no previous request
        assert elapsed < 0.05
    
    @pytest.mark.asyncio
    async def test_wait_with_previous_request(self):
        """Test waiting when previous request was recent."""
        limiter = RateLimiter(delay=0.1)
        limiter.last_request_time = time.time()
        start_time = time.time()
        await limiter.wait()
        elapsed = time.time() - start_time
        # Should wait for the delay period
        assert elapsed >= 0.09
    
    def test_on_rate_limit(self):
        """Test rate limit handling."""
        limiter = RateLimiter(delay=1.0, backoff_factor=2.0)
        
        # First rate limit
        limiter.on_rate_limit()
        assert limiter.consecutive_rate_limits == 1
        assert limiter.current_delay == 2.0
        
        # Second rate limit
        limiter.on_rate_limit()
        assert limiter.consecutive_rate_limits == 2
        assert limiter.current_delay == 4.0
    
    def test_on_rate_limit_max_delay(self):
        """Test rate limit handling with max delay."""
        limiter = RateLimiter(delay=1.0, max_delay=5.0, backoff_factor=10.0)
        
        limiter.on_rate_limit()
        limiter.on_rate_limit()
        # Should not exceed max_delay
        assert limiter.current_delay == 5.0
    
    def test_on_success(self):
        """Test successful request handling."""
        limiter = RateLimiter(delay=1.0)
        limiter.consecutive_rate_limits = 3
        limiter.current_delay = 8.0
        
        limiter.on_success()
        assert limiter.consecutive_rate_limits == 0
        assert limiter.current_delay == 1.0


class TestResponseCache:
    """Test response caching functionality."""
    
    def setup_method(self):
        """Set up test cache."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir)
        self.cache = ResponseCache(self.cache_dir, default_ttl=300)
    
    def test_init(self):
        """Test cache initialization."""
        assert self.cache.cache_dir == self.cache_dir
        assert self.cache.default_ttl == 300
        assert self.cache_dir.exists()
    
    def test_get_cache_key(self):
        """Test cache key generation."""
        key1 = self.cache._get_cache_key("http://example.com", {"param": "value"})
        key2 = self.cache._get_cache_key("http://example.com", {"param": "value"})
        key3 = self.cache._get_cache_key("http://example.com", {"param": "other"})
        
        assert key1 == key2  # Same URL and params should generate same key
        assert key1 != key3  # Different params should generate different key
        assert len(key1) == 32  # MD5 hash length
    
    def test_determine_ttl(self):
        """Test TTL determination based on URL."""
        assert self.cache._determine_ttl("/api/course_list") == 1800
        assert self.cache._determine_ttl("/api/course_outline") == 900
        assert self.cache._determine_ttl("/api/video_info") == 3600
        assert self.cache._determine_ttl("/api/user_info") == 600
        assert self.cache._determine_ttl("/api/enrollment") == 300
        assert self.cache._determine_ttl("/api/unknown") == 300  # default
    
    def test_set_and_get(self):
        """Test setting and getting cached responses."""
        url = "http://example.com/api/test"
        response_data = {"key": "value", "number": 42}
        
        # Cache should be empty initially
        assert self.cache.get(url) is None
        
        # Set cache
        self.cache.set(url, response_data)
        
        # Should retrieve cached data
        cached = self.cache.get(url)
        assert cached == response_data
    
    def test_cache_expiration(self):
        """Test cache expiration."""
        # Create cache with very short TTL
        short_cache = ResponseCache(self.cache_dir, default_ttl=0)
        
        url = "http://example.com/api/test"
        response_data = {"key": "value"}
        
        short_cache.set(url, response_data)
        
        # Should be expired immediately
        time.sleep(0.01)
        assert short_cache.get(url) is None
    
    def test_cache_with_params(self):
        """Test caching with URL parameters."""
        url = "http://example.com/api/test"
        params1 = {"page": 1}
        params2 = {"page": 2}
        response1 = {"data": "page1"}
        response2 = {"data": "page2"}
        
        self.cache.set(url, response1, params1)
        self.cache.set(url, response2, params2)
        
        assert self.cache.get(url, params1) == response1
        assert self.cache.get(url, params2) == response2
    
    def test_clear_cache(self):
        """Test clearing all cached responses."""
        self.cache.set("http://example.com/1", {"data": 1})
        self.cache.set("http://example.com/2", {"data": 2})
        
        # Verify cache files exist
        cache_files = list(self.cache_dir.glob("*.cache"))
        assert len(cache_files) == 2
        
        self.cache.clear()
        
        # Verify cache files are removed
        cache_files = list(self.cache_dir.glob("*.cache"))
        assert len(cache_files) == 0


class TestEdxApiClient:
    """Test EDX API client functionality."""
    
    def setup_method(self):
        """Set up test client."""
        self.config = AppConfig(
            cache_directory=tempfile.mkdtemp(),
            rate_limit_delay=0.1,
            retry_attempts=2
        )
        self.client = EdxApiClient(self.config)
    
    def teardown_method(self):
        """Clean up test client."""
        self.client.close()
    
    def test_init(self):
        """Test client initialization."""
        assert self.client.config == self.config
        assert self.client.base_url == "https://courses.edx.org"
        assert isinstance(self.client.session, requests.Session)
        assert isinstance(self.client.rate_limiter, RateLimiter)
        assert isinstance(self.client.cache, ResponseCache)
    
    def test_create_session(self):
        """Test session creation with proper configuration."""
        session = self.client._create_session()
        
        # Check headers
        assert 'User-Agent' in session.headers
        assert 'edx-downloader' in session.headers['User-Agent']
        assert session.headers['Accept'] == 'application/json, text/html, */*'
        
        # Check adapters are configured
        assert len(session.adapters) >= 2
    
    def test_set_auth_session(self):
        """Test setting authentication session."""
        auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session", "csrftoken": "test-csrf"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        
        self.client.set_auth_session(auth_session)
        
        assert self.client.auth_session == auth_session
        assert self.client.session.headers['X-CSRFToken'] == "test-csrf-token"
        assert self.client.session.cookies.get('sessionid') == "test-session"
    
    def test_check_auth_session_no_session(self):
        """Test auth session check when no session is set."""
        with pytest.raises(SessionExpiredError, match="No authentication session"):
            self.client._check_auth_session()
    
    def test_check_auth_session_expired(self):
        """Test auth session check when session is expired."""
        expired_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() - timedelta(hours=1),  # Expired
            user_id="test-user"
        )
        
        self.client.set_auth_session(expired_session)
        
        with pytest.raises(SessionExpiredError, match="Authentication session has expired"):
            self.client._check_auth_session()
    
    def test_parse_response_json(self):
        """Test parsing JSON response."""
        mock_response = Mock()
        mock_response.headers = {'content-type': 'application/json'}
        mock_response.json.return_value = {"key": "value"}
        
        result = self.client._parse_response(mock_response)
        assert result == {"key": "value"}
    
    def test_parse_response_html(self):
        """Test parsing HTML response."""
        mock_response = Mock()
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.text = "<html><body>Test</body></html>"
        
        result = self.client._parse_response(mock_response)
        assert result == {
            'content': "<html><body>Test</body></html>",
            'content_type': 'html'
        }
    
    def test_parse_response_other(self):
        """Test parsing other content types."""
        mock_response = Mock()
        mock_response.headers = {'content-type': 'text/plain'}
        mock_response.text = "Plain text content"
        
        result = self.client._parse_response(mock_response)
        assert result == {
            'content': "Plain text content",
            'content_type': 'text/plain'
        }
    
    @pytest.mark.asyncio
    @patch('edx_downloader.api_client.EdxApiClient._check_auth_session')
    async def test_make_request_success(self, mock_check_auth):
        """Test successful request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'application/json'}
        mock_response.json.return_value = {"success": True}
        
        with patch.object(self.client.session, 'request', return_value=mock_response):
            result = await self.client._make_request('GET', '/api/test')
            assert result == {"success": True}
    
    @pytest.mark.asyncio
    @patch('edx_downloader.api_client.EdxApiClient._check_auth_session')
    async def test_make_request_rate_limit(self, mock_check_auth):
        """Test rate limit error handling."""
        mock_response = Mock()
        mock_response.status_code = 429
        
        with patch.object(self.client.session, 'request', return_value=mock_response):
            with pytest.raises(RateLimitError):
                await self.client._make_request('GET', '/api/test')
    
    @pytest.mark.asyncio
    @patch('edx_downloader.api_client.EdxApiClient._check_auth_session')
    async def test_make_request_auth_error(self, mock_check_auth):
        """Test authentication error handling."""
        mock_response = Mock()
        mock_response.status_code = 401
        
        with patch.object(self.client.session, 'request', return_value=mock_response):
            with pytest.raises(AuthenticationError):
                await self.client._make_request('GET', '/api/test')
    
    @pytest.mark.asyncio
    @patch('edx_downloader.api_client.EdxApiClient._check_auth_session')
    async def test_make_request_server_error(self, mock_check_auth):
        """Test server error handling."""
        mock_response = Mock()
        mock_response.status_code = 500
        
        with patch.object(self.client.session, 'request', return_value=mock_response):
            with pytest.raises(ServerError):
                await self.client._make_request('GET', '/api/test')
    
    @pytest.mark.asyncio
    @patch('edx_downloader.api_client.EdxApiClient._check_auth_session')
    async def test_make_request_timeout(self, mock_check_auth):
        """Test timeout error handling."""
        with patch.object(self.client.session, 'request', side_effect=requests.exceptions.Timeout):
            with pytest.raises(TimeoutError):
                await self.client._make_request('GET', '/api/test')
    
    @pytest.mark.asyncio
    @patch('edx_downloader.api_client.EdxApiClient._check_auth_session')
    async def test_make_request_connection_error(self, mock_check_auth):
        """Test connection error handling."""
        with patch.object(self.client.session, 'request', side_effect=requests.exceptions.ConnectionError):
            with pytest.raises(ConnectionError):
                await self.client._make_request('GET', '/api/test')
    
    @pytest.mark.asyncio
    async def test_get_method(self):
        """Test GET method wrapper."""
        with patch.object(self.client, '_make_request', return_value={"data": "test"}) as mock_request:
            result = await self.client.get('/api/test', params={'key': 'value'})
            
            mock_request.assert_called_once_with(
                'GET', '/api/test', params={'key': 'value'}, headers=None,
                require_auth=True, use_cache=True
            )
            assert result == {"data": "test"}
    
    @pytest.mark.asyncio
    async def test_post_method(self):
        """Test POST method wrapper."""
        with patch.object(self.client, '_make_request', return_value={"success": True}) as mock_request:
            result = await self.client.post('/api/test', data={'key': 'value'})
            
            mock_request.assert_called_once_with(
                'POST', '/api/test', data={'key': 'value'}, json_data=None,
                headers=None, require_auth=True, use_cache=False
            )
            assert result == {"success": True}
    
    def test_clear_cache(self):
        """Test cache clearing."""
        with patch.object(self.client.cache, 'clear') as mock_clear:
            self.client.clear_cache()
            mock_clear.assert_called_once()
    
    def test_close(self):
        """Test client cleanup."""
        with patch.object(self.client.session, 'close') as mock_close:
            self.client.close()
            mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_integration_rate_limiting():
    """Integration test for rate limiting behavior."""
    config = AppConfig(rate_limit_delay=0.1)
    client = EdxApiClient(config)
    
    # Mock successful responses
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {'content-type': 'application/json'}
    mock_response.json.return_value = {"success": True}
    
    start_time = time.time()
    
    with patch.object(client.session, 'request', return_value=mock_response):
        with patch.object(client, '_check_auth_session'):
            # Make two requests
            await client._make_request('GET', '/api/test1')
            await client._make_request('GET', '/api/test2')
    
    elapsed = time.time() - start_time
    # Should have waited for rate limit delay
    assert elapsed >= 0.1
    
    client.close()


@pytest.mark.asyncio
async def test_integration_caching():
    """Integration test for response caching."""
    config = AppConfig(cache_directory=tempfile.mkdtemp())
    client = EdxApiClient(config)
    
    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {'content-type': 'application/json'}
    mock_response.json.return_value = {"cached": True}
    
    with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
        with patch.object(client, '_check_auth_session'):
            # First request should hit the server
            result1 = await client._make_request('GET', '/api/test')
            assert result1 == {"cached": True}
            assert mock_request.call_count == 1
            
            # Second request should use cache
            result2 = await client._make_request('GET', '/api/test')
            assert result2 == {"cached": True}
            assert mock_request.call_count == 1  # No additional call
    
    client.close()