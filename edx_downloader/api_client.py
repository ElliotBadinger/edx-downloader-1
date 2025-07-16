"""Modern EDX API client with session management, rate limiting, and caching."""

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from urllib.parse import urljoin, urlparse
import hashlib
import pickle

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from edx_downloader.models import AuthSession, AppConfig
from edx_downloader.exceptions import (
    NetworkError, ConnectionError, TimeoutError, RateLimitError, 
    ServerError, AuthenticationError, SessionExpiredError
)


class RateLimiter:
    """Rate limiting functionality with configurable delays and backoff strategies."""
    
    def __init__(self, delay: float = 1.0, max_delay: float = 60.0, backoff_factor: float = 2.0):
        """Initialize rate limiter.
        
        Args:
            delay: Base delay between requests in seconds.
            max_delay: Maximum delay between requests in seconds.
            backoff_factor: Factor to multiply delay on rate limit errors.
        """
        self.base_delay = delay
        self.current_delay = delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.last_request_time = 0.0
        self.consecutive_rate_limits = 0
    
    async def wait(self) -> None:
        """Wait for the appropriate delay before making a request."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.current_delay:
            wait_time = self.current_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request_time = time.time()
    
    def on_rate_limit(self) -> None:
        """Handle rate limit response by increasing delay."""
        self.consecutive_rate_limits += 1
        self.current_delay = min(
            self.base_delay * (self.backoff_factor ** self.consecutive_rate_limits),
            self.max_delay
        )
    
    def on_success(self) -> None:
        """Handle successful response by resetting delay."""
        self.consecutive_rate_limits = 0
        self.current_delay = self.base_delay


class ResponseCache:
    """Response caching with appropriate TTL for different endpoint types."""
    
    def __init__(self, cache_dir: Path, default_ttl: int = 300):
        """Initialize response cache.
        
        Args:
            cache_dir: Directory to store cache files.
            default_ttl: Default time-to-live in seconds.
        """
        self.cache_dir = cache_dir
        self.default_ttl = default_ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # TTL settings for different endpoint types
        self.ttl_settings = {
            'course_list': 1800,      # 30 minutes
            'course_outline': 900,    # 15 minutes
            'video_info': 3600,       # 1 hour
            'user_info': 600,         # 10 minutes
            'enrollment': 300,        # 5 minutes
        }
    
    def _get_cache_key(self, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key for URL and parameters.
        
        Args:
            url: Request URL.
            params: Request parameters.
            
        Returns:
            Cache key string.
        """
        cache_data = f"{url}:{json.dumps(params or {}, sort_keys=True)}"
        return hashlib.md5(cache_data.encode()).hexdigest()
    
    def _get_cache_file(self, cache_key: str) -> Path:
        """Get cache file path for cache key.
        
        Args:
            cache_key: Cache key.
            
        Returns:
            Path to cache file.
        """
        return self.cache_dir / f"{cache_key}.cache"
    
    def _determine_ttl(self, url: str) -> int:
        """Determine TTL based on URL endpoint type.
        
        Args:
            url: Request URL.
            
        Returns:
            TTL in seconds.
        """
        for endpoint_type, ttl in self.ttl_settings.items():
            if endpoint_type in url.lower():
                return ttl
        return self.default_ttl
    
    def get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """Get cached response if available and not expired.
        
        Args:
            url: Request URL.
            params: Request parameters.
            
        Returns:
            Cached response data or None if not available/expired.
        """
        cache_key = self._get_cache_key(url, params)
        cache_file = self._get_cache_file(cache_key)
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                cached_data = pickle.load(f)
            
            # Check if cache is expired
            if datetime.now() > cached_data['expires_at']:
                cache_file.unlink()  # Remove expired cache
                return None
            
            return cached_data['response']
            
        except (pickle.PickleError, KeyError, OSError):
            # Remove corrupted cache file
            try:
                cache_file.unlink()
            except OSError:
                pass
            return None
    
    def set(self, url: str, response: Dict[str, Any], params: Optional[Dict] = None) -> None:
        """Cache response data.
        
        Args:
            url: Request URL.
            response: Response data to cache.
            params: Request parameters.
        """
        cache_key = self._get_cache_key(url, params)
        cache_file = self._get_cache_file(cache_key)
        ttl = self._determine_ttl(url)
        
        cached_data = {
            'response': response,
            'expires_at': datetime.now() + timedelta(seconds=ttl),
            'cached_at': datetime.now()
        }
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(cached_data, f)
        except (pickle.PickleError, OSError):
            # Ignore cache write errors
            pass
    
    def clear(self) -> None:
        """Clear all cached responses."""
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
            except OSError:
                pass


class EdxApiClient:
    """Modern EDX API client with proper session management and error handling."""
    
    def __init__(self, config: AppConfig):
        """Initialize EDX API client.
        
        Args:
            config: Application configuration.
        """
        self.config = config
        self.base_url = "https://courses.edx.org"
        self.session = self._create_session()
        self.rate_limiter = RateLimiter(
            delay=config.rate_limit_delay,
            max_delay=60.0,
            backoff_factor=2.0
        )
        self.cache = ResponseCache(
            cache_dir=config.cache_path / "api_responses",
            default_ttl=300
        )
        self.auth_session: Optional[AuthSession] = None
    
    def _create_session(self) -> requests.Session:
        """Create configured requests session with retry strategy.
        
        Returns:
            Configured requests session.
        """
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.config.retry_attempts,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set default headers
        session.headers.update({
            'User-Agent': 'edx-downloader/2.0 (Educational Content Downloader)',
            'Accept': 'application/json, text/html, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
        
        return session
    
    def set_auth_session(self, auth_session: AuthSession) -> None:
        """Set authentication session for API requests.
        
        Args:
            auth_session: Authentication session information.
        """
        self.auth_session = auth_session
        
        # Update session cookies
        for name, value in auth_session.session_cookies.items():
            self.session.cookies.set(name, value)
        
        # Set CSRF token header
        self.session.headers.update({
            'X-CSRFToken': auth_session.csrf_token,
            'Referer': self.base_url
        })
    
    def _check_auth_session(self) -> None:
        """Check if authentication session is valid.
        
        Raises:
            SessionExpiredError: If session is expired or not set.
        """
        if not self.auth_session:
            raise SessionExpiredError("No authentication session available")
        
        if self.auth_session.is_expired:
            raise SessionExpiredError("Authentication session has expired")
    
    async def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        require_auth: bool = True,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Make HTTP request with rate limiting and error handling.
        
        Args:
            method: HTTP method.
            url: Request URL.
            params: URL parameters.
            data: Form data.
            json_data: JSON data.
            headers: Additional headers.
            require_auth: Whether authentication is required.
            use_cache: Whether to use response caching.
            
        Returns:
            Response data.
            
        Raises:
            NetworkError: For network-related errors.
            AuthenticationError: For authentication errors.
        """
        if require_auth:
            self._check_auth_session()
        
        # Check cache for GET requests
        if method.upper() == 'GET' and use_cache:
            cached_response = self.cache.get(url, params)
            if cached_response:
                return cached_response
        
        # Apply rate limiting
        await self.rate_limiter.wait()
        
        # Prepare request
        full_url = urljoin(self.base_url, url) if not url.startswith('http') else url
        request_headers = self.session.headers.copy()
        if headers:
            request_headers.update(headers)
        
        try:
            response = self.session.request(
                method=method,
                url=full_url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=30
            )
            
            # Handle different response status codes
            if response.status_code == 200:
                self.rate_limiter.on_success()
                response_data = self._parse_response(response)
                
                # Cache successful GET responses
                if method.upper() == 'GET' and use_cache:
                    self.cache.set(url, response_data, params)
                
                return response_data
            
            elif response.status_code == 429:
                self.rate_limiter.on_rate_limit()
                raise RateLimitError(
                    "Rate limit exceeded",
                    status_code=response.status_code,
                    url=full_url
                )
            
            elif response.status_code in [401, 403]:
                raise AuthenticationError(
                    f"Authentication failed: {response.status_code}",
                    details={'status_code': response.status_code, 'url': full_url}
                )
            
            elif response.status_code >= 500:
                raise ServerError(
                    f"Server error: {response.status_code}",
                    status_code=response.status_code,
                    url=full_url
                )
            
            else:
                raise NetworkError(
                    f"HTTP error: {response.status_code}",
                    status_code=response.status_code,
                    url=full_url
                )
        
        except requests.exceptions.Timeout:
            raise TimeoutError("Request timed out", url=full_url)
        
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Connection failed: {str(e)}", url=full_url)
        
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Request failed: {str(e)}", url=full_url)
    
    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """Parse response content based on content type.
        
        Args:
            response: HTTP response object.
            
        Returns:
            Parsed response data.
        """
        content_type = response.headers.get('content-type', '').lower()
        
        if 'application/json' in content_type:
            try:
                return response.json()
            except json.JSONDecodeError:
                return {'content': response.text, 'content_type': 'json_error'}
        
        elif 'text/html' in content_type:
            return {'content': response.text, 'content_type': 'html'}
        
        else:
            return {'content': response.text, 'content_type': content_type}
    
    # Public API methods
    
    async def get(
        self,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        require_auth: bool = True,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Make GET request.
        
        Args:
            url: Request URL.
            params: URL parameters.
            headers: Additional headers.
            require_auth: Whether authentication is required.
            use_cache: Whether to use response caching.
            
        Returns:
            Response data.
        """
        return await self._make_request(
            'GET', url, params=params, headers=headers,
            require_auth=require_auth, use_cache=use_cache
        )
    
    async def post(
        self,
        url: str,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        require_auth: bool = True
    ) -> Dict[str, Any]:
        """Make POST request.
        
        Args:
            url: Request URL.
            data: Form data.
            json_data: JSON data.
            headers: Additional headers.
            require_auth: Whether authentication is required.
            
        Returns:
            Response data.
        """
        return await self._make_request(
            'POST', url, data=data, json_data=json_data,
            headers=headers, require_auth=require_auth, use_cache=False
        )
    
    def clear_cache(self) -> None:
        """Clear all cached responses."""
        self.cache.clear()
    
    def close(self) -> None:
        """Close the session and cleanup resources."""
        self.session.close()