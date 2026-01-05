#!/usr/bin/env bash
# Build script for Tidal Media Downloader (macOS/Linux)
# Usage: ./build.sh

set -e

echo "🎵 Building Tidal Media Downloader..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
pip install pyinstaller

# Build executable
echo "Building executable..."
pyinstaller tidal-media-downloader.spec --clean

# Check if build was successful
if [ -f "dist/tidal-media-downloader" ]; then
    echo ""
    echo "✅ Build successful!"
    echo "📦 Executable: dist/tidal-media-downloader"
    echo ""
    echo "To run: ./dist/tidal-media-downloader"
else
    echo "❌ Build failed!"
    exit 1
fi
