#!/usr/bin/env python3
"""
Tidal MDL - Console Interface
A Tidal media downloader for advanced users
"""

import sys
import os
from pathlib import Path
from typing import Optional, List

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TaskProgressColumn,
)
from rich.live import Live
from rich.layout import Layout
from rich.style import Style
from rich import box

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config, load_config, save_config
from src.auth import get_authenticated_session, delete_session
from src.search import (
    search, SearchType, SearchResult,
    display_search_results, display_tracks, display_albums,
    get_album_by_id, get_track_by_id, get_playlist_by_id,
    get_artist_by_id, get_video_by_id, parse_tidal_url,
)
from src.downloader import (
    DownloadQueue, DownloadTask, DownloadStatus,
    create_album_tasks, create_playlist_tasks,
    create_track_task, create_video_task,
    get_artist_albums, save_album_art,
)
from src.logger import logger

console = Console()

# ASCII Art Banner
BANNER = """
╔════════════════════════════════════════════════════════════╗
║  ████████╗██╗██████╗  █████╗ ██╗       ███╗   ███╗██████╗ ██╗    ║
║  ╚══██╔══╝██║██╔══██╗██╔══██╗██║       ████╗ ████║██╔══██╗██║    ║
║     ██║   ██║██║  ██║███████║██║       ██╔████╔██║██║  ██║██║    ║
║     ██║   ██║██║  ██║██╔══██║██║       ██║╚██╔╝██║██║  ██║██║    ║
║     ██║   ██║██████╔╝██║  ██║███████╗  ██║ ╚═╝ ██║██████╔╝███████╗║
║     ╚═╝   ╚═╝╚═════╝ ╚═╝  ╚═╝╚══════╝  ╚═╝     ╚═╝╚═════╝ ╚══════╝║
║                                                                    ║
║                         Tidal MDL                                 ║
╚════════════════════════════════════════════════════════════╝
"""


def show_banner():
    """Display the application banner"""
    console.print(BANNER, style="bold cyan")


def show_status(config: Config, queue: Optional[DownloadQueue] = None):
    """Show current status and configuration"""
    table = Table(title="Current Status", box=box.ROUNDED)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Download Quality", str(config.download_quality.value))
    table.add_row("Download Folder", str(config.download_folder.absolute()))
    table.add_row("Max Concurrent Downloads", str(config.max_concurrent_downloads))
    table.add_row("Rate Limit Delay", f"{config.rate_limit_delay}s")
    table.add_row("Embed Album Art", "Yes" if config.embed_album_art else "No")
    table.add_row("Skip Existing", "Yes" if config.skip_existing else "No")
    
    if queue:
        status = queue.get_status()
        table.add_row("─" * 20, "─" * 20)
        table.add_row("Queued Downloads", str(status["queued"]))
        table.add_row("Active Downloads", str(status["downloading"]))
        table.add_row("Completed", str(status["completed"]))
        table.add_row("Failed", str(status["failed"]))
    
    console.print(table)


def interactive_mode(config: Config, session):
    """Run the interactive console mode"""
    queue = DownloadQueue(config, session)
    
    # Start background download workers
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    
    show_help()
    
    while True:
        try:
            console.print()
            command = console.input("[bold green]tidal>[/bold green] ").strip()
            
            if not command:
                continue
            
            parts = command.split(maxsplit=1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            if cmd in ("q", "quit", "exit"):
                if queue.get_status()["queued"] > 0 or queue.get_status()["downloading"] > 0:
                    if not click.confirm("Downloads in progress. Are you sure you want to quit?"):
                        continue
                queue.stop_workers()
                console.print("[dim]Goodbye! 👋[/dim]")
                break
            
            elif cmd in ("h", "help", "?"):
                show_help()
            
            elif cmd in ("s", "search"):
                if not args:
                    console.print("[yellow]Usage: search <query>[/yellow]")
                    continue
                do_search(session, args)
            
            elif cmd in ("st", "search-track", "track"):
                if not args:
                    console.print("[yellow]Usage: track <query>[/yellow]")
                    continue
                do_search(session, args, SearchType.TRACK)
            
            elif cmd in ("sa", "search-album", "album"):
                if not args:
                    console.print("[yellow]Usage: album <query>[/yellow]")
                    continue
                do_search(session, args, SearchType.ALBUM)
            
            elif cmd in ("sp", "search-playlist", "playlist"):
                if not args:
                    console.print("[yellow]Usage: playlist <query>[/yellow]")
                    continue
                do_search(session, args, SearchType.PLAYLIST)
            
            elif cmd in ("d", "dl", "download"):
                if not args:
                    console.print("[yellow]Usage: download <url or id>[/yellow]")
                    continue
                do_download(session, config, queue, args)
            
            elif cmd in ("da", "dl-album"):
                if not args:
                    console.print("[yellow]Usage: dl-album <album_id>[/yellow]")
                    continue
                download_album(session, config, queue, args)
            
            elif cmd in ("dt", "dl-track"):
                if not args:
                    console.print("[yellow]Usage: dl-track <track_id>[/yellow]")
                    continue
                download_track(session, config, queue, args)
            
            elif cmd in ("dp", "dl-playlist"):
                if not args:
                    console.print("[yellow]Usage: dl-playlist <playlist_id>[/yellow]")
                    continue
                download_playlist(session, config, queue, args)
            
            elif cmd in ("dar", "dl-artist"):
                if not args:
                    console.print("[yellow]Usage: dl-artist <artist_id>[/yellow]")
                    continue
                download_artist(session, config, queue, args)
            
            elif cmd == "status":
                show_status(config, queue)
            
            elif cmd == "queue":
                show_queue(queue)
            
            elif cmd == "start":
                if not queue.is_running:
                    console.print("[green]Starting download workers...[/green]")
                    queue.start_workers(progress)
                    console.print(f"[green]Started {config.max_concurrent_downloads} download workers[/green]")
                else:
                    console.print("[yellow]Workers already running[/yellow]")
            
            elif cmd == "stop":
                queue.stop_workers()
                console.print("[yellow]Download workers stopped[/yellow]")
            
            elif cmd == "clear":
                queue.clear()
                console.print("[green]Queue cleared[/green]")
            
            elif cmd == "config":
                show_config(config)
            
            elif cmd == "logout":
                delete_session(config.session_file)
                console.print("[green]Logged out successfully. Restart to re-authenticate.[/green]")
                break
            
            else:
                console.print(f"[red]Unknown command: {cmd}[/red]")
                console.print("[dim]Type 'help' for available commands[/dim]")
        
        except KeyboardInterrupt:
            console.print("\n[dim]Use 'quit' to exit[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def show_help():
    """Show help message"""
    help_text = """
[bold cyan]🎵 Tidal MDL Commands[/bold cyan]

[bold]Search:[/bold]
  [green]search[/green] <query>      Search all content types
  [green]track[/green] <query>       Search for tracks only
  [green]album[/green] <query>       Search for albums only  
  [green]playlist[/green] <query>    Search for playlists only

[bold]Download:[/bold]
  [green]download[/green] <url/id>   Download from Tidal URL or auto-detect ID
  [green]dl-track[/green] <id>       Download a single track by ID
  [green]dl-album[/green] <id>       Download an entire album by ID
  [green]dl-playlist[/green] <id>    Download a playlist by UUID
  [green]dl-artist[/green] <id>      Download all albums by artist ID

[bold]Queue:[/bold]
  [green]start[/green]               Start download workers
  [green]stop[/green]                Stop download workers
  [green]queue[/green]               Show download queue
  [green]clear[/green]               Clear the queue

[bold]Other:[/bold]
  [green]status[/green]              Show current status
  [green]config[/green]              Show configuration
  [green]logout[/green]              Log out and delete session
  [green]help[/green]                Show this help
  [green]quit[/green]                Exit the application
"""
    console.print(Panel(help_text, title="Help", border_style="blue"))


def show_config(config: Config):
    """Show current configuration"""
    table = Table(title="⚙️  Configuration", box=box.ROUNDED)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Download Quality", str(config.download_quality.value))
    table.add_row("Video Quality", str(config.video_quality.value))
    table.add_row("Download Folder", str(config.download_folder.absolute()))
    table.add_row("Max Concurrent", str(config.max_concurrent_downloads))
    table.add_row("Rate Limit", f"{config.rate_limit_delay}s")
    table.add_row("Album Folder Template", config.album_folder_template)
    table.add_row("Track File Template", config.track_file_template)
    table.add_row("Embed Album Art", "✓" if config.embed_album_art else "✗")
    table.add_row("Embed Lyrics", "✓" if config.embed_lyrics else "✗")
    table.add_row("Save Album Art", "✓" if config.save_album_art else "✗")
    table.add_row("Skip Existing", "✓" if config.skip_existing else "✗")
    
    console.print(table)


def show_queue(queue: DownloadQueue):
    """Show the download queue"""
    status = queue.get_status()
    
    table = Table(title="📥 Download Queue", box=box.ROUNDED)
    table.add_column("Status", style="cyan", width=12)
    table.add_column("Count", style="green", justify="right")
    
    table.add_row("Queued", str(status["queued"]))
    table.add_row("Downloading", str(status["downloading"]))
    table.add_row("Completed", str(status["completed"]))
    table.add_row("Failed", str(status["failed"]))
    table.add_row("─" * 10, "─" * 5)
    table.add_row("[bold]Total[/bold]", f"[bold]{status['total']}[/bold]")
    
    console.print(table)
    
    # Show failed items if any
    if queue.failed:
        console.print("\n[bold red]Failed Downloads:[/bold red]")
        for task in queue.failed[-5:]:  # Show last 5 failed
            console.print(f"  • {task.item.name}: {task.error}")


def do_search(session, query: str, search_type: SearchType = SearchType.ALL):
    """Perform a search and display results"""
    with console.status(f"[bold blue]Searching for '{query}'...[/bold blue]"):
        results = search(session, query, search_type)
    
    display_search_results(results, search_type)


def do_download(session, config: Config, queue: DownloadQueue, url_or_id: str):
    """Download from URL or ID with auto-detection"""
    # Try parsing as Tidal URL first
    parsed = parse_tidal_url(url_or_id)
    
    if parsed:
        content_type, content_id = parsed
        if content_type == "track":
            download_track(session, config, queue, content_id)
        elif content_type == "album":
            download_album(session, config, queue, content_id)
        elif content_type == "playlist":
            download_playlist(session, config, queue, content_id)
        elif content_type == "artist":
            download_artist(session, config, queue, content_id)
        elif content_type == "video":
            download_video(session, config, queue, content_id)
        return
    
    # Try as numeric ID (assume album if large number, track otherwise)
    try:
        item_id = int(url_or_id)
        # Try as track first, then album
        track = get_track_by_id(session, item_id)
        if track:
            download_track(session, config, queue, url_or_id)
            return
        
        album = get_album_by_id(session, item_id)
        if album:
            download_album(session, config, queue, url_or_id)
            return
        
        console.print(f"[red]Could not find track or album with ID: {item_id}[/red]")
    except ValueError:
        # Try as playlist UUID
        playlist = get_playlist_by_id(session, url_or_id)
        if playlist:
            download_playlist(session, config, queue, url_or_id)
            return
        
        console.print(f"[red]Could not parse: {url_or_id}[/red]")
        console.print("[dim]Provide a Tidal URL, track ID, album ID, or playlist UUID[/dim]")


def download_track(session, config: Config, queue: DownloadQueue, track_id: str):
    """Download a single track"""
    try:
        track = get_track_by_id(session, int(track_id))
        if not track:
            return
        
        task = create_track_task(config, track)
        queue.add_task(task)
        
        console.print(f"[green]✓ Added to queue:[/green] {track.name} by {track.artist.name if track.artist else 'Unknown'}")
        
        # Auto-start workers if not running
        if not queue.is_running:
            console.print("[dim]Starting download workers...[/dim]")
            progress = create_progress()
            queue.start_workers(progress)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def download_album(session, config: Config, queue: DownloadQueue, album_id: str):
    """Download an entire album"""
    try:
        album = get_album_by_id(session, int(album_id))
        if not album:
            return
        
        console.print(f"[bold]📀 Album:[/bold] {album.name}")
        console.print(f"[dim]Artist: {album.artist.name if album.artist else 'Unknown'}[/dim]")
        
        tasks = create_album_tasks(config, session, album)
        queue.add_tasks(tasks)
        
        console.print(f"[green]✓ Added {len(tasks)} tracks to queue[/green]")
        
        # Save album art if configured
        if config.save_album_art:
            from src.downloader import create_output_path
            if tasks:
                album_folder = tasks[0].output_path.parent
                save_album_art(album, album_folder, config.album_art_filename)
        
        # Auto-start workers if not running
        if not queue.is_running:
            console.print("[dim]Starting download workers...[/dim]")
            progress = create_progress()
            queue.start_workers(progress)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def download_playlist(session, config: Config, queue: DownloadQueue, playlist_id: str):
    """Download a playlist"""
    try:
        playlist = get_playlist_by_id(session, playlist_id)
        if not playlist:
            return
        
        console.print(f"[bold]📋 Playlist:[/bold] {playlist.name}")
        console.print(f"[dim]Tracks: {playlist.num_tracks}[/dim]")
        
        tasks = create_playlist_tasks(config, session, playlist)
        queue.add_tasks(tasks)
        
        console.print(f"[green]✓ Added {len(tasks)} tracks to queue[/green]")
        
        # Auto-start workers if not running
        if not queue.is_running:
            console.print("[dim]Starting download workers...[/dim]")
            progress = create_progress()
            queue.start_workers(progress)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def download_artist(session, config: Config, queue: DownloadQueue, artist_id: str):
    """Download all albums by an artist"""
    try:
        artist = get_artist_by_id(session, int(artist_id))
        if not artist:
            return
        
        console.print(f"[bold]🎤 Artist:[/bold] {artist.name}")
        
        with console.status("[bold blue]Fetching artist albums...[/bold blue]"):
            albums = get_artist_albums(session, artist)
        
        if not albums:
            console.print("[yellow]No albums found for this artist[/yellow]")
            return
        
        console.print(f"[dim]Found {len(albums)} albums[/dim]")
        
        total_tasks = 0
        for album in albums:
            tasks = create_album_tasks(config, session, album)
            queue.add_tasks(tasks)
            total_tasks += len(tasks)
            console.print(f"  • {album.name} ({len(tasks)} tracks)")
        
        console.print(f"\n[green]✓ Added {total_tasks} tracks from {len(albums)} albums to queue[/green]")
        
        # Auto-start workers if not running
        if not queue.is_running:
            console.print("[dim]Starting download workers...[/dim]")
            progress = create_progress()
            queue.start_workers(progress)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def download_video(session, config: Config, queue: DownloadQueue, video_id: str):
    """Download a video"""
    try:
        video = get_video_by_id(session, int(video_id))
        if not video:
            return
        
        task = create_video_task(config, video)
        queue.add_task(task)
        
        console.print(f"[green]✓ Added to queue:[/green] {video.name}")
        
        # Auto-start workers if not running
        if not queue.is_running:
            console.print("[dim]Starting download workers...[/dim]")
            progress = create_progress()
            queue.start_workers(progress)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def create_progress() -> Progress:
    """Create a progress bar instance"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


@click.command()
@click.option("--config", "-c", "config_path", type=click.Path(exists=True), help="Path to .env config file")
@click.option("--force-login", "-f", is_flag=True, help="Force new login, ignore saved session")
@click.option("--quality", "-q", type=click.Choice(["NORMAL", "HIGH", "LOSSLESS", "HI_RES"]), help="Download quality")
@click.option("--download", "-d", "download_url", help="Download URL/ID directly and exit")
@click.version_option(version="1.0.0")
def main(config_path: Optional[str], force_login: bool, quality: Optional[str], download_url: Optional[str]):
    """
    🎵 Tidal MDL - A Tidal media downloader
    
    Download high-quality music from Tidal with ease.
    Supports tracks, albums, playlists, and artists.
    """
    show_banner()
    logger.info("Application started")
    
    # Load configuration
    config = load_config(Path(config_path) if config_path else None)
    
    # Override quality if specified
    if quality:
        import tidalapi
        quality_map = {
            "NORMAL": tidalapi.Quality.low_96k,
            "HIGH": tidalapi.Quality.low_320k,
            "LOSSLESS": tidalapi.Quality.high_lossless,
            "HI_RES": tidalapi.Quality.hi_res_lossless,
        }
        config.download_quality = quality_map[quality]
    
    # Authenticate
    session = get_authenticated_session(
        config.session_file,
        config.download_quality,
        force_login
    )
    
    if not session:
        console.print("[red]Authentication failed. Please try again.[/red]")
        sys.exit(1)
    
    # If download URL provided, download and exit
    if download_url:
        queue = DownloadQueue(config, session)
        progress = create_progress()
        do_download(session, config, queue, download_url)
        queue.start_workers(progress)
        queue.wait_for_completion()
        
        status = queue.get_status()
        if status["failed"] > 0:
            console.print(f"\n[yellow]Completed with {status['failed']} failed downloads[/yellow]")
            sys.exit(1)
        else:
            console.print(f"\n[green]✓ Successfully downloaded {status['completed']} items[/green]")
            sys.exit(0)
    
    # Start interactive mode
    interactive_mode(config, session)


if __name__ == "__main__":
    main()
