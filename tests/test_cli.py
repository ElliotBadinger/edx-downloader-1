"""Tests for enhanced CLI interface with seamless features."""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock, mock_open
import tempfile
import os

from edx_downloader.cli import cli, handle_authentication
from edx_downloader.models import AppConfig


class TestCLI:
    """Test basic CLI functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    def test_cli_help(self):
        """Test CLI help command."""
        result = self.runner.invoke(cli, ['--help'])
        assert result.exit_code == 0
        assert 'Modern EDX course video downloader' in result.output
        assert 'download' in result.output
        assert 'config' in result.output
        assert 'accounts' in result.output
        assert 'quick' in result.output
        assert 'batch' in result.output
        assert 'setup' in result.output
    
    def test_cli_version(self):
        """Test CLI version command."""
        result = self.runner.invoke(cli, ['--version'])
        assert result.exit_code == 0
        assert '2.0.0' in result.output
    
    def test_download_help(self):
        """Test download command help."""
        result = self.runner.invoke(cli, ['download', '--help'])
        assert result.exit_code == 0
        assert 'Download videos from an EDX course' in result.output
        assert '--email' in result.output
        assert '--quality' in result.output
        assert '--concurrent' in result.output
        assert '--auto' in result.output
        assert '--fast' in result.output
    
    def test_quick_help(self):
        """Test quick command help."""
        result = self.runner.invoke(cli, ['quick', '--help'])
        assert result.exit_code == 0
        assert 'Quick download with minimal prompts' in result.output
        assert '--email' in result.output
        assert '--quality' in result.output
    
    def test_batch_help(self):
        """Test batch command help."""
        result = self.runner.invoke(cli, ['batch', '--help'])
        assert result.exit_code == 0
        assert 'Download multiple courses from a file' in result.output
        assert '--concurrent-courses' in result.output
    
    def test_setup_help(self):
        """Test setup command help."""
        result = self.runner.invoke(cli, ['setup', '--help'])
        assert result.exit_code == 0
        assert 'Interactive setup wizard' in result.output
    
    @patch('edx_downloader.cli.ConfigManager')
    def test_config_command(self, mock_config_manager):
        """Test config command."""
        # Mock configuration
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        
        result = self.runner.invoke(cli, ['config'])
        assert result.exit_code == 0
        assert 'Current Configuration' in result.output
        assert 'Default Output Directory' in result.output
    
    @patch('edx_downloader.cli.ConfigManager')
    def test_accounts_command_empty(self, mock_config_manager):
        """Test accounts command with no stored accounts."""
        mock_config_manager.return_value.list_stored_usernames.return_value = []
        
        result = self.runner.invoke(cli, ['accounts'])
        assert result.exit_code == 0
        assert 'No stored accounts found' in result.output
    
    @patch('edx_downloader.cli.ConfigManager')
    def test_accounts_command_with_accounts(self, mock_config_manager):
        """Test accounts command with stored accounts."""
        mock_config_manager.return_value.list_stored_usernames.return_value = ['test@example.com']
        
        result = self.runner.invoke(cli, ['accounts'])
        assert result.exit_code == 0
        assert 'Stored Accounts' in result.output
        assert 'test@example.com' in result.output


class TestSeamlessAuthentication:
    """Test seamless authentication features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('edx_downloader.cli.AuthenticationManager')
    @patch('edx_downloader.cli.console')
    def test_handle_authentication_single_account_auto_select(self, mock_console, mock_auth_manager):
        """Test auto-selection when only one account is stored."""
        mock_config_manager = MagicMock()
        mock_config_manager.list_stored_usernames.return_value = ['test@example.com']
        mock_config_manager.get_credentials.return_value = 'password123'
        
        mock_auth_instance = MagicMock()
        mock_auth_manager.return_value = mock_auth_instance
        
        result = handle_authentication(mock_config_manager, None, None, silent=False)
        
        # Should auto-select the single account
        mock_config_manager.list_stored_usernames.assert_called_once()
        mock_config_manager.get_credentials.assert_called_with('test@example.com')
        mock_auth_instance.authenticate.assert_called_with('test@example.com', 'password123')
    
    @patch('edx_downloader.cli.AuthenticationManager')
    @patch('edx_downloader.cli.console')
    def test_handle_authentication_silent_mode(self, mock_console, mock_auth_manager):
        """Test silent mode authentication."""
        mock_config_manager = MagicMock()
        mock_config_manager.list_stored_usernames.return_value = ['test@example.com']
        mock_config_manager.get_credentials.return_value = 'password123'
        
        mock_auth_instance = MagicMock()
        mock_auth_manager.return_value = mock_auth_instance
        
        result = handle_authentication(mock_config_manager, None, None, silent=True)
        
        # Should not print account selection message in silent mode
        mock_console.print.assert_not_called()
    
    @patch('edx_downloader.cli.AuthenticationManager')
    @patch('edx_downloader.cli.Prompt.ask')
    @patch('edx_downloader.cli.Confirm.ask')
    def test_handle_authentication_auto_store_credentials(self, mock_confirm, mock_prompt, mock_auth_manager):
        """Test auto-storing new credentials."""
        mock_config_manager = MagicMock()
        mock_config_manager.list_stored_usernames.return_value = []
        mock_config_manager.get_credentials.return_value = None
        
        mock_prompt.side_effect = ['test@example.com', 'password123']
        mock_confirm.return_value = True
        
        mock_auth_instance = MagicMock()
        mock_auth_manager.return_value = mock_auth_instance
        
        result = handle_authentication(mock_config_manager, None, None)
        
        # Should store credentials after successful authentication
        mock_config_manager.store_credentials.assert_called_with('test@example.com', 'password123')


class TestEnhancedCommands:
    """Test enhanced command features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.handle_authentication')
    @patch('edx_downloader.cli.ConfigManager')
    def test_quick_command(self, mock_config_manager, mock_auth, mock_asyncio):
        """Test quick command functionality."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_auth.return_value = MagicMock()
        mock_asyncio.return_value = None
        
        result = self.runner.invoke(cli, [
            'quick',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            '--email', 'test@example.com',
            '--quality', '720p'
        ])
        
        # Should call authentication in silent mode
        mock_auth.assert_called_with(mock_config_manager.return_value, 'test@example.com', None, silent=True)
        mock_asyncio.assert_called_once()
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.handle_authentication')
    @patch('edx_downloader.cli.ConfigManager')
    def test_quick_alias_command(self, mock_config_manager, mock_auth, mock_asyncio):
        """Test quick alias 'q' command."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_auth.return_value = MagicMock()
        mock_asyncio.return_value = None
        
        result = self.runner.invoke(cli, [
            'q',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/'
        ])
        
        mock_auth.assert_called_once()
        mock_asyncio.assert_called_once()
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.download_course_videos')
    @patch('edx_downloader.cli.ConfigManager')
    def test_download_alias_command(self, mock_config_manager, mock_download, mock_asyncio):
        """Test download alias 'dl' command."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_config_manager.return_value.list_stored_usernames.return_value = ['test@example.com']
        mock_asyncio.return_value = None
        
        result = self.runner.invoke(cli, [
            'dl',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            '--auto'
        ])
        
        mock_asyncio.assert_called_once()
        assert result.exit_code == 0
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.download_course_videos')
    @patch('edx_downloader.cli.ConfigManager')
    def test_download_fast_mode(self, mock_config_manager, mock_download, mock_asyncio):
        """Test download command with fast mode."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_config_manager.return_value.list_stored_usernames.return_value = ['test@example.com']
        mock_asyncio.return_value = None
        
        result = self.runner.invoke(cli, [
            'download',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            '--fast'
        ])
        
        # Fast mode should enable auto mode and high concurrency
        mock_asyncio.assert_called_once()
        assert result.exit_code == 0
    
    def test_batch_command_file_not_found(self):
        """Test batch command with non-existent file."""
        result = self.runner.invoke(cli, ['batch', 'nonexistent.txt'])
        assert result.exit_code == 2  # Click error for file not found
        assert 'does not exist' in result.output
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.handle_authentication')
    @patch('edx_downloader.cli.ConfigManager')
    def test_batch_command_success(self, mock_config_manager, mock_auth, mock_asyncio):
        """Test batch command with valid URLs file."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_auth.return_value = MagicMock()
        mock_asyncio.return_value = None
        
        # Create a temporary file with URLs
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write('https://course1.edx.org\nhttps://course2.edx.org\n# comment\n')
            temp_file = f.name
        
        try:
            result = self.runner.invoke(cli, ['batch', temp_file])
            
            # Should authenticate and run async download
            mock_auth.assert_called_once()
            mock_asyncio.assert_called_once()
        finally:
            # Clean up temp file
            os.unlink(temp_file)


class TestInteractiveFeatures:
    """Test interactive features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('edx_downloader.cli.Prompt.ask')
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.download_course_videos')
    @patch('edx_downloader.cli.ConfigManager')
    def test_download_interactive_url_prompt(self, mock_config_manager, mock_download, mock_asyncio, mock_prompt):
        """Test interactive URL prompting when URL not provided."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_config_manager.return_value.list_stored_usernames.return_value = ['test@example.com']
        mock_asyncio.return_value = None
        mock_prompt.side_effect = [
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            'password123'
        ]
        
        result = self.runner.invoke(cli, ['download'])
        
        # Should prompt for course URL
        assert mock_prompt.call_count >= 1
        mock_asyncio.assert_called_once()
    
    @patch('edx_downloader.cli.Prompt.ask')
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.get_course_info')
    @patch('edx_downloader.cli.ConfigManager')
    def test_info_interactive_url_prompt(self, mock_config_manager, mock_info, mock_asyncio, mock_prompt):
        """Test interactive URL prompting for info command."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_config_manager.return_value.list_stored_usernames.return_value = ['test@example.com']
        mock_asyncio.return_value = None
        mock_prompt.side_effect = [
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            'password123'
        ]
        
        result = self.runner.invoke(cli, ['info'])
        
        # Should prompt for course URL
        assert mock_prompt.call_count >= 1
        mock_asyncio.assert_called_once()
    
    @patch('edx_downloader.cli.Prompt.ask')
    @patch('edx_downloader.cli.Confirm.ask')
    @patch('edx_downloader.cli.ConfigManager')
    def test_setup_wizard(self, mock_config_manager, mock_confirm, mock_prompt):
        """Test setup wizard functionality."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.store_credentials = MagicMock()
        mock_config_manager.return_value.update_config = MagicMock(return_value=mock_config)
        mock_config_manager.return_value.save_config = MagicMock()
        
        # Mock user inputs
        mock_prompt.side_effect = [
            'test@example.com',  # email
            'password123',       # password
            './downloads',       # output dir
            'highest',          # quality
            '3'                 # concurrent
        ]
        mock_confirm.side_effect = [False]  # Don't test download
        
        result = self.runner.invoke(cli, ['setup'])
        
        # Should store credentials and save config
        mock_config_manager.return_value.store_credentials.assert_called_with('test@example.com', 'password123')
        mock_config_manager.return_value.save_config.assert_called_once()


class TestShortOptions:
    """Test short option aliases."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.download_course_videos')
    @patch('edx_downloader.cli.ConfigManager')
    def test_short_options(self, mock_config_manager, mock_download, mock_asyncio):
        """Test short option aliases work correctly."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_asyncio.return_value = None
        
        result = self.runner.invoke(cli, [
            'download',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            '-e', 'test@example.com',  # --email
            '-p', 'password123',       # --password
            '-o', './downloads',       # --output-dir
            '-q', '720p',             # --quality
            '-c', '5',                # --concurrent
            '-a'                      # --auto
        ])
        
        mock_asyncio.assert_called_once()
        assert result.exit_code == 0


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('edx_downloader.cli.ConfigManager')
    @patch('edx_downloader.cli.Prompt.ask')
    def test_add_account_command(self, mock_prompt, mock_config_manager):
        """Test add account command."""
        mock_prompt.return_value = 'password123'
        mock_config_manager.return_value.store_credentials = MagicMock()
        
        result = self.runner.invoke(cli, ['add-account', 'test@example.com'])
        assert result.exit_code == 0
        assert 'Account test@example.com added successfully' in result.output
        mock_config_manager.return_value.store_credentials.assert_called_once_with('test@example.com', 'password123')
    
    @patch('edx_downloader.cli.ConfigManager')
    @patch('edx_downloader.cli.Confirm.ask')
    def test_remove_account_command(self, mock_confirm, mock_config_manager):
        """Test remove account command."""
        mock_confirm.return_value = True
        mock_config_manager.return_value.delete_credentials = MagicMock()
        
        result = self.runner.invoke(cli, ['remove-account', 'test@example.com'])
        assert result.exit_code == 0
        assert 'Account test@example.com removed successfully' in result.output
        mock_config_manager.return_value.delete_credentials.assert_called_once_with('test@example.com')
    
    @patch('edx_downloader.cli.ConfigManager')
    @patch('edx_downloader.cli.Prompt.ask')
    def test_add_account_error_handling(self, mock_prompt, mock_config_manager):
        """Test add account command error handling."""
        mock_prompt.return_value = 'password123'
        mock_config_manager.return_value.store_credentials.side_effect = Exception("Storage error")
        
        result = self.runner.invoke(cli, ['add-account', 'test@example.com'])
        assert result.exit_code == 0
        assert 'Failed to add account' in result.output
    
    @patch('edx_downloader.cli.ConfigManager')
    def test_cli_with_config_file(self, mock_config_manager):
        """Test CLI with custom config file."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        
        result = self.runner.invoke(cli, ['--config-file', '/custom/config.json', 'config'])
        assert result.exit_code == 0
        mock_config_manager.assert_called_with('/custom/config.json')
    
    @patch('edx_downloader.cli.ConfigManager')
    def test_cli_verbose_mode(self, mock_config_manager):
        """Test CLI with verbose mode."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        
        result = self.runner.invoke(cli, ['--verbose', 'config'])
        assert result.exit_code == 0
        mock_config_manager.assert_called_once()


class TestCLIIntegration:
    """Test CLI integration with other components."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.download_course_videos')
    @patch('edx_downloader.cli.ConfigManager')
    def test_download_command_integration(self, mock_config_manager, mock_download, mock_asyncio):
        """Test download command integration."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_asyncio.return_value = None
        
        result = self.runner.invoke(cli, [
            'download',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            '--email', 'test@example.com',
            '--password', 'password123',
            '--output-dir', './test-downloads',
            '--quality', '720p',
            '--concurrent', '2'
        ])
        
        assert mock_asyncio.called
        assert result.exit_code == 0
    
    @patch('edx_downloader.cli.asyncio.run')
    @patch('edx_downloader.cli.create_app')
    @patch('edx_downloader.cli.ConfigManager')
    def test_info_command_integration(self, mock_config_manager, mock_create_app, mock_asyncio):
        """Test info command integration."""
        mock_config = AppConfig()
        mock_config_manager.return_value.config = mock_config
        mock_config_manager.return_value.get_credentials.return_value = None
        mock_config_manager.return_value.list_stored_usernames.return_value = ['test@example.com']
        mock_asyncio.return_value = None
        
        # Mock the app context manager
        mock_app = MagicMock()
        mock_create_app.return_value.__aenter__.return_value = mock_app
        
        result = self.runner.invoke(cli, [
            'info',
            'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
            '--email', 'test@example.com',
            '--password', 'password123'
        ])
        
        assert mock_asyncio.called
        assert result.exit_code == 0


if __name__ == '__main__':
    pytest.main([__file__])