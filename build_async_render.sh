#!/usr/bin/env bash

# Build script for async YGO API on Render
# This script handles all build requirements for the async browser pool implementation

set -e  # Exit on error

echo "============================================"
echo "YGO API Async Build Script for Render"
echo "============================================"

# Check if we're in Render environment
if [ -n "$RENDER" ]; then
    echo "✓ Detected Render environment"
else
    echo "⚠️  Warning: Not running in Render environment"
fi

# Python version check
echo ""
echo "=== Python Environment ==="
python --version
pip --version

# Upgrade pip first
echo ""
echo "=== Upgrading pip ==="
pip install --upgrade pip

# Install Python dependencies
echo ""
echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

# Install Playwright
echo ""
echo "=== Installing Playwright ==="
pip install playwright

# Install Chromium and its dependencies
echo ""
echo "=== Installing Chromium browser ==="
# Set Playwright to skip browser downloads if we're going to install via apt
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Install system dependencies for Chromium
echo "Installing system dependencies..."
playwright install-deps chromium

# Now install Chromium via Playwright
unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
playwright install chromium

# Verify installation
echo ""
echo "=== Verifying Playwright installation ==="
python -c "from playwright.sync_api import sync_playwright; print('✓ Playwright import successful')"

# Create necessary directories
echo ""
echo "=== Creating directories ==="
mkdir -p logs
mkdir -p cache

# Set permissions
echo ""
echo "=== Setting permissions ==="
chmod +x run_async.py 2>/dev/null || true
chmod +x build_async_render.sh 2>/dev/null || true

# Display environment info
echo ""
echo "=== Build Environment Summary ==="
echo "Python: $(python --version 2>&1)"
echo "Pip packages installed: $(pip list | wc -l)"
echo "Playwright version: $(pip show playwright | grep Version | cut -d' ' -f2)"
echo "Available memory: $(free -h | grep Mem | awk '{print $2}') (if available)"

# Test imports
echo ""
echo "=== Testing critical imports ==="
python -c "
import sys
try:
    import quart
    print('✓ Quart imported successfully')
except ImportError as e:
    print(f'✗ Quart import failed: {e}')
    sys.exit(1)

try:
    import playwright
    print('✓ Playwright imported successfully')
except ImportError as e:
    print(f'✗ Playwright import failed: {e}')
    sys.exit(1)

try:
    from ygoapi.async_app import create_async_app
    print('✓ Async app imported successfully')
except ImportError as e:
    print(f'✗ Async app import failed: {e}')
    sys.exit(1)
"

echo ""
echo "============================================"
echo "✓ Build completed successfully!"
echo "============================================"
echo ""
echo "To start the server, Render will run:"
echo "hypercorn ygoapi.async_app:create_async_app --bind 0.0.0.0:\$PORT --workers 1"
