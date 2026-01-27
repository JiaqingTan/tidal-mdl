"""
Download module for Tidal MDL
Handles downloading tracks, albums, playlists with rate limiting and concurrency
"""

import asyncio
import aiohttp
import aiofiles
import os
import re
import time
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from queue import Queue
from threading import Thread, Lock, Event
import requests

import tidalapi
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK, TYER, TDRC
from rich.console import Console
from rich.progress import (
    Progress, 
    TaskID, 
    TextColumn, 
    BarColumn, 
    DownloadColumn, 
    TransferSpeedColumn, 
    TimeRemainingColumn,
    SpinnerColumn,
)

from .config import Config
from .logger import logger

console = Console()


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available on the system"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def remux_to_flac(input_path: Path, output_path: Path) -> bool:
    """
    Remux MP4 container with FLAC audio to native FLAC file.
    This is a lossless operation - just changes the container, no re-encoding.
    
    Args:
        input_path: Path to the MP4/M4A file containing FLAC audio
        output_path: Path for the output FLAC file
    
    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", str(input_path),
            "-vn",           # No video
            "-acodec", "copy",  # Copy audio stream without re-encoding
            "-y",            # Overwrite output
            str(output_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120  # 2 minute timeout for large files
        )
        
        if result.returncode == 0:
            logger.info(f"Successfully remuxed to FLAC: {output_path}")
            return True
        else:
            logger.error(f"FFmpeg remux failed: {result.stderr.decode()}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg remux timed out")
        return False
    except Exception as e:
        logger.error(f"FFmpeg remux error: {e}")
        return False


def safe_add_extension(path: Path, extension: str) -> Path:
    """
    Safely add an extension to a path without breaking filenames that contain periods.
    
    Python's Path.with_suffix() replaces anything after the last '.' which breaks
    filenames like 'Song (feat. Artist)' -> 'Song (feat.flac' instead of 'Song (feat. Artist).flac'
    
    Args:
        path: The path (without extension)
        extension: The extension to add (should start with '.')
    
    Returns:
        Path with extension appended
    """
    if not extension.startswith('.'):
        extension = '.' + extension
    return Path(str(path) + extension)


# Check ffmpeg availability at module load
FFMPEG_AVAILABLE = is_ffmpeg_available()
if FFMPEG_AVAILABLE:
    logger.info("FFmpeg detected - FLAC remuxing enabled")
else:
    logger.warning("FFmpeg not found - DASH FLAC streams will be saved as M4A container")


class DownloadStatus(Enum):
    """Status of a download task"""
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


# Temp file extension used during downloads
TEMP_DOWNLOAD_EXTENSION = ".downloading"


@dataclass
class DownloadTask:
    """Represents a download task in the queue"""
    id: str
    item: Any  # tidalapi.Track, tidalapi.Video, etc.
    item_type: str  # "track", "video", etc.
    output_path: Path
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    error: Optional[str] = None
    album: Optional[tidalapi.Album] = None
    track_number: int = 1
    total_tracks: int = 1
    # Playlist compilation info (for "download as one" mode)
    playlist_name: Optional[str] = None
    playlist_album_artist: Optional[str] = None
    # Stream info (populated during download)
    codec: Optional[str] = None
    quality: Optional[str] = None
    bit_depth: Optional[int] = None
    sample_rate: Optional[int] = None
    # Conversion tracking
    is_converting: bool = False
    conversion_progress: float = 0.0
    
    def __hash__(self):
        return hash(self.id)
    
    @property
    def format_info(self) -> str:
        """Get formatted string of codec/quality info"""
        if not self.codec:
            return ""
        parts = []
        if self.codec:
            parts.append(self.codec)
        if self.bit_depth and self.sample_rate:
            parts.append(f"{self.bit_depth}bit/{self.sample_rate/1000:.1f}kHz")
        elif self.quality:
            parts.append(str(self.quality))
        return " • ".join(parts)


class DownloadQueue:
    """Thread-safe download queue with rate limiting"""
    
    def __init__(self, config: Config, session: tidalapi.Session):
        self.config = config
        self.session = session
        self.queue: List[DownloadTask] = []
        self.completed: List[DownloadTask] = []
        self.failed: List[DownloadTask] = []
        self.lock = Lock()
        self.stop_event = Event()
        self.worker_threads: List[Thread] = []
        self.is_running = False
        self.last_download_time = 0.0
        self.rate_limit_lock = Lock()
        self.session_lock = Lock()
        self._callbacks: List[Callable[[DownloadTask], None]] = []
    
    def add_callback(self, callback: Callable[[DownloadTask], None]) -> None:
        """Add a callback to be called when a download completes or fails"""
        self._callbacks.append(callback)
    
    def _notify_callbacks(self, task: DownloadTask) -> None:
        """Notify all registered callbacks"""
        for callback in self._callbacks:
            try:
                callback(task)
            except Exception:
                pass
    
    def add_task(self, task: DownloadTask) -> None:
        """Add a new download task to the queue"""
        with self.lock:
            # Check for duplicates in current queue
            existing_ids = {t.id for t in self.queue if t.status == DownloadStatus.QUEUED}
            
            # Also check completed tasks - but only skip if file still exists
            for completed_task in self.completed:
                if completed_task.id == task.id:
                    if completed_task.output_path and completed_task.output_path.exists():
                        logger.debug(f"Skipping already completed task: {task.id}")
                        return
                    else:
                        # File was deleted, remove from completed so we can re-download
                        self.completed.remove(completed_task)
                        logger.debug(f"File deleted, allowing re-download: {task.id}")
                        break
            
            if task.id not in existing_ids:
                self.queue.append(task)
                logger.debug(f"Added task to queue: {task.id}")
    
    def add_tasks(self, tasks: List[DownloadTask]) -> None:
        """Add multiple download tasks to the queue"""
        for task in tasks:
            self.add_task(task)
    
    def get_next_task(self) -> Optional[DownloadTask]:
        """Get the next queued task"""
        with self.lock:
            for task in self.queue:
                if task.status == DownloadStatus.QUEUED:
                    task.status = DownloadStatus.DOWNLOADING
                    return task
        return None
    
    def get_status(self) -> Dict[str, int]:
        """Get current queue status"""
        with self.lock:
            queued = sum(1 for t in self.queue if t.status == DownloadStatus.QUEUED)
            downloading = sum(1 for t in self.queue if t.status == DownloadStatus.DOWNLOADING)
            completed = len(self.completed)
            failed = len(self.failed)
            return {
                "queued": queued,
                "downloading": downloading,
                "completed": completed,
                "failed": failed,
                "total": queued + downloading + completed + failed
            }
    
    def _apply_rate_limit(self) -> None:
        """Apply rate limiting between downloads"""
        with self.rate_limit_lock:
            elapsed = time.time() - self.last_download_time
            if elapsed < self.config.rate_limit_delay:
                time.sleep(self.config.rate_limit_delay - elapsed)
            self.last_download_time = time.time()
    
    def _check_session(self) -> bool:
        """Check if session is valid and refresh if needed"""
        try:
            if not self.session.check_login():
                logger.warning("Session invalid, attempting refresh check...")
                # tidalapi handles auto-refresh if token is present, but good to check explicit login state
                # If this fails, we might need to handle re-login in the main thread or prompt user
                return False
            return True
        except Exception as e:
            logger.error(f"Session check failed: {e}")
            return False

    def _worker(self, worker_id: int, progress: Progress) -> None:
        """Worker thread for processing downloads"""
        logger.info(f"Worker {worker_id} started")
        
        while not self.stop_event.is_set():
            task = self.get_next_task()
            if task is None:
                # No more tasks, wait a bit and check again
                time.sleep(0.5)
                # Check if we should exit if queue is fully cleared (optional, here we stay alive)
                continue
            
            # Apply rate limiting
            self._apply_rate_limit()
            
            try:
                logger.info(f"Starting download: {task.item.name} ({task.id})")
                
                # Create progress task (only if progress UI is available)
                task_id = None
                if progress is not None:
                    task_id = progress.add_task(
                        f"[cyan]{task.item.name[:30]}...[/cyan]" if len(task.item.name) > 30 else f"[cyan]{task.item.name}[/cyan]",
                        total=100
                    )
                
                # Download the item
                success = self._download_item(task, progress, task_id)
                
                if success:
                    # Preserve SKIPPED status; otherwise mark COMPLETED
                    if task.status != DownloadStatus.SKIPPED:
                        task.status = DownloadStatus.COMPLETED
                    task.progress = 100.0
                    with self.lock:
                        self.completed.append(task)
                    logger.info(f"Completed download: {task.item.name} (status: {task.status.value})")
                else:
                    task.status = DownloadStatus.FAILED
                    with self.lock:
                        self.failed.append(task)
                    logger.error(f"Failed download: {task.item.name} - {task.error}")
                
                if progress is not None and task_id is not None:
                    progress.update(task_id, completed=100)
                    progress.remove_task(task_id)
                
            except Exception as e:
                task.status = DownloadStatus.FAILED
                task.error = str(e)
                with self.lock:
                    self.failed.append(task)
                logger.exception(f"Worker exception for {task.item.name}: {e}")
            
            self._notify_callbacks(task)
        
        logger.info(f"Worker {worker_id} stopped")
    
    def _download_item(self, task: DownloadTask, progress: Progress, task_id: TaskID) -> bool:
        """Download a single item"""
        # Ensure session is valid before starting
        # Note: Thread-safe session check is tricky, relying on library's internal handling + simple check
        
        if task.item_type == "track":
            return self._download_track(task, progress, task_id)
        elif task.item_type == "video":
            return self._download_video(task, progress, task_id)
        return False
    
    def _download_track(self, task: DownloadTask, progress: Progress, task_id: TaskID) -> bool:
        """Download a track"""
        track = task.item
        output_path = task.output_path
        download_path = None  # Initialize for cleanup in exception handler
        
        # Skip if exists and configured to skip
        if self.config.skip_existing and output_path.exists():
            task.status = DownloadStatus.SKIPPED
            logger.info(f"Skipping existing file: {output_path}")
            return True
        
        try:
            # Fallback logic for stream URL
            stream = None
            
            # Define quality order
            quality_order = [
                tidalapi.Quality.hi_res_lossless,
                tidalapi.Quality.high_lossless,
                tidalapi.Quality.low_320k,
                tidalapi.Quality.low_96k,
            ]
            
            # Find start index based on config
            start_index = 0
            if self.config.download_quality in quality_order:
                start_index = quality_order.index(self.config.download_quality)
            
            # Try qualities from configured down to lowest
            stream_error = None
            original_quality = self.config.download_quality # Keep track of original
            
            for quality in quality_order[start_index:]:
                try:
                    logger.debug(f"Trying to get stream for track {track.id} with quality {quality}")
                    
                    # Thread-safe session config change and stream fetch
                    # We utilize a lock because session config is global
                    with self.session_lock:
                        self.session.config.quality = quality
                        stream = track.get_stream()
                        
                    if stream:
                        logger.info(f"Successfully got stream with quality: {quality}")
                        break
                except Exception as e:
                    logger.warning(f"Failed to get stream with quality {quality}: {e}")
                    stream_error = e
                    continue
            
            # Restore original quality preference in session (best effort, next thread will overwrite anyway)
            # with self.session_lock:
            #     self.session.config.quality = original_quality

            if not stream:
                if stream_error:
                    if "401" in str(stream_error) or "403" in str(stream_error):
                        logger.error("Authentication error getting stream. Session may vary expired.")
                        task.error = "Session expired or invalid rights."
                    else:
                        logger.error(f"Error getting stream: {stream_error}")
                        task.error = f"Stream error: {stream_error}"
                else:
                    task.error = "Could not get stream URL (all qualities failed)"
                return False
            
            # Get the manifest and extract URL
            manifest = stream.get_stream_manifest()
            
            # Create output directory
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Log actual stream quality and codec received
            actual_quality = getattr(stream, 'audio_quality', 'unknown')
            bit_depth = getattr(stream, 'bit_depth', 16)
            sample_rate = getattr(stream, 'sample_rate', 44100)
            codec = getattr(manifest, 'codecs', 'unknown')
            file_ext = getattr(manifest, 'file_extension', '.m4a')
            
            # Store stream info in task for GUI display
            task.codec = codec
            task.quality = str(actual_quality) if actual_quality else None
            task.bit_depth = bit_depth
            task.sample_rate = sample_rate
            
            logger.info(f"Stream received: quality={actual_quality}, codec={codec}, "
                       f"bit_depth={bit_depth}, sample_rate={sample_rate}, extension={file_ext}")
            
            # Determine if we need to remux
            # FLAC codec inside MP4 container needs remuxing to native FLAC
            needs_remux = (codec == "FLAC" and file_ext == ".m4a" and FFMPEG_AVAILABLE)
            
            if needs_remux:
                # Download to temp file, then remux to FLAC
                final_path = safe_add_extension(output_path, ".flac")
                # Use .downloading extension for temp file
                download_path = Path(str(final_path) + TEMP_DOWNLOAD_EXTENSION)
                logger.info(f"FLAC in MP4 container detected - will remux to native FLAC")
            elif codec == "FLAC" and file_ext == ".m4a" and not FFMPEG_AVAILABLE:
                # FLAC in MP4 but no ffmpeg - save as M4A with warning
                final_path = safe_add_extension(output_path, ".m4a")
                download_path = Path(str(final_path) + TEMP_DOWNLOAD_EXTENSION)
                logger.warning("FLAC in MP4 container but ffmpeg not available - saving as .m4a")
            else:
                # Normal case - use the extension from manifest
                ext = file_ext if file_ext else ".m4a"
                final_path = safe_add_extension(output_path, ext)
                # Always download to temp file first, then rename on success
                download_path = Path(str(final_path) + TEMP_DOWNLOAD_EXTENSION)
            
            task.output_path = final_path
            
            # Skip if final file already exists
            if self.config.skip_existing and final_path.exists():
                task.status = DownloadStatus.SKIPPED
                logger.info(f"Skipping existing file: {final_path}")
                return True
            
            # Download the file
            urls = manifest.get_urls()
            if not urls:
                task.error = "No download URLs available"
                return False
            
            # Timeout configuration
            TIMEOUT = 30
            
            # Track if download was cancelled
            was_cancelled = False
            
            # For single URL streams (BTS)
            if len(urls) == 1:
                url = urls[0]
                response = requests.get(url, stream=True, timeout=TIMEOUT)
                response.raise_for_status()
                
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                
                with open(download_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        # Check for stop signal - allows quick cancellation
                        if self.stop_event.is_set():
                            was_cancelled = True
                            break
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = (downloaded / total_size) * 100
                                task.progress = pct
                                if progress is not None and task_id is not None:
                                    progress.update(task_id, completed=pct)
            else:
                # For segmented streams (DASH), concatenate segments
                with open(download_path, "wb") as f:
                    for i, url in enumerate(urls):
                        # Check for stop signal - allows quick cancellation
                        if self.stop_event.is_set():
                            was_cancelled = True
                            break
                        response = requests.get(url, timeout=TIMEOUT)
                        response.raise_for_status()
                        f.write(response.content)
                        pct = ((i + 1) / len(urls)) * 100
                        task.progress = pct
                        if progress is not None and task_id is not None:
                            progress.update(task_id, completed=pct)
            
            # If cancelled, clean up partial download and return
            if was_cancelled:
                task.status = DownloadStatus.CANCELLED
                task.error = "Download cancelled by user"
                logger.info(f"Download cancelled, cleaning up: {download_path}")
                try:
                    if download_path.exists():
                        download_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to remove partial download: {e}")
                return False
            
            # Remux if needed (FLAC in MP4 container -> native FLAC)
            if needs_remux:
                logger.info(f"Remuxing {download_path} to {final_path}")
                task.is_converting = True
                task.conversion_progress = 0.0
                if remux_to_flac(download_path, final_path):
                    task.conversion_progress = 100.0
                    task.is_converting = False  # Reset after conversion
                    # Remove temp file
                    try:
                        download_path.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file: {e}")
                else:
                    # Remux failed - rename temp file to M4A
                    task.is_converting = False  # Reset after conversion
                    logger.warning("Remux failed - keeping as M4A file")
                    # Remove .downloading extension and change final extension to .m4a
                    final_path = Path(str(download_path).replace(TEMP_DOWNLOAD_EXTENSION, "").rsplit(".", 1)[0] + ".m4a")
                    shutil.move(str(download_path), str(final_path))
                    task.output_path = final_path
            else:
                # Rename temp file to final destination
                try:
                    shutil.move(str(download_path), str(final_path))
                    logger.debug(f"Moved temp file to final destination: {final_path}")
                except Exception as e:
                    logger.error(f"Failed to rename temp file to final: {e}")
                    task.error = f"Failed to finalize download: {e}"
                    return False
            
            # Embed metadata
            try:
                self._embed_metadata(track, task.output_path, task.album, task)
            except Exception as e:
                logger.error(f"Failed to embed metadata for {task.output_path}: {e}")
                # Don't fail the download just because metadata failed
            
            return True
            
        except Exception as e:
            # Clean up partial downloads on error
            try:
                if download_path and download_path.exists():
                    download_path.unlink()
                    logger.info(f"Cleaned up partial download: {download_path}")
            except Exception:
                pass
            task.error = str(e)
            logger.exception(f"Download error for {task.item.name}")
            return False
    
    def _download_video(self, task: DownloadTask, progress: Progress, task_id: TaskID) -> bool:
        """Download a video"""
        video = task.item
        final_path = safe_add_extension(task.output_path, ".mp4")
        task.output_path = final_path
        
        # Skip if exists
        if self.config.skip_existing and final_path.exists():
            task.status = DownloadStatus.SKIPPED
            return True
        
        # Use temp file for download
        download_path = Path(str(final_path) + TEMP_DOWNLOAD_EXTENSION)
        
        try:
            # Get video URL
            stream_url = video.get_url()
            if not stream_url:
                task.error = "Could not get video URL"
                return False
            
            # Create output directory
            final_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Download video
            response = requests.get(stream_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            was_cancelled = False
            
            with open(download_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    # Check for stop signal
                    if self.stop_event.is_set():
                        was_cancelled = True
                        break
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = (downloaded / total_size) * 100
                            task.progress = pct
                            if progress is not None and task_id is not None:
                                progress.update(task_id, completed=pct)
            
            # Handle cancellation
            if was_cancelled:
                task.status = DownloadStatus.CANCELLED
                task.error = "Download cancelled by user"
                try:
                    if download_path.exists():
                        download_path.unlink()
                except Exception:
                    pass
                return False
            
            # Rename temp file to final destination
            try:
                shutil.move(str(download_path), str(final_path))
            except Exception as e:
                task.error = f"Failed to finalize download: {e}"
                return False
            
            return True
            
        except Exception as e:
            # Clean up partial download
            try:
                if download_path.exists():
                    download_path.unlink()
            except Exception:
                pass
            task.error = str(e)
            return False
    
    def _embed_metadata(self, track: tidalapi.Track, file_path: Path, album: Optional[tidalapi.Album] = None, task: Optional[DownloadTask] = None) -> None:
        """Embed metadata into the downloaded file"""
        if not self.config.embed_album_art:
             # Even if album art is disabled, we probably want basic tags
             pass

        suffix = file_path.suffix.lower()
        logger.debug(f"Embedding metadata for {file_path}")
        
        if suffix == ".flac":
            self._embed_flac_metadata(track, file_path, album, task)
        elif suffix in (".m4a", ".mp4"):
            self._embed_m4a_metadata(track, file_path, album, task)
    
    def _embed_flac_metadata(self, track: tidalapi.Track, file_path: Path, album: Optional[tidalapi.Album] = None, task: Optional[DownloadTask] = None) -> None:
        """Embed metadata into FLAC file"""
        try:
            audio = FLAC(file_path)
        except Exception as e:
            logger.error(f"Could not open FLAC file for tagging: {file_path} - {e}")
            return
        
        # Basic tags
        audio["TITLE"] = track.name or ""
        audio["ARTIST"] = track.artist.name if track.artist else ""
        
        # Check if this is a playlist compilation download
        if task and task.playlist_name:
            # Override Album with playlist name and set Album Artist
            audio["ALBUM"] = task.playlist_name
            audio["ALBUMARTIST"] = task.playlist_album_artist or "Various Artists"
            # Use playlist track number
            audio["TRACKNUMBER"] = str(task.track_number or 1)
            logger.info(f"Playlist compilation metadata: Album='{task.playlist_name}', AlbumArtist='{task.playlist_album_artist}'")
        else:
            # Use original album metadata
            audio["ALBUM"] = track.album.name if track.album else ""
            audio["TRACKNUMBER"] = str(track.track_num or 1)
        
        # Date/Year
        if album and album.release_date:
            audio["DATE"] = str(album.release_date.year)
            audio["YEAR"] = str(album.release_date.year)
        elif track.album and hasattr(track.album, "release_date") and track.album.release_date:
            audio["DATE"] = str(track.album.release_date.year)
            audio["YEAR"] = str(track.album.release_date.year)
        
        logger.info(f"Embedding metadata: {track.name} by {track.artist.name if track.artist else 'Unknown'}")
        
        # Album Art
        if self.config.embed_album_art:
            try:
                cover_url = None
                if album:
                    cover_url = album.image(1280)
                elif track.album:
                    cover_url = track.album.image(1280)
                
                if cover_url:
                    logger.debug(f"Fetching album art from {cover_url}")
                    response = requests.get(cover_url, timeout=15)
                    if response.status_code == 200:
                        picture = Picture()
                        picture.type = 3  # Cover (front)
                        picture.desc = "Front Cover"
                        
                        # Detect MIME type
                        content_type = response.headers.get("content-type", "")
                        if "jpeg" in content_type or "jpg" in content_type:
                            picture.mime = "image/jpeg"
                        elif "png" in content_type:
                            picture.mime = "image/png"
                        else:
                            picture.mime = "image/jpeg"  # Default
                        
                        # Set image dimensions (mutagen requires these for FLAC)
                        picture.width = 1280
                        picture.height = 1280
                        picture.depth = 24  # 24-bit color
                            
                        picture.data = response.content
                        audio.clear_pictures()  # Clear existing
                        audio.add_picture(picture)
                        logger.info(f"Album art embedded: {len(response.content)} bytes")
                    else:
                        logger.warning(f"Failed to fetch album art: HTTP {response.status_code}")
                else:
                    logger.warning("No album art URL available")
            except Exception as e:
                logger.warning(f"Error embedding FLAC album art: {e}")
        audio.save()
        logger.debug(f"Saved FLAC metadata to {file_path}")
    
    def _embed_m4a_metadata(self, track: tidalapi.Track, file_path: Path, album: Optional[tidalapi.Album] = None, task: Optional[DownloadTask] = None) -> None:
        """Embed metadata into M4A file"""
        try:
            audio = MP4(file_path)
        except Exception:
            # Sometimes MP4 header is not ready or file is corrupt
            logger.error(f"Could not open MP4/M4A file for tagging: {file_path}")
            return

        audio["\xa9nam"] = track.name or ""
        audio["\xa9ART"] = track.artist.name if track.artist else ""
        
        # Check if this is a playlist compilation download
        if task and task.playlist_name:
            # Override Album with playlist name and set Album Artist
            audio["\xa9alb"] = task.playlist_name
            audio["aART"] = task.playlist_album_artist or "Various Artists"
            # Use playlist track number
            audio["trkn"] = [(task.track_number or 1, task.total_tracks or 0)]
            logger.info(f"Playlist compilation metadata: Album='{task.playlist_name}', AlbumArtist='{task.playlist_album_artist}'")
        else:
            # Use original album metadata
            audio["\xa9alb"] = track.album.name if track.album else ""
            audio["trkn"] = [(track.track_num or 1, 0)]
        
        if album and album.release_date:
            audio["\xa9day"] = str(album.release_date.year)
        elif track.album and hasattr(track.album, "release_date") and track.album.release_date:
            audio["\xa9day"] = str(track.album.release_date.year)
        
        # Add album art if configured
        if self.config.embed_album_art:
            try:
                cover_url = None
                if album:
                    cover_url = album.image(1280)
                elif track.album:
                    cover_url = track.album.image(1280)
                
                if cover_url:
                    response = requests.get(cover_url, timeout=10)
                    if response.status_code == 200:
                        image_format = MP4Cover.FORMAT_JPEG
                        if "png" in response.headers.get("content-type", ""):
                            image_format = MP4Cover.FORMAT_PNG
                            
                        audio["covr"] = [MP4Cover(response.content, imageformat=image_format)]
            except Exception as e:
                logger.warning(f"Error embedding M4A album art: {e}")
        
        audio.save()
    
    def start_workers(self, progress: Progress) -> None:
        """Start worker threads"""
        if self.is_running:
            return
        
        self.is_running = True
        self.stop_event.clear()
        
        for i in range(self.config.max_concurrent_downloads):
            thread = Thread(target=self._worker, args=(i, progress))
            thread.daemon = True
            thread.start()
            self.worker_threads.append(thread)
        logger.info(f"Started {self.config.max_concurrent_downloads} worker threads")
    
    def stop_workers(self) -> None:
        """Stop all worker threads"""
        self.stop_event.set()
        for thread in self.worker_threads:
            thread.join(timeout=5.0)
        self.worker_threads.clear()
        self.is_running = False
        logger.info("Stopped all worker threads")
    
    def wait_for_completion(self) -> None:
        """Wait for all downloads to complete"""
        for thread in self.worker_threads:
            thread.join()
    
    def clear(self) -> None:
        """Clear the queue"""
        with self.lock:
            self.queue.clear()
            self.completed.clear()
            self.failed.clear()
        logger.info("Cleared download queue")


def sanitize_filename(name: str) -> str:
    """Remove invalid characters from filename"""
    # Replace colons with Unicode fullwidth colon (looks like : but valid in filenames)
    name = name.replace(":", "꞉")  # U+A789 MODIFIER LETTER COLON
    
    # Remove or replace other invalid characters
    invalid_chars = '<>"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    
    # Remove leading/trailing spaces and dots
    name = name.strip(". ")
    
    # Limit length (255 is max for most filesystems)
    if len(name) > 250:
        name = name[:250]
    
    return name


def create_output_path(
    config: Config,
    track: tidalapi.Track,
    album: Optional[tidalapi.Album] = None
) -> Path:
    """
    Create output path for a track based on configuration templates
    
    Args:
        config: Application configuration
        track: Track to create path for
        album: Optional album (for album downloads)
    
    Returns:
        Path object for the output file
    """
    # Get album info
    if album is None and track.album:
        album = track.album
    
    artist_name = sanitize_filename(track.artist.name if track.artist else "Unknown Artist")
    album_name = sanitize_filename(album.name if album else "Unknown Album")
    track_title = sanitize_filename(track.name or "Unknown Track")
    year = album.release_date.year if album and album.release_date else "Unknown"
    track_number = track.track_num or 1
    
    # Create folder path from template
    folder_name = config.album_folder_template.format(
        artist=artist_name,
        album=album_name,
        year=year,
        quality=str(config.download_quality.value)
    )
    
    # Create file name from template
    file_name = config.track_file_template.format(
        track_number=track_number,
        title=track_title,
        artist=artist_name,
        album=album_name,
        quality=str(config.download_quality.value)
    )
    
    # Combine paths (extension will be added during download)
    output_path = config.download_folder / folder_name / file_name
    
    return output_path


def create_album_tasks(
    config: Config,
    session: tidalapi.Session,
    album: tidalapi.Album
) -> List[DownloadTask]:
    """Create download tasks for all tracks in an album"""
    tasks = []
    
    try:
        tracks = album.tracks()
        total_tracks = len(tracks)
        
        for idx, track in enumerate(tracks, 1):
            output_path = create_output_path(config, track, album)
            task = DownloadTask(
                id=f"track_{track.id}",
                item=track,
                item_type="track",
                output_path=output_path,
                album=album,
                track_number=idx,
                total_tracks=total_tracks,
            )
            tasks.append(task)
    except Exception as e:
        console.print(f"[red]Error creating album tasks: {e}[/red]")
    
    return tasks


def create_playlist_tasks(
    config: Config,
    session: tidalapi.Session,
    playlist: tidalapi.Playlist,
    as_compilation: bool = True
) -> List[DownloadTask]:
    """
    Create download tasks for all tracks in a playlist
    
    Args:
        config: Application config
        session: Tidal session
        playlist: Playlist to download
        as_compilation: If True, save as "Various Artists - PlaylistName" folder
                       and override metadata with playlist name as Album.
                       If False, organize by original artist/album with original metadata.
    """
    tasks = []
    
    try:
        tracks = playlist.tracks()
        total_tracks = len(tracks)
        
        playlist_folder = sanitize_filename(playlist.name or "Unknown Playlist")
        
        for idx, track in enumerate(tracks, 1):
            artist_name = sanitize_filename(track.artist.name if track.artist else "Unknown Artist")
            track_title = sanitize_filename(track.name or "Unknown Track")
            
            if as_compilation:
                # Save as single folder with playlist name
                file_name = f"{idx:02d} - {artist_name} - {track_title}"
                output_path = config.download_folder / playlist_folder / file_name
            else:
                # Organize by original artist/album
                album = track.album
                if album:
                    album_name = sanitize_filename(album.name or "Unknown Album")
                    year = album.release_date.year if album.release_date else "Unknown"
                    folder = f"{artist_name}/{album_name} [{year}]"
                else:
                    folder = f"{artist_name}/Singles"
                
                # Use track's album track number if available
                track_num = track.track_num if hasattr(track, 'track_num') and track.track_num else idx
                file_name = f"{track_num:02d} - {track_title}"
                output_path = config.download_folder / folder / file_name
            
            # Get playlist ID (could be 'id' or 'uuid' depending on API version)
            playlist_id = getattr(playlist, 'id', None) or getattr(playlist, 'uuid', 'unknown')
            
            task = DownloadTask(
                id=f"track_{track.id}_pl_{playlist_id}_{idx}",
                item=track,
                item_type="track",
                output_path=output_path,
                track_number=idx,
                total_tracks=total_tracks,
                album=track.album if hasattr(track, 'album') else None,
                # Pass playlist info for metadata override when downloading as compilation
                playlist_name=playlist.name if as_compilation else None,
                playlist_album_artist=config.playlist_album_artist if as_compilation else None,
            )
            tasks.append(task)
    except Exception as e:
        console.print(f"[red]Error creating playlist tasks: {e}[/red]")
    
    return tasks


def create_track_task(config: Config, track: tidalapi.Track) -> DownloadTask:
    """Create a download task for a single track"""
    output_path = create_output_path(config, track)
    return DownloadTask(
        id=f"track_{track.id}",
        item=track,
        item_type="track",
        output_path=output_path,
    )


def create_video_task(config: Config, video: tidalapi.Video) -> DownloadTask:
    """Create a download task for a video"""
    artist_name = sanitize_filename(video.artist.name if video.artist else "Unknown Artist")
    video_title = sanitize_filename(video.name or "Unknown Video")
    
    output_path = config.download_folder / "Videos" / artist_name / video_title
    
    return DownloadTask(
        id=f"video_{video.id}",
        item=video,
        item_type="video",
        output_path=output_path,
    )


def get_artist_albums(session: tidalapi.Session, artist: tidalapi.Artist) -> List[tidalapi.Album]:
    """Get all albums by an artist"""
    try:
        return artist.get_albums()
    except Exception as e:
        console.print(f"[red]Error fetching artist albums: {e}[/red]")
        return []


def save_album_art(album: tidalapi.Album, output_folder: Path, filename: str = "cover.jpg") -> bool:
    """Save album artwork to a file"""
    try:
        cover_url = album.image(1280)
        if cover_url:
            response = requests.get(cover_url)
            if response.status_code == 200:
                output_path = output_folder / filename
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"Saved album art: {output_path}")
                return True
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save album art: {e}[/yellow]")
        logger.error(f"Error saving album art: {e}")
    return False
