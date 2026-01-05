@echo off
REM Build script for Tidal Media Downloader (Windows)
REM Usage: build.bat

echo 🎵 Building Tidal Media Downloader...

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

REM Build executable
echo Building executable...
pyinstaller tidal-media-downloader.spec --clean

REM Check if build was successful
if exist "dist\tidal-media-downloader.exe" (
    echo.
    echo ✅ Build successful!
    echo 📦 Executable: dist\tidal-media-downloader.exe
    echo.
    echo To run: dist\tidal-media-downloader.exe
) else (
    echo ❌ Build failed!
    exit /b 1
)
