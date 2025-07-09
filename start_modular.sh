#!/bin/bash

# Print environment info
echo "=== Starting YGO API Modular Implementation on Render ==="
echo "Python version: $(python --version)"

# Set environment variables
export PYTHONPATH="$PYTHONPATH:$(pwd)"

# Set Playwright browser path for Render
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"

# Create necessary directories
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

# Install Playwright browser
echo "=== Installing Playwright browsers... ==="
pip install playwright
playwright install chromium
playwright install-deps

echo "=== Installing Python dependencies... ==="
pip install -r requirements.txt

# Check if we're running in a Render environment
if [ -n "$RENDER" ]; then
    echo "=== Detected Render environment ==="
    # Additional Render-specific setup can go here
fi

# Run the modular application
echo "=== Starting YGO API Modular Implementation... ==="
python ygoapi/main_modular.py

# Check if the application started successfully
if [ $? -eq 0 ]; then
    echo "=== YGO API Modular Implementation started successfully! ==="
else
    echo "=== Failed to start YGO API Modular Implementation ==="
    exit 1
fi
