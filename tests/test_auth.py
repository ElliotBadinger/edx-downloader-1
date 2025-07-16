"""Unit tests for EDX authentication system."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
import requests
from bs4 import BeautifulSoup

from edx_downloader.auth import AuthenticationManager
from edx_downloader.config import CredentialManager
from edx_downloader.models import AuthSession
from edx_downloader.exceptions import (
    AuthenticationError, InvalidCredentialsError, SessionExpiredError,
    TwoFactorRequiredError
)


class TestAuthenticationManager:
    """Test authentication manager functionality."""
    
    def setup_method(self):
        """Set up test authentication manager."""
        self.temp_dir = tempfile.mkdtemp()
        self.credential_manager = CredentialManager()
        self.auth_manager = AuthenticationManager(
            credential_manager=self.credential_manager,
            base_url="https://courses.edx.org"
        )
    
    def teardown_method(self):
        """Clean up test authentication manager."""
        self.auth_manager.close()
    
    def test_init(self):
        """Test authentication manager initialization."""
        assert self.auth_manager.credential_manager == self.credential_manager
        assert self.auth_manager.base_url == "https://courses.edx.org"
        assert isinstance(self.auth_manager.session, requests.Session)
        assert self.auth_manager.current_auth_session is None
    
    def test_create_session(self):
        """Test session creation with proper headers."""
        session = self.auth_manager._create_session()
        
        assert 'User-Agent' in session.headers
        assert 'Mozilla' in session.headers['User-Agent']
        assert session.headers['Accept'].startswith('text/html')
        assert session.headers['Connection'] == 'keep-alive'
    
    @patch('edx_downloader.auth.AuthenticationManager._get_csrf_token')
    @patch('edx_downloader.auth.AuthenticationManager._perform_login')
    @patch('edx_downloader.auth.AuthenticationManager._validate_session')
    def test_authenticate_with_password(self, mock_validate, mock_login, mock_csrf):
        """Test authentication with provided password."""
        # Setup mocks
        mock_csrf.return_value = "test-csrf-token"
        mock_auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        mock_login.return_value = mock_auth_session
        
        with patch.object(self.credential_manager, 'store_credentials') as mock_store:
            result = self.auth_manager.authenticate("test@example.com", "password123")
            
            assert result == mock_auth_session
            assert self.auth_manager.current_auth_session == mock_auth_session
            mock_csrf.assert_called_once()
            mock_login.assert_called_once_with("test@example.com", "password123", "test-csrf-token")
            mock_validate.assert_called_once_with(mock_auth_session)
            mock_store.assert_called_once_with("test@example.com", "password123")
    
    @patch('edx_downloader.auth.AuthenticationManager._get_csrf_token')
    @patch('edx_downloader.auth.AuthenticationManager._perform_login')
    @patch('edx_downloader.auth.AuthenticationManager._validate_session')
    def test_authenticate_with_stored_credentials(self, mock_validate, mock_login, mock_csrf):
        """Test authentication with stored credentials."""
        # Setup mocks
        mock_csrf.return_value = "test-csrf-token"
        mock_auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        mock_login.return_value = mock_auth_session
        
        with patch.object(self.credential_manager, 'get_credentials', return_value="stored-password"):
            with patch.object(self.credential_manager, 'store_credentials') as mock_store:
                result = self.auth_manager.authenticate("test@example.com")
                
                assert result == mock_auth_session
                mock_login.assert_called_once_with("test@example.com", "stored-password", "test-csrf-token")
    
    def test_authenticate_no_stored_credentials(self):
        """Test authentication when no stored credentials are found."""
        with patch.object(self.credential_manager, 'get_credentials', return_value=None):
            with pytest.raises(InvalidCredentialsError, match="No stored credentials found"):
                self.auth_manager.authenticate("test@example.com")
    
    @patch('requests.Session.get')
    def test_get_csrf_token_from_meta(self, mock_get):
        """Test CSRF token extraction from meta tag."""
        html_content = '''
        <html>
        <head>
            <meta name="csrf-token" content="meta-csrf-token">
        </head>
        </html>
        '''
        mock_response = Mock()
        mock_response.text = html_content
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        token = self.auth_manager._get_csrf_token()
        assert token == "meta-csrf-token"
    
    @patch('requests.Session.get')
    def test_get_csrf_token_from_input(self, mock_get):
        """Test CSRF token extraction from form input."""
        html_content = '''
        <html>
        <body>
            <form>
                <input name="csrfmiddlewaretoken" value="input-csrf-token">
            </form>
        </body>
        </html>
        '''
        mock_response = Mock()
        mock_response.text = html_content
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        token = self.auth_manager._get_csrf_token()
        assert token == "input-csrf-token"
    
    @patch('requests.Session.get')
    def test_get_csrf_token_from_cookie(self, mock_get):
        """Test CSRF token extraction from cookie."""
        mock_response = Mock()
        mock_response.text = "<html></html>"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        # Mock session cookies
        self.auth_manager.session.cookies.set('csrftoken', 'cookie-csrf-token')
        
        token = self.auth_manager._get_csrf_token()
        assert token == "cookie-csrf-token"
    
    @patch('requests.Session.get')
    def test_get_csrf_token_not_found(self, mock_get):
        """Test CSRF token extraction when token is not found."""
        mock_response = Mock()
        mock_response.text = "<html></html>"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        with pytest.raises(AuthenticationError, match="CSRF token not found"):
            self.auth_manager._get_csrf_token()
    
    @patch('requests.Session.post')
    @patch('edx_downloader.auth.AuthenticationManager._create_auth_session')
    def test_perform_login_success_json(self, mock_create_session, mock_post):
        """Test successful login with JSON response."""
        mock_auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        mock_create_session.return_value = mock_auth_session
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_post.return_value = mock_response
        
        result = self.auth_manager._perform_login("test@example.com", "password123", "csrf-token")
        
        assert result == mock_auth_session
        mock_post.assert_called_once()
        mock_create_session.assert_called_once_with("csrf-token")
    
    @patch('requests.Session.post')
    def test_perform_login_invalid_credentials(self, mock_post):
        """Test login with invalid credentials."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "value": "Email or password is incorrect"
        }
        mock_post.return_value = mock_response
        
        with pytest.raises(InvalidCredentialsError, match="Email or password is incorrect"):
            self.auth_manager._perform_login("test@example.com", "wrong-password", "csrf-token")
    
    @patch('requests.Session.post')
    def test_perform_login_two_factor_required(self, mock_post):
        """Test login when two-factor authentication is required."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "value": "Two-factor authentication is required"
        }
        mock_post.return_value = mock_response
        
        with pytest.raises(TwoFactorRequiredError, match="Two-factor authentication is required"):
            self.auth_manager._perform_login("test@example.com", "password123", "csrf-token")
    
    @patch('requests.Session.post')
    def test_perform_login_bad_request(self, mock_post):
        """Test login with bad request response."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_post.return_value = mock_response
        
        with pytest.raises(InvalidCredentialsError, match="Invalid credentials"):
            self.auth_manager._perform_login("test@example.com", "password123", "csrf-token")
    
    @patch('requests.Session.post')
    def test_perform_login_forbidden(self, mock_post):
        """Test login with forbidden response (rate limiting)."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response
        
        with pytest.raises(AuthenticationError, match="Login forbidden"):
            self.auth_manager._perform_login("test@example.com", "password123", "csrf-token")
    
    @patch('edx_downloader.auth.AuthenticationManager._extract_user_id')
    def test_create_auth_session(self, mock_extract_user_id):
        """Test authentication session creation."""
        mock_extract_user_id.return_value = "test-user-123"
        
        # Set up session cookies
        self.auth_manager.session.cookies.set('sessionid', 'test-session-id')
        self.auth_manager.session.cookies.set('csrftoken', 'test-csrf-cookie')
        
        auth_session = self.auth_manager._create_auth_session("csrf-token")
        
        assert auth_session.csrf_token == "csrf-token"
        assert auth_session.user_id == "test-user-123"
        assert 'sessionid' in auth_session.session_cookies
        assert auth_session.session_cookies['sessionid'] == 'test-session-id'
        assert isinstance(auth_session.expires_at, datetime)
        assert auth_session.expires_at > datetime.now()
    
    @patch('requests.Session.get')
    def test_extract_user_id_from_data_attribute(self, mock_get):
        """Test user ID extraction from data attribute."""
        html_content = '''
        <html>
        <body>
            <div data-user-id="12345">User content</div>
        </body>
        </html>
        '''
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_get.return_value = mock_response
        
        user_id = self.auth_manager._extract_user_id()
        assert user_id == "12345"
    
    @patch('requests.Session.get')
    def test_extract_user_id_from_javascript(self, mock_get):
        """Test user ID extraction from JavaScript variables."""
        html_content = '''
        <html>
        <body>
            <script>
                var config = {"user_id": "67890"};
            </script>
        </body>
        </html>
        '''
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_get.return_value = mock_response
        
        user_id = self.auth_manager._extract_user_id()
        assert user_id == "67890"
    
    @patch('requests.Session.get')
    def test_extract_user_id_fallback(self, mock_get):
        """Test user ID extraction fallback to session ID."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html></html>"
        mock_get.return_value = mock_response
        
        # Set session cookie
        self.auth_manager.session.cookies.set('sessionid', 'abcdef123456')
        
        user_id = self.auth_manager._extract_user_id()
        assert user_id == "session_abcdef12"
    
    @patch('requests.Session.get')
    def test_validate_session_success(self, mock_get):
        """Test successful session validation."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        
        # Should not raise exception
        self.auth_manager._validate_session(auth_session)
        mock_get.assert_called_once()
    
    @patch('requests.Session.get')
    def test_validate_session_failure(self, mock_get):
        """Test session validation failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        
        with pytest.raises(AuthenticationError, match="Session validation failed"):
            self.auth_manager._validate_session(auth_session)
    
    @patch('edx_downloader.auth.AuthenticationManager._get_csrf_token')
    @patch('edx_downloader.auth.AuthenticationManager._validate_session')
    def test_refresh_session_success(self, mock_validate, mock_get_csrf):
        """Test successful session refresh."""
        mock_get_csrf.return_value = "new-csrf-token"
        
        old_session = AuthSession(
            csrf_token="old-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() - timedelta(hours=1),  # Expired
            user_id="test-user"
        )
        
        refreshed_session = self.auth_manager.refresh_session(old_session)
        
        assert refreshed_session.csrf_token == "new-csrf-token"
        assert refreshed_session.user_id == "test-user"
        assert refreshed_session.session_cookies == old_session.session_cookies
        assert refreshed_session.expires_at > datetime.now()
        assert self.auth_manager.current_auth_session == refreshed_session
        mock_validate.assert_called_once_with(refreshed_session)
    
    @patch('edx_downloader.auth.AuthenticationManager._get_csrf_token')
    def test_refresh_session_failure(self, mock_get_csrf):
        """Test session refresh failure."""
        mock_get_csrf.side_effect = Exception("CSRF token retrieval failed")
        
        old_session = AuthSession(
            csrf_token="old-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() - timedelta(hours=1),
            user_id="test-user"
        )
        
        with pytest.raises(SessionExpiredError, match="Failed to refresh session"):
            self.auth_manager.refresh_session(old_session)
    
    def test_is_authenticated_no_session(self):
        """Test authentication check when no session exists."""
        assert not self.auth_manager.is_authenticated()
    
    def test_is_authenticated_expired_session(self):
        """Test authentication check with expired session."""
        expired_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() - timedelta(hours=1),  # Expired
            user_id="test-user"
        )
        self.auth_manager.current_auth_session = expired_session
        
        assert not self.auth_manager.is_authenticated()
    
    @patch('edx_downloader.auth.AuthenticationManager._validate_session')
    def test_is_authenticated_valid_session(self, mock_validate):
        """Test authentication check with valid session."""
        valid_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        self.auth_manager.current_auth_session = valid_session
        
        assert self.auth_manager.is_authenticated()
        mock_validate.assert_called_once_with(valid_session)
    
    @patch('edx_downloader.auth.AuthenticationManager._validate_session')
    def test_is_authenticated_validation_failure(self, mock_validate):
        """Test authentication check when validation fails."""
        mock_validate.side_effect = AuthenticationError("Validation failed")
        
        valid_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        self.auth_manager.current_auth_session = valid_session
        
        assert not self.auth_manager.is_authenticated()
    
    @patch('requests.Session.post')
    def test_logout_success(self, mock_post):
        """Test successful logout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        # Set current session
        auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        self.auth_manager.current_auth_session = auth_session
        
        self.auth_manager.logout()
        
        assert self.auth_manager.current_auth_session is None
        mock_post.assert_called_once()
    
    def test_logout_no_session(self):
        """Test logout when no session exists."""
        # Should not raise exception
        self.auth_manager.logout()
        assert self.auth_manager.current_auth_session is None
    
    def test_get_current_session(self):
        """Test getting current session."""
        assert self.auth_manager.get_current_session() is None
        
        auth_session = AuthSession(
            csrf_token="test-csrf-token",
            session_cookies={"sessionid": "test-session"},
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="test-user"
        )
        self.auth_manager.current_auth_session = auth_session
        
        assert self.auth_manager.get_current_session() == auth_session
    
    @patch('edx_downloader.auth.AuthenticationManager.logout')
    def test_close(self, mock_logout):
        """Test authentication manager cleanup."""
        with patch.object(self.auth_manager.session, 'close') as mock_session_close:
            self.auth_manager.close()
            
            mock_logout.assert_called_once()
            mock_session_close.assert_called_once()


@pytest.mark.integration
class TestAuthenticationIntegration:
    """Integration tests for authentication system."""
    
    def setup_method(self):
        """Set up integration test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.credential_manager = CredentialManager()
        self.auth_manager = AuthenticationManager(self.credential_manager)
    
    def teardown_method(self):
        """Clean up integration test environment."""
        self.auth_manager.close()
    
    @patch('requests.Session.get')
    @patch('requests.Session.post')
    def test_full_authentication_flow(self, mock_post, mock_get):
        """Test complete authentication flow."""
        # Mock login page response
        login_page_html = '''
        <html>
        <head>
            <meta name="csrf-token" content="test-csrf-token">
        </head>
        </html>
        '''
        mock_login_response = Mock()
        mock_login_response.text = login_page_html
        mock_login_response.raise_for_status.return_value = None
        
        # Mock dashboard response for user ID extraction
        dashboard_html = '''
        <html>
        <body>
            <div data-user-id="12345">Dashboard</div>
        </body>
        </html>
        '''
        mock_dashboard_response = Mock()
        mock_dashboard_response.status_code = 200
        mock_dashboard_response.text = dashboard_html
        
        # Mock account API response for validation
        mock_account_response = Mock()
        mock_account_response.status_code = 200
        
        mock_get.side_effect = [
            mock_login_response,    # Login page
            mock_dashboard_response, # Dashboard for user ID
            mock_account_response,   # Account API for validation
            mock_account_response   # Account API for is_authenticated check
        ]
        
        # Mock login POST response
        mock_login_post_response = Mock()
        mock_login_post_response.status_code = 200
        mock_login_post_response.json.return_value = {"success": True}
        mock_post.return_value = mock_login_post_response
        
        # Perform authentication
        auth_session = self.auth_manager.authenticate("test@example.com", "password123")
        
        # Verify session properties
        assert auth_session.csrf_token == "test-csrf-token"
        assert auth_session.user_id == "12345"
        assert isinstance(auth_session.expires_at, datetime)
        assert auth_session.expires_at > datetime.now()
        
        # Verify manager state
        assert self.auth_manager.current_auth_session == auth_session
        assert self.auth_manager.is_authenticated()