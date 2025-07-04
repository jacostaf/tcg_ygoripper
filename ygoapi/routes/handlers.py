"""
Flask routes for YGO API

HTTP endpoints and request handling.
"""

import asyncio
import logging
from flask import Blueprint, jsonify, request
from typing import Dict, Any

from ..services import get_price_service
from ..services.card_sets import get_card_set_service
from ..memory import get_memory_manager
from ..models import PriceRequestModel, MemoryStatsModel

logger = logging.getLogger(__name__)

# Create blueprints for different route groups
health_bp = Blueprint('health', __name__)
price_bp = Blueprint('price', __name__, url_prefix='/cards')
card_sets_bp = Blueprint('card_sets', __name__, url_prefix='/card-sets')
debug_bp = Blueprint('debug', __name__, url_prefix='/debug')

# Health check routes
@health_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    memory_manager = get_memory_manager()
    memory_stats = memory_manager.get_memory_usage()
    
    return jsonify({
        "status": "healthy",
        "message": "YGO API is running",
        "memory": {
            "usage_mb": memory_stats.get('rss_mb', 0),
            "limit_mb": memory_stats.get('limit_mb', 0),
            "level": memory_manager.get_memory_level()
        }
    })

# Price scraping routes
@price_bp.route('/price', methods=['POST'])
def scrape_card_price():
    """Scrape price data for a specific card from TCGPlayer.com."""
    try:
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({
                "success": False,
                "error": "No data provided in request body"
            }), 400
        
        # Validate request data
        try:
            price_request = PriceRequestModel(**data)
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Invalid request data: {str(e)}"
            }), 400
        
        # Get price service
        price_service = get_price_service()
        
        # Run async scraping
        result = asyncio.run(
            price_service.scrape_card_price(
                card_number=price_request.card_number,
                card_name=price_request.card_name,
                card_rarity=price_request.card_rarity,
                art_variant=price_request.art_variant,
                force_refresh=price_request.force_refresh
            )
        )
        
        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 500
    
    except Exception as e:
        logger.error(f"Error in price scraping endpoint: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error during price scraping"
        }), 500

@price_bp.route('/price/cache-stats', methods=['GET'])
def get_price_cache_stats():
    """Get statistics about the price cache collection."""
    try:
        price_service = get_price_service()
        stats = price_service.get_cache_stats()
        
        if stats:
            return jsonify({
                "success": True,
                "stats": stats
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to get cache statistics"
            }), 500
    
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to get cache statistics"
        }), 500

# Card sets routes
@card_sets_bp.route('', methods=['GET'])
def get_all_card_sets():
    """Get all card sets from YGO API."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.fetch_all_card_sets()
        
        if result["success"]:
            return jsonify(result)
        else:
            status_code = 504 if "timed out" in result["error"] else 500
            return jsonify(result), status_code
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@card_sets_bp.route('/search/<string:set_name>', methods=['GET'])
def search_card_sets(set_name: str):
    """Search for card sets by name."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.search_card_sets(set_name)
        
        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 500
    
    except Exception as e:
        logger.error(f"Error searching card sets: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@card_sets_bp.route('/upload', methods=['POST'])
def upload_card_sets_to_mongodb():
    """Upload card sets to MongoDB cache."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.upload_card_sets_to_cache()
        
        if result["success"]:
            return jsonify(result)
        else:
            status_code = 504 if "timed out" in result["error"] else 500
            return jsonify(result), status_code
    
    except Exception as e:
        logger.error(f"Unexpected error during upload: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during upload"
        }), 500

@card_sets_bp.route('/from-cache', methods=['GET'])
def get_card_sets_from_cache():
    """Get card sets from MongoDB cache."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.get_card_sets_from_cache()
        
        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 404 if "not found" in result["error"] else 500
    
    except Exception as e:
        logger.error(f"Error retrieving card sets from cache: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to retrieve card sets from cache"
        }), 500

@card_sets_bp.route('/count', methods=['GET'])
def get_card_sets_count():
    """Get total count of card sets in cache."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.get_card_sets_count()
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error getting card sets count: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to get card sets count"
        }), 500

@card_sets_bp.route('/<string:set_name>/cards', methods=['GET'])
def get_cards_from_specific_set(set_name: str):
    """Get all cards from a specific set."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.get_cards_from_set(set_name)
        
        if result["success"]:
            return jsonify(result)
        else:
            status_code = 404 if "not found" in result["error"] else 500
            return jsonify(result), status_code
    
    except Exception as e:
        logger.error(f"Error fetching cards from set {set_name}: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to fetch cards from set"
        }), 500

@card_sets_bp.route('/fetch-all-cards', methods=['POST'])
def fetch_all_cards_from_sets():
    """Fetch all cards from all cached sets."""
    try:
        card_set_service = get_card_set_service()
        result = card_set_service.fetch_all_cards_from_sets()
        
        if result["success"]:
            return jsonify(result)
        else:
            status_code = 404 if "not found" in result["error"] else 500
            return jsonify(result), status_code
    
    except Exception as e:
        logger.error(f"Unexpected error during card fetching: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during card fetching"
        }), 500

# Debug routes
@debug_bp.route('/memory-stats', methods=['GET'])
def get_memory_stats():
    """Get current memory usage statistics."""
    try:
        memory_manager = get_memory_manager()
        stats = memory_manager.get_memory_usage()
        
        memory_stats = MemoryStatsModel(
            rss_mb=stats.get('rss_mb', 0),
            vms_mb=stats.get('vms_mb', 0),
            percent=stats.get('percent', 0),
            limit_mb=stats.get('limit_mb', 0),
            usage_ratio=stats.get('usage_ratio', 0),
            available_mb=stats.get('available_mb', 0),
            level=memory_manager.get_memory_level()
        )
        
        return jsonify({
            "success": True,
            "memory_stats": memory_stats.dict()
        })
    
    except Exception as e:
        logger.error(f"Error getting memory stats: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to get memory statistics"
        }), 500

@debug_bp.route('/memory-cleanup', methods=['POST'])
def trigger_memory_cleanup():
    """Trigger memory cleanup and garbage collection."""
    try:
        memory_manager = get_memory_manager()
        
        # Get stats before cleanup
        before_stats = memory_manager.get_memory_usage()
        
        # Trigger cleanup
        cleanup_performed = memory_manager.check_memory_and_cleanup()
        
        # Get stats after cleanup
        after_stats = memory_manager.get_memory_usage()
        
        return jsonify({
            "success": True,
            "cleanup_performed": cleanup_performed,
            "before_cleanup": {
                "rss_mb": before_stats.get('rss_mb', 0),
                "level": memory_manager.get_memory_level()
            },
            "after_cleanup": {
                "rss_mb": after_stats.get('rss_mb', 0),
                "level": memory_manager.get_memory_level()
            }
        })
    
    except Exception as e:
        logger.error(f"Error triggering memory cleanup: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to trigger memory cleanup"
        }), 500

# Error handlers
@health_bp.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404

@health_bp.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500

# Function to register all blueprints
def register_routes(app):
    """Register all route blueprints with the Flask app."""
    app.register_blueprint(health_bp)
    app.register_blueprint(price_bp)
    app.register_blueprint(card_sets_bp)
    app.register_blueprint(debug_bp)
    
    # Register error handlers globally
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, internal_error)