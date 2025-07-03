"""
API Blueprints for the YGOAPI application.

API Package

This package contains all API endpoints and related functionality.
"""
from flask import Blueprint, jsonify
from functools import wraps
from typing import Callable, Any, Optional, Dict, List, Tuple, TypeVar, Union
from pydantic import BaseModel

# Create main API blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Import API blueprints
from .v1.cards import bp as cards_bp
from .v1.sets import bp as sets_bp

# Register blueprints
api_bp.register_blueprint(cards_bp, url_prefix='/v1/cards')
api_bp.register_blueprint(sets_bp, url_prefix='/v1/sets')

# Import decorators
from .decorators import (
    validate_json,
    paginate,
    handle_errors,
    require_auth,
    cache_control,
    PaginationParams
)

# Error handlers
@api_bp.errorhandler(404)
def not_found_error(error):
    return jsonify({"error": "Resource not found"}), 404

@api_bp.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

@api_bp.errorhandler(400)
def bad_request_error(error):
    return jsonify({"error": "Bad request"}), 400

@api_bp.errorhandler(401)
def unauthorized_error(error):
    return jsonify({"error": "Unauthorized"}), 401

@api_bp.errorhandler(403)
def forbidden_error(error):
    return jsonify({"error": "Forbidden"}), 403

# Health check endpoint
@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({"status": "healthy"}), 200

# API version endpoint
@api_bp.route('/version', methods=['GET'])
def api_version():
    """Get the current API version."""
    return jsonify({
        "api": "YGOPYGUY API",
        "version": "1.0.0",
        "status": "active"
    }), 200

# Import routes to register them with the blueprint
# This is done at the bottom to avoid circular imports
from . import cards, prices, sets  # noqa: E402

# Register blueprints with URL prefixes
api_bp.register_blueprint(cards.bp, url_prefix='/cards')
api_bp.register_blueprint(prices.bp, url_prefix='/prices')
api_bp.register_blueprint(sets.bp, url_prefix='/sets')

__all__ = ['api_bp']
