# Tidal Media Downloader (Tidal-MDL)

A beautiful app to download high-quality music from Tidal.

## Features

- **Modern UI** - Clean, professional dark interface
- **Visual Search** - Album art thumbnails everywhere
- **Queue Management** - Full control over downloads
- **Configurable** - All settings in one place
- **Hi-Res Audio** - FLAC up to 24-bit/192kHz

## Quick Start

### Download

Download from [Releases](../../releases):

| Platform | File |
|----------|------|
| Windows | `tidal-mdl-gui-windows.exe` |
| macOS | `tidal-mdl-gui-macos.zip` |

### Run from Source

```bash
# Clone and setup
git clone https://github.com/yourusername/tidal-mdl.git
cd tidal-mdl
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run
python gui.py
```

### Optional: Install FFmpeg

FFmpeg enables native FLAC output for Hi-Res downloads:

```bash
# macOS
brew install ffmpeg

# Windows: https://ffmpeg.org/download.html
```

## Usage

Launch the application and:

1. **Search** - Find albums and tracks
2. **Add to Queue** - Click download on any result
3. **Monitor** - View progress in Downloads tab
4. **Configure** - Adjust settings as needed

## Configuration

All settings are configurable via the Settings page:

| Setting | Options |
|---------|---------|
| Download Quality | HI_RES, LOSSLESS, HIGH, NORMAL |
| Download Folder | Browse to select |
| Embed Album Art | On/Off |
| Skip Existing | On/Off |

### Quality Options

| Quality | Format |
|---------|--------|
| `HI_RES` | FLAC 24-bit up to 192kHz |
| `LOSSLESS` | FLAC 16-bit 44.1kHz |
| `HIGH` | AAC 320kbps |
| `NORMAL` | AAC 96kbps |

## Build

Build standalone executables:

```bash
# macOS/Linux
pyinstaller tidal-mdl-gui.spec --clean

# Windows
pyinstaller tidal-mdl-gui.spec --clean
```

## Disclaimer

- **Private use only** - Do not distribute copyrighted content
- **Requires Tidal HiFi subscription**
- **May violate Tidal ToS** - Use at your own risk
- **Educational purposes only**

## Credits

Built with:
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) - Modern UI
- [tidalapi](https://github.com/tamland/python-tidal) - Tidal API
- [Mutagen](https://github.com/quodlibet/mutagen) - Audio metadata
