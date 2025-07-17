"""
Comprehensive logging and debugging configuration for EDX Downloader.

This module provides structured logging with configurable levels, output formats,
and detailed debug information for troubleshooting API and parsing issues.
"""

import logging
import logging.handlers
import sys
import time
import json
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, Union
from datetime import datetime
from contextlib import contextmanager

from .models import AppConfig


class PerformanceTimer:
    """Context manager for measuring and logging performance metrics."""
    
    def __init__(self, operation_name: str, logger: logging.Logger, log_level: int = logging.DEBUG):
        self.operation_name = operation_name
        self.logger = logger
        self.log_level = log_level
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        self.logger.log(self.log_level, f"Starting {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        duration = self.end_time - self.start_time
        
        if exc_type is None:
            self.logger.log(self.log_level, f"Completed {self.operation_name} in {duration:.3f}s")
        else:
            self.logger.error(f"Failed {self.operation_name} after {duration:.3f}s: {exc_val}")
    
    @property
    def duration(self) -> Optional[float]:
        """Get the duration of the operation if completed."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


class ContextualFormatter(logging.Formatter):
    """Custom formatter that includes contextual information and structured data."""
    
    def __init__(self, include_context: bool = True, json_format: bool = False):
        self.include_context = include_context
        self.json_format = json_format
        
        if json_format:
            super().__init__()
        else:
            fmt = '%(asctime)s - %(name)s - %(levelname)s'
            if include_context:
                fmt += ' - [%(filename)s:%(lineno)d]'
            fmt += ' - %(message)s'
            super().__init__(fmt, datefmt='%Y-%m-%d %H:%M:%S')
    
    def format(self, record):
        if self.json_format:
            return self._format_json(record)
        else:
            return self._format_text(record)
    
    def _format_json(self, record) -> str:
        """Format log record as JSON."""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception information if present
        if record.exc_info and record.exc_info != (None, None, None):
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra context if available
        if hasattr(record, 'context'):
            log_data['context'] = record.context
        
        # Add performance metrics if available
        if hasattr(record, 'duration'):
            log_data['duration_seconds'] = record.duration
        
        return json.dumps(log_data, ensure_ascii=False)
    
    def _format_text(self, record) -> str:
        """Format log record as human-readable text."""
        formatted = super().format(record)
        
        # Add context information if available
        if hasattr(record, 'context') and self.include_context:
            context_str = ', '.join(f"{k}={v}" for k, v in record.context.items())
            formatted += f" | Context: {context_str}"
        
        # Add performance information if available
        if hasattr(record, 'duration'):
            formatted += f" | Duration: {record.duration:.3f}s"
        
        return formatted


class EdxDownloaderLogger:
    """Main logging manager for EDX Downloader with comprehensive configuration."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.loggers: Dict[str, logging.Logger] = {}
        self.performance_timers: Dict[str, PerformanceTimer] = {}
        self._setup_logging()
    
    def _setup_logging(self):
        """Set up logging configuration based on app config."""
        # Create logs directory if it doesn't exist
        log_dir = Path(self.config.cache_directory) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Console handler for user-facing messages
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = ContextualFormatter(include_context=False, json_format=False)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File handler for detailed logging
        log_file = log_dir / "edx_downloader.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = ContextualFormatter(include_context=True, json_format=False)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # Error file handler for errors only
        error_file = log_dir / "errors.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_formatter = ContextualFormatter(include_context=True, json_format=False)
        error_handler.setFormatter(error_formatter)
        root_logger.addHandler(error_handler)
        
        # JSON debug handler for structured debugging
        debug_file = log_dir / "debug.jsonl"
        debug_handler = logging.handlers.RotatingFileHandler(
            debug_file,
            maxBytes=20 * 1024 * 1024,  # 20MB
            backupCount=3,
            encoding='utf-8'
        )
        debug_handler.setLevel(logging.DEBUG)
        debug_formatter = ContextualFormatter(include_context=True, json_format=True)
        debug_handler.setFormatter(debug_formatter)
        root_logger.addHandler(debug_handler)
        
        # Performance log handler
        perf_file = log_dir / "performance.log"
        perf_handler = logging.handlers.RotatingFileHandler(
            perf_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=2,
            encoding='utf-8'
        )
        perf_handler.setLevel(logging.DEBUG)
        perf_formatter = ContextualFormatter(include_context=False, json_format=False)
        perf_handler.setFormatter(perf_formatter)
        
        # Create performance logger
        perf_logger = logging.getLogger('edx_downloader.performance')
        perf_logger.addHandler(perf_handler)
        perf_logger.propagate = False
        
        # Suppress noisy third-party loggers
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance with contextual capabilities.
        
        Args:
            name: Logger name (usually __name__).
            
        Returns:
            Configured logger instance.
        """
        if name not in self.loggers:
            logger = logging.getLogger(name)
            self.loggers[name] = logger
        
        return self.loggers[name]
    
    def log_with_context(self, logger: logging.Logger, level: int, message: str, 
                        context: Optional[Dict[str, Any]] = None, **kwargs):
        """Log a message with additional context information.
        
        Args:
            logger: Logger instance to use.
            level: Logging level.
            message: Log message.
            context: Additional context information.
            **kwargs: Additional keyword arguments.
        """
        # Create log record
        record = logger.makeRecord(
            logger.name, level, "", 0, message, (), None
        )
        
        # Add context information
        if context:
            record.context = context
        
        # Add any additional attributes
        for key, value in kwargs.items():
            setattr(record, key, value)
        
        # Handle the record
        logger.handle(record)
    
    def log_api_request(self, logger: logging.Logger, method: str, url: str, 
                       status_code: Optional[int] = None, duration: Optional[float] = None,
                       request_size: Optional[int] = None, response_size: Optional[int] = None):
        """Log API request details for debugging.
        
        Args:
            logger: Logger instance.
            method: HTTP method.
            url: Request URL.
            status_code: Response status code.
            duration: Request duration in seconds.
            request_size: Request size in bytes.
            response_size: Response size in bytes.
        """
        context = {
            'api_method': method,
            'api_url': url,
            'status_code': status_code,
            'request_size_bytes': request_size,
            'response_size_bytes': response_size
        }
        
        level = logging.DEBUG
        if status_code and status_code >= 400:
            level = logging.WARNING if status_code < 500 else logging.ERROR
        
        message = f"API {method} {url}"
        if status_code:
            message += f" -> {status_code}"
        
        self.log_with_context(logger, level, message, context, duration=duration)
    
    def log_download_progress(self, logger: logging.Logger, video_title: str, 
                            bytes_downloaded: int, total_bytes: Optional[int] = None,
                            speed_bps: Optional[float] = None):
        """Log download progress information.
        
        Args:
            logger: Logger instance.
            video_title: Title of the video being downloaded.
            bytes_downloaded: Number of bytes downloaded.
            total_bytes: Total bytes to download.
            speed_bps: Download speed in bytes per second.
        """
        context = {
            'video_title': video_title,
            'bytes_downloaded': bytes_downloaded,
            'total_bytes': total_bytes,
            'speed_bps': speed_bps
        }
        
        if total_bytes:
            progress_pct = (bytes_downloaded / total_bytes) * 100
            context['progress_percent'] = progress_pct
            message = f"Download progress: {video_title} - {progress_pct:.1f}%"
        else:
            message = f"Download progress: {video_title} - {bytes_downloaded} bytes"
        
        self.log_with_context(logger, logging.DEBUG, message, context)
    
    def log_parsing_error(self, logger: logging.Logger, url: str, error: Exception,
                         html_content: Optional[str] = None, json_content: Optional[Dict] = None):
        """Log parsing errors with detailed context for debugging.
        
        Args:
            logger: Logger instance.
            url: URL that was being parsed.
            error: The parsing error that occurred.
            html_content: HTML content that failed to parse (truncated for logging).
            json_content: JSON content that failed to parse.
        """
        context = {
            'parsing_url': url,
            'error_type': type(error).__name__,
            'error_message': str(error)
        }
        
        # Add content samples for debugging (truncated)
        if html_content:
            context['html_sample'] = html_content[:500] + "..." if len(html_content) > 500 else html_content
        
        if json_content:
            context['json_content'] = json_content
        
        message = f"Parsing failed for {url}: {error}"
        
        self.log_with_context(logger, logging.ERROR, message, context)
    
    def log_authentication_event(self, logger: logging.Logger, username: str, 
                                success: bool, error: Optional[str] = None):
        """Log authentication events.
        
        Args:
            logger: Logger instance.
            username: Username attempting authentication.
            success: Whether authentication was successful.
            error: Error message if authentication failed.
        """
        context = {
            'username': username,
            'auth_success': success,
            'auth_error': error
        }
        
        if success:
            message = f"Authentication successful for {username}"
            level = logging.INFO
        else:
            message = f"Authentication failed for {username}: {error}"
            level = logging.WARNING
        
        self.log_with_context(logger, level, message, context)
    
    @contextmanager
    def performance_timer(self, operation_name: str, logger: Optional[logging.Logger] = None):
        """Context manager for measuring and logging operation performance.
        
        Args:
            operation_name: Name of the operation being timed.
            logger: Logger to use (defaults to performance logger).
            
        Yields:
            PerformanceTimer instance.
        """
        if logger is None:
            logger = logging.getLogger('edx_downloader.performance')
        
        timer = PerformanceTimer(operation_name, logger)
        self.performance_timers[operation_name] = timer
        
        try:
            with timer:
                yield timer
        finally:
            if operation_name in self.performance_timers:
                del self.performance_timers[operation_name]
    
    def log_system_info(self, logger: logging.Logger):
        """Log system information for debugging purposes.
        
        Args:
            logger: Logger instance.
        """
        import platform
        
        context = {
            'python_version': platform.python_version(),
            'platform': platform.platform(),
        }
        
        try:
            import psutil
            context.update({
                'cpu_count': psutil.cpu_count(),
                'memory_gb': round(psutil.virtual_memory().total / (1024**3), 2),
                'disk_free_gb': round(psutil.disk_usage('.').free / (1024**3), 2)
            })
        except ImportError:
            context.update({
                'cpu_count': 'unknown',
                'memory_gb': 'unknown',
                'disk_free_gb': 'unknown'
            })
        
        message = f"System info: Python {context['python_version']} on {context['platform']}"
        
        self.log_with_context(logger, logging.INFO, message, context)
    
    def configure_debug_mode(self, enabled: bool = True):
        """Enable or disable debug mode with verbose logging.
        
        Args:
            enabled: Whether to enable debug mode.
        """
        level = logging.DEBUG if enabled else logging.INFO
        
        # Update console handler level
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
                handler.setLevel(level)
                break
    
    def get_log_files(self) -> Dict[str, Path]:
        """Get paths to all log files.
        
        Returns:
            Dictionary mapping log types to file paths.
        """
        log_dir = Path(self.config.cache_directory) / "logs"
        
        return {
            'main': log_dir / "edx_downloader.log",
            'errors': log_dir / "errors.log",
            'debug': log_dir / "debug.jsonl",
            'performance': log_dir / "performance.log"
        }


# Global logger instance
_logger_instance: Optional[EdxDownloaderLogger] = None


def setup_logging(config: AppConfig) -> EdxDownloaderLogger:
    """Set up global logging configuration.
    
    Args:
        config: Application configuration.
        
    Returns:
        Configured logger instance.
    """
    global _logger_instance
    _logger_instance = EdxDownloaderLogger(config)
    return _logger_instance


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.
    
    Args:
        name: Logger name (usually __name__).
        
    Returns:
        Configured logger instance.
    """
    if _logger_instance is None:
        # Fallback to basic logging if not configured
        return logging.getLogger(name)
    
    return _logger_instance.get_logger(name)


def log_with_context(logger: logging.Logger, level: int, message: str, 
                    context: Optional[Dict[str, Any]] = None, **kwargs):
    """Log a message with additional context information.
    
    Args:
        logger: Logger instance to use.
        level: Logging level.
        message: Log message.
        context: Additional context information.
        **kwargs: Additional keyword arguments.
    """
    if _logger_instance:
        _logger_instance.log_with_context(logger, level, message, context, **kwargs)
    else:
        logger.log(level, message)


@contextmanager
def performance_timer(operation_name: str, logger: Optional[logging.Logger] = None):
    """Context manager for measuring and logging operation performance.
    
    Args:
        operation_name: Name of the operation being timed.
        logger: Logger to use.
        
    Yields:
        PerformanceTimer instance.
    """
    if _logger_instance:
        with _logger_instance.performance_timer(operation_name, logger) as timer:
            yield timer
    else:
        # Fallback timer without logging
        timer = PerformanceTimer(operation_name, logger or logging.getLogger(), logging.DEBUG)
        with timer:
            yield timer