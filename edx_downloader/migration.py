"""
Migration utilities and backward compatibility for EDX Downloader.

This module provides migration scripts for existing .edxauth files and configurations,
backward compatibility layer for existing CLI usage patterns, and configuration
export/import functionality.
"""

import json
import logging
import os
import shutil
import warnings
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import asdict
from datetime import datetime

from .config import ConfigManager, CredentialManager
from .models import AppConfig
from .exceptions import ConfigurationError, MigrationError
from .logging_config import get_logger, log_with_context, performance_timer

logger = get_logger(__name__)


class LegacyConfigMigrator:
    """Handles migration from legacy configuration formats."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.legacy_auth_file = Path(".edxauth")
        self.legacy_config_paths = [
            Path.home() / ".edx-downloader.conf",
            Path.home() / ".edxdownloader.conf",
            Path("edx-downloader.conf"),
            Path("config.ini")
        ]
    
    def needs_migration(self) -> bool:
        """Check if migration is needed.
        
        Returns:
            True if legacy files are found that need migration.
        """
        # Check for legacy .edxauth file
        if self.legacy_auth_file.exists():
            return True
        
        # Check for legacy config files
        for config_path in self.legacy_config_paths:
            if config_path.exists():
                return True
        
        return False
    
    def migrate_all(self, backup: bool = True) -> Dict[str, Any]:
        """Migrate all legacy configurations.
        
        Args:
            backup: Whether to create backups of legacy files.
            
        Returns:
            Migration results dictionary.
        """
        with performance_timer("migrate_all_legacy_configs", logger):
            log_with_context(logger, logging.INFO, "Starting legacy configuration migration", {
                'backup_enabled': backup,
                'legacy_auth_exists': self.legacy_auth_file.exists(),
                'legacy_configs_found': sum(1 for p in self.legacy_config_paths if p.exists())
            })
            
            results = {
                'migrated_accounts': 0,
                'migrated_configs': 0,
                'backup_files': [],
                'errors': [],
                'warnings': []
            }
            
            try:
                # Migrate .edxauth file
                if self.legacy_auth_file.exists():
                    auth_result = self._migrate_edxauth_file(backup)
                    results['migrated_accounts'] = auth_result['accounts_migrated']
                    if auth_result['backup_file']:
                        results['backup_files'].append(auth_result['backup_file'])
                    results['warnings'].extend(auth_result['warnings'])
                
                # Migrate legacy config files
                for config_path in self.legacy_config_paths:
                    if config_path.exists():
                        config_result = self._migrate_config_file(config_path, backup)
                        if config_result['migrated']:
                            results['migrated_configs'] += 1
                        if config_result['backup_file']:
                            results['backup_files'].append(config_result['backup_file'])
                        results['warnings'].extend(config_result['warnings'])
                
                log_with_context(logger, logging.INFO, "Legacy migration completed", {
                    'migrated_accounts': results['migrated_accounts'],
                    'migrated_configs': results['migrated_configs'],
                    'backup_files': len(results['backup_files']),
                    'warnings': len(results['warnings'])
                })
                
                return results
                
            except Exception as e:
                error_msg = f"Migration failed: {str(e)}"
                results['errors'].append(error_msg)
                log_with_context(logger, logging.ERROR, "Migration failed", {
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                raise MigrationError(error_msg)
    
    def _migrate_edxauth_file(self, backup: bool = True) -> Dict[str, Any]:
        """Migrate legacy .edxauth file.
        
        Args:
            backup: Whether to create a backup.
            
        Returns:
            Migration results.
        """
        result = {
            'accounts_migrated': 0,
            'backup_file': None,
            'warnings': []
        }
        
        try:
            log_with_context(logger, logging.INFO, "Migrating .edxauth file", {
                'file_path': str(self.legacy_auth_file),
                'file_size': self.legacy_auth_file.stat().st_size
            })
            
            # Read legacy auth file
            with open(self.legacy_auth_file, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            
            if len(lines) < 2:
                result['warnings'].append("Invalid .edxauth format: insufficient lines")
                return result
            
            # Extract credentials (first two lines: username, password)
            username = lines[0]
            password = lines[1]
            
            if not username or not password:
                result['warnings'].append("Invalid .edxauth format: empty username or password")
                return result
            
            # Store credentials using new system
            self.config_manager.store_credentials(username, password)
            result['accounts_migrated'] = 1
            
            log_with_context(logger, logging.INFO, "Migrated credentials from .edxauth", {
                'username': username,
                'password_length': len(password)
            })
            
            # Create backup if requested
            if backup:
                backup_file = self.legacy_auth_file.with_suffix('.edxauth.backup')
                shutil.copy2(self.legacy_auth_file, backup_file)
                result['backup_file'] = str(backup_file)
                log_with_context(logger, logging.DEBUG, "Created backup of .edxauth", {
                    'backup_file': str(backup_file)
                })
            
            # Add deprecation warning
            result['warnings'].append(
                "Legacy .edxauth file migrated. Consider removing the old file after verifying the migration."
            )
            
        except Exception as e:
            error_msg = f"Failed to migrate .edxauth file: {str(e)}"
            result['warnings'].append(error_msg)
            log_with_context(logger, logging.ERROR, "Failed to migrate .edxauth", {
                'error_type': type(e).__name__,
                'error_message': str(e)
            })
        
        return result
    
    def _migrate_config_file(self, config_path: Path, backup: bool = True) -> Dict[str, Any]:
        """Migrate a legacy configuration file.
        
        Args:
            config_path: Path to legacy config file.
            backup: Whether to create a backup.
            
        Returns:
            Migration results.
        """
        result = {
            'migrated': False,
            'backup_file': None,
            'warnings': []
        }
        
        try:
            log_with_context(logger, logging.INFO, "Migrating legacy config file", {
                'config_path': str(config_path),
                'file_size': config_path.stat().st_size
            })
            
            # Try to parse as different formats
            config_data = None
            
            # Try JSON format first
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except json.JSONDecodeError:
                # Try INI format
                try:
                    import configparser
                    parser = configparser.ConfigParser()
                    parser.read(config_path)
                    config_data = {section: dict(parser[section]) for section in parser.sections()}
                except Exception:
                    result['warnings'].append(f"Could not parse config file: {config_path}")
                    return result
            
            if config_data:
                # Map legacy config keys to new format
                new_config = self._map_legacy_config(config_data)
                
                # Update current configuration
                current_config = self.config_manager.config
                updated_config = self.config_manager.update_config(**new_config)
                self.config_manager.save_config(updated_config)
                
                result['migrated'] = True
                
                log_with_context(logger, logging.INFO, "Migrated legacy config", {
                    'config_path': str(config_path),
                    'migrated_keys': list(new_config.keys())
                })
                
                # Create backup if requested
                if backup:
                    backup_file = config_path.with_suffix(config_path.suffix + '.backup')
                    shutil.copy2(config_path, backup_file)
                    result['backup_file'] = str(backup_file)
        
        except Exception as e:
            error_msg = f"Failed to migrate config file {config_path}: {str(e)}"
            result['warnings'].append(error_msg)
            log_with_context(logger, logging.ERROR, "Failed to migrate config file", {
                'config_path': str(config_path),
                'error_type': type(e).__name__,
                'error_message': str(e)
            })
        
        return result
    
    def _map_legacy_config(self, legacy_config: Dict[str, Any]) -> Dict[str, Any]:
        """Map legacy configuration keys to new format.
        
        Args:
            legacy_config: Legacy configuration dictionary.
            
        Returns:
            Mapped configuration for new system.
        """
        mapping = {
            # Legacy key -> new key
            'output_dir': 'default_output_dir',
            'output_directory': 'default_output_dir',
            'download_dir': 'default_output_dir',
            'concurrent': 'max_concurrent_downloads',
            'concurrent_downloads': 'max_concurrent_downloads',
            'max_concurrent': 'max_concurrent_downloads',
            'quality': 'video_quality_preference',
            'video_quality': 'video_quality_preference',
            'preferred_quality': 'video_quality_preference',
            'delay': 'rate_limit_delay',
            'rate_limit': 'rate_limit_delay',
            'request_delay': 'rate_limit_delay',
            'retries': 'retry_attempts',
            'max_retries': 'retry_attempts',
            'retry_count': 'retry_attempts',
            'cache_dir': 'cache_directory',
            'cache_directory': 'cache_directory',
            'temp_dir': 'cache_directory'
        }
        
        new_config = {}
        
        # Handle flat configuration
        for legacy_key, value in legacy_config.items():
            if legacy_key in mapping:
                new_key = mapping[legacy_key]
                new_config[new_key] = value
        
        # Handle nested configuration (e.g., from INI files)
        for section_name, section_data in legacy_config.items():
            if isinstance(section_data, dict):
                for legacy_key, value in section_data.items():
                    if legacy_key in mapping:
                        new_key = mapping[legacy_key]
                        new_config[new_key] = value
        
        return new_config


class BackwardCompatibilityLayer:
    """Provides backward compatibility for existing CLI usage patterns."""
    
    def __init__(self):
        self.deprecated_options = {
            '--user': '--email',
            '-u': '-e',
            '--pass': '--password',
            '--output': '--output-dir',
            '--concurrent-downloads': '--concurrent',
            '--video-quality': '--quality',
            '--no-cache': '--no-resume',  # Approximate mapping
        }
        
        self.deprecated_commands = {
            'get': 'download',
            'fetch': 'download',
            'dl': 'download',
            'list': 'info',
            'show': 'info'
        }
    
    def handle_deprecated_option(self, option: str) -> Optional[str]:
        """Handle deprecated command-line options.
        
        Args:
            option: The deprecated option.
            
        Returns:
            New option name or None if not deprecated.
        """
        if option in self.deprecated_options:
            new_option = self.deprecated_options[option]
            self._warn_deprecated_option(option, new_option)
            return new_option
        return None
    
    def handle_deprecated_command(self, command: str) -> Optional[str]:
        """Handle deprecated commands.
        
        Args:
            command: The deprecated command.
            
        Returns:
            New command name or None if not deprecated.
        """
        if command in self.deprecated_commands:
            new_command = self.deprecated_commands[command]
            self._warn_deprecated_command(command, new_command)
            return new_command
        return None
    
    def _warn_deprecated_option(self, old_option: str, new_option: str):
        """Issue deprecation warning for option."""
        warnings.warn(
            f"Option '{old_option}' is deprecated. Use '{new_option}' instead.",
            DeprecationWarning,
            stacklevel=3
        )
        log_with_context(logger, logging.WARNING, "Deprecated option used", {
            'old_option': old_option,
            'new_option': new_option,
            'migration_guidance': f"Please update your scripts to use '{new_option}' instead of '{old_option}'"
        })
    
    def _warn_deprecated_command(self, old_command: str, new_command: str):
        """Issue deprecation warning for command."""
        warnings.warn(
            f"Command '{old_command}' is deprecated. Use '{new_command}' instead.",
            DeprecationWarning,
            stacklevel=3
        )
        log_with_context(logger, logging.WARNING, "Deprecated command used", {
            'old_command': old_command,
            'new_command': new_command,
            'migration_guidance': f"Please update your scripts to use '{new_command}' instead of '{old_command}'"
        })


class ConfigurationExporter:
    """Handles configuration export and import functionality."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
    
    def export_configuration(self, export_path: Union[str, Path], 
                           include_credentials: bool = False,
                           format: str = 'json') -> Dict[str, Any]:
        """Export current configuration to file.
        
        Args:
            export_path: Path to export file.
            include_credentials: Whether to include stored credentials.
            format: Export format ('json' or 'yaml').
            
        Returns:
            Export results.
        """
        with performance_timer("export_configuration", logger):
            export_path = Path(export_path)
            
            log_with_context(logger, logging.INFO, "Exporting configuration", {
                'export_path': str(export_path),
                'include_credentials': include_credentials,
                'format': format
            })
            
            export_data = {
                'export_info': {
                    'version': '2.0.0',
                    'export_date': datetime.now().isoformat(),
                    'includes_credentials': include_credentials
                },
                'configuration': asdict(self.config_manager.config)
            }
            
            # Add credentials if requested
            if include_credentials:
                stored_usernames = self.config_manager.list_stored_usernames()
                credentials = {}
                for username in stored_usernames:
                    password = self.config_manager.get_credentials(username)
                    if password:
                        credentials[username] = password
                export_data['credentials'] = credentials
                
                log_with_context(logger, logging.WARNING, "Exporting credentials", {
                    'credential_count': len(credentials),
                    'security_warning': 'Exported file contains sensitive credentials'
                })
            
            # Write export file
            try:
                if format.lower() == 'yaml':
                    try:
                        import yaml
                        with open(export_path, 'w', encoding='utf-8') as f:
                            yaml.dump(export_data, f, default_flow_style=False, indent=2)
                    except ImportError:
                        raise ConfigurationError("PyYAML not installed. Cannot export to YAML format.")
                else:
                    with open(export_path, 'w', encoding='utf-8') as f:
                        json.dump(export_data, f, indent=2, ensure_ascii=False)
                
                log_with_context(logger, logging.INFO, "Configuration exported successfully", {
                    'export_path': str(export_path),
                    'file_size': export_path.stat().st_size,
                    'format': format
                })
                
                return {
                    'success': True,
                    'export_path': str(export_path),
                    'format': format,
                    'includes_credentials': include_credentials,
                    'file_size': export_path.stat().st_size
                }
                
            except Exception as e:
                log_with_context(logger, logging.ERROR, "Configuration export failed", {
                    'export_path': str(export_path),
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                raise ConfigurationError(f"Failed to export configuration: {str(e)}")
    
    def import_configuration(self, import_path: Union[str, Path],
                           merge: bool = True,
                           import_credentials: bool = False) -> Dict[str, Any]:
        """Import configuration from file.
        
        Args:
            import_path: Path to import file.
            merge: Whether to merge with existing config or replace.
            import_credentials: Whether to import credentials.
            
        Returns:
            Import results.
        """
        with performance_timer("import_configuration", logger):
            import_path = Path(import_path)
            
            if not import_path.exists():
                raise ConfigurationError(f"Import file not found: {import_path}")
            
            log_with_context(logger, logging.INFO, "Importing configuration", {
                'import_path': str(import_path),
                'merge': merge,
                'import_credentials': import_credentials
            })
            
            try:
                # Read import file
                with open(import_path, 'r', encoding='utf-8') as f:
                    if import_path.suffix.lower() in ['.yaml', '.yml']:
                        try:
                            import yaml
                            import_data = yaml.safe_load(f)
                        except ImportError:
                            raise ConfigurationError("PyYAML not installed. Cannot import YAML format.")
                    else:
                        import_data = json.load(f)
                
                results = {
                    'config_imported': False,
                    'credentials_imported': 0,
                    'warnings': []
                }
                
                # Validate import data
                if not isinstance(import_data, dict):
                    raise ConfigurationError("Invalid import file format")
                
                # Import configuration
                if 'configuration' in import_data:
                    config_data = import_data['configuration']
                    
                    if merge:
                        # Merge with existing configuration
                        current_config = asdict(self.config_manager.config)
                        current_config.update(config_data)
                        new_config = AppConfig(**current_config)
                    else:
                        # Replace configuration
                        new_config = AppConfig(**config_data)
                    
                    self.config_manager.save_config(new_config)
                    results['config_imported'] = True
                    
                    log_with_context(logger, logging.INFO, "Configuration imported", {
                        'merge': merge,
                        'config_keys': list(config_data.keys())
                    })
                
                # Import credentials if requested and available
                if import_credentials and 'credentials' in import_data:
                    credentials = import_data['credentials']
                    for username, password in credentials.items():
                        try:
                            self.config_manager.store_credentials(username, password)
                            results['credentials_imported'] += 1
                        except Exception as e:
                            results['warnings'].append(f"Failed to import credentials for {username}: {str(e)}")
                    
                    log_with_context(logger, logging.INFO, "Credentials imported", {
                        'credentials_imported': results['credentials_imported'],
                        'warnings': len(results['warnings'])
                    })
                
                return results
                
            except Exception as e:
                log_with_context(logger, logging.ERROR, "Configuration import failed", {
                    'import_path': str(import_path),
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                raise ConfigurationError(f"Failed to import configuration: {str(e)}")


def run_migration_wizard(config_manager: ConfigManager) -> Dict[str, Any]:
    """Run interactive migration wizard.
    
    Args:
        config_manager: Configuration manager instance.
        
    Returns:
        Migration results.
    """
    migrator = LegacyConfigMigrator(config_manager)
    
    if not migrator.needs_migration():
        return {
            'migration_needed': False,
            'message': 'No legacy files found that need migration.'
        }
    
    print("EDX Downloader Migration Wizard")
    print("=" * 40)
    print("Legacy configuration files detected.")
    print("This wizard will help migrate them to the new format.")
    print()
    
    # Ask user for confirmation
    response = input("Do you want to proceed with migration? [Y/n]: ").strip().lower()
    if response and response not in ['y', 'yes']:
        return {
            'migration_needed': True,
            'migration_performed': False,
            'message': 'Migration cancelled by user.'
        }
    
    # Ask about backup
    backup_response = input("Create backups of original files? [Y/n]: ").strip().lower()
    create_backup = not backup_response or backup_response in ['y', 'yes']
    
    try:
        results = migrator.migrate_all(backup=create_backup)
        results['migration_needed'] = True
        results['migration_performed'] = True
        
        print("\nMigration completed successfully!")
        print(f"Migrated accounts: {results['migrated_accounts']}")
        print(f"Migrated configs: {results['migrated_configs']}")
        
        if results['backup_files']:
            print(f"Backup files created: {len(results['backup_files'])}")
            for backup_file in results['backup_files']:
                print(f"  - {backup_file}")
        
        if results['warnings']:
            print(f"\nWarnings ({len(results['warnings'])}):")
            for warning in results['warnings']:
                print(f"  - {warning}")
        
        return results
        
    except Exception as e:
        return {
            'migration_needed': True,
            'migration_performed': False,
            'error': str(e),
            'message': f'Migration failed: {str(e)}'
        }