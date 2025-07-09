"""
Main Application Module

Initializes and configures the Flask application with all modules and services.
This module replaces the original main.py file with a modular architecture.
"""

import logging
import os
from flask import Flask
from flask_cors import CORS

from .config import validate_config, get_port, get_debug_mode, get_log_level, ALLOW_START_WITHOUT_DATABASE
from .database import test_database_connection
from .memory_manager import get_memory_manager
from .routes import register_routes

def create_app() -> Flask:
    """
    Create and configure the Flask application.
    
    Returns:
        Flask: Configured Flask application
    """
    # Validate configuration
    if not validate_config():
        raise RuntimeError("Configuration validation failed")
    
    # Create Flask app
    app = Flask(__name__)

        # Enable CORS for all routes
    CORS(app, resources={
        r"/*": {
            "origins": [
                "http://localhost:*", 
                "http://127.0.0.1:*",
                "https://ygopwa.onrender.com",
                "https://*.onrender.com"
            ],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            "supports_credentials": True,
            "expose_headers": ["Content-Length", "X-Foo", "X-Bar"],
            "max_age": 600  # Cache preflight request for 10 minutes
        }
    })
    
    # Configure logging
    log_level = getattr(logging, get_log_level())
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Initializing YGO Card Sets API...")
    
    # Initialize memory manager
    memory_manager = get_memory_manager()
    logger.info(f"Memory manager initialized with limit: {memory_manager.limit_mb}MB")
    
    # Test database connection
    database_available = test_database_connection()
    if not database_available:
        if ALLOW_START_WITHOUT_DATABASE:
            logger.warning("Database connection failed, but continuing startup as ALLOW_START_WITHOUT_DATABASE is enabled")
        else:
            logger.error("Database connection test failed")
            raise RuntimeError("Database connection failed")
    else:
        logger.info("Database connection test passed")
    
    # Register routes
    register_routes(app)
    logger.info("Routes registered successfully")
    
    # Log available endpoints
    logger.info("Available endpoints:")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.methods} {rule.rule}")
    
    return app

def run_app():
    """
    Run the Flask application.
    In production, uses Waitress as the WSGI server.
    In development, uses Flask's built-in server with debug mode.
    """
    app = create_app()
    port = get_port()
    debug = get_debug_mode()
    
    print(f"Starting YGO Card Sets API on port {port}...")
    print("Available endpoints:")
    print("  GET /health - Health check")
    print("  GET /card-sets - Get all card sets")
    print("  GET /card-sets/search/<set_name> - Search card sets by name")
    print("  POST /card-sets/upload - Upload card sets to MongoDB")
    print("  GET /card-sets/from-cache - Get card sets from MongoDB cache")
    print("  POST /card-sets/fetch-all-cards - Fetch all cards from all cached sets")
    print("  GET /card-sets/<set_name>/cards - Get all cards from a specific set")
    print("  GET /card-sets/count - Get total count of card sets")
    print("  POST /cards/price - Scrape card prices")
    print("  GET /cards/price/cache-stats - Get price cache statistics")
    print("  POST /debug/art-extraction - Debug art variant extraction")
    print("  POST /cards/upload-variants - Upload card variants to MongoDB")
    print("  GET /cards/variants - Get card variants from MongoDB cache")
    print("  GET /memory/stats - Get memory usage statistics")
    print("  POST /memory/cleanup - Force memory cleanup")
    
    if debug:
        # Use Flask's built-in server for development
        app.run(host='0.0.0.0', port=port, debug=debug)
    else:
        # Use Waitress for production
        from waitress import serve
        print(f"Starting Waitress WSGI server on port {port}...")
        print("Running in production mode (debug=False)")
        serve(app, host='0.0.0.0', port=port, threads=4)

if __name__ == '__main__':
    run_app()