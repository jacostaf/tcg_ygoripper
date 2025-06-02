#!/bin/bash

# Print environment info
echo "Starting YGO API deployment script"
echo "Node version: $(node -v)"
echo "Python version: $(python --version)"

# Install Playwright browser
echo "Installing Playwright browsers..."
playwright install chromium
echo "Playwright browser installation completed"

# Set environment variables if needed
export PLAYWRIGHT_BROWSERS_PATH="/opt/render/.cache/ms-playwright"

# Check if browser is installed correctly
if [ -d "$PLAYWRIGHT_BROWSERS_PATH/chromium-"* ]; then
  echo "Chromium browser is installed correctly"
else
  echo "WARNING: Chromium browser directory not found after installation"
  echo "Directories in $PLAYWRIGHT_BROWSERS_PATH:"
  ls -la "$PLAYWRIGHT_BROWSERS_PATH"
fi

# Start the application
echo "Starting application..."
python main.py