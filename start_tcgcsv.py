#!/usr/bin/env python3
"""
TCGcsv Implementation Startup Script
Simple launcher for the TCGcsv-based Yu-Gi-Oh API
"""

import os
import sys
import logging
import argparse
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tcgcsv_config import validate_config, PORT, DEBUG
from tcgcsv_app import app, cleanup_app

def setup_logging(log_level: str = "INFO"):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )

def check_environment():
    """Check if environment is properly configured."""
    # Validate configuration
    validation = validate_config()
    
    if not validation["valid"]:
        print("❌ Configuration validation failed:")
        for issue in validation["issues"]:
            print(f"   - {issue}")
        return False
    
    if validation["warnings"]:
        print("⚠️  Configuration warnings:")
        for warning in validation["warnings"]:
            print(f"   - {warning}")
    
    # Check if data directory exists
    data_dir = Path("./data")
    if not data_dir.exists():
        print(f"📁 Creating data directory: {data_dir}")
        data_dir.mkdir(exist_ok=True)
    
    return True

def print_startup_info():
    """Print startup information."""
    print("🎯 TCGcsv Yu-Gi-Oh API Server")
    print("=" * 50)
    print(f"📡 Data Source: TCGcsv.com")
    print(f"🌐 Port: {PORT}")
    print(f"🔧 Debug Mode: {DEBUG}")
    print(f"📂 Working Directory: {os.getcwd()}")
    print("=" * 50)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="TCGcsv Yu-Gi-Oh API Server")
    parser.add_argument("--port", type=int, default=PORT, help="Port to run on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--validate-only", action="store_true", help="Only validate configuration and exit")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    try:
        # Check environment
        if not check_environment():
            sys.exit(1)
        
        if args.validate_only:
            print("✅ Configuration is valid!")
            sys.exit(0)
        
        # Print startup info
        print_startup_info()
        
        # Test TCGcsv connectivity
        print("🔍 Testing TCGcsv connectivity...")
        try:
            import requests
            response = requests.get("https://tcgcsv.com/tcgplayer/2/Groups.csv", timeout=10)
            if response.status_code == 200:
                print("✅ TCGcsv connectivity test passed")
            else:
                print(f"⚠️  TCGcsv returned status {response.status_code}")
        except Exception as e:
            print(f"❌ TCGcsv connectivity test failed: {e}")
            print("   - Check your internet connection")
            print("   - Verify TCGcsv.com is accessible")
            sys.exit(1)
        
        print("🚀 Starting server...")
        
        # Start the Flask app
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug or DEBUG,
            threaded=True,
            use_reloader=False  # Disable reloader for better async compatibility
        )
        
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
        logger.info("Server stopped by user interrupt")
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        logger.error(f"Server startup failed: {e}")
        sys.exit(1)
    finally:
        print("🧹 Cleaning up...")
        cleanup_app()
        print("✅ Cleanup complete")

if __name__ == "__main__":
    main()