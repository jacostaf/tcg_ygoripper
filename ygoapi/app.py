"""
Application Factory

This module contains the application factory function and configuration settings.
"""
import os
from flask import Flask, jsonify
from flask_cors import CORS
from .extensions import mongo, cors
from .api import api_bp
from .config import Config

def create_app(config_class=Config):
    """
    Create and configure the Flask application.
    
    Args:
        config_class: Configuration class to use (defaults to Config)
        
    Returns:
        Configured Flask application instance
    """
    # Create and configure the app
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config_class)
    
    # Initialize extensions
    mongo.init_app(app)
    cors.init_app(app, resources={
        r"/api/*": {"origins": app.config.get("CORS_ORIGINS", ["*"])}
    })
    
    # Register blueprints
    app.register_blueprint(api_bp)
    
    # Add error handlers
    register_error_handlers(app)
    
    # Add shell context
    @app.shell_context_processor
    def make_shell_context():
        return {
            'app': app,
            'mongo': mongo,
        }
    
    # Add health check endpoint
    @app.route('/health')
    def health_check():
        """Health check endpoint for monitoring."""
        return jsonify({"status": "healthy"}), 200
    
    # Add root endpoint
    @app.route('/')
    def index():
        """Root endpoint with API information."""
        return jsonify({
            "name": "YGOPYGUY API",
            "version": "1.0.0",
            "status": "active",
            "documentation": "/docs"
        })
    
    return app

def register_error_handlers(app):
    """Register error handlers for the application."""
    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({"error": "Not found"}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Internal server error: {str(error)}")
        return jsonify({"error": "Internal server error"}), 500
    
    @app.errorhandler(400)
    def bad_request_error(error):
        return jsonify({"error": "Bad request"}), 400
    
    @app.errorhandler(401)
    def unauthorized_error(error):
        return jsonify({"error": "Unauthorized"}), 401
    
    @app.errorhandler(403)
    def forbidden_error(error):
        return jsonify({"error": "Forbidden"}), 403
    
    @app.errorhandler(429)
    def ratelimit_error(error):
        return jsonify({
            "error": "Too many requests",
            "message": "Rate limit exceeded"
        }), 429
