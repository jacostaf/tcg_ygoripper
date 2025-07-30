"""
Async Application Module using Quart

This is the async version of the Flask app that supports proper browser pooling
and eliminates event loop conflicts.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime
from quart import Quart
from quart_cors import cors

from .config import (
    ALLOW_START_WITHOUT_DATABASE,
    get_debug_mode,
    get_log_level,
    get_port,
    validate_config,
)
from .database import test_database_connection
from .memory_manager import get_memory_manager
from .async_routes import register_async_routes
from .async_browser_pool import cleanup_browser_pool


def create_async_app() -> Quart:
    """
    Create and configure the Quart application.

    Returns:
        Quart: Configured Quart application
    """
    # Validate configuration
    if not validate_config():
        raise RuntimeError("Configuration validation failed")

    # Create Quart app
    app = Quart(__name__)

    # Enable CORS for all routes
    app = cors(
        app,
        allow_origin=[
            "http://localhost:*",
            "http://127.0.0.1:*",
            "https://ygopwa.onrender.com",
            "https://*.onrender.com",
        ],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
        allow_credentials=True,
        expose_headers=["Content-Length", "X-Foo", "X-Bar"],
        max_age=600,  # Cache preflight request for 10 minutes
    )

    # Configure logging
    log_level = getattr(logging, get_log_level())
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger = logging.getLogger(__name__)
    logger.info("Initializing Async YGO Card Sets API...")

    # Initialize memory manager
    memory_manager = get_memory_manager()
    logger.info(f"Memory manager initialized with limit: {memory_manager.limit_mb}MB")

    # Test database connection
    database_available = test_database_connection()
    if not database_available:
        if ALLOW_START_WITHOUT_DATABASE:
            logger.warning(
                "Database connection failed, but continuing startup as ALLOW_START_WITHOUT_DATABASE is enabled"
            )
        else:
            logger.error("Database connection test failed")
            raise RuntimeError("Database connection failed")
    else:
        logger.info("Database connection test passed")

    # Register async routes
    register_async_routes(app)
    logger.info("Async routes registered successfully")

    # Setup shutdown handler
    @app.after_serving
    async def shutdown():
        """Cleanup resources on shutdown."""
        logger.info("Shutting down async app...")
        await cleanup_browser_pool()
        logger.info("Cleanup completed")

    # Log available endpoints
    logger.info("Available endpoints:")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.methods} {rule.rule}")

    return app


async def run_async_app():
    """
    Run the Quart application with Hypercorn.
    """
    app = create_async_app()
    port = get_port()
    debug = get_debug_mode()

    print(f"Starting Async YGO Card Sets API on port {port}...")
    print("Available endpoints:")
    print("  GET /health - Health check")
    print("  GET /card-sets - Get all card sets")
    print("  GET /card-sets/search/<set_name> - Search card sets by name")
    print("  POST /card-sets/upload - Upload card sets to MongoDB")
    print("  GET /card-sets/from-cache - Get card sets from MongoDB cache")
    print("  POST /card-sets/fetch-all-cards - Fetch all cards from all cached sets")
    print("  GET /card-sets/<set_name>/cards - Get all cards from a specific set")
    print("  GET /card-sets/count - Get total count of card sets")
    print("  POST /cards/price - Scrape card prices (ASYNC)")
    print("  GET /cards/price/cache-stats - Get price cache statistics")
    print("  POST /debug/art-extraction - Debug art variant extraction")
    print("  POST /cards/upload-variants - Upload card variants to MongoDB")
    print("  GET /cards/variants - Get card variants from MongoDB cache")
    print("  GET /memory/stats - Get memory usage statistics")
    print("  POST /memory/cleanup - Force memory cleanup")
    print("  GET /browser/stats - Get browser pool statistics")

    if debug:
        # Use Quart's built-in server for development
        await app.run_task(host="0.0.0.0", port=port, debug=debug)
    else:
        # Use Hypercorn for production
        from hypercorn.asyncio import serve
        from hypercorn.config import Config

        config = Config()
        config.bind = [f"0.0.0.0:{port}"]
        config.workers = 1  # Single worker for browser pool sharing
        config.accesslog = "-"
        config.errorlog = "-"
        
        # Get worker threads from env var
        worker_threads = int(os.environ.get('HYPERCORN_THREADS', '4'))
        config.worker_class = "asyncio"
        
        print(f"Starting Hypercorn ASGI server on port {port}...")
        print(f"Running in production mode with {worker_threads} threads")
        
        await serve(app, config)


if __name__ == "__main__":
    asyncio.run(run_async_app())
