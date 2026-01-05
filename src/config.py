"""
Configuration management for Tidal DL CLI
Loads settings from .env file and provides defaults
"""

import os
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
    
    # Video
    video_quality: tidalapi.VideoQuality = tidalapi.VideoQuality.high
    
    # Behavior
    skip_existing: bool = True
    
    # Session file path
    session_file: Path = field(default_factory=lambda: Path.home() / ".tidal-media-downloader" / "session.json")


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
        load_dotenv()
    
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
        video_quality=video_quality,
        skip_existing=os.getenv("SKIP_EXISTING", "true").lower() == "true",
    )


def save_config(config: Config, env_path: Path = Path(".env")) -> None:
    """
    Save configuration to .env file
    
    Args:
        config: Config object to save
        env_path: Path to .env file
    """
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
    
    content = f"""# Tidal DL CLI Configuration

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

# Video Settings
VIDEO_QUALITY={video_quality_reverse.get(config.video_quality, "HIGH")}

# Behavior
SKIP_EXISTING={str(config.skip_existing).lower()}
"""
    
    env_path.write_text(content)
