"""Tests for migration utilities and backward compatibility."""

import json
import os
import tempfile
import warnings
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
import pytest
import configparser
from datetime import datetime

from edx_downloader.migration import (
    LegacyConfigMigrator, BackwardCompatibilityLayer, ConfigurationExporter,
    run_migration_wizard
)
from edx_downloader.config import ConfigManager, CredentialManager
from edx_downloader.models import AppConfig
from edx_downloader.exceptions import ConfigurationError, MigrationError


class TestLegacyConfigMigrator:
    """Test legacy configuration migration functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
        # Create mock config manager
        self.mock_config_manager = Mock(spec=ConfigManager)
        self.mock_config_manager.config = AppConfig()
        
        # Create migrator instance
        self.migrator = LegacyConfigMigrator(self.mock_config_manager)
        
        # Override paths to use temp directory
        self.migrator.legacy_auth_file = self.temp_path / ".edxauth"
        self.migrator.legacy_config_paths = [
            self.temp_path / ".edx-downloader.conf",
            self.temp_path / "config.ini"
        ]
    
    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_needs_migration_no_legacy_files(self):
        """Test needs_migration returns False when no legacy files exist."""
        assert not self.migrator.needs_migration()
    
    def test_needs_migration_with_edxauth_file(self):
        """Test needs_migration returns True when .edxauth file exists."""
        self.migrator.legacy_auth_file.touch()
        assert self.migrator.needs_migration()
    
    def test_needs_migration_with_config_file(self):
        """Test needs_migration returns True when legacy config file exists."""
        (self.temp_path / ".edx-downloader.conf").touch()
        assert self.migrator.needs_migration()
    
    def test_migrate_edxauth_file_success(self):
        """Test successful migration of .edxauth file."""
        # Create test .edxauth file
        auth_content = "test@example.com\npassword123\n"
        self.migrator.legacy_auth_file.write_text(auth_content)
        
        result = self.migrator._migrate_edxauth_file(backup=True)
        
        assert result['accounts_migrated'] == 1
        assert result['backup_file'] is not None
        assert len(result['warnings']) == 1
        
        # Verify credentials were stored
        self.mock_config_manager.store_credentials.assert_called_once_with(
            "test@example.com", "password123"
        )
        
        # Verify backup was created
        backup_file = Path(result['backup_file'])
        assert backup_file.exists()
        assert backup_file.read_text() == auth_content
    
    def test_migrate_edxauth_file_invalid_format(self):
        """Test migration of invalid .edxauth file."""
        # Create invalid .edxauth file (only one line)
        self.migrator.legacy_auth_file.write_text("test@example.com\n")
        
        result = self.migrator._migrate_edxauth_file()
        
        assert result['accounts_migrated'] == 0
        assert "Invalid .edxauth format: insufficient lines" in result['warnings'][0]
        self.mock_config_manager.store_credentials.assert_not_called()
    
    def test_migrate_edxauth_file_empty_credentials(self):
        """Test migration of .edxauth file with empty credentials."""
        # Create .edxauth file with empty password (spaces that get stripped)
        self.migrator.legacy_auth_file.write_text("user@example.com\n   \n")
        
        result = self.migrator._migrate_edxauth_file()
        
        assert result['accounts_migrated'] == 0
        assert "Invalid .edxauth format: insufficient lines" in result['warnings'][0]
        self.mock_config_manager.store_credentials.assert_not_called()
    
    def test_migrate_edxauth_file_no_backup(self):
        """Test migration without creating backup."""
        auth_content = "test@example.com\npassword123\n"
        self.migrator.legacy_auth_file.write_text(auth_content)
        
        result = self.migrator._migrate_edxauth_file(backup=False)
        
        assert result['accounts_migrated'] == 1
        assert result['backup_file'] is None
    
    def test_migrate_config_file_json_format(self):
        """Test migration of JSON format config file."""
        config_path = self.temp_path / "config.json"
        config_data = {
            "output_dir": "/downloads",
            "concurrent": 5,
            "quality": "720p",
            "delay": 2.0
        }
        config_path.write_text(json.dumps(config_data))
        
        result = self.migrator._migrate_config_file(config_path, backup=True)
        
        assert result['migrated'] is True
        assert result['backup_file'] is not None
        
        # Verify config was updated
        expected_config = {
            "default_output_dir": "/downloads",
            "max_concurrent_downloads": 5,
            "video_quality_preference": "720p",
            "rate_limit_delay": 2.0
        }
        self.mock_config_manager.update_config.assert_called_once_with(**expected_config)
    
    def test_migrate_config_file_ini_format(self):
        """Test migration of INI format config file."""
        config_path = self.temp_path / "config.ini"
        config_content = """
[settings]
output_dir = /downloads
concurrent = 3
quality = 1080p

[advanced]
retries = 5
cache_dir = /tmp/cache
"""
        config_path.write_text(config_content)
        
        result = self.migrator._migrate_config_file(config_path, backup=True)
        
        assert result['migrated'] is True
        
        # Verify config mapping worked
        self.mock_config_manager.update_config.assert_called_once()
        call_args = self.mock_config_manager.update_config.call_args[1]
        assert call_args["default_output_dir"] == "/downloads"
        assert call_args["max_concurrent_downloads"] == "3"
        assert call_args["video_quality_preference"] == "1080p"
        assert call_args["retry_attempts"] == "5"
        assert call_args["cache_directory"] == "/tmp/cache"
    
    def test_migrate_config_file_invalid_format(self):
        """Test migration of invalid config file."""
        config_path = self.temp_path / "invalid.conf"
        config_path.write_text("invalid content that's not JSON or INI")
        
        result = self.migrator._migrate_config_file(config_path)
        
        assert result['migrated'] is False
        assert len(result['warnings']) == 1
        assert "Could not parse config file" in result['warnings'][0]
    
    def test_map_legacy_config_flat_structure(self):
        """Test mapping of flat legacy configuration."""
        legacy_config = {
            "output_dir": "/downloads",
            "concurrent_downloads": 4,
            "video_quality": "720p",
            "rate_limit": 1.5,
            "max_retries": 3
        }
        
        mapped = self.migrator._map_legacy_config(legacy_config)
        
        expected = {
            "default_output_dir": "/downloads",
            "max_concurrent_downloads": 4,
            "video_quality_preference": "720p",
            "rate_limit_delay": 1.5,
            "retry_attempts": 3
        }
        assert mapped == expected
    
    def test_map_legacy_config_nested_structure(self):
        """Test mapping of nested legacy configuration."""
        legacy_config = {
            "downloads": {
                "output_directory": "/downloads",
                "concurrent": 2
            },
            "video": {
                "preferred_quality": "1080p"
            },
            "network": {
                "request_delay": 2.0,
                "retry_count": 5
            }
        }
        
        mapped = self.migrator._map_legacy_config(legacy_config)
        
        expected = {
            "default_output_dir": "/downloads",
            "max_concurrent_downloads": 2,
            "video_quality_preference": "1080p",
            "rate_limit_delay": 2.0,
            "retry_attempts": 5
        }
        assert mapped == expected
    
    def test_migrate_all_success(self):
        """Test successful migration of all legacy files."""
        # Create test files
        auth_content = "user@example.com\npassword123\n"
        self.migrator.legacy_auth_file.write_text(auth_content)
        
        config_data = {"output_dir": "/downloads", "concurrent": 3}
        config_file = self.temp_path / ".edx-downloader.conf"
        config_file.write_text(json.dumps(config_data))
        
        # Mock successful operations
        self.mock_config_manager.update_config.return_value = AppConfig()
        
        results = self.migrator.migrate_all(backup=True)
        
        assert results['migrated_accounts'] == 1
        assert results['migrated_configs'] == 1
        assert len(results['backup_files']) == 2
        assert len(results['errors']) == 0
    
    def test_migrate_all_no_legacy_files(self):
        """Test migrate_all when no legacy files exist."""
        results = self.migrator.migrate_all()
        
        assert results['migrated_accounts'] == 0
        assert results['migrated_configs'] == 0
        assert len(results['backup_files']) == 0
        assert len(results['errors']) == 0
    
    @patch('edx_downloader.migration.log_with_context')
    def test_migrate_all_with_errors(self, mock_log):
        """Test migrate_all handles errors gracefully."""
        # Create test .edxauth file
        self.migrator.legacy_auth_file.write_text("user@example.com\npassword123\n")
        
        # Mock store_credentials to raise an exception
        self.mock_config_manager.store_credentials.side_effect = Exception("Storage failed")
        
        # The migration should complete but with warnings about the error
        results = self.migrator.migrate_all()
        
        assert results['migrated_accounts'] == 0  # Failed to migrate due to error
        assert results['migrated_configs'] == 0
        assert len(results['warnings']) > 0
        assert any("Failed to migrate .edxauth file" in warning for warning in results['warnings'])


class TestBackwardCompatibilityLayer:
    """Test backward compatibility functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.compat_layer = BackwardCompatibilityLayer()
    
    def test_handle_deprecated_option_known(self):
        """Test handling of known deprecated options."""
        result = self.compat_layer.handle_deprecated_option('--user')
        assert result == '--email'
        
        result = self.compat_layer.handle_deprecated_option('-u')
        assert result == '-e'
        
        result = self.compat_layer.handle_deprecated_option('--pass')
        assert result == '--password'
    
    def test_handle_deprecated_option_unknown(self):
        """Test handling of unknown options."""
        result = self.compat_layer.handle_deprecated_option('--unknown')
        assert result is None
    
    def test_handle_deprecated_command_known(self):
        """Test handling of known deprecated commands."""
        result = self.compat_layer.handle_deprecated_command('get')
        assert result == 'download'
        
        result = self.compat_layer.handle_deprecated_command('fetch')
        assert result == 'download'
        
        result = self.compat_layer.handle_deprecated_command('list')
        assert result == 'info'
    
    def test_handle_deprecated_command_unknown(self):
        """Test handling of unknown commands."""
        result = self.compat_layer.handle_deprecated_command('unknown')
        assert result is None
    
    @patch('edx_downloader.migration.log_with_context')
    def test_deprecated_option_warning(self, mock_log):
        """Test that deprecated option usage generates warnings."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            self.compat_layer.handle_deprecated_option('--user')
            
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "Option '--user' is deprecated" in str(w[0].message)
    
    @patch('edx_downloader.migration.log_with_context')
    def test_deprecated_command_warning(self, mock_log):
        """Test that deprecated command usage generates warnings."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            self.compat_layer.handle_deprecated_command('get')
            
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "Command 'get' is deprecated" in str(w[0].message)


class TestConfigurationExporter:
    """Test configuration export/import functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
        # Create mock config manager
        self.mock_config_manager = Mock(spec=ConfigManager)
        self.mock_config_manager.config = AppConfig(
            default_output_dir="/downloads",
            max_concurrent_downloads=3,
            video_quality_preference="720p"
        )
        
        self.exporter = ConfigurationExporter(self.mock_config_manager)
    
    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_export_configuration_json_without_credentials(self):
        """Test exporting configuration to JSON without credentials."""
        export_path = self.temp_path / "config_export.json"
        
        result = self.exporter.export_configuration(
            export_path, include_credentials=False, format='json'
        )
        
        assert result['success'] is True
        assert result['export_path'] == str(export_path)
        assert result['format'] == 'json'
        assert result['includes_credentials'] is False
        
        # Verify file was created and contains expected data
        assert export_path.exists()
        with open(export_path, 'r') as f:
            exported_data = json.load(f)
        
        assert 'export_info' in exported_data
        assert 'configuration' in exported_data
        assert 'credentials' not in exported_data
        assert exported_data['export_info']['includes_credentials'] is False
        assert exported_data['configuration']['default_output_dir'] == "/downloads"
    
    def test_export_configuration_with_credentials(self):
        """Test exporting configuration with credentials."""
        export_path = self.temp_path / "config_with_creds.json"
        
        # Mock credential methods
        self.mock_config_manager.list_stored_usernames.return_value = ["user1@example.com", "user2@example.com"]
        self.mock_config_manager.get_credentials.side_effect = lambda u: "password123" if u == "user1@example.com" else "password456"
        
        result = self.exporter.export_configuration(
            export_path, include_credentials=True, format='json'
        )
        
        assert result['includes_credentials'] is True
        
        # Verify credentials were included
        with open(export_path, 'r') as f:
            exported_data = json.load(f)
        
        assert 'credentials' in exported_data
        assert exported_data['credentials']['user1@example.com'] == "password123"
        assert exported_data['credentials']['user2@example.com'] == "password456"
    
    @pytest.mark.skipif(not pytest.importorskip("yaml", reason="PyYAML not available"), reason="PyYAML required")
    def test_export_configuration_yaml_format(self):
        """Test exporting configuration to YAML format."""
        export_path = self.temp_path / "config_export.yaml"
        
        result = self.exporter.export_configuration(
            export_path, include_credentials=False, format='yaml'
        )
        
        assert result['format'] == 'yaml'
        assert export_path.exists()
        
        # Verify YAML content
        import yaml
        with open(export_path, 'r') as f:
            exported_data = yaml.safe_load(f)
        
        assert 'export_info' in exported_data
        assert 'configuration' in exported_data
    
    def test_export_configuration_yaml_without_pyyaml(self):
        """Test exporting to YAML format when PyYAML is not available."""
        export_path = self.temp_path / "config_export.yaml"
        
        with patch('builtins.__import__', side_effect=ImportError("No module named 'yaml'")):
            with pytest.raises(ConfigurationError, match="PyYAML not installed"):
                self.exporter.export_configuration(
                    export_path, include_credentials=False, format='yaml'
                )
    
    def test_import_configuration_json_merge(self):
        """Test importing JSON configuration with merge."""
        import_path = self.temp_path / "import_config.json"
        
        # Create import file
        import_data = {
            'export_info': {
                'version': '2.0.0',
                'export_date': datetime.now().isoformat()
            },
            'configuration': {
                'default_output_dir': '/imported/downloads',
                'max_concurrent_downloads': 5,
                'rate_limit_delay': 2.0
            }
        }
        
        with open(import_path, 'w') as f:
            json.dump(import_data, f)
        
        # Mock current config
        from dataclasses import asdict
        self.mock_config_manager.config = AppConfig()
        
        result = self.exporter.import_configuration(
            import_path, merge=True, import_credentials=False
        )
        
        assert result['config_imported'] is True
        assert result['credentials_imported'] == 0
        
        # Verify config was updated
        self.mock_config_manager.save_config.assert_called_once()
    
    def test_import_configuration_replace(self):
        """Test importing configuration with replace (no merge)."""
        import_path = self.temp_path / "import_config.json"
        
        import_data = {
            'configuration': {
                'default_output_dir': '/new/downloads',
                'max_concurrent_downloads': 2
            }
        }
        
        with open(import_path, 'w') as f:
            json.dump(import_data, f)
        
        result = self.exporter.import_configuration(
            import_path, merge=False, import_credentials=False
        )
        
        assert result['config_imported'] is True
        self.mock_config_manager.save_config.assert_called_once()
    
    def test_import_configuration_with_credentials(self):
        """Test importing configuration with credentials."""
        import_path = self.temp_path / "import_with_creds.json"
        
        import_data = {
            'configuration': {
                'default_output_dir': '/downloads'
            },
            'credentials': {
                'user1@example.com': 'password123',
                'user2@example.com': 'password456'
            }
        }
        
        with open(import_path, 'w') as f:
            json.dump(import_data, f)
        
        result = self.exporter.import_configuration(
            import_path, merge=True, import_credentials=True
        )
        
        assert result['config_imported'] is True
        assert result['credentials_imported'] == 2
        
        # Verify credentials were stored
        expected_calls = [
            (('user1@example.com', 'password123'), {}),
            (('user2@example.com', 'password456'), {})
        ]
        assert self.mock_config_manager.store_credentials.call_args_list == expected_calls
    
    def test_import_configuration_file_not_found(self):
        """Test importing from non-existent file."""
        import_path = self.temp_path / "nonexistent.json"
        
        with pytest.raises(ConfigurationError, match="Import file not found"):
            self.exporter.import_configuration(import_path)
    
    def test_import_configuration_invalid_format(self):
        """Test importing invalid configuration file."""
        import_path = self.temp_path / "invalid.json"
        import_path.write_text("invalid json content")
        
        with pytest.raises(ConfigurationError, match="Failed to import configuration"):
            self.exporter.import_configuration(import_path)
    
    def test_import_configuration_credential_errors(self):
        """Test importing configuration with credential storage errors."""
        import_path = self.temp_path / "import_with_bad_creds.json"
        
        import_data = {
            'configuration': {'default_output_dir': '/downloads'},
            'credentials': {
                'user1@example.com': 'password123',
                'user2@example.com': 'password456'
            }
        }
        
        with open(import_path, 'w') as f:
            json.dump(import_data, f)
        
        # Mock credential storage to fail for one user
        def mock_store_credentials(username, password):
            if username == 'user2@example.com':
                raise Exception("Storage failed")
        
        self.mock_config_manager.store_credentials.side_effect = mock_store_credentials
        
        result = self.exporter.import_configuration(
            import_path, merge=True, import_credentials=True
        )
        
        assert result['config_imported'] is True
        assert result['credentials_imported'] == 1  # Only one succeeded
        assert len(result['warnings']) == 1
        assert "Failed to import credentials for user2@example.com" in result['warnings'][0]


class TestMigrationWizard:
    """Test interactive migration wizard functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.mock_config_manager = Mock(spec=ConfigManager)
    
    @patch('edx_downloader.migration.LegacyConfigMigrator')
    @patch('builtins.input')
    @patch('builtins.print')
    def test_run_migration_wizard_no_migration_needed(self, mock_print, mock_input, mock_migrator_class):
        """Test wizard when no migration is needed."""
        mock_migrator = Mock()
        mock_migrator.needs_migration.return_value = False
        mock_migrator_class.return_value = mock_migrator
        
        result = run_migration_wizard(self.mock_config_manager)
        
        assert result['migration_needed'] is False
        assert 'No legacy files found' in result['message']
    
    @patch('edx_downloader.migration.LegacyConfigMigrator')
    @patch('builtins.input')
    @patch('builtins.print')
    def test_run_migration_wizard_user_cancels(self, mock_print, mock_input, mock_migrator_class):
        """Test wizard when user cancels migration."""
        mock_migrator = Mock()
        mock_migrator.needs_migration.return_value = True
        mock_migrator_class.return_value = mock_migrator
        
        # User says no to migration
        mock_input.side_effect = ['n']
        
        result = run_migration_wizard(self.mock_config_manager)
        
        assert result['migration_needed'] is True
        assert result['migration_performed'] is False
        assert 'Migration cancelled by user' in result['message']
    
    @patch('edx_downloader.migration.LegacyConfigMigrator')
    @patch('builtins.input')
    @patch('builtins.print')
    def test_run_migration_wizard_successful_migration(self, mock_print, mock_input, mock_migrator_class):
        """Test successful migration through wizard."""
        mock_migrator = Mock()
        mock_migrator.needs_migration.return_value = True
        mock_migrator.migrate_all.return_value = {
            'migrated_accounts': 1,
            'migrated_configs': 1,
            'backup_files': ['/path/to/backup'],
            'warnings': ['Test warning']
        }
        mock_migrator_class.return_value = mock_migrator
        
        # User says yes to migration and backup
        mock_input.side_effect = ['y', 'y']
        
        result = run_migration_wizard(self.mock_config_manager)
        
        assert result['migration_needed'] is True
        assert result['migration_performed'] is True
        assert result['migrated_accounts'] == 1
        assert result['migrated_configs'] == 1
        
        # Verify migration was called with backup=True
        mock_migrator.migrate_all.assert_called_once_with(backup=True)
    
    @patch('edx_downloader.migration.LegacyConfigMigrator')
    @patch('builtins.input')
    @patch('builtins.print')
    def test_run_migration_wizard_no_backup(self, mock_print, mock_input, mock_migrator_class):
        """Test migration wizard without backup."""
        mock_migrator = Mock()
        mock_migrator.needs_migration.return_value = True
        mock_migrator.migrate_all.return_value = {
            'migrated_accounts': 1,
            'migrated_configs': 0,
            'backup_files': [],
            'warnings': []
        }
        mock_migrator_class.return_value = mock_migrator
        
        # User says yes to migration but no to backup
        mock_input.side_effect = ['y', 'n']
        
        result = run_migration_wizard(self.mock_config_manager)
        
        assert result['migration_performed'] is True
        
        # Verify migration was called with backup=False
        mock_migrator.migrate_all.assert_called_once_with(backup=False)
    
    @patch('edx_downloader.migration.LegacyConfigMigrator')
    @patch('builtins.input')
    @patch('builtins.print')
    def test_run_migration_wizard_migration_error(self, mock_print, mock_input, mock_migrator_class):
        """Test wizard when migration fails."""
        mock_migrator = Mock()
        mock_migrator.needs_migration.return_value = True
        mock_migrator.migrate_all.side_effect = Exception("Migration failed")
        mock_migrator_class.return_value = mock_migrator
        
        # User says yes to migration
        mock_input.side_effect = ['y', 'y']
        
        result = run_migration_wizard(self.mock_config_manager)
        
        assert result['migration_needed'] is True
        assert result['migration_performed'] is False
        assert 'error' in result
        assert 'Migration failed' in result['message']


if __name__ == '__main__':
    pytest.main([__file__])