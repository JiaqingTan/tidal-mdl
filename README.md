# Tidal MDL

A desktop app for downloading high-quality music from Tidal, with a modern dark UI and full queue management.

![Screenshot](tidal-mdl-screenshot.png)

---

## Releases & Downloads

Grab the latest build from [**Releases**](../../releases):

| Platform | File |
|----------|------|
| Windows  | `tidal-mdl-gui-windows.exe` |
| macOS    | `tidal-mdl-gui-macos.zip` |

> **FFmpeg** (optional) is needed to remux Hi-Res/Lossless streams into native `.flac` files.
> Without it, FLAC audio is saved in an `.m4a` container (still lossless).
>
> ```bash
> # macOS
> brew install ffmpeg
>
> # Windows — download from https://ffmpeg.org/download.html
> ```

---

## Directories

The app stores configuration, session, and log files in the following locations.

### macOS

| Purpose | Path |
|---------|------|
| Config  | `~/.tidal-mdl/config.env` |
| Session | `~/.tidal-mdl/session.json` |
| Logs    | `~/Library/Logs/TidalMDL/` |

### Windows

| Purpose | Path |
|---------|------|
| Config  | `%USERPROFILE%\.tidal-mdl\config.env` |
| Session | `%USERPROFILE%\.tidal-mdl\session.json` |
| Logs    | `%APPDATA%\TidalMDL\logs\` |

### Linux

| Purpose | Path |
|---------|------|
| Config  | `~/.tidal-mdl/config.env` |
| Session | `~/.tidal-mdl/session.json` |
| Logs    | `~/.tidal-mdl/logs/` |

> When running from source (non-bundled), config is read from `.env` in the project directory instead.

---

## Troubleshooting

### Authentication issues

Delete the cached session and restart:

```bash
# macOS / Linux
rm ~/.tidal-mdl/session.json

# Windows (PowerShell)
Remove-Item "$env:USERPROFILE\.tidal-mdl\session.json"
```

### "Read-only file system" error on macOS

This has been fixed. If you're on an older build, update to the latest release. The app now writes settings to `~/.tidal-mdl/config.env` instead of inside the app bundle.

### Logs

Check the log files listed in [Directories](#directories) above for detailed error output. Two log files are produced:

- `tidal.log` — standard log
- `tidal-debug.log` — verbose debug log

---

## Source Usage

### Setup

```bash
git clone https://github.com/yourusername/tidal-mdl.git
cd tidal-mdl
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
python gui.py
```

### Build

```bash
pip install pyinstaller
pyinstaller tidal-mdl-gui.spec --clean
```

Output is in `dist/`. On macOS this produces `Tidal MDL.app`; on Windows, `tidal-mdl-gui.exe`.

---

## Disclaimers

- **Private use only** — do not distribute copyrighted content.
- **Requires a Tidal HiFi subscription.**
- **May violate Tidal's Terms of Service** — use at your own risk.
- **For educational purposes only.**

---

## Credits

Built with:

- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — modern UI framework
- [tidalapi](https://github.com/tamland/python-tidal) — Tidal API client
- [Mutagen](https://github.com/quodlibet/mutagen) — audio metadata
- [python-dotenv](https://github.com/theskumar/python-dotenv) — config management

Development assisted by **Google Antigravity** and **Claude Opus** 🎵
