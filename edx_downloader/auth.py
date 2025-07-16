"""Modern authentication system for EDX downloader."""

import re
import time
import base64
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
import requests

from edx_downloader.models import AuthSession
from edx_downloader.config import CredentialManager
from edx_downloader.exceptions import (
    AuthenticationError, InvalidCredentialsError, SessionExpiredError,
    TwoFactorRequiredError, NetworkError, ParseError
)


class AuthenticationManager:
    """Manages EDX authentication flows with modern session handling."""
    
    def __init__(self, credential_manager: CredentialManager, base_url: str = "https://courses.edx.org"):
        """Initialize authentication manager.
        
        Args:
            credential_manager: Credential storage manager.
            base_url: Base URL for EDX platform.
        """
        self.credential_manager = credential_manager
        self.base_url = base_url
        self.session = self._create_session()
        self.current_auth_session: Optional[AuthSession] = None
    
    def _create_session(self) -> requests.Session:
        """Create configured requests session for authentication.
        
        Returns:
            Configured requests session.
        """
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        return session
    
    def authenticate(self, username: str, password: Optional[str] = None) -> AuthSession:
        """Authenticate user and create session.
        
        Args:
            username: EDX username or email.
            password: EDX password. If None, will try to retrieve from storage.
            
        Returns:
            Authentication session.
            
        Raises:
            AuthenticationError: If authentication fails.
            InvalidCredentialsError: If credentials are invalid.
            TwoFactorRequiredError: If 2FA is required.
        """
        # Get password from storage if not provided
        if password is None:
            password = self.credential_manager.get_credentials(username)
            if password is None:
                raise InvalidCredentialsError(
                    "No stored credentials found for user",
                    username=username
                )
        
        try:
            # Step 1: Get login page and extract CSRF token
            csrf_token = self._get_csrf_token()
            
            # Step 2: Perform login
            auth_session = self._perform_login(username, password, csrf_token)
            
            # Step 3: Validate session
            self._validate_session(auth_session)
            
            # Store successful credentials
            self.credential_manager.store_credentials(username, password)
            self.current_auth_session = auth_session
            
            return auth_session
            
        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Authentication failed: {str(e)}", username=username)
    
    def _get_csrf_token(self) -> str:
        """Get CSRF token from login page.
        
        Returns:
            CSRF token string.
            
        Raises:
            AuthenticationError: If CSRF token cannot be retrieved.
        """
        try:
            login_url = urljoin(self.base_url, "/login")
            response = self.session.get(login_url, timeout=30)
            response.raise_for_status()
            
            # Parse HTML to find CSRF token
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for CSRF token in meta tag
            csrf_meta = soup.find('meta', {'name': 'csrf-token'})
            if csrf_meta and csrf_meta.get('content'):
                return csrf_meta['content']
            
            # Look for CSRF token in form input
            csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})
            if csrf_input and csrf_input.get('value'):
                return csrf_input['value']
            
            # Look for CSRF token in cookies
            csrf_cookie = self.session.cookies.get('csrftoken')
            if csrf_cookie:
                return csrf_cookie
            
            raise AuthenticationError("CSRF token not found in login page")
            
        except requests.RequestException as e:
            raise AuthenticationError(f"Failed to get login page: {str(e)}")
    
    def _perform_login(self, username: str, password: str, csrf_token: str) -> AuthSession:
        """Perform login with credentials.
        
        Args:
            username: EDX username or email.
            password: EDX password.
            csrf_token: CSRF token.
            
        Returns:
            Authentication session.
            
        Raises:
            InvalidCredentialsError: If credentials are invalid.
            TwoFactorRequiredError: If 2FA is required.
            AuthenticationError: If login fails.
        """
        try:
            login_url = urljoin(self.base_url, "/user_api/v1/account/login_session/")
            
            # Prepare login data
            login_data = {
                'email': username,
                'password': password,
                'remember': 'false',
            }
            
            # Set headers for login request
            headers = {
                'X-CSRFToken': csrf_token,
                'Referer': urljoin(self.base_url, "/login"),
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
            }
            
            response = self.session.post(
                login_url,
                data=login_data,
                headers=headers,
                timeout=30
            )
            
            # Handle different response scenarios
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get('success'):
                        return self._create_auth_session(csrf_token)
                    else:
                        error_msg = result.get('value', 'Login failed')
                        if 'email or password is incorrect' in error_msg.lower():
                            raise InvalidCredentialsError(error_msg, username=username)
                        elif 'two-factor' in error_msg.lower() or '2fa' in error_msg.lower():
                            raise TwoFactorRequiredError(error_msg, username=username)
                        else:
                            raise AuthenticationError(error_msg, username=username)
                except ValueError:
                    # Response is not JSON, check for redirect or other indicators
                    if 'dashboard' in response.url or response.status_code == 302:
                        return self._create_auth_session(csrf_token)
                    else:
                        raise AuthenticationError("Unexpected login response format")
            
            elif response.status_code == 400:
                raise InvalidCredentialsError("Invalid credentials", username=username)
            elif response.status_code == 403:
                raise AuthenticationError("Login forbidden - possible rate limiting", username=username)
            else:
                raise AuthenticationError(f"Login failed with status {response.status_code}", username=username)
                
        except requests.RequestException as e:
            raise AuthenticationError(f"Login request failed: {str(e)}", username=username)
    
    def _create_auth_session(self, csrf_token: str) -> AuthSession:
        """Create authentication session from current session state.
        
        Args:
            csrf_token: CSRF token.
            
        Returns:
            Authentication session.
        """
        # Extract session cookies
        session_cookies = {}
        for cookie in self.session.cookies:
            session_cookies[cookie.name] = cookie.value
        
        # Get user ID from session or dashboard
        user_id = self._extract_user_id()
        
        # Set expiration time (EDX sessions typically last 2 weeks)
        expires_at = datetime.now() + timedelta(days=14)
        
        return AuthSession(
            csrf_token=csrf_token,
            session_cookies=session_cookies,
            expires_at=expires_at,
            user_id=user_id
        )
    
    def _extract_user_id(self) -> str:
        """Extract user ID from session.
        
        Returns:
            User ID string.
        """
        try:
            # Try to get user info from dashboard
            dashboard_url = urljoin(self.base_url, "/dashboard")
            response = self.session.get(dashboard_url, timeout=30)
            
            if response.status_code == 200:
                # Look for user ID in page content
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check for user ID in data attributes
                user_element = soup.find(attrs={'data-user-id': True})
                if user_element:
                    return user_element['data-user-id']
                
                # Check for user ID in JavaScript variables
                script_tags = soup.find_all('script')
                for script in script_tags:
                    if script.string:
                        # Look for user ID patterns in JavaScript
                        user_id_match = re.search(r'"user_id":\s*"?(\d+)"?', script.string)
                        if user_id_match:
                            return user_id_match.group(1)
                        
                        user_id_match = re.search(r'userId["\']:\s*["\']?(\d+)["\']?', script.string)
                        if user_id_match:
                            return user_id_match.group(1)
            
            # Fallback: use session ID or generate from cookies
            session_id = self.session.cookies.get('sessionid', '')
            if session_id:
                return f"session_{session_id[:8]}"
            
            return f"user_{int(time.time())}"
            
        except Exception:
            # Fallback user ID
            return f"user_{int(time.time())}"
    
    def _validate_session(self, auth_session: AuthSession) -> None:
        """Validate authentication session by making a test request.
        
        Args:
            auth_session: Authentication session to validate.
            
        Raises:
            AuthenticationError: If session validation fails.
        """
        try:
            # Test session by accessing user account info
            account_url = urljoin(self.base_url, "/api/user/v1/me")
            headers = {
                'X-CSRFToken': auth_session.csrf_token,
            }
            
            # Set session cookies
            for name, value in auth_session.session_cookies.items():
                self.session.cookies.set(name, value)
            
            response = self.session.get(account_url, headers=headers, timeout=30)
            
            if response.status_code not in [200, 404]:  # 404 is acceptable for some EDX versions
                raise AuthenticationError("Session validation failed")
                
        except requests.RequestException as e:
            raise AuthenticationError(f"Session validation request failed: {str(e)}")
    
    def refresh_session(self, auth_session: AuthSession) -> AuthSession:
        """Refresh authentication session.
        
        Args:
            auth_session: Current authentication session.
            
        Returns:
            Refreshed authentication session.
            
        Raises:
            SessionExpiredError: If session cannot be refreshed.
        """
        try:
            # Set current session cookies
            for name, value in auth_session.session_cookies.items():
                self.session.cookies.set(name, value)
            
            # Get new CSRF token
            csrf_token = self._get_csrf_token()
            
            # Create refreshed session
            refreshed_session = AuthSession(
                csrf_token=csrf_token,
                session_cookies=auth_session.session_cookies,
                expires_at=datetime.now() + timedelta(days=14),
                user_id=auth_session.user_id
            )
            
            # Validate refreshed session
            self._validate_session(refreshed_session)
            
            self.current_auth_session = refreshed_session
            return refreshed_session
            
        except Exception as e:
            raise SessionExpiredError(f"Failed to refresh session: {str(e)}")
    
    def is_authenticated(self) -> bool:
        """Check if currently authenticated.
        
        Returns:
            True if authenticated and session is valid.
        """
        if not self.current_auth_session:
            return False
        
        if self.current_auth_session.is_expired:
            return False
        
        try:
            self._validate_session(self.current_auth_session)
            return True
        except AuthenticationError:
            return False
    
    def logout(self) -> None:
        """Logout and clear session.
        
        Raises:
            AuthenticationError: If logout fails.
        """
        try:
            if self.current_auth_session:
                logout_url = urljoin(self.base_url, "/logout")
                headers = {
                    'X-CSRFToken': self.current_auth_session.csrf_token,
                    'Referer': self.base_url,
                }
                
                self.session.post(logout_url, headers=headers, timeout=30)
            
            # Clear session state
            self.session.cookies.clear()
            self.current_auth_session = None
            
        except requests.RequestException as e:
            raise AuthenticationError(f"Logout failed: {str(e)}")
    
    def get_current_session(self) -> Optional[AuthSession]:
        """Get current authentication session.
        
        Returns:
            Current authentication session or None.
        """
        return self.current_auth_session
    
    async def _authenticate_oauth2(self, username: str, password: str) -> AuthSession:
        """Authenticate using OAuth2 flow (modern EDX).
        
        Args:
            username: EDX username or email.
            password: EDX password.
            
        Returns:
            Authentication session with OAuth2 token.
            
        Raises:
            AuthenticationError: If OAuth2 authentication fails.
        """
        try:
            # Step 1: Get OAuth2 application credentials
            # Note: In production, these would be configured per EDX instance
            client_id = "your-client-id"  # Would be configured
            client_secret = "your-client-secret"  # Would be configured
            
            # Step 2: Create basic auth header
            credential = f"{client_id}:{client_secret}"
            encoded_credential = base64.b64encode(credential.encode("utf-8")).decode("utf-8")
            
            # Step 3: Request OAuth2 token
            token_url = urljoin(self.base_url, "/oauth2/access_token")
            headers = {
                "Authorization": f"Basic {encoded_credential}",
                "Cache-Control": "no-cache",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "grant_type": "password",
                "username": username,
                "password": password,
                "token_type": "jwt"
            }
            
            response = self.session.post(token_url, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                
                if access_token:
                    # Create OAuth2-based auth session
                    expires_at = datetime.now() + timedelta(seconds=token_data.get("expires_in", 3600))
                    
                    return AuthSession(
                        csrf_token="",  # Not needed for OAuth2
                        session_cookies={"oauth_token": access_token},
                        expires_at=expires_at,
                        user_id=username
                    )
            
            raise AuthenticationError("OAuth2 authentication failed")
            
        except requests.RequestException as e:
            raise AuthenticationError(f"OAuth2 request failed: {str(e)}")
    
    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests.
        
        Returns:
            Dictionary of authentication headers.
        """
        if not self.current_auth_session:
            return {}
        
        headers = {}
        
        # Check if we have OAuth2 token
        oauth_token = self.current_auth_session.session_cookies.get("oauth_token")
        if oauth_token:
            headers["Authorization"] = f"JWT {oauth_token}"
        
        # Add CSRF token if available
        if self.current_auth_session.csrf_token:
            headers["X-CSRFToken"] = self.current_auth_session.csrf_token
        
        return headers
    
    def close(self) -> None:
        """Close authentication manager and cleanup resources."""
        try:
            self.logout()
        except AuthenticationError:
            pass  # Ignore logout errors during cleanup
        
        self.session.close()