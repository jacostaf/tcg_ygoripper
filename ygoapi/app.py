"""
Main Application Module

Initializes and configures the Flask application with all modules and services.
This module replaces the original main.py file with a modular architecture.
"""

import logging
import os
from flask import Flask

from .config import validate_config, get_port, get_debug_mode, get_log_level
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
    if not test_database_connection():
        logger.error("Database connection test failed")
        raise RuntimeError("Database connection failed")
    
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
    
    app.run(host='0.0.0.0', port=port, debug=debug)

if __name__ == '__main__':
    run_app()