"""Command-line interface for EDX downloader."""

import asyncio
import sys
import logging
from pathlib import Path
from typing import Optional, List
import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.text import Text

from . import __version__
from .app import EdxDownloaderApp, create_app, download_course_simple, get_course_info_simple
from .config import ConfigManager
from .auth import AuthenticationManager
from .api_client import EdxApiClient
from .course_manager import CourseManager
from .download_manager import DownloadManager
from .models import DownloadOptions, CourseInfo, VideoInfo
from .exceptions import (
    AuthenticationError, CourseNotFoundError, EnrollmentRequiredError,
    ConfigurationError, DownloadError, EdxDownloaderError
)

console = Console()


class ProgressReporter:
    """Handles progress reporting for downloads."""
    
    def __init__(self):
        self.progress = None
        self.course_task = None
        self.video_tasks = {}
    
    def start_course_progress(self, course_title: str, total_videos: int):
        """Start progress tracking for course download."""
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console
        )
        self.progress.start()
        
        self.course_task = self.progress.add_task(
            f"Downloading {course_title}",
            total=total_videos
        )
    
    def update_progress(self, course_progress):
        """Update progress display."""
        if self.progress and self.course_task is not None:
            self.progress.update(
                self.course_task,
                completed=course_progress.completed_videos,
                description=f"Downloaded {course_progress.completed_videos}/{course_progress.total_videos} videos"
            )
    
    def finish_progress(self):
        """Finish progress tracking."""
        if self.progress:
            self.progress.stop()


def setup_logging(verbose: bool = False, config_manager: Optional[ConfigManager] = None):
    """Setup logging configuration."""
    from .logging_config import setup_logging as setup_comprehensive_logging
    
    if config_manager:
        # Use comprehensive logging system
        logger_instance = setup_comprehensive_logging(config_manager.config)
        logger_instance.configure_debug_mode(verbose)
        
        # Log system information for debugging
        if verbose:
            main_logger = logger_instance.get_logger(__name__)
            logger_instance.log_system_info(main_logger)
    else:
        # Fallback to basic logging
        level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('edx_downloader.log'),
                logging.StreamHandler() if verbose else logging.NullHandler()
            ]
        )


def handle_authentication(config_manager: ConfigManager, email: Optional[str], password: Optional[str], silent: bool = False) -> AuthenticationManager:
    """Handle user authentication with seamless credential management."""
    auth_manager = AuthenticationManager(config_manager.credential_manager)
    
    # Get credentials with smart defaults
    if not email:
        stored_usernames = config_manager.list_stored_usernames()
        if len(stored_usernames) == 1:
            # Auto-select if only one account stored
            email = stored_usernames[0]
            if not silent:
                console.print(f"[dim]Using stored account: {email}[/dim]")
        elif len(stored_usernames) > 1:
            if not silent:
                console.print("\n[bold blue]Select account:[/bold blue]")
                for i, username in enumerate(stored_usernames, 1):
                    console.print(f"  {i}. {username}")
            
            choice = Prompt.ask(
                "Account",
                choices=[str(i) for i in range(1, len(stored_usernames) + 1)] + ["new"],
                default="1"
            )
            
            if choice != "new":
                email = stored_usernames[int(choice) - 1]
            else:
                email = Prompt.ask("EDX email")
        else:
            email = Prompt.ask("EDX email")
    
    # Auto-use stored password without prompting
    if not password:
        stored_password = config_manager.get_credentials(email)
        if stored_password:
            password = stored_password
            if not silent:
                console.print(f"[dim]Using stored credentials for {email}[/dim]")
        else:
            password = Prompt.ask("EDX password", password=True)
            # Auto-store new credentials
            if Confirm.ask("Save credentials for future use?", default=True):
                config_manager.store_credentials(email, password)
    
    # Authenticate
    with console.status("[bold green]Authenticating..."):
        try:
            auth_session = auth_manager.authenticate(email, password)
            if not silent:
                console.print(f"[green]✓[/green] Successfully authenticated as {email}")
            return auth_manager
        except AuthenticationError as e:
            console.print(f"[red]✗[/red] Authentication failed: {e}")
            sys.exit(1)


async def download_course_videos(course_url: str, options: DownloadOptions, username: str, password: Optional[str] = None, auto_mode: bool = False, config_file: Optional[str] = None):
    """Download videos from a course using the integrated app."""
    progress_reporter = ProgressReporter()
    
    def progress_callback(course_progress):
        """Progress callback for the app."""
        progress_reporter.update_progress(course_progress)
    
    try:
        # Use the integrated app for downloading
        async with create_app(config_file) as app:
            # Initialize the app
            with console.status("[bold green]Initializing application..."):
                await app.initialize(username, password)
            
            # Get course info first for display
            with console.status("[bold blue]Getting course information..."):
                course_info = await app.get_course_info(course_url)
                console.print(f"[green]✓[/green] Found course: {course_info.title}")
            
            # Get video list for preview
            if not auto_mode:
                with console.status("[bold blue]Getting video list..."):
                    all_videos = await app.list_course_videos(course_url)
                    console.print(f"[green]✓[/green] Found {len(all_videos)} videos to download")
                
                if not all_videos:
                    console.print("[yellow]No videos found in course[/yellow]")
                    return
                
                # Show video summary
                display_video_summary(all_videos, course_info)
                
                if not Confirm.ask(f"\nProceed with downloading {len(all_videos)} videos?", default=True):
                    console.print("Download cancelled")
                    return
            else:
                console.print(f"[dim]Starting auto-download...[/dim]")
            
            # Start progress tracking
            progress_reporter.start_course_progress(course_info.title, 0)  # Will be updated by callback
            
            # Download the course
            result = await app.download_course(course_url, options, progress_callback)
            
            progress_reporter.finish_progress()
            
            # Show final results
            if result['success']:
                display_download_results_from_dict(result)
            else:
                console.print(f"[red]✗[/red] Download failed: {result.get('message', 'Unknown error')}")
    
    except (CourseNotFoundError, EnrollmentRequiredError, EdxDownloaderError) as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Unexpected error: {e}")
        if hasattr(e, '__traceback__'):
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        progress_reporter.finish_progress()


def display_video_summary(videos: List[VideoInfo], course_info: CourseInfo):
    """Display summary of videos to be downloaded."""
    table = Table(title=f"Videos in {course_info.title}")
    table.add_column("Title", style="cyan", no_wrap=False)
    table.add_column("Quality", style="magenta")
    table.add_column("Size", style="green")
    table.add_column("Duration", style="blue")
    
    total_size = 0
    for video in videos[:10]:  # Show first 10 videos
        size_str = f"{video.size_mb:.1f} MB" if video.size_mb else "Unknown"
        duration_str = video.duration_formatted or "Unknown"
        
        table.add_row(
            video.title[:50] + "..." if len(video.title) > 50 else video.title,
            video.quality,
            size_str,
            duration_str
        )
        
        if video.size:
            total_size += video.size
    
    if len(videos) > 10:
        table.add_row(f"... and {len(videos) - 10} more videos", "", "", "")
    
    console.print(table)
    
    if total_size > 0:
        total_gb = total_size / (1024**3)
        console.print(f"\n[bold]Total estimated size: {total_gb:.2f} GB[/bold]")


def display_download_results(course_progress):
    """Display final download results."""
    panel_content = []
    panel_content.append(f"Course: {course_progress.course_title}")
    panel_content.append(f"Total videos: {course_progress.total_videos}")
    panel_content.append(f"Successfully downloaded: {course_progress.completed_videos}")
    panel_content.append(f"Failed downloads: {course_progress.failed_videos}")
    panel_content.append(f"Success rate: {course_progress.success_rate:.1f}%")
    
    if course_progress.total_size > 0:
        downloaded_gb = course_progress.downloaded_size / (1024**3)
        panel_content.append(f"Downloaded: {downloaded_gb:.2f} GB")
    
    style = "green" if course_progress.success_rate > 90 else "yellow" if course_progress.success_rate > 50 else "red"
    
    console.print(Panel(
        "\n".join(panel_content),
        title="Download Complete",
        border_style=style
    ))


def display_download_results_from_dict(result: dict):
    """Display final download results from result dictionary."""
    panel_content = []
    panel_content.append(f"Course: {result.get('course_info', {}).get('title', 'Unknown')}")
    panel_content.append(f"Total videos: {result.get('videos_found', 0)}")
    panel_content.append(f"Successfully downloaded: {result.get('videos_downloaded', 0)}")
    panel_content.append(f"Failed downloads: {result.get('videos_failed', 0)}")
    panel_content.append(f"Success rate: {result.get('success_rate', 0):.1f}%")
    
    if result.get('downloaded_size_gb', 0) > 0:
        panel_content.append(f"Downloaded: {result['downloaded_size_gb']:.2f} GB")
    
    success_rate = result.get('success_rate', 0)
    style = "green" if success_rate > 90 else "yellow" if success_rate > 50 else "red"
    
    console.print(Panel(
        "\n".join(panel_content),
        title="Download Complete",
        border_style=style
    ))


@click.group()
@click.version_option(version=__version__)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--config-file", help="Path to configuration file")
@click.pass_context
def cli(ctx, verbose: bool, config_file: Optional[str]):
    """Modern EDX course video downloader."""
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['config_file'] = config_file
    
    # Initialize configuration first
    try:
        config_manager = ConfigManager(config_file)
        ctx.obj['config_manager'] = config_manager
        
        # Setup comprehensive logging with config
        setup_logging(verbose, config_manager)
        
    except ConfigurationError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("course_url", required=False)
@click.option("--email", "-e", help="EDX account email")
@click.option("--password", "-p", help="EDX account password")
@click.option("--output-dir", "-o", help="Output directory for downloads")
@click.option("--quality", "-q", 
              type=click.Choice(["highest", "high", "medium", "low", "720p", "480p", "360p", "240p"]),
              help="Video quality preference")
@click.option("--concurrent", "-c", type=int, help="Number of concurrent downloads")
@click.option("--no-resume", is_flag=True, help="Disable resume functionality")
@click.option("--no-organize", is_flag=True, help="Don't organize files by section")
@click.option("--auto", "-a", is_flag=True, help="Auto-download without confirmations")
@click.option("--fast", "-f", is_flag=True, help="Fast mode: auto + highest concurrent + no confirmations")
@click.pass_context
def download(ctx, course_url: Optional[str], email: Optional[str], password: Optional[str], 
             output_dir: Optional[str], quality: Optional[str], concurrent: Optional[int],
             no_resume: bool, no_organize: bool, auto: bool, fast: bool):
    """Download videos from an EDX course."""
    config_manager = ctx.obj['config_manager']
    
    # Interactive course URL input if not provided
    if not course_url:
        console.print("[bold blue]EDX Course Downloader[/bold blue]")
        course_url = Prompt.ask("Enter course URL")
    
    # Handle fast mode
    if fast:
        auto = True
        concurrent = concurrent or 8  # Higher concurrency for fast mode
        quality = quality or "highest"
    
    # Create download options with smart defaults
    options = DownloadOptions(
        output_directory=output_dir or config_manager.config.default_output_dir,
        quality_preference=quality or config_manager.config.video_quality_preference,
        concurrent_downloads=concurrent or config_manager.config.max_concurrent_downloads,
        resume_enabled=not no_resume,
        organize_by_section=not no_organize
    )
    
    # Only show details if not in auto mode
    if not auto:
        console.print(f"[bold blue]EDX Downloader v{__version__}[/bold blue]")
        console.print(f"Course URL: {course_url}")
        console.print(f"Output directory: {options.output_directory}")
        console.print(f"Quality preference: {options.quality_preference}")
        console.print(f"Concurrent downloads: {options.concurrent_downloads}")
        console.print()
    
    # Get credentials for the integrated app
    if not email:
        stored_usernames = config_manager.list_stored_usernames()
        if len(stored_usernames) == 1:
            email = stored_usernames[0]
            if not auto:
                console.print(f"[dim]Using stored account: {email}[/dim]")
        elif len(stored_usernames) > 1:
            if not auto:
                console.print("\n[bold blue]Select account:[/bold blue]")
                for i, username in enumerate(stored_usernames, 1):
                    console.print(f"  {i}. {username}")
            
            choice = Prompt.ask(
                "Account",
                choices=[str(i) for i in range(1, len(stored_usernames) + 1)] + ["new"],
                default="1"
            )
            
            if choice != "new":
                email = stored_usernames[int(choice) - 1]
            else:
                email = Prompt.ask("EDX email")
        else:
            email = Prompt.ask("EDX email")
    
    # Get password if not provided
    if not password:
        stored_password = config_manager.get_credentials(email)
        if stored_password:
            password = stored_password
            if not auto:
                console.print(f"[dim]Using stored credentials for {email}[/dim]")
        else:
            password = Prompt.ask("EDX password", password=True)
            # Auto-store new credentials
            if Confirm.ask("Save credentials for future use?", default=True):
                config_manager.store_credentials(email, password)
    
    # Run download with integrated app
    asyncio.run(download_course_videos(course_url, options, email, password, auto, ctx.obj['config_file']))


@cli.command()
@click.pass_context
def config(ctx):
    """Show current configuration."""
    config_manager = ctx.obj['config_manager']
    
    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    config_dict = {
        "Default Output Directory": config_manager.config.default_output_dir,
        "Max Concurrent Downloads": str(config_manager.config.max_concurrent_downloads),
        "Video Quality Preference": config_manager.config.video_quality_preference,
        "Rate Limit Delay": f"{config_manager.config.rate_limit_delay}s",
        "Retry Attempts": str(config_manager.config.retry_attempts),
        "Cache Directory": config_manager.config.cache_directory,
        "Credentials File": config_manager.config.credentials_file
    }
    
    for setting, value in config_dict.items():
        table.add_row(setting, value)
    
    console.print(table)


@cli.command()
@click.pass_context
def accounts(ctx):
    """Manage stored accounts."""
    config_manager = ctx.obj['config_manager']
    
    stored_usernames = config_manager.list_stored_usernames()
    
    if not stored_usernames:
        console.print("[yellow]No stored accounts found[/yellow]")
        return
    
    table = Table(title="Stored Accounts")
    table.add_column("Email", style="cyan")
    
    for username in stored_usernames:
        table.add_row(username)
    
    console.print(table)


@cli.command()
@click.argument("email")
@click.pass_context
def add_account(ctx, email: str):
    """Add a new account."""
    config_manager = ctx.obj['config_manager']
    
    password = Prompt.ask(f"Password for {email}", password=True)
    
    try:
        config_manager.store_credentials(email, password)
        console.print(f"[green]✓[/green] Account {email} added successfully")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to add account: {e}")


@cli.command()
@click.argument("email")
@click.pass_context
def remove_account(ctx, email: str):
    """Remove a stored account."""
    config_manager = ctx.obj['config_manager']
    
    if Confirm.ask(f"Remove account {email}?"):
        try:
            config_manager.delete_credentials(email)
            console.print(f"[green]✓[/green] Account {email} removed successfully")
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to remove account: {e}")


@cli.command()
@click.argument("course_url", required=False)
@click.option("--email", help="EDX account email")
@click.option("--password", help="EDX account password")
@click.pass_context
def info(ctx, course_url: Optional[str], email: Optional[str], password: Optional[str]):
    """Get information about a course without downloading."""
    
    # Interactive course URL input if not provided
    if not course_url:
        course_url = Prompt.ask("Enter course URL")
    config_manager = ctx.obj['config_manager']
    
    # Get credentials
    if not email:
        stored_usernames = config_manager.list_stored_usernames()
        if len(stored_usernames) == 1:
            email = stored_usernames[0]
            console.print(f"[dim]Using stored account: {email}[/dim]")
        elif len(stored_usernames) > 1:
            console.print("\n[bold blue]Select account:[/bold blue]")
            for i, username in enumerate(stored_usernames, 1):
                console.print(f"  {i}. {username}")
            
            choice = Prompt.ask(
                "Account",
                choices=[str(i) for i in range(1, len(stored_usernames) + 1)] + ["new"],
                default="1"
            )
            
            if choice != "new":
                email = stored_usernames[int(choice) - 1]
            else:
                email = Prompt.ask("EDX email")
        else:
            email = Prompt.ask("EDX email")
    
    if not password:
        stored_password = config_manager.get_credentials(email)
        if stored_password:
            password = stored_password
            console.print(f"[dim]Using stored credentials for {email}[/dim]")
        else:
            password = Prompt.ask("EDX password", password=True)
    
    async def get_course_info():
        try:
            async with create_app(ctx.obj['config_file']) as app:
                await app.initialize(email, password)
                
                with console.status("[bold blue]Getting course information..."):
                    course_info = await app.get_course_info(course_url)
                
                # Display course information
                table = Table(title="Course Information")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")
                
                table.add_row("Title", course_info.title)
                table.add_row("Course ID", course_info.id)
                table.add_row("URL", course_info.url)
                table.add_row("Enrollment Status", course_info.enrollment_status)
                table.add_row("Access Level", course_info.access_level)
                table.add_row("Accessible", "Yes" if course_info.is_accessible else "No")
                
                console.print(table)
                
                # Get video count
                try:
                    with console.status("[bold blue]Counting videos..."):
                        videos = await app.list_course_videos(course_url)
                        console.print(f"\n[bold]Total videos found: {len(videos)}[/bold]")
                        
                        if videos:
                            total_size = sum(v.size or 0 for v in videos)
                            if total_size > 0:
                                total_gb = total_size / (1024**3)
                                console.print(f"[bold]Estimated total size: {total_gb:.2f} GB[/bold]")
                except Exception as e:
                    console.print(f"[yellow]Could not count videos: {e}[/yellow]")
        
        except Exception as e:
            console.print(f"[red]✗[/red] Error getting course info: {e}")
    
    asyncio.run(get_course_info())


@cli.command()
@click.argument("course_url")
@click.option("--email", "-e", help="EDX account email")
@click.option("--output-dir", "-o", help="Output directory for downloads")
@click.option("--quality", "-q", default="highest", help="Video quality preference")
@click.pass_context
def quick(ctx, course_url: str, email: Optional[str], output_dir: Optional[str], quality: str):
    """Quick download with minimal prompts (alias: q)."""
    config_manager = ctx.obj['config_manager']
    
    # Use fast mode settings
    options = DownloadOptions(
        output_directory=output_dir or config_manager.config.default_output_dir,
        quality_preference=quality,
        concurrent_downloads=8,  # High concurrency for quick mode
        resume_enabled=True,
        organize_by_section=True
    )
    
    console.print(f"[bold blue]Quick Download Mode[/bold blue]")
    console.print(f"[dim]Course: {course_url}[/dim]")
    console.print(f"[dim]Output: {options.output_directory}[/dim]")
    console.print(f"[dim]Quality: {quality}[/dim]")
    
    # Handle authentication (silent mode)
    auth_manager = handle_authentication(config_manager, email, None, silent=True)
    
    # Run download in auto mode
    asyncio.run(download_course_videos(course_url, options, auth_manager, auto_mode=True))


@cli.command()
@click.argument("urls_file", type=click.Path(exists=True))
@click.option("--email", "-e", help="EDX account email")
@click.option("--output-dir", "-o", help="Output directory for downloads")
@click.option("--quality", "-q", default="highest", help="Video quality preference")
@click.option("--concurrent-courses", default=2, help="Number of courses to download concurrently")
@click.pass_context
def batch(ctx, urls_file: str, email: Optional[str], output_dir: Optional[str], 
          quality: str, concurrent_courses: int):
    """Download multiple courses from a file containing URLs."""
    config_manager = ctx.obj['config_manager']
    
    # Read URLs from file
    try:
        with open(urls_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        console.print(f"[red]✗[/red] Error reading URLs file: {e}")
        return
    
    if not urls:
        console.print("[yellow]No URLs found in file[/yellow]")
        return
    
    console.print(f"[bold blue]Batch Download Mode[/bold blue]")
    console.print(f"Found {len(urls)} courses to download")
    
    # Handle authentication once
    auth_manager = handle_authentication(config_manager, email, None, silent=True)
    
    # Create download options
    options = DownloadOptions(
        output_directory=output_dir or config_manager.config.default_output_dir,
        quality_preference=quality,
        concurrent_downloads=4,  # Lower per-course concurrency for batch
        resume_enabled=True,
        organize_by_section=True
    )
    
    async def download_all_courses():
        """Download all courses with limited concurrency."""
        semaphore = asyncio.Semaphore(concurrent_courses)
        
        async def download_single_course(url, index):
            async with semaphore:
                console.print(f"[dim]Starting course {index + 1}/{len(urls)}: {url}[/dim]")
                try:
                    await download_course_videos(url, options, auth_manager, auto_mode=True)
                    console.print(f"[green]✓[/green] Completed course {index + 1}: {url}")
                except Exception as e:
                    console.print(f"[red]✗[/red] Failed course {index + 1}: {url} - {e}")
        
        tasks = [download_single_course(url, i) for i, url in enumerate(urls)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        console.print(f"[bold green]Batch download completed![/bold green]")
    
    asyncio.run(download_all_courses())


@cli.command()
@click.pass_context
def setup(ctx):
    """Interactive setup wizard for first-time users."""
    config_manager = ctx.obj['config_manager']
    
    console.print(Panel(
        "[bold blue]Welcome to EDX Downloader![/bold blue]\n\n"
        "This wizard will help you set up the downloader for first use.",
        title="Setup Wizard"
    ))
    
    # Check for migration first
    from .migration import LegacyConfigMigrator
    migrator = LegacyConfigMigrator(config_manager)
    
    if migrator.needs_migration():
        console.print("\n[yellow]Legacy configuration files detected![/yellow]")
        if Confirm.ask("Would you like to migrate them first?", default=True):
            try:
                results = migrator.migrate_all(backup=True)
                console.print(f"[green]✓[/green] Migrated {results['migrated_accounts']} accounts and {results['migrated_configs']} configs")
                if results['warnings']:
                    for warning in results['warnings']:
                        console.print(f"[yellow]⚠[/yellow] {warning}")
            except Exception as e:
                console.print(f"[red]✗[/red] Migration failed: {e}")
    
    # Step 1: Add account
    console.print("\n[bold]Step 1: Add your EDX account[/bold]")
    email = Prompt.ask("EDX email address")
    password = Prompt.ask("EDX password", password=True)
    
    try:
        config_manager.store_credentials(email, password)
        console.print(f"[green]✓[/green] Account {email} saved")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to save account: {e}")
        return
    
    # Step 2: Set preferences
    console.print("\n[bold]Step 2: Set your preferences[/bold]")
    
    output_dir = Prompt.ask(
        "Default download directory", 
        default=config_manager.config.default_output_dir
    )
    
    quality = Prompt.ask(
        "Default video quality",
        choices=["highest", "high", "medium", "low", "720p", "480p"],
        default="highest"
    )
    
    concurrent = int(Prompt.ask(
        "Concurrent downloads (1-10)",
        default=str(config_manager.config.max_concurrent_downloads)
    ))
    
    # Update configuration
    try:
        updated_config = config_manager.update_config(
            default_output_dir=output_dir,
            video_quality_preference=quality,
            max_concurrent_downloads=concurrent
        )
        config_manager.save_config(updated_config)
        console.print("[green]✓[/green] Preferences saved")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to save preferences: {e}")
        return
    
    # Step 3: Test download (optional)
    console.print("\n[bold]Step 3: Test setup (optional)[/bold]")
    if Confirm.ask("Would you like to test with a sample course?", default=False):
        test_url = Prompt.ask("Enter a course URL to test")
        console.print("\n[dim]Running test download...[/dim]")
        
        # Run info command to test
        try:
            auth_manager = AuthenticationManager(config_manager.credential_manager)
            auth_session = auth_manager.authenticate(email, password)
            console.print("[green]✓[/green] Authentication test successful")
        except Exception as e:
            console.print(f"[red]✗[/red] Authentication test failed: {e}")
    
    console.print(Panel(
        "[bold green]Setup completed successfully![/bold green]\n\n"
        "You can now use:\n"
        "• [cyan]edxdl download <course-url>[/cyan] - Download a course\n"
        "• [cyan]edxdl quick <course-url>[/cyan] - Quick download\n"
        "• [cyan]edxdl info <course-url>[/cyan] - Get course info\n"
        "• [cyan]edxdl --help[/cyan] - See all commands",
        title="Setup Complete"
    ))


@cli.command()
@click.option("--backup/--no-backup", default=True, help="Create backups of original files")
@click.option("--interactive/--auto", default=True, help="Run in interactive mode")
@click.pass_context
def migrate(ctx, backup: bool, interactive: bool):
    """Migrate legacy configuration files and credentials."""
    from .migration import LegacyConfigMigrator, run_migration_wizard
    
    config_manager = ctx.obj['config_manager']
    
    if interactive:
        # Run interactive migration wizard
        results = run_migration_wizard(config_manager)
        
        if not results.get('migration_needed'):
            console.print("[green]No legacy files found that need migration.[/green]")
            return
        
        if results.get('error'):
            console.print(f"[red]Migration failed: {results['error']}[/red]")
            sys.exit(1)
        
        if not results.get('migration_performed'):
            console.print("[yellow]Migration cancelled or not performed.[/yellow]")
            return
    
    else:
        # Run automatic migration
        migrator = LegacyConfigMigrator(config_manager)
        
        if not migrator.needs_migration():
            console.print("[green]No legacy files found that need migration.[/green]")
            return
        
        console.print("[blue]Running automatic migration...[/blue]")
        
        try:
            results = migrator.migrate_all(backup=backup)
            
            console.print(f"[green]✓[/green] Migration completed successfully!")
            console.print(f"Migrated accounts: {results['migrated_accounts']}")
            console.print(f"Migrated configs: {results['migrated_configs']}")
            
            if results['backup_files']:
                console.print(f"Backup files created: {len(results['backup_files'])}")
                for backup_file in results['backup_files']:
                    console.print(f"  - {backup_file}")
            
            if results['warnings']:
                console.print(f"\n[yellow]Warnings:[/yellow]")
                for warning in results['warnings']:
                    console.print(f"  - {warning}")
        
        except Exception as e:
            console.print(f"[red]✗[/red] Migration failed: {e}")
            sys.exit(1)


@cli.command()
@click.argument("export_path", type=click.Path())
@click.option("--include-credentials", is_flag=True, help="Include stored credentials in export")
@click.option("--format", type=click.Choice(["json", "yaml"]), default="json", help="Export format")
@click.pass_context
def export_config(ctx, export_path: str, include_credentials: bool, format: str):
    """Export current configuration to file."""
    from .migration import ConfigurationExporter
    
    config_manager = ctx.obj['config_manager']
    exporter = ConfigurationExporter(config_manager)
    
    try:
        with console.status("[bold blue]Exporting configuration..."):
            results = exporter.export_configuration(
                export_path, 
                include_credentials=include_credentials,
                format=format
            )
        
        console.print(f"[green]✓[/green] Configuration exported successfully!")
        console.print(f"Export path: {results['export_path']}")
        console.print(f"Format: {results['format']}")
        console.print(f"File size: {results['file_size']} bytes")
        
        if include_credentials:
            console.print("[yellow]⚠[/yellow] Export includes sensitive credentials. Keep the file secure!")
    
    except Exception as e:
        console.print(f"[red]✗[/red] Export failed: {e}")
        sys.exit(1)


@cli.command()
@click.argument("import_path", type=click.Path(exists=True))
@click.option("--merge/--replace", default=True, help="Merge with existing config or replace")
@click.option("--import-credentials", is_flag=True, help="Import credentials from file")
@click.pass_context
def import_config(ctx, import_path: str, merge: bool, import_credentials: bool):
    """Import configuration from file."""
    from .migration import ConfigurationExporter
    
    config_manager = ctx.obj['config_manager']
    exporter = ConfigurationExporter(config_manager)
    
    try:
        with console.status("[bold blue]Importing configuration..."):
            results = exporter.import_configuration(
                import_path,
                merge=merge,
                import_credentials=import_credentials
            )
        
        console.print(f"[green]✓[/green] Configuration imported successfully!")
        
        if results['config_imported']:
            console.print("Configuration settings imported")
        
        if results['credentials_imported'] > 0:
            console.print(f"Imported {results['credentials_imported']} credential(s)")
        
        if results['warnings']:
            console.print(f"\n[yellow]Warnings:[/yellow]")
            for warning in results['warnings']:
                console.print(f"  - {warning}")
    
    except Exception as e:
        console.print(f"[red]✗[/red] Import failed: {e}")
        sys.exit(1)


# Add command aliases for better UX
@cli.command(name="q")
@click.argument("course_url")
@click.option("--email", "-e", help="EDX account email")
@click.option("--output-dir", "-o", help="Output directory for downloads")
@click.option("--quality", "-q", default="highest", help="Video quality preference")
@click.pass_context
def quick_alias(ctx, course_url: str, email: Optional[str], output_dir: Optional[str], quality: str):
    """Quick download (alias for 'quick' command)."""
    ctx.invoke(quick, course_url=course_url, email=email, output_dir=output_dir, quality=quality)


@cli.command(name="dl")
@click.argument("course_url", required=False)
@click.option("--email", "-e", help="EDX account email")
@click.option("--password", "-p", help="EDX account password")
@click.option("--output-dir", "-o", help="Output directory for downloads")
@click.option("--quality", "-q", 
              type=click.Choice(["highest", "high", "medium", "low", "720p", "480p", "360p", "240p"]),
              help="Video quality preference")
@click.option("--concurrent", "-c", type=int, help="Number of concurrent downloads")
@click.option("--auto", "-a", is_flag=True, help="Auto-download without confirmations")
@click.option("--fast", "-f", is_flag=True, help="Fast mode")
@click.pass_context
def download_alias(ctx, course_url: Optional[str], email: Optional[str], password: Optional[str], 
                  output_dir: Optional[str], quality: Optional[str], concurrent: Optional[int],
                  auto: bool, fast: bool):
    """Download (alias for 'download' command)."""
    ctx.invoke(download, course_url=course_url, email=email, password=password,
               output_dir=output_dir, quality=quality, concurrent=concurrent,
               no_resume=False, no_organize=False, auto=auto, fast=fast)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
