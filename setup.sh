#!/bin/bash
# Setup script for Tidal DL CLI

set -e

echo "🎵 Tidal DL CLI Setup"
echo "===================="
echo

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Python 3 is required"; exit 1; }

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create config if not exists
if [ ! -f .env ]; then
    echo "Creating default configuration..."
    cp .env.example .env
fi

# Create downloads folder
mkdir -p downloads

echo
echo "✅ Setup complete!"
echo
echo "To start using Tidal DL CLI:"
echo "  1. Activate the virtual environment: source venv/bin/activate"
echo "  2. Run the application: python cli.py"
echo
echo "Optional: Edit .env to customize your settings"
echo
