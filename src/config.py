"""
Configuration management for Tidal MDL
Loads settings from .env file and provides defaults
"""

import sys
import os
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv
import tidalapi


@dataclass
class Config:
    """Application configuration loaded from .env file"""
    
    # Download quality
    download_quality: tidalapi.Quality = tidalapi.Quality.high_lossless
    
    # Concurrency settings
    max_concurrent_downloads: int = 3
    rate_limit_delay: float = 1.0
    
    # Paths
    download_folder: Path = field(default_factory=lambda: Path("./downloads"))
    
    # Templates
    album_folder_template: str = "{artist}/{album} [{year}]"
    track_file_template: str = "{track_number:02d} - {title}"
    
    # Metadata
    embed_album_art: bool = True
    embed_lyrics: bool = True
    save_album_art: bool = True
    album_art_filename: str = "cover.jpg"
    
    # Playlist settings
    playlist_album_artist: str = "Various Artists"
    
    # Video
    video_quality: tidalapi.VideoQuality = tidalapi.VideoQuality.high
    
    # Behavior
    skip_existing: bool = True
    
    # Session file path
    session_file: Path = field(default_factory=lambda: Path.home() / ".tidal-mdl" / "session.json")


def get_config_path() -> Path:
    """
    Return a user-writable path for the config (.env) file.

    When running inside a frozen PyInstaller bundle (e.g. macOS .app), the
    working directory is typically inside the read-only app bundle, so we
    store the config in ~/.tidal-mdl/config.env instead.

    In development (non-frozen), we use the traditional .env in the CWD.
    """
    if getattr(sys, "frozen", False):
        config_dir = Path.home() / ".tidal-mdl"
        config_dir.mkdir(parents=True, exist_ok=True)
        user_config = config_dir / "config.env"

        # Seed from the bundled .env on first run so the user starts with
        # sensible defaults that match .env.example.
        if not user_config.exists():
            # PyInstaller puts bundled data files in sys._MEIPASS
            bundled_env = Path(getattr(sys, "_MEIPASS", "")) / ".env"
            if bundled_env.exists():
                shutil.copy2(bundled_env, user_config)

        return user_config

    return Path(".env")


def load_config(env_path: Optional[Path] = None) -> Config:
    """
    Load configuration from .env file
    
    Args:
        env_path: Optional path to .env file. Defaults to .env in current directory.
    
    Returns:
        Config object with loaded or default values
    """
    # Load .env file
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv(get_config_path())
    
    # Map quality strings to tidalapi.Quality
    quality_map = {
        "NORMAL": tidalapi.Quality.low_96k,
        "HIGH": tidalapi.Quality.low_320k,
        "LOSSLESS": tidalapi.Quality.high_lossless,
        "HI_RES": tidalapi.Quality.hi_res_lossless,
    }
    
    video_quality_map = {
        "LOW": tidalapi.VideoQuality.low,
        "MEDIUM": tidalapi.VideoQuality.medium,
        "HIGH": tidalapi.VideoQuality.high,
    }
    
    # Parse config values
    quality_str = os.getenv("DOWNLOAD_QUALITY", "LOSSLESS").upper()
    download_quality = quality_map.get(quality_str, tidalapi.Quality.high_lossless)
    
    video_quality_str = os.getenv("VIDEO_QUALITY", "HIGH").upper()
    video_quality = video_quality_map.get(video_quality_str, tidalapi.VideoQuality.high)
    
    download_folder = Path(os.getenv("DOWNLOAD_FOLDER", "./downloads"))
    
    return Config(
        download_quality=download_quality,
        max_concurrent_downloads=int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3")),
        rate_limit_delay=float(os.getenv("RATE_LIMIT_DELAY", "1.0")),
        download_folder=download_folder,
        album_folder_template=os.getenv("ALBUM_FOLDER_TEMPLATE", "{artist}/{album} [{year}]"),
        track_file_template=os.getenv("TRACK_FILE_TEMPLATE", "{track_number:02d} - {title}"),
        embed_album_art=os.getenv("EMBED_ALBUM_ART", "true").lower() == "true",
        embed_lyrics=os.getenv("EMBED_LYRICS", "true").lower() == "true",
        save_album_art=os.getenv("SAVE_ALBUM_ART", "true").lower() == "true",
        album_art_filename=os.getenv("ALBUM_ART_FILENAME", "cover.jpg"),
        playlist_album_artist=os.getenv("PLAYLIST_ALBUM_ARTIST", "Various Artists"),
        video_quality=video_quality,
        skip_existing=os.getenv("SKIP_EXISTING", "true").lower() == "true",
    )


def save_config(config: Config, env_path: Optional[Path] = None) -> None:
    """
    Save configuration to .env file
    
    Args:
        config: Config object to save
        env_path: Path to .env file. Defaults to get_config_path().
    """
    if env_path is None:
        env_path = get_config_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    # Reverse quality maps
    quality_reverse = {
        tidalapi.Quality.low_96k: "NORMAL",
        tidalapi.Quality.low_320k: "HIGH",
        tidalapi.Quality.high_lossless: "LOSSLESS",
        tidalapi.Quality.hi_res_lossless: "HI_RES",
    }
    
    video_quality_reverse = {
        tidalapi.VideoQuality.low: "LOW",
        tidalapi.VideoQuality.medium: "MEDIUM",
        tidalapi.VideoQuality.high: "HIGH",
    }
    
    content = f"""# Tidal MDL Configuration

# Download Settings
DOWNLOAD_QUALITY={quality_reverse.get(config.download_quality, "LOSSLESS")}
MAX_CONCURRENT_DOWNLOADS={config.max_concurrent_downloads}
RATE_LIMIT_DELAY={config.rate_limit_delay}
DOWNLOAD_FOLDER={config.download_folder}

# Folder/File Templates
ALBUM_FOLDER_TEMPLATE={config.album_folder_template}
TRACK_FILE_TEMPLATE={config.track_file_template}

# Metadata Settings
EMBED_ALBUM_ART={str(config.embed_album_art).lower()}
EMBED_LYRICS={str(config.embed_lyrics).lower()}
SAVE_ALBUM_ART={str(config.save_album_art).lower()}
ALBUM_ART_FILENAME={config.album_art_filename}

# Playlist Settings
PLAYLIST_ALBUM_ARTIST={config.playlist_album_artist}

# Video Settings
VIDEO_QUALITY={video_quality_reverse.get(config.video_quality, "HIGH")}

# Behavior
SKIP_EXISTING={str(config.skip_existing).lower()}
"""
    
    env_path.write_text(content)
