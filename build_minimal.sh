#!/usr/bin/env bash

# Minimal build script for Render - use if main script fails

set -e

echo "=== Minimal Async Build ==="

# Essential steps only
pip install --upgrade pip
pip install -r requirements.txt
pip install playwright

# Install chromium without system deps (Render provides them)
playwright install chromium

echo "=== Build complete ==="
