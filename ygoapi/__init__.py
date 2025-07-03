""
YGOAPI - A Flask-based API for Yu-Gi-Oh! card data and pricing.

This package provides a RESTful API for accessing Yu-Gi-Oh! card information,
prices, and set data from various sources including TCGPlayer and PriceCharting.
"""
from flask import Flask
from .extensions import init_extensions, mongo
from .config import get_config

def create_app(config=None):
    """Create and configure the Flask application.
    
    Args:
        config: Configuration class or dictionary (optional)
    
    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)
    
    # Load configuration
    if config is None:
        config = get_config()
    app.config.from_object(config)
    
    # Initialize extensions
    init_extensions(app)
    
    # Register blueprints
    from .api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Register error handlers
    register_error_handlers(app)
    
    # Add health check endpoint
    @app.route('/health')
    def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "message": "YGO API is running"}
    
    # Add teardown context
    @app.teardown_appcontext
    def teardown_db(exception):
        """Close MongoDB connection when the application context is torn down."""
        mongo.close()
    
    return app

def register_error_handlers(app):
    ""Register error handlers for the application."""
    from werkzeug.exceptions import HTTPException
    
    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Not Found"}, 404
    
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Internal Server Error: {str(error)}")
        return {"error": "Internal Server Error"}, 500
    
    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        return {"error": error.description}, error.code
