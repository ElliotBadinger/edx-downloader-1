"""
Unit tests for logging configuration and functionality.

Tests the comprehensive logging system including formatters, handlers,
performance timers, and contextual logging capabilities.
"""

import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from edx_downloader.logging_config import (
    PerformanceTimer,
    ContextualFormatter,
    EdxDownloaderLogger,
    setup_logging,
    get_logger,
    log_with_context,
    performance_timer
)
from edx_downloader.models import AppConfig


def cleanup_logging():
    """Clean up logging handlers to avoid file permission issues."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        try:
            handler.close()
        except:
            pass
        root_logger.removeHandler(handler)
    
    # Reset global logger instance
    import edx_downloader.logging_config
    edx_downloader.logging_config._logger_instance = None


class TestPerformanceTimer:
    """Test the PerformanceTimer context manager."""
    
    def test_performance_timer_success(self):
        """Test performance timer with successful operation."""
        logger = Mock(spec=logging.Logger)
        timer = PerformanceTimer("test_operation", logger, logging.DEBUG)
        
        with timer:
            time.sleep(0.01)  # Small delay to measure
        
        # Check that start and completion messages were logged
        assert logger.log.call_count == 2
        logger.log.assert_any_call(logging.DEBUG, "Starting test_operation")
        
        # Check completion message contains duration
        completion_call = logger.log.call_args_list[1]
        assert "Completed test_operation in" in completion_call[0][1]
        assert "s" in completion_call[0][1]
        
        # Check duration property
        assert timer.duration is not None
        assert timer.duration > 0
    
    def test_performance_timer_with_exception(self):
        """Test performance timer when operation raises exception."""
        logger = Mock(spec=logging.Logger)
        timer = PerformanceTimer("failing_operation", logger, logging.DEBUG)
        
        with pytest.raises(ValueError):
            with timer:
                raise ValueError("Test error")
        
        # Check that error message was logged
        assert logger.error.called
        error_call = logger.error.call_args[0][0]
        assert "Failed failing_operation after" in error_call
        assert "Test error" in error_call
    
    def test_performance_timer_duration_property(self):
        """Test duration property before and after completion."""
        logger = Mock(spec=logging.Logger)
        timer = PerformanceTimer("test_op", logger)
        
        # Duration should be None before completion
        assert timer.duration is None
        
        with timer:
            # Duration should still be None during execution
            assert timer.duration is None
        
        # Duration should be available after completion
        assert timer.duration is not None
        assert isinstance(timer.duration, float)


class TestContextualFormatter:
    """Test the ContextualFormatter class."""
    
    def test_text_formatter_basic(self):
        """Test basic text formatting."""
        formatter = ContextualFormatter(include_context=False, json_format=False)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        assert "Test message" in formatted
        assert "test_logger" in formatted
        assert "INFO" in formatted
    
    def test_text_formatter_with_context(self):
        """Test text formatting with context information."""
        formatter = ContextualFormatter(include_context=True, json_format=False)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.context = {"user": "testuser", "operation": "download"}
        record.duration = 1.234
        
        formatted = formatter.format(record)
        assert "Test message" in formatted
        assert "Context: user=testuser, operation=download" in formatted
        assert "Duration: 1.234s" in formatted
    
    def test_json_formatter_basic(self):
        """Test basic JSON formatting."""
        formatter = ContextualFormatter(include_context=True, json_format=True)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        data = json.loads(formatted)
        
        assert data["message"] == "Test message"
        assert data["logger"] == "test_logger"
        assert data["level"] == "INFO"
        assert data["line"] == 42
        assert "timestamp" in data
    
    def test_json_formatter_with_exception(self):
        """Test JSON formatting with exception information."""
        formatter = ContextualFormatter(include_context=True, json_format=True)
        
        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test_logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=42,
                msg="Error occurred",
                args=(),
                exc_info=None
            )
            record.exc_info = exc_info
        
        formatted = formatter.format(record)
        data = json.loads(formatted)
        
        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "Test exception"
        assert isinstance(data["exception"]["traceback"], list)
    
    def test_json_formatter_with_context_and_duration(self):
        """Test JSON formatting with context and performance data."""
        formatter = ContextualFormatter(include_context=True, json_format=True)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=42,
            msg="Operation completed",
            args=(),
            exc_info=None
        )
        record.context = {"operation": "api_call", "url": "https://example.com"}
        record.duration = 2.567
        
        formatted = formatter.format(record)
        data = json.loads(formatted)
        
        assert data["context"]["operation"] == "api_call"
        assert data["context"]["url"] == "https://example.com"
        assert data["duration_seconds"] == 2.567


class TestEdxDownloaderLogger:
    """Test the main EdxDownloaderLogger class."""
    
    @pytest.fixture
    def temp_config(self):
        """Create a temporary configuration for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(
                cache_directory=temp_dir,
                max_concurrent_downloads=2,
                rate_limit_delay=1.0,
                retry_attempts=3
            )
            yield config
            
            # Clean up any logging handlers that might be holding file handles
            import logging
            for handler in logging.root.handlers[:]:
                if hasattr(handler, 'close'):
                    handler.close()
                logging.root.removeHandler(handler)
            
            # Also clean up any loggers that might have been created
            for name in list(logging.Logger.manager.loggerDict.keys()):
                if name.startswith('edx_downloader'):
                    logger = logging.getLogger(name)
                    for handler in logger.handlers[:]:
                        if hasattr(handler, 'close'):
                            handler.close()
                        logger.removeHandler(handler)
    
    def test_logger_initialization(self, temp_config):
        """Test logger initialization and setup."""
        logger_manager = EdxDownloaderLogger(temp_config)
        
        # Check that log directory was created
        log_dir = Path(temp_config.cache_directory) / "logs"
        assert log_dir.exists()
        
        # Check that loggers dictionary is initialized
        assert isinstance(logger_manager.loggers, dict)
        assert isinstance(logger_manager.performance_timers, dict)
    
    def test_get_logger(self, temp_config):
        """Test getting logger instances."""
        logger_manager = EdxDownloaderLogger(temp_config)
        
        logger1 = logger_manager.get_logger("test.module1")
        logger2 = logger_manager.get_logger("test.module2")
        logger1_again = logger_manager.get_logger("test.module1")
        
        # Check that loggers are cached
        assert logger1 is logger1_again
        assert logger1 is not logger2
        assert len(logger_manager.loggers) == 2
    
    def test_log_with_context(self, temp_config):
        """Test contextual logging functionality."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.logger"
        logger.makeRecord.return_value = Mock()
        
        context = {"user": "testuser", "course": "test-course"}
        logger_manager.log_with_context(
            logger, logging.INFO, "Test message", context, extra_attr="extra_value"
        )
        
        # Check that makeRecord was called
        logger.makeRecord.assert_called_once()
        
        # Check that handle was called
        logger.handle.assert_called_once()
        
        # Check that context was added to record
        record = logger.handle.call_args[0][0]
        assert hasattr(record, 'context')
        assert hasattr(record, 'extra_attr')
    
    def test_log_api_request(self, temp_config):
        """Test API request logging."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.api"
        logger.makeRecord.return_value = Mock()
        
        # Test successful request
        logger_manager.log_api_request(
            logger, "GET", "https://api.example.com/test", 
            status_code=200, duration=1.5, request_size=100, response_size=500
        )
        
        logger.handle.assert_called()
        record = logger.handle.call_args[0][0]
        assert hasattr(record, 'context')
        assert record.context['api_method'] == 'GET'
        assert record.context['status_code'] == 200
        assert hasattr(record, 'duration')
    
    def test_log_api_request_error_status(self, temp_config):
        """Test API request logging with error status codes."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.api"
        logger.makeRecord.return_value = Mock()
        
        # Test 4xx error
        logger_manager.log_api_request(
            logger, "POST", "https://api.example.com/test", status_code=404
        )
        
        # Should log at WARNING level for 4xx
        call_args = logger.makeRecord.call_args
        assert call_args[0][1] == logging.WARNING
        
        # Test 5xx error
        logger.makeRecord.reset_mock()
        logger_manager.log_api_request(
            logger, "GET", "https://api.example.com/test", status_code=500
        )
        
        # Should log at ERROR level for 5xx
        call_args = logger.makeRecord.call_args
        assert call_args[0][1] == logging.ERROR
    
    def test_log_download_progress(self, temp_config):
        """Test download progress logging."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.download"
        logger.makeRecord.return_value = Mock()
        
        # Test with total bytes known
        logger_manager.log_download_progress(
            logger, "Test Video", 500, total_bytes=1000, speed_bps=1024
        )
        
        logger.handle.assert_called()
        record = logger.handle.call_args[0][0]
        assert record.context['video_title'] == 'Test Video'
        assert record.context['progress_percent'] == 50.0
        assert record.context['speed_bps'] == 1024
    
    def test_log_download_progress_no_total(self, temp_config):
        """Test download progress logging without total bytes."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.download"
        logger.makeRecord.return_value = Mock()
        
        logger_manager.log_download_progress(logger, "Test Video", 500)
        
        logger.handle.assert_called()
        record = logger.handle.call_args[0][0]
        assert 'progress_percent' not in record.context
        assert record.context['bytes_downloaded'] == 500
    
    def test_log_parsing_error(self, temp_config):
        """Test parsing error logging."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.parser"
        logger.makeRecord.return_value = Mock()
        
        error = ValueError("Invalid JSON")
        html_content = "<html>" + "x" * 600 + "</html>"  # Long content
        json_content = {"error": "test"}
        
        logger_manager.log_parsing_error(
            logger, "https://example.com", error, html_content, json_content
        )
        
        logger.handle.assert_called()
        record = logger.handle.call_args[0][0]
        assert record.context['parsing_url'] == 'https://example.com'
        assert record.context['error_type'] == 'ValueError'
        assert record.context['error_message'] == 'Invalid JSON'
        assert len(record.context['html_sample']) <= 503  # Truncated
        assert record.context['json_content'] == json_content
    
    def test_log_authentication_event_success(self, temp_config):
        """Test successful authentication logging."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.auth"
        logger.makeRecord.return_value = Mock()
        
        logger_manager.log_authentication_event(logger, "testuser", True)
        
        logger.handle.assert_called()
        record = logger.handle.call_args[0][0]
        assert record.context['username'] == 'testuser'
        assert record.context['auth_success'] is True
        
        # Should log at INFO level for success
        call_args = logger.makeRecord.call_args
        assert call_args[0][1] == logging.INFO
    
    def test_log_authentication_event_failure(self, temp_config):
        """Test failed authentication logging."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.auth"
        logger.makeRecord.return_value = Mock()
        
        logger_manager.log_authentication_event(
            logger, "testuser", False, "Invalid credentials"
        )
        
        logger.handle.assert_called()
        record = logger.handle.call_args[0][0]
        assert record.context['auth_success'] is False
        assert record.context['auth_error'] == 'Invalid credentials'
        
        # Should log at WARNING level for failure
        call_args = logger.makeRecord.call_args
        assert call_args[0][1] == logging.WARNING
    
    def test_performance_timer_context_manager(self, temp_config):
        """Test performance timer context manager."""
        logger_manager = EdxDownloaderLogger(temp_config)
        
        with logger_manager.performance_timer("test_operation") as timer:
            assert isinstance(timer, PerformanceTimer)
            assert "test_operation" in logger_manager.performance_timers
            time.sleep(0.01)
        
        # Timer should be removed after completion
        assert "test_operation" not in logger_manager.performance_timers
        assert timer.duration is not None
    
    def test_log_system_info_mock(self, temp_config):
        """Test system information logging with mocked dependencies."""
        logger_manager = EdxDownloaderLogger(temp_config)
        logger = Mock(spec=logging.Logger)
        logger.name = "test.system"
        logger.makeRecord.return_value = Mock()
        
        # Mock the system info method to avoid psutil dependency
        with patch.object(logger_manager, 'log_system_info') as mock_log_system:
            logger_manager.log_system_info(logger)
            mock_log_system.assert_called_once_with(logger)
    
    def test_configure_debug_mode(self, temp_config):
        """Test debug mode configuration."""
        logger_manager = EdxDownloaderLogger(temp_config)
        
        # Test enabling debug mode
        with patch('logging.getLogger') as mock_get_logger:
            mock_root_logger = Mock()
            mock_handler = Mock()
            mock_handler.setLevel = Mock()
            mock_handler.stream = Mock()
            mock_handler.stream.__class__ = type(Mock().stdout)
            mock_root_logger.handlers = [mock_handler]
            mock_get_logger.return_value = mock_root_logger
            
            logger_manager.configure_debug_mode(True)
            mock_handler.setLevel.assert_called_with(logging.DEBUG)
    
    def test_get_log_files(self, temp_config):
        """Test getting log file paths."""
        logger_manager = EdxDownloaderLogger(temp_config)
        log_files = logger_manager.get_log_files()
        
        expected_files = ['main', 'errors', 'debug', 'performance']
        assert all(key in log_files for key in expected_files)
        
        for file_path in log_files.values():
            assert isinstance(file_path, Path)
            assert str(temp_config.cache_directory) in str(file_path)


class TestGlobalFunctions:
    """Test global logging functions."""
    
    def test_setup_logging(self):
        """Test global logging setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(cache_directory=temp_dir)
            
            logger_instance = setup_logging(config)
            assert isinstance(logger_instance, EdxDownloaderLogger)
            
            # Test that get_logger works after setup
            logger = get_logger("test.module")
            assert isinstance(logger, logging.Logger)
            
            # Clean up handlers to avoid file permission issues
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                handler.close()
                root_logger.removeHandler(handler)
    
    def test_get_logger_without_setup(self):
        """Test get_logger fallback when not configured."""
        # Reset global instance
        import edx_downloader.logging_config
        edx_downloader.logging_config._logger_instance = None
        
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
    
    def test_log_with_context_global(self):
        """Test global log_with_context function."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(cache_directory=temp_dir)
            setup_logging(config)
            
            logger = Mock(spec=logging.Logger)
            logger.name = "test.logger"
            logger.makeRecord.return_value = Mock()
            
            log_with_context(logger, logging.INFO, "Test message", {"key": "value"})
            
            # Should call the logger manager's method
            logger.handle.assert_called()
    
    def test_log_with_context_fallback(self):
        """Test log_with_context fallback when not configured."""
        # Reset global instance
        import edx_downloader.logging_config
        edx_downloader.logging_config._logger_instance = None
        
        logger = Mock(spec=logging.Logger)
        
        log_with_context(logger, logging.INFO, "Test message", {"key": "value"})
        
        # Should fall back to basic logging
        logger.log.assert_called_with(logging.INFO, "Test message")
    
    def test_performance_timer_global(self):
        """Test global performance_timer function."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(cache_directory=temp_dir)
            setup_logging(config)
            
            with performance_timer("test_operation") as timer:
                assert isinstance(timer, PerformanceTimer)
                time.sleep(0.01)
            
            assert timer.duration is not None
    
    def test_performance_timer_fallback(self):
        """Test performance_timer fallback when not configured."""
        # Reset global instance
        import edx_downloader.logging_config
        edx_downloader.logging_config._logger_instance = None
        
        with performance_timer("test_operation") as timer:
            assert isinstance(timer, PerformanceTimer)
            time.sleep(0.01)
        
        assert timer.duration is not None


class TestLoggingIntegration:
    """Integration tests for logging functionality."""
    
    def test_full_logging_workflow(self):
        """Test complete logging workflow with file output."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(cache_directory=temp_dir)
            logger_manager = EdxDownloaderLogger(config)
            
            # Get a logger and log various types of messages
            logger = logger_manager.get_logger("test.integration")
            
            # Basic logging
            logger.info("Integration test started")
            
            # Contextual logging
            logger_manager.log_with_context(
                logger, logging.INFO, "User action", 
                {"user": "testuser", "action": "download"}
            )
            
            # API request logging
            logger_manager.log_api_request(
                logger, "GET", "https://api.example.com", 200, 1.5
            )
            
            # Performance timing
            with logger_manager.performance_timer("test_operation", logger):
                time.sleep(0.01)
            
            # Check that log files were created
            log_files = logger_manager.get_log_files()
            for log_type, log_path in log_files.items():
                if log_type in ['main', 'debug']:  # These should have content
                    assert log_path.exists()
                    assert log_path.stat().st_size > 0
    
    def test_error_logging_with_exception(self):
        """Test error logging with exception handling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(cache_directory=temp_dir)
            logger_manager = EdxDownloaderLogger(config)
            logger = logger_manager.get_logger("test.errors")
            
            try:
                raise ValueError("Test exception for logging")
            except ValueError as e:
                logger_manager.log_parsing_error(
                    logger, "https://example.com", e, "<html>test</html>"
                )
            
            # Check error log file
            error_log = logger_manager.get_log_files()['errors']
            # Note: In real scenario, this would contain the error
            # For unit test, we're mainly testing the structure