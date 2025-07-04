#!/usr/bin/env python3
"""
YGO API - Yu-Gi-Oh! Card Database API

A modular Flask application for managing Yu-Gi-Oh! card data with price scraping,
memory optimization, and MongoDB caching.

Usage:
    python3 main.py

Environment Variables:
    - PORT: Server port (default: 8081)
    - MEM_LIMIT: Memory limit in MB (default: 512)
    - MONGODB_CONNECTION_STRING: MongoDB connection string
    - DEBUG_MODE: Enable debug mode (default: false)
"""

import logging
import os
import sys
from flask import Flask

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ygoapi.config import PORT, DEBUG_MODE, MEM_LIMIT
from ygoapi.memory import initialize_memory_manager, start_memory_monitoring
from ygoapi.routes import register_routes

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app() -> Flask:
    """Create and configure the Flask application."""
    
    app = Flask(__name__)
    
    # Initialize memory manager
    logger.info(f"Initializing memory manager with limit: {MEM_LIMIT}MB")
    memory_manager = initialize_memory_manager(MEM_LIMIT)
    
    # Start memory monitoring
    start_memory_monitoring()
    
    # Register all routes
    register_routes(app)
    
    # Add cleanup on app teardown
    @app.teardown_appcontext
    def cleanup_memory(exception):
        """Clean up memory on request teardown."""
        if memory_manager.get_memory_level() != "normal":
            memory_manager.force_garbage_collection()
    
    return app

def print_startup_info():
    """Print startup information and available endpoints."""
    print(f"🚀 Starting YGO Card Sets API on port {PORT}...")
    print(f"💾 Memory limit: {MEM_LIMIT}MB")
    print(f"🔧 Debug mode: {'enabled' if DEBUG_MODE else 'disabled'}")
    print()
    print("📋 Available endpoints:")
    print("  🏥 GET /health - Health check")
    print("  📊 GET /debug/memory-stats - Memory usage statistics")
    print("  🧹 POST /debug/memory-cleanup - Trigger memory cleanup")
    print()
    print("  🃏 GET /card-sets - Get all card sets")
    print("  🔍 GET /card-sets/search/<set_name> - Search card sets by name")
    print("  📤 POST /card-sets/upload - Upload card sets to MongoDB")
    print("  📂 GET /card-sets/from-cache - Get card sets from MongoDB cache")
    print("  📊 GET /card-sets/count - Get total count of card sets")
    print("  📋 GET /card-sets/<set_name>/cards - Get all cards from a specific set")
    print("  🔄 POST /card-sets/fetch-all-cards - Fetch all cards from all cached sets")
    print()
    print("  💰 POST /cards/price - Scrape price data for a specific card")
    print("  📊 GET /cards/price/cache-stats - Get price cache statistics")
    print()
    print("🌐 Server starting...")

if __name__ == '__main__':
    try:
        # Print startup information
        print_startup_info()
        
        # Create the Flask app
        app = create_app()
        
        # Run the application
        app.run(
            host='0.0.0.0',
            port=PORT,
            debug=DEBUG_MODE,
            threaded=True
        )
        
    except KeyboardInterrupt:
        logger.info("⏹️ Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        sys.exit(1)