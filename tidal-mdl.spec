# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Tidal MDL
Build with: pyinstaller tidal-mdl.spec
"""

import sys
from pathlib import Path

# Determine if we're on Windows
is_windows = sys.platform == 'win32'

block_cipher = None

a = Analysis(
    ['cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env.example', '.'),
    ],
    hiddenimports=[
        'tidalapi',
        'tidalapi.session',
        'tidalapi.media',
        'tidalapi.album',
        'tidalapi.artist',
        'tidalapi.playlist',
        'tidalapi.user',
        'tidalapi.mix',
        'tidalapi.page',
        'mutagen',
        'mutagen.flac',
        'mutagen.mp4',
        'mutagen.id3',
        'rich',
        'rich.console',
        'rich.progress',
        'rich.table',
        'rich.panel',
        'click',
        'dotenv',
        'requests',
        'mpegdash',
        'mpegdash.parser',
        'isodate',
        'dateutil',
        'dateutil.parser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='tidal-mdl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if is_windows and Path('icon.ico').exists() else None,
)
