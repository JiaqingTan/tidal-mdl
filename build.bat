@echo off
REM Build script for Tidal MDL (Windows)
REM Usage: build.bat

echo 🎵 Building Tidal MDL...

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
pyinstaller tidal-mdl.spec --clean

REM Check if build was successful
if exist "dist\tidal-mdl.exe" (
    echo.
    echo ✅ Build successful!
    echo 📦 Executable: dist\tidal-mdl.exe
    echo.
    echo To run: dist\tidal-mdl.exe
) else (
    echo ❌ Build failed!
    exit /b 1
)
