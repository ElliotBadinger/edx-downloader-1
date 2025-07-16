"""Tests for CLI interface."""

import pytest
from click.testing import CliRunner
from edx_downloader.cli import main
from edx_downloader import __version__


def test_cli_help():
    """Test CLI help output."""
    runner = CliRunner()
    result = runner.invoke(main, ['--help'])
    
    assert result.exit_code == 0
    assert 'Modern EDX course video downloader' in result.output
    assert '--course-url' in result.output
    assert '--email' in result.output
    assert '--password' in result.output
    assert '--output-dir' in result.output
    assert '--quality' in result.output
    assert '--concurrent' in result.output


def test_cli_version():
    """Test CLI version output."""
    runner = CliRunner()
    result = runner.invoke(main, ['--version'])
    
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_with_course_url():
    """Test CLI with course URL provided."""
    runner = CliRunner()
    result = runner.invoke(main, [
        '--course-url', 'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/'
    ])
    
    assert result.exit_code == 0
    assert f'EDX Downloader v{__version__}' in result.output
    assert 'modernized version - implementation in progress' in result.output
    assert 'Course URL: https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/' in result.output


def test_cli_with_all_options():
    """Test CLI with all options provided."""
    runner = CliRunner()
    result = runner.invoke(main, [
        '--course-url', 'https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/',
        '--email', 'test@example.com',
        '--password', 'testpass',
        '--output-dir', './test-downloads',
        '--quality', 'medium',
        '--concurrent', '5'
    ])
    
    assert result.exit_code == 0
    assert 'Course URL: https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/' in result.output
    assert 'Output directory: ./test-downloads' in result.output
    assert 'Quality preference: medium' in result.output
    assert 'Concurrent downloads: 5' in result.output


def test_cli_interactive_course_url():
    """Test CLI with interactive course URL input."""
    runner = CliRunner()
    result = runner.invoke(main, input='https://courses.edx.org/courses/course-v1:MITx+6.00.1x+2T2017/course/\n')
    
    assert result.exit_code == 0
    assert 'Course URL:' in result.output
    assert f'EDX Downloader v{__version__}' in result.output


def test_cli_quality_choices():
    """Test CLI quality parameter validation."""
    runner = CliRunner()
    
    # Test valid quality choice
    result = runner.invoke(main, [
        '--course-url', 'https://courses.edx.org/test',
        '--quality', 'highest'
    ])
    assert result.exit_code == 0
    assert 'Quality preference: highest' in result.output
    
    # Test invalid quality choice
    result = runner.invoke(main, [
        '--course-url', 'https://courses.edx.org/test',
        '--quality', 'invalid'
    ])
    assert result.exit_code != 0
    assert 'Invalid value for' in result.output


def test_cli_concurrent_parameter():
    """Test CLI concurrent downloads parameter."""
    runner = CliRunner()
    result = runner.invoke(main, [
        '--course-url', 'https://courses.edx.org/test',
        '--concurrent', '10'
    ])
    
    assert result.exit_code == 0
    assert 'Concurrent downloads: 10' in result.output


def test_cli_default_values():
    """Test CLI default parameter values."""
    runner = CliRunner()
    result = runner.invoke(main, [
        '--course-url', 'https://courses.edx.org/test'
    ])
    
    assert result.exit_code == 0
    assert 'Output directory: ./downloads' in result.output
    assert 'Quality preference: highest' in result.output
    assert 'Concurrent downloads: 3' in result.output