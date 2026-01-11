"""
Search module for Tidal MDL
Handles searching for tracks, albums, artists, and playlists
"""

from typing import List, Optional, Union
from dataclasses import dataclass
from enum import Enum

import tidalapi
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


class SearchType(Enum):
    """Types of content that can be searched"""
    TRACK = "track"
    ALBUM = "album"
    ARTIST = "artist"
    PLAYLIST = "playlist"
    VIDEO = "video"
    ALL = "all"


@dataclass
class SearchResult:
    """Container for search results"""
    tracks: List[tidalapi.Track]
    albums: List[tidalapi.Album]
    artists: List[tidalapi.Artist]
    playlists: List[tidalapi.Playlist]
    videos: List[tidalapi.Video]


def search(
    session: tidalapi.Session,
    query: str,
    search_type: SearchType = SearchType.ALL,
    limit: int = 50,
    offset: int = 0
) -> SearchResult:
    """
    Search Tidal for content
    
    Args:
        session: Authenticated tidalapi.Session
        query: Search query string
        search_type: Type of content to search for
        limit: Maximum number of results per category
        offset: Offset for pagination
    
    Returns:
        SearchResult containing matching items
    """
    tracks = []
    albums = []
    artists = []
    playlists = []
    videos = []
    
    if search_type in (SearchType.ALL, SearchType.TRACK):
        try:
            tracks = session.search(query, models=[tidalapi.Track], limit=limit, offset=offset).get("tracks", [])
        except Exception:
            tracks = []
    
    if search_type in (SearchType.ALL, SearchType.ALBUM):
        try:
            albums = session.search(query, models=[tidalapi.Album], limit=limit, offset=offset).get("albums", [])
        except Exception:
            albums = []
    
    if search_type in (SearchType.ALL, SearchType.ARTIST):
        try:
            artists = session.search(query, models=[tidalapi.Artist], limit=limit, offset=offset).get("artists", [])
        except Exception:
            artists = []
    
    if search_type in (SearchType.ALL, SearchType.PLAYLIST):
        try:
            playlists = session.search(query, models=[tidalapi.Playlist], limit=limit, offset=offset).get("playlists", [])
        except Exception:
            playlists = []
    
    if search_type in (SearchType.ALL, SearchType.VIDEO):
        try:
            videos = session.search(query, models=[tidalapi.Video], limit=limit, offset=offset).get("videos", [])
        except Exception:
            videos = []
    
    return SearchResult(
        tracks=tracks,
        albums=albums,
        artists=artists,
        playlists=playlists,
        videos=videos,
    )


def format_duration(seconds: Optional[int]) -> str:
    """Format duration in seconds to MM:SS format"""
    if seconds is None:
        return "--:--"
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


def display_tracks(tracks: List[tidalapi.Track], title: str = "Tracks") -> None:
    """Display tracks in a formatted table"""
    if not tracks:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return
    
    table = Table(title=f"🎵 {title}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("Artist", style="green", max_width=30)
    table.add_column("Album", style="yellow", max_width=30)
    table.add_column("Duration", style="dim", justify="right")
    table.add_column("ID", style="dim")
    
    for idx, track in enumerate(tracks, 1):
        artist_name = track.artist.name if track.artist else "Unknown"
        album_name = track.album.name if track.album else "Unknown"
        table.add_row(
            str(idx),
            track.name or "Unknown",
            artist_name,
            album_name,
            format_duration(track.duration),
            str(track.id)
        )
    
    console.print(table)
    console.print()


def display_albums(albums: List[tidalapi.Album], title: str = "Albums") -> None:
    """Display albums in a formatted table"""
    if not albums:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return
    
    table = Table(title=f"💿 {title}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Album", style="cyan", max_width=40)
    table.add_column("Artist", style="green", max_width=30)
    table.add_column("Year", style="yellow", justify="center")
    table.add_column("Tracks", style="dim", justify="right")
    table.add_column("ID", style="dim")
    
    for idx, album in enumerate(albums, 1):
        artist_name = album.artist.name if album.artist else "Unknown"
        year = str(album.release_date.year) if album.release_date else "----"
        tracks = str(album.num_tracks) if album.num_tracks else "-"
        table.add_row(
            str(idx),
            album.name or "Unknown",
            artist_name,
            year,
            tracks,
            str(album.id)
        )
    
    console.print(table)
    console.print()


def display_artists(artists: List[tidalapi.Artist], title: str = "Artists") -> None:
    """Display artists in a formatted table"""
    if not artists:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return
    
    table = Table(title=f"🎤 {title}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Artist", style="cyan", max_width=50)
    table.add_column("ID", style="dim")
    
    for idx, artist in enumerate(artists, 1):
        table.add_row(
            str(idx),
            artist.name or "Unknown",
            str(artist.id)
        )
    
    console.print(table)
    console.print()


def display_playlists(playlists: List[tidalapi.Playlist], title: str = "Playlists") -> None:
    """Display playlists in a formatted table"""
    if not playlists:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return
    
    table = Table(title=f"📋 {title}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Playlist", style="cyan", max_width=40)
    table.add_column("Creator", style="green", max_width=30)
    table.add_column("Tracks", style="dim", justify="right")
    table.add_column("ID", style="dim")
    
    for idx, playlist in enumerate(playlists, 1):
        creator = playlist.creator.name if playlist.creator else "Tidal"
        tracks = str(playlist.num_tracks) if playlist.num_tracks else "-"
        table.add_row(
            str(idx),
            playlist.name or "Unknown",
            creator,
            tracks,
            str(getattr(playlist, 'id', None) or getattr(playlist, 'uuid', 'unknown'))
        )
    
    console.print(table)
    console.print()


def display_videos(videos: List[tidalapi.Video], title: str = "Videos") -> None:
    """Display videos in a formatted table"""
    if not videos:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return
    
    table = Table(title=f"🎬 {title}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("Artist", style="green", max_width=30)
    table.add_column("Duration", style="dim", justify="right")
    table.add_column("ID", style="dim")
    
    for idx, video in enumerate(videos, 1):
        artist_name = video.artist.name if video.artist else "Unknown"
        table.add_row(
            str(idx),
            video.name or "Unknown",
            artist_name,
            format_duration(video.duration),
            str(video.id)
        )
    
    console.print(table)
    console.print()


def display_search_results(results: SearchResult, search_type: SearchType = SearchType.ALL) -> None:
    """Display all search results"""
    has_results = False
    
    if search_type in (SearchType.ALL, SearchType.TRACK) and results.tracks:
        display_tracks(results.tracks)
        has_results = True
    
    if search_type in (SearchType.ALL, SearchType.ALBUM) and results.albums:
        display_albums(results.albums)
        has_results = True
    
    if search_type in (SearchType.ALL, SearchType.ARTIST) and results.artists:
        display_artists(results.artists)
        has_results = True
    
    if search_type in (SearchType.ALL, SearchType.PLAYLIST) and results.playlists:
        display_playlists(results.playlists)
        has_results = True
    
    if search_type in (SearchType.ALL, SearchType.VIDEO) and results.videos:
        display_videos(results.videos)
        has_results = True
    
    if not has_results:
        console.print("[yellow]No results found.[/yellow]")


def get_album_by_id(session: tidalapi.Session, album_id: int) -> Optional[tidalapi.Album]:
    """Get an album by its ID"""
    try:
        return session.album(album_id)
    except Exception as e:
        console.print(f"[red]Error fetching album: {e}[/red]")
        return None


def get_track_by_id(session: tidalapi.Session, track_id: int) -> Optional[tidalapi.Track]:
    """Get a track by its ID"""
    try:
        return session.track(track_id)
    except Exception as e:
        console.print(f"[red]Error fetching track: {e}[/red]")
        return None


def get_playlist_by_id(session: tidalapi.Session, playlist_id: str) -> Optional[tidalapi.Playlist]:
    """Get a playlist by its UUID"""
    try:
        return session.playlist(playlist_id)
    except Exception as e:
        console.print(f"[red]Error fetching playlist: {e}[/red]")
        return None


def get_artist_by_id(session: tidalapi.Session, artist_id: int) -> Optional[tidalapi.Artist]:
    """Get an artist by its ID"""
    try:
        return session.artist(artist_id)
    except Exception as e:
        console.print(f"[red]Error fetching artist: {e}[/red]")
        return None


def get_video_by_id(session: tidalapi.Session, video_id: int) -> Optional[tidalapi.Video]:
    """Get a video by its ID"""
    try:
        return session.video(video_id)
    except Exception as e:
        console.print(f"[red]Error fetching video: {e}[/red]")
        return None


def parse_tidal_url(url: str) -> Optional[tuple]:
    """
    Parse a Tidal URL and extract the content type and ID
    
    Args:
        url: Tidal URL (e.g., https://tidal.com/browse/album/12345)
    
    Returns:
        Tuple of (content_type, id) or None if URL is invalid
    """
    import re
    
    patterns = [
        # https://tidal.com/browse/track/12345
        (r"tidal\.com/browse/track/(\d+)", "track"),
        # https://tidal.com/browse/album/12345
        (r"tidal\.com/browse/album/(\d+)", "album"),
        # https://tidal.com/browse/artist/12345
        (r"tidal\.com/browse/artist/(\d+)", "artist"),
        # https://tidal.com/browse/playlist/uuid
        (r"tidal\.com/browse/playlist/([a-f0-9-]+)", "playlist"),
        # https://tidal.com/browse/video/12345
        (r"tidal\.com/browse/video/(\d+)", "video"),
        # https://listen.tidal.com/album/12345
        (r"listen\.tidal\.com/album/(\d+)", "album"),
        (r"listen\.tidal\.com/track/(\d+)", "track"),
        (r"listen\.tidal\.com/artist/(\d+)", "artist"),
        (r"listen\.tidal\.com/playlist/([a-f0-9-]+)", "playlist"),
        (r"listen\.tidal\.com/video/(\d+)", "video"),
    ]
    
    for pattern, content_type in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return (content_type, match.group(1))
    
    return None
