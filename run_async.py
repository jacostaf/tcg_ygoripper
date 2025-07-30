#!/usr/bin/env python3
"""
Run the async YGO API with browser pooling support.
"""

import asyncio
import os
import sys

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Starting async YGO API...")
print(f"Python path: {sys.path}")
print(f"Working directory: {os.getcwd()}")

try:
    from ygoapi.async_app import app
    print("Successfully imported app instance")
    
    # For direct execution
    if __name__ == "__main__":
        from ygoapi.async_app import run_async_app
        print("=" * 60)
        print("Browser pool will be initialized on first request")
        print("Pool size: " + os.getenv('PLAYWRIGHT_POOL_SIZE', '2'))
        print("=" * 60)
        asyncio.run(run_async_app())
except Exception as e:
    print(f"Error during startup: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
