"""Tests for configuration management."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
import pytest

from edx_downloader.config import ConfigurationLoader, CredentialManager, ConfigManager
from edx_downloader.models import AppConfig
from edx_downloader.exceptions import ConfigurationError


class TestConfigurationLoader:
    """Test ConfigurationLoader class."""
    
    def test_load_default_config(self):
        """Test loading default configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            loader = ConfigurationLoader(config_file)
            
            config = loader.load_config()
            
            assert isinstance(config, AppConfig)
            assert config.max_concurrent_downloads == 3
            assert config.rate_limit_delay == 1.0
    
    def test_load_config_from_file(self):
        """Test loading configuration from file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            
            # Create test config file
            test_config = {
                "max_concurrent_downloads": 5,
                "rate_limit_delay": 2.0,
                "video_quality_preference": "720p"
            }
            
            with open(config_file, 'w') as f:
                json.dump(test_config, f)
            
            loader = ConfigurationLoader(config_file)
            config = loader.load_config()
            
            assert config.max_concurrent_downloads == 5
            assert config.rate_limit_delay == 2.0
            assert config.video_quality_preference == "720p"
    
    def test_load_config_from_env(self):
        """Test loading configuration from environment variables."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            loader = ConfigurationLoader(config_file)
            
            with patch.dict(os.environ, {
                'EDX_MAX_CONCURRENT_DOWNLOADS': '7',
                'EDX_RATE_LIMIT_DELAY': '3.5',
                'EDX_VIDEO_QUALITY': '480p'
            }):
                config = loader.load_config()
                
                assert config.max_concurrent_downloads == 7
                assert config.rate_limit_delay == 3.5
                assert config.video_quality_preference == "480p"
    
    def test_env_overrides_file(self):
        """Test that environment variables override file configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            
            # Create test config file
            test_config = {"max_concurrent_downloads": 5}
            with open(config_file, 'w') as f:
                json.dump(test_config, f)
            
            loader = ConfigurationLoader(config_file)
            
            with patch.dict(os.environ, {'EDX_MAX_CONCURRENT_DOWNLOADS': '10'}):
                config = loader.load_config()
                assert config.max_concurrent_downloads == 10
    
    def test_save_config(self):
        """Test saving configuration to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            loader = ConfigurationLoader(config_file)
            
            config = AppConfig(max_concurrent_downloads=8, rate_limit_delay=2.5)
            loader.save_config(config)
            
            assert config_file.exists()
            
            with open(config_file, 'r') as f:
                saved_data = json.load(f)
            
            assert saved_data["max_concurrent_downloads"] == 8
            assert saved_data["rate_limit_delay"] == 2.5
    
    def test_invalid_json_file(self):
        """Test handling of invalid JSON in config file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            
            # Create invalid JSON file
            with open(config_file, 'w') as f:
                f.write("invalid json content")
            
            loader = ConfigurationLoader(config_file)
            
            with pytest.raises(ConfigurationError, match="Invalid JSON"):
                loader.load_config()
    
    def test_invalid_env_values(self):
        """Test handling of invalid environment variable values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            loader = ConfigurationLoader(config_file)
            
            with patch.dict(os.environ, {'EDX_MAX_CONCURRENT_DOWNLOADS': 'invalid'}):
                with pytest.raises(ConfigurationError, match="Invalid integer value"):
                    loader.load_config()


class TestCredentialManager:
    """Test CredentialManager class."""
    
    def test_store_and_get_credentials_keyring(self):
        """Test storing and retrieving credentials using keyring."""
        manager = CredentialManager()
        
        with patch('keyring.set_password') as mock_set, \
             patch('keyring.get_password', return_value='test_password') as mock_get:
            
            manager.store_credentials('testuser', 'test_password')
            password = manager.get_credentials('testuser')
            
            mock_set.assert_called_once_with('edx-downloader', 'testuser', 'test_password')
            mock_get.assert_called_once_with('edx-downloader', 'testuser')
            assert password == 'test_password'
    
    def test_store_credentials_fallback_to_file(self):
        """Test fallback to file storage when keyring fails."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback_file = Path(temp_dir) / ".edxauth"
            manager = CredentialManager()
            manager.fallback_file = fallback_file
            
            with patch('keyring.set_password', side_effect=Exception("Keyring failed")):
                manager.store_credentials('testuser', 'test_password')
                
                assert fallback_file.exists()
                
                with open(fallback_file, 'r') as f:
                    data = json.load(f)
                
                assert data['testuser'] == 'test_password'
    
    def test_get_credentials_from_file(self):
        """Test retrieving credentials from file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback_file = Path(temp_dir) / ".edxauth"
            manager = CredentialManager()
            manager.fallback_file = fallback_file
            
            # Create credentials file
            credentials = {'testuser': 'test_password'}
            with open(fallback_file, 'w') as f:
                json.dump(credentials, f)
            
            with patch('keyring.get_password', return_value=None):
                password = manager.get_credentials('testuser')
                assert password == 'test_password'
    
    def test_delete_credentials(self):
        """Test deleting credentials."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback_file = Path(temp_dir) / ".edxauth"
            manager = CredentialManager()
            manager.fallback_file = fallback_file
            
            # Create credentials file
            credentials = {'testuser': 'test_password', 'other': 'other_password'}
            with open(fallback_file, 'w') as f:
                json.dump(credentials, f)
            
            with patch('keyring.delete_password'):
                manager.delete_credentials('testuser')
                
                with open(fallback_file, 'r') as f:
                    remaining = json.load(f)
                
                assert 'testuser' not in remaining
                assert 'other' in remaining
    
    def test_list_stored_usernames(self):
        """Test listing stored usernames."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback_file = Path(temp_dir) / ".edxauth"
            manager = CredentialManager()
            manager.fallback_file = fallback_file
            
            # Create credentials file
            credentials = {'user1': 'pass1', 'user2': 'pass2'}
            with open(fallback_file, 'w') as f:
                json.dump(credentials, f)
            
            usernames = manager.list_stored_usernames()
            assert set(usernames) == {'user1', 'user2'}
    
    def test_file_permissions(self):
        """Test that credential files have correct permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback_file = Path(temp_dir) / ".edxauth"
            manager = CredentialManager()
            manager.fallback_file = fallback_file
            
            with patch('keyring.set_password', side_effect=Exception("Keyring failed")):
                manager.store_credentials('testuser', 'test_password')
                
                # Check that file exists and is readable by owner
                assert fallback_file.exists()
                assert fallback_file.is_file()
                
                # On Unix systems, check file permissions
                if os.name != 'nt':  # Not Windows
                    file_mode = fallback_file.stat().st_mode & 0o777
                    assert file_mode == 0o600


class TestConfigManager:
    """Test ConfigManager class."""
    
    def test_config_property(self):
        """Test config property loads configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(config_file)
            
            config = manager.config
            assert isinstance(config, AppConfig)
    
    def test_reload_config(self):
        """Test reloading configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(config_file)
            
            # Get initial config
            initial_config = manager.config
            
            # Modify config file
            test_config = {"max_concurrent_downloads": 10}
            with open(config_file, 'w') as f:
                json.dump(test_config, f)
            
            # Reload and verify changes
            reloaded_config = manager.reload_config()
            assert reloaded_config.max_concurrent_downloads == 10
            assert manager.config.max_concurrent_downloads == 10
    
    def test_save_config(self):
        """Test saving configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(config_file)
            
            new_config = AppConfig(max_concurrent_downloads=15)
            manager.save_config(new_config)
            
            assert config_file.exists()
            
            # Verify saved content
            with open(config_file, 'r') as f:
                saved_data = json.load(f)
            
            assert saved_data["max_concurrent_downloads"] == 15
    
    def test_update_config(self):
        """Test updating configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(config_file)
            
            updated_config = manager.update_config(
                max_concurrent_downloads=12,
                rate_limit_delay=4.0
            )
            
            assert updated_config.max_concurrent_downloads == 12
            assert updated_config.rate_limit_delay == 4.0
            assert manager.config.max_concurrent_downloads == 12
    
    def test_credential_operations(self):
        """Test credential management operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(config_file)
            
            with patch.object(manager.credential_manager, 'store_credentials') as mock_store, \
                 patch.object(manager.credential_manager, 'get_credentials', return_value='password') as mock_get, \
                 patch.object(manager.credential_manager, 'delete_credentials') as mock_delete, \
                 patch.object(manager.credential_manager, 'list_stored_usernames', return_value=['user1']) as mock_list:
                
                # Test store
                manager.store_credentials('testuser', 'testpass')
                mock_store.assert_called_once_with('testuser', 'testpass')
                
                # Test get
                password = manager.get_credentials('testuser')
                mock_get.assert_called_once_with('testuser')
                assert password == 'password'
                
                # Test delete
                manager.delete_credentials('testuser')
                mock_delete.assert_called_once_with('testuser')
                
                # Test list
                usernames = manager.list_stored_usernames()
                mock_list.assert_called_once()
                assert usernames == ['user1']
    
    def test_setup_directories(self):
        """Test setting up directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            manager = ConfigManager(config_file)
            
            with patch.object(manager.config, 'create_directories') as mock_create:
                manager.setup_directories()
                mock_create.assert_called_once()