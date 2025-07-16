"""Configuration management for EDX downloader."""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import asdict
import keyring
from edx_downloader.models import AppConfig
from edx_downloader.exceptions import ConfigurationError, ValidationError


class ConfigurationLoader:
    """Handles loading and saving configuration from various sources."""
    
    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        """Initialize configuration loader.
        
        Args:
            config_file: Path to configuration file. If None, uses default location.
        """
        self.config_file = Path(config_file) if config_file else Path.home() / ".edx-downloader" / "config.json"
        self.keyring_service = "edx-downloader"
    
    def load_config(self) -> AppConfig:
        """Load configuration from file and environment variables.
        
        Returns:
            AppConfig instance with loaded configuration.
            
        Raises:
            ConfigurationError: If configuration loading fails.
        """
        try:
            # Start with default configuration
            config_dict = asdict(AppConfig())
            
            # Load from file if it exists
            if self.config_file.exists():
                file_config = self._load_from_file()
                config_dict.update(file_config)
            
            # Override with environment variables
            env_config = self._load_from_env()
            config_dict.update(env_config)
            
            # Create and validate AppConfig
            return AppConfig(**config_dict)
            
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {str(e)}")
    
    def save_config(self, config: AppConfig) -> None:
        """Save configuration to file.
        
        Args:
            config: AppConfig instance to save.
            
        Raises:
            ConfigurationError: If configuration saving fails.
        """
        try:
            # Ensure config directory exists
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert to dictionary and save
            config_dict = asdict(config)
            with open(self.config_file, 'w') as f:
                json.dump(config_dict, f, indent=2)
                
        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration: {str(e)}")
    
    def _load_from_file(self) -> Dict[str, Any]:
        """Load configuration from JSON file.
        
        Returns:
            Dictionary with configuration values.
            
        Raises:
            ConfigurationError: If file loading fails.
        """
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in config file: {str(e)}")
        except Exception as e:
            raise ConfigurationError(f"Failed to read config file: {str(e)}")
    
    def _load_from_env(self) -> Dict[str, Any]:
        """Load configuration from environment variables.
        
        Returns:
            Dictionary with configuration values from environment.
        """
        env_config = {}
        
        # Map environment variables to config keys
        env_mappings = {
            'EDX_CREDENTIALS_FILE': 'credentials_file',
            'EDX_CACHE_DIRECTORY': 'cache_directory',
            'EDX_OUTPUT_DIR': 'default_output_dir',
            'EDX_MAX_CONCURRENT_DOWNLOADS': 'max_concurrent_downloads',
            'EDX_RATE_LIMIT_DELAY': 'rate_limit_delay',
            'EDX_RETRY_ATTEMPTS': 'retry_attempts',
            'EDX_VIDEO_QUALITY': 'video_quality_preference'
        }
        
        for env_var, config_key in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convert types as needed
                if config_key in ['max_concurrent_downloads', 'retry_attempts']:
                    try:
                        env_config[config_key] = int(value)
                    except ValueError:
                        raise ConfigurationError(f"Invalid integer value for {env_var}: {value}")
                elif config_key == 'rate_limit_delay':
                    try:
                        env_config[config_key] = float(value)
                    except ValueError:
                        raise ConfigurationError(f"Invalid float value for {env_var}: {value}")
                else:
                    env_config[config_key] = value
        
        return env_config


class CredentialManager:
    """Manages secure storage and retrieval of user credentials."""
    
    def __init__(self, service_name: str = "edx-downloader"):
        """Initialize credential manager.
        
        Args:
            service_name: Name of the service for keyring storage.
        """
        self.service_name = service_name
        self.fallback_file = Path.home() / ".edxauth"
    
    def store_credentials(self, username: str, password: str) -> None:
        """Store credentials securely.
        
        Args:
            username: EDX username.
            password: EDX password.
            
        Raises:
            ConfigurationError: If credential storage fails.
        """
        try:
            # Try to use system keyring first
            keyring.set_password(self.service_name, username, password)
        except Exception as keyring_error:
            try:
                # Fallback to encrypted file storage
                self._store_in_file(username, password)
            except Exception as file_error:
                raise ConfigurationError(
                    f"Failed to store credentials: keyring error: {keyring_error}, "
                    f"file error: {file_error}"
                )
    
    def get_credentials(self, username: str) -> Optional[str]:
        """Retrieve stored password for username.
        
        Args:
            username: EDX username.
            
        Returns:
            Password if found, None otherwise.
            
        Raises:
            ConfigurationError: If credential retrieval fails.
        """
        try:
            # Try keyring first
            password = keyring.get_password(self.service_name, username)
            if password:
                return password
        except Exception:
            pass
        
        try:
            # Fallback to file storage
            return self._get_from_file(username)
        except Exception as e:
            raise ConfigurationError(f"Failed to retrieve credentials: {str(e)}")
    
    def delete_credentials(self, username: str) -> None:
        """Delete stored credentials for username.
        
        Args:
            username: EDX username.
            
        Raises:
            ConfigurationError: If credential deletion fails.
        """
        try:
            # Try to delete from keyring
            keyring.delete_password(self.service_name, username)
        except Exception:
            pass
        
        try:
            # Try to delete from file
            self._delete_from_file(username)
        except Exception as e:
            raise ConfigurationError(f"Failed to delete credentials: {str(e)}")
    
    def list_stored_usernames(self) -> list[str]:
        """List all stored usernames.
        
        Returns:
            List of stored usernames.
        """
        usernames = set()
        
        # Get usernames from file if it exists
        try:
            file_usernames = self._list_file_usernames()
            usernames.update(file_usernames)
        except Exception:
            pass
        
        return list(usernames)
    
    def _store_in_file(self, username: str, password: str) -> None:
        """Store credentials in encrypted file.
        
        Args:
            username: EDX username.
            password: EDX password.
        """
        # For now, use simple JSON storage (in production, this should be encrypted)
        credentials = {}
        
        if self.fallback_file.exists():
            try:
                with open(self.fallback_file, 'r') as f:
                    credentials = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                credentials = {}
        
        credentials[username] = password
        
        # Ensure file has restricted permissions
        self.fallback_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.fallback_file, 'w') as f:
            json.dump(credentials, f, indent=2)
        
        # Set restrictive permissions (owner read/write only)
        self.fallback_file.chmod(0o600)
    
    def _get_from_file(self, username: str) -> Optional[str]:
        """Get credentials from file.
        
        Args:
            username: EDX username.
            
        Returns:
            Password if found, None otherwise.
        """
        if not self.fallback_file.exists():
            return None
        
        try:
            with open(self.fallback_file, 'r') as f:
                credentials = json.load(f)
            return credentials.get(username)
        except (json.JSONDecodeError, FileNotFoundError):
            return None
    
    def _delete_from_file(self, username: str) -> None:
        """Delete credentials from file.
        
        Args:
            username: EDX username.
        """
        if not self.fallback_file.exists():
            return
        
        try:
            with open(self.fallback_file, 'r') as f:
                credentials = json.load(f)
            
            if username in credentials:
                del credentials[username]
                
                if credentials:
                    with open(self.fallback_file, 'w') as f:
                        json.dump(credentials, f, indent=2)
                else:
                    # Remove file if no credentials left
                    self.fallback_file.unlink()
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    
    def _list_file_usernames(self) -> list[str]:
        """List usernames stored in file.
        
        Returns:
            List of usernames.
        """
        if not self.fallback_file.exists():
            return []
        
        try:
            with open(self.fallback_file, 'r') as f:
                credentials = json.load(f)
            return list(credentials.keys())
        except (json.JSONDecodeError, FileNotFoundError):
            return []


class ConfigManager:
    """High-level configuration management interface."""
    
    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        """Initialize configuration manager.
        
        Args:
            config_file: Path to configuration file.
        """
        self.config_loader = ConfigurationLoader(config_file)
        self.credential_manager = CredentialManager()
        self._config: Optional[AppConfig] = None
    
    @property
    def config(self) -> AppConfig:
        """Get current configuration, loading if necessary.
        
        Returns:
            Current AppConfig instance.
        """
        if self._config is None:
            self._config = self.config_loader.load_config()
        return self._config
    
    def reload_config(self) -> AppConfig:
        """Reload configuration from sources.
        
        Returns:
            Reloaded AppConfig instance.
        """
        self._config = self.config_loader.load_config()
        return self._config
    
    def save_config(self, config: Optional[AppConfig] = None) -> None:
        """Save configuration to file.
        
        Args:
            config: AppConfig to save. If None, saves current config.
        """
        config_to_save = config or self.config
        self.config_loader.save_config(config_to_save)
        self._config = config_to_save
    
    def update_config(self, **kwargs) -> AppConfig:
        """Update configuration with new values.
        
        Args:
            **kwargs: Configuration values to update.
            
        Returns:
            Updated AppConfig instance.
        """
        current_config = self.config
        config_dict = asdict(current_config)
        config_dict.update(kwargs)
        
        # Validate new configuration
        new_config = AppConfig(**config_dict)
        self._config = new_config
        return new_config
    
    def store_credentials(self, username: str, password: str) -> None:
        """Store user credentials securely.
        
        Args:
            username: EDX username.
            password: EDX password.
        """
        self.credential_manager.store_credentials(username, password)
    
    def get_credentials(self, username: str) -> Optional[str]:
        """Get stored credentials for username.
        
        Args:
            username: EDX username.
            
        Returns:
            Password if found, None otherwise.
        """
        return self.credential_manager.get_credentials(username)
    
    def delete_credentials(self, username: str) -> None:
        """Delete stored credentials.
        
        Args:
            username: EDX username.
        """
        self.credential_manager.delete_credentials(username)
    
    def list_stored_usernames(self) -> list[str]:
        """List all stored usernames.
        
        Returns:
            List of stored usernames.
        """
        return self.credential_manager.list_stored_usernames()
    
    def setup_directories(self) -> None:
        """Create necessary directories based on configuration."""
        self.config.create_directories()