"""
TCGcsv Flask Application
Main Flask app using TCGcsv as the sole data source, no MongoDB required
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

from flask import Flask, jsonify, request
from flask_cors import CORS
try:
    import uvloop
    UVLOOP_AVAILABLE = True
except ImportError:
    UVLOOP_AVAILABLE = False

from tcgcsv_config import (
    PORT, DEBUG, LOG_LEVEL, get_cors_origins, 
    ENABLE_DEBUG_ENDPOINTS, validate_config
)
from tcgcsv_service import get_tcgcsv_service, cleanup_tcgcsv_service, Card, CardSet

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Configure CORS
cors_origins = get_cors_origins()
CORS(app, origins=cors_origins, supports_credentials=True)

# Set asyncio event loop policy for better performance
if UVLOOP_AVAILABLE and sys.platform != 'win32':
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Global variables
_background_tasks = set()

def run_async(coro):
    """Run async function in the Flask context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def create_error_response(message: str, status_code: int = 500, error_type: str = "error") -> tuple:
    """Create standardized error response."""
    return jsonify({
        "success": False,
        "error": {
            "type": error_type,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
    }), status_code

def create_success_response(data: Any, message: str = "Success") -> Dict[str, Any]:
    """Create standardized success response."""
    return jsonify({
        "success": True,
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat()
    })

# =============================================================================
# HEALTH AND STATUS ENDPOINTS
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        service = run_async(get_tcgcsv_service())
        cache_stats = service.get_cache_stats()
        
        return create_success_response({
            "status": "healthy",
            "service": "tcgcsv-api",
            "cache": cache_stats,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return create_error_response(f"Service unhealthy: {str(e)}")

@app.route('/status', methods=['GET'])
def get_status():
    """Get detailed service status."""
    try:
        service = run_async(get_tcgcsv_service())
        cache_stats = service.get_cache_stats()
        
        config_validation = validate_config()
        
        status_data = {
            "service": "TCGcsv Yu-Gi-Oh API",
            "version": "1.0.0-tcgcsv",
            "environment": "development" if DEBUG else "production",
            "data_source": "TCGcsv.com",
            "cache": cache_stats,
            "configuration": {
                "valid": config_validation["valid"],
                "warnings": config_validation.get("warnings", [])
            }
        }
        
        return create_success_response(status_data)
        
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return create_error_response(f"Failed to get status: {str(e)}")

# =============================================================================
# CARD SETS ENDPOINTS
# =============================================================================

@app.route('/card-sets', methods=['GET'])
@app.route('/card-sets/from-cache', methods=['GET'])
def get_card_sets():
    """Get all card sets from TCGcsv."""
    try:
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        
        service = run_async(get_tcgcsv_service())
        card_sets = run_async(service.get_card_sets(force_refresh=force_refresh))
        
        # Convert to frontend-compatible format
        sets_data = []
        for card_set in card_sets:
            set_dict = card_set.to_dict()
            # Map to expected frontend format
            set_dict.update({
                'id': card_set.abbreviation or str(card_set.group_id),
                'set_name': card_set.name,
                'set_code': card_set.abbreviation,
                'tcg_date': card_set.published_on,
                'group_id': card_set.group_id
            })
            sets_data.append(set_dict)
        
        return create_success_response(sets_data, f"Retrieved {len(sets_data)} card sets")
        
    except Exception as e:
        logger.error(f"Failed to get card sets: {e}")
        return create_error_response(f"Failed to retrieve card sets: {str(e)}")

@app.route('/card-sets/<set_identifier>/cards', methods=['GET'])
def get_set_cards(set_identifier: str):
    """Get all cards for a specific set."""
    try:
        service = run_async(get_tcgcsv_service())
        
        # Try to find set by abbreviation or group_id
        card_sets = run_async(service.get_card_sets())
        target_set = None
        
        # First try by abbreviation
        for card_set in card_sets:
            if card_set.abbreviation.upper() == set_identifier.upper():
                target_set = card_set
                break
        
        # If not found, try by group_id
        if not target_set:
            try:
                group_id = int(set_identifier)
                for card_set in card_sets:
                    if card_set.group_id == group_id:
                        target_set = card_set
                        break
            except ValueError:
                pass
        
        if not target_set:
            return create_error_response(f"Set '{set_identifier}' not found", 404, "not_found")
        
        # Get cards for the set
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        cards = run_async(service.get_cards_for_set(target_set.group_id, force_refresh=force_refresh))
        
        # Convert to frontend-compatible format
        cards_data = []
        for card in cards:
            card_dict = card.to_dict()
            # Map to expected frontend format
            card_dict.update({
                'id': str(card.product_id),
                'name': card.name,
                'rarity': card.ext_rarity,
                'set_code': target_set.abbreviation,
                'card_number': card.ext_number,
                'attack': card.ext_attack,
                'defense': card.ext_defense,
                'level': card.ext_link_rating,  # For now, map link rating to level
                'attribute': card.ext_attribute,
                'type': card.ext_card_type,
                'race': card.ext_monster_type,
                'image_url': card.get_image_url(),
                'tcg_price': card.get_primary_price(),
                'market_price': card.market_price,
                'low_price': card.low_price,
                'mid_price': card.mid_price,
                'high_price': card.high_price
            })
            cards_data.append(card_dict)
        
        return create_success_response({
            'set_info': target_set.to_dict(),
            'cards': cards_data
        }, f"Retrieved {len(cards_data)} cards for set {set_identifier}")
        
    except Exception as e:
        logger.error(f"Failed to get cards for set {set_identifier}: {e}")
        return create_error_response(f"Failed to retrieve cards for set: {str(e)}")

@app.route('/card-sets/search/<query>', methods=['GET'])
def search_card_sets(query: str):
    """Search card sets by name."""
    try:
        service = run_async(get_tcgcsv_service())
        card_sets = run_async(service.get_card_sets())
        
        # Filter sets by query
        query_lower = query.lower()
        matching_sets = [
            card_set for card_set in card_sets
            if query_lower in card_set.name.lower() or 
               query_lower in card_set.abbreviation.lower()
        ]
        
        # Convert to frontend format
        sets_data = []
        for card_set in matching_sets:
            set_dict = card_set.to_dict()
            set_dict.update({
                'id': card_set.abbreviation or str(card_set.group_id),
                'set_name': card_set.name,
                'set_code': card_set.abbreviation,
                'tcg_date': card_set.published_on
            })
            sets_data.append(set_dict)
        
        return create_success_response(sets_data, f"Found {len(sets_data)} matching sets")
        
    except Exception as e:
        logger.error(f"Failed to search card sets: {e}")
        return create_error_response(f"Failed to search card sets: {str(e)}")

# =============================================================================
# CARD SEARCH AND PRICING ENDPOINTS
# =============================================================================

@app.route('/cards/search', methods=['GET'])
def search_cards():
    """Search for cards by name."""
    try:
        query = request.args.get('q', '').strip()
        set_filter = request.args.get('set', '').strip()
        
        if not query:
            return create_error_response("Query parameter 'q' is required", 400, "bad_request")
        
        service = run_async(get_tcgcsv_service())
        
        # Determine group_id if set filter provided
        group_id = None
        if set_filter:
            card_sets = run_async(service.get_card_sets())
            for card_set in card_sets:
                if (card_set.abbreviation.upper() == set_filter.upper() or 
                    str(card_set.group_id) == set_filter):
                    group_id = card_set.group_id
                    break
        
        # Search for cards
        cards = run_async(service.search_cards(query, group_id))
        
        # Convert to frontend format
        cards_data = []
        for card in cards:
            card_dict = {
                'id': str(card.product_id),
                'name': card.name,
                'rarity': card.ext_rarity,
                'card_number': card.ext_number,
                'image_url': card.get_image_url(),
                'tcg_price': card.get_primary_price(),
                'market_price': card.market_price,
                'set_code': card.group_id  # Would need mapping to abbreviation
            }
            cards_data.append(card_dict)
        
        return create_success_response(cards_data, f"Found {len(cards_data)} matching cards")
        
    except Exception as e:
        logger.error(f"Failed to search cards: {e}")
        return create_error_response(f"Failed to search cards: {str(e)}")

@app.route('/cards/price', methods=['POST'])
def get_card_price():
    """Get price information for a specific card (maintains compatibility)."""
    try:
        data = request.get_json()
        if not data:
            return create_error_response("JSON data required", 400, "bad_request")
        
        card_name = data.get('cardName', '').strip()
        set_code = data.get('setCode', '').strip()
        
        if not card_name:
            return create_error_response("cardName is required", 400, "bad_request")
        
        service = run_async(get_tcgcsv_service())
        
        # Search for the specific card
        group_id = None
        if set_code:
            card_sets = run_async(service.get_card_sets())
            for card_set in card_sets:
                if card_set.abbreviation.upper() == set_code.upper():
                    group_id = card_set.group_id
                    break
        
        cards = run_async(service.search_cards(card_name, group_id))
        
        if not cards:
            return create_error_response(f"Card '{card_name}' not found", 404, "not_found")
        
        # Find best match (exact name match preferred)
        best_card = None
        for card in cards:
            if card.name.lower() == card_name.lower():
                best_card = card
                break
        
        if not best_card:
            best_card = cards[0]  # Use first match
        
        # Format response similar to original API
        price_data = {
            'success': True,
            'cardName': best_card.name,
            'setCode': set_code,
            'rarity': best_card.ext_rarity,
            'tcgPrice': best_card.get_primary_price(),
            'marketPrice': best_card.market_price,
            'lowPrice': best_card.low_price,
            'midPrice': best_card.mid_price,
            'highPrice': best_card.high_price,
            'imageUrl': best_card.get_image_url(),
            'source': 'tcgcsv',
            'productId': best_card.product_id
        }
        
        return jsonify(price_data)
        
    except Exception as e:
        logger.error(f"Failed to get card price: {e}")
        return create_error_response(f"Failed to get card price: {str(e)}")

# =============================================================================
# CACHE AND ADMIN ENDPOINTS
# =============================================================================

@app.route('/cache/stats', methods=['GET'])
def get_cache_stats():
    """Get cache statistics."""
    try:
        service = run_async(get_tcgcsv_service())
        stats = service.get_cache_stats()
        return create_success_response(stats)
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return create_error_response(f"Failed to get cache stats: {str(e)}")

@app.route('/cache/refresh', methods=['POST'])
def refresh_cache():
    """Force refresh cache from TCGcsv."""
    try:
        service = run_async(get_tcgcsv_service())
        
        # Refresh sets
        card_sets = run_async(service.get_card_sets(force_refresh=True))
        
        # Optionally refresh all cards (this could be expensive)
        refresh_cards = request.json and request.json.get('refresh_cards', False)
        cards_refreshed = 0
        
        if refresh_cards:
            for card_set in card_sets:
                run_async(service.get_cards_for_set(card_set.group_id, force_refresh=True))
                cards_refreshed += 1
        
        return create_success_response({
            'sets_refreshed': len(card_sets),
            'cards_sets_refreshed': cards_refreshed
        }, "Cache refreshed successfully")
        
    except Exception as e:
        logger.error(f"Failed to refresh cache: {e}")
        return create_error_response(f"Failed to refresh cache: {str(e)}")

# =============================================================================
# DEBUG ENDPOINTS (if enabled)
# =============================================================================

if ENABLE_DEBUG_ENDPOINTS:
    @app.route('/debug/config', methods=['GET'])
    def debug_config():
        """Get configuration (debug only)."""
        config_validation = validate_config()
        return create_success_response(config_validation)
    
    @app.route('/debug/raw-set/<int:group_id>', methods=['GET'])
    def debug_raw_set(group_id: int):
        """Get raw set data (debug only)."""
        try:
            service = run_async(get_tcgcsv_service())
            cards = run_async(service.get_cards_for_set(group_id, force_refresh=True))
            return create_success_response([card.to_dict() for card in cards])
        except Exception as e:
            return create_error_response(f"Debug error: {str(e)}")

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found_error(error):
    return create_error_response("Endpoint not found", 404, "not_found")

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return create_error_response("Internal server error", 500, "internal_error")

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    return create_error_response(f"Unexpected error: {str(e)}", 500, "unexpected_error")

# =============================================================================
# APPLICATION LIFECYCLE
# =============================================================================

def initialize_app():
    """Initialize the application on startup."""
    logger.info("Initializing TCGcsv application...")
    config_validation = validate_config()
    
    if not config_validation["valid"]:
        logger.error("Configuration validation failed:")
        for issue in config_validation["issues"]:
            logger.error(f"  - {issue}")
        sys.exit(1)
    
    if config_validation["warnings"]:
        logger.warning("Configuration warnings:")
        for warning in config_validation["warnings"]:
            logger.warning(f"  - {warning}")

def cleanup_app():
    """Cleanup application resources."""
    logger.info("Cleaning up TCGcsv application...")
    run_async(cleanup_tcgcsv_service())

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    try:
        logger.info("Starting TCGcsv Yu-Gi-Oh API server...")
        logger.info(f"Port: {PORT}, Debug: {DEBUG}")
        
        # Initialize application
        initialize_app()
        
        # Test connectivity
        logger.info("Testing TCGcsv connectivity...")
        import requests
        test_response = requests.get("https://tcgcsv.com/tcgplayer/2/Groups.csv", timeout=10)
        if test_response.status_code == 200:
            logger.info("✅ TCGcsv connectivity test passed")
        else:
            logger.warning(f"⚠️ TCGcsv returned status {test_response.status_code}")
        
        app.run(
            host='0.0.0.0',
            port=PORT,
            debug=DEBUG,
            threaded=True
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)
    finally:
        cleanup_app()