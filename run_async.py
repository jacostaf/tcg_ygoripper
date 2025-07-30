#!/usr/bin/env python3
"""
Run the async YGO API with browser pooling support.
"""

import asyncio
import os
import sys

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ygoapi.async_app import run_async_app


if __name__ == "__main__":
    print("Starting Async YGO API with Browser Pooling...")
    print("=" * 60)
    print("Browser pool will be initialized on first request")
    print("Pool size: " + os.getenv('PLAYWRIGHT_POOL_SIZE', '2'))
    print("=" * 60)
    
    # Run the async app
    asyncio.run(run_async_app())
