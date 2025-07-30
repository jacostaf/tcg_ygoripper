#!/usr/bin/env bash

# Render-specific build script for async YGO API
# This avoids root permission issues on Render

set -e

echo "============================================"
echo "Render Build for YGO API (Async Browser Pool)"
echo "============================================"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright
echo "Installing Playwright..."
pip install playwright

# Install only Chromium browser (no system deps)
echo "Installing Chromium browser..."
PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/.playwright playwright install chromium

echo ""
echo "Build complete! ✓"
echo "Browser installed at: /opt/render/project/.playwright"
