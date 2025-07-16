"""Command-line interface for EDX downloader."""

import click
from typing import Optional

from . import __version__


@click.command()
@click.version_option(version=__version__)
@click.option("--course-url", prompt="Course URL", help="EDX course URL to download")
@click.option("--email", help="EDX account email")
@click.option("--password", help="EDX account password")
@click.option(
    "--output-dir", default="./downloads", help="Output directory for downloads"
)
@click.option(
    "--quality",
    default="highest",
    type=click.Choice(["highest", "medium", "lowest"]),
    help="Video quality preference",
)
@click.option(
    "--concurrent", default=3, type=int, help="Number of concurrent downloads"
)
def main(
    course_url: str,
    email: Optional[str],
    password: Optional[str],
    output_dir: str,
    quality: str,
    concurrent: int,
) -> None:
    """Modern EDX course video downloader."""
    click.echo(f"EDX Downloader v{__version__}")
    click.echo("This is the modernized version - implementation in progress!")

    # TODO: Implement the actual download logic
    click.echo(f"Course URL: {course_url}")
    click.echo(f"Output directory: {output_dir}")
    click.echo(f"Quality preference: {quality}")
    click.echo(f"Concurrent downloads: {concurrent}")


if __name__ == "__main__":
    main()
