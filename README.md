# 🎵 Tidal MDL

A beautiful app to download high-quality music from Tidal.

![Screenshot](tidal-mdl-screenshot.png)

## Features

- 🎨 **Modern UI** - Beautiful pastel-themed interface
- 🖼️ **Visual Search** - Album art thumbnails everywhere
- 📥 **Queue Management** - Full control over downloads
- ⚙️ **Configurable** - All settings in one place
- 🎧 **Hi-Res Audio** - FLAC up to 24-bit/192kHz

## Quick Start

### Download Executable

Download from [Releases](../../releases):

| Platform | File |
|----------|------|
| Windows | `tidal-mdl-windows.exe` |
| macOS | `tidal-mdl-macos` |
| Linux | `tidal-mdl-linux` |

### Run from Source

```bash
# Clone and setup
git clone https://github.com/yourusername/tidal-mdl.git
cd tidal-mdl
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run GUI
python gui.py

# Or run CLI
python cli.py
```

### Optional: Install FFmpeg

FFmpeg enables native FLAC output for Hi-Res downloads:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian  
sudo apt install ffmpeg

# Windows: https://ffmpeg.org/download.html
```

## Usage

### GUI Mode (Recommended)

```bash
python gui.py
```

The GUI provides:
- 🔍 **Search** - Find albums, tracks, artists
- 📥 **Downloads** - Manage your download queue
- ⚙️ **Settings** - Configure all options visually

### CLI Mode

```bash
# Interactive mode
python cli.py

# Direct download
python cli.py --download "https://tidal.com/browse/album/12345678"
```

| Command | Description |
|---------|-------------|
| `search <query>` | Search for music |
| `dl-album <id>` | Download album |
| `dl-track <id>` | Download track |
| `dl-playlist <id>` | Download playlist |
| `queue` | View download queue |
| `help` | Show all commands |

## Configuration

Settings can be configured via:
- **GUI**: Settings page with visual controls
- **CLI**: Edit `.env` file

```ini
DOWNLOAD_QUALITY=HI_RES    # NORMAL, HIGH, LOSSLESS, HI_RES
DOWNLOAD_FOLDER=./downloads
EMBED_ALBUM_ART=true
```

### Quality Options

| Quality | Format |
|---------|--------|
| `HI_RES` | FLAC 24-bit up to 192kHz |
| `LOSSLESS` | FLAC 16-bit 44.1kHz |
| `HIGH` | AAC 320kbps |
| `NORMAL` | AAC 96kbps |

## Build

```bash
# macOS/Linux
./build.sh

# Windows
build.bat
```

## ⚠️ Disclaimer

- **Private use only** - Do not distribute copyrighted content
- **Requires Tidal HiFi subscription**
- **May violate Tidal ToS** - Use at your own risk
- **Educational purposes only**

## Credits

Built with:
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) - Modern UI
- [tidalapi](https://github.com/tamland/python-tidal) - Tidal API
- [Mutagen](https://github.com/quodlibet/mutagen) - Audio metadata
