"""
TCGcsv Flask Application - Fixed for proper async handling
"""

import asyncio
import logging
import sys
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request
from flask_cors import CORS

from tcgcsv_config import (
    PORT, DEBUG, LOG_LEVEL, get_cors_origins, 
    ENABLE_DEBUG_ENDPOINTS, validate_config
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app, origins=get_cors_origins(), supports_credentials=True)

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=4)

# Simple synchronous version of the service
from tcgcsv_simple_app import SimpleCache, CardSet, Card, fetch_card_sets, fetch_cards_for_set

# Global cache
cache = SimpleCache()

def create_success_response(data: Any, message: str = "Success") -> Dict[str, Any]:
    """Create standardized success response."""
    return jsonify({
        "success": True,
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat()
    })

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

# =============================================================================
# HEALTH AND STATUS ENDPOINTS
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        cache_stats = {
            "cache_hits": getattr(cache, 'cache_hits', 0),
            "cache_misses": getattr(cache, 'cache_misses', 0),
            "hit_rate": 0.0,
            "sets_count": len(cache.card_sets),
            "cards_count": sum(len(cards) for cards in cache.cards.values()),
            "last_updated": cache.last_updated.isoformat() if cache.last_updated else None,
            "is_expired": cache.is_expired()
        }
        
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
        cache_stats = {
            "sets_count": len(cache.card_sets),
            "cards_count": sum(len(cards) for cards in cache.cards.values()),
            "last_updated": cache.last_updated.isoformat() if cache.last_updated else None,
            "is_expired": cache.is_expired()
        }
        
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
        
        # Check cache first
        cached_sets = cache.get_sets()
        if not cached_sets or force_refresh:
            logger.info("Fetching fresh card sets from TCGcsv...")
            cached_sets = fetch_card_sets()
            cache.update_sets(cached_sets)
        else:
            logger.info(f"Returning {len(cached_sets)} sets from cache")
        
        # Convert to frontend-compatible format
        sets_data = []
        for card_set in cached_sets:
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
        # Find the set
        sets = cache.get_sets()
        if not sets:
            sets = fetch_card_sets()
            cache.update_sets(sets)
        
        target_set = None
        for card_set in sets:
            if (card_set.abbreviation and card_set.abbreviation.upper() == set_identifier.upper()) or \
               str(card_set.group_id) == set_identifier:
                target_set = card_set
                break
        
        if not target_set:
            return create_error_response(f"Set '{set_identifier}' not found", 404, "not_found")
        
        # Get cards
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        cards = cache.get_cards(target_set.group_id)
        if not cards or force_refresh:
            logger.info(f"Fetching cards for set {target_set.group_id} from TCGcsv...")
            cards = fetch_cards_for_set(target_set.group_id)
            cache.update_cards(target_set.group_id, cards)
        else:
            logger.info(f"Returning {len(cards)} cards from cache for set {set_identifier}")
        
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
                'level': None,  # TCGcsv doesn't have level data
                'attribute': card.ext_attribute,
                'type': card.ext_card_type,
                'race': card.ext_monster_type,
                'image_url': card.image_url,
                'tcg_price': card.market_price or card.mid_price or card.low_price,
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
        sets = cache.get_sets()
        if not sets:
            sets = fetch_card_sets()
            cache.update_sets(sets)
        
        # Filter sets by query
        query_lower = query.lower()
        matching_sets = [
            card_set for card_set in sets
            if query_lower in card_set.name.lower() or 
               (card_set.abbreviation and query_lower in card_set.abbreviation.lower())
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
# CARD PRICING ENDPOINT (COMPATIBILITY)
# =============================================================================

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
        
        # Find set if provided
        target_group_id = None
        if set_code:
            sets = cache.get_sets()
            if not sets:
                sets = fetch_card_sets()
                cache.update_sets(sets)
            
            for card_set in sets:
                if card_set.abbreviation and card_set.abbreviation.upper() == set_code.upper():
                    target_group_id = card_set.group_id
                    break
        
        # Search for card
        found_card = None
        if target_group_id:
            # Search in specific set
            cards = cache.get_cards(target_group_id)
            if not cards:
                cards = fetch_cards_for_set(target_group_id)
                cache.update_cards(target_group_id, cards)
            
            for card in cards:
                if card.name.lower() == card_name.lower():
                    found_card = card
                    break
        else:
            # Search in all sets (this could be expensive)
            sets = cache.get_sets()
            if not sets:
                sets = fetch_card_sets()
                cache.update_sets(sets)
            
            # Only search in a few recent sets to avoid timeout
            recent_sets = sets[:10]  # Limit search scope
            for card_set in recent_sets:
                cards = cache.get_cards(card_set.group_id)
                if not cards:
                    cards = fetch_cards_for_set(card_set.group_id)
                    cache.update_cards(card_set.group_id, cards)
                
                for card in cards:
                    if card.name.lower() == card_name.lower():
                        found_card = card
                        break
                if found_card:
                    break
        
        if not found_card:
            return create_error_response(f"Card '{card_name}' not found", 404, "not_found")
        
        # Format response similar to original API
        price_data = {
            'success': True,
            'cardName': found_card.name,
            'setCode': set_code,
            'rarity': found_card.ext_rarity,
            'tcgPrice': found_card.market_price or found_card.mid_price or found_card.low_price,
            'marketPrice': found_card.market_price,
            'lowPrice': found_card.low_price,
            'midPrice': found_card.mid_price,
            'highPrice': found_card.high_price,
            'imageUrl': found_card.image_url,
            'source': 'tcgcsv',
            'productId': found_card.product_id
        }
        
        return jsonify(price_data)
        
    except Exception as e:
        logger.error(f"Failed to get card price: {e}")
        return create_error_response(f"Failed to get card price: {str(e)}")

# =============================================================================
# CACHE ENDPOINTS
# =============================================================================

@app.route('/cache/stats', methods=['GET'])
def get_cache_stats():
    """Get cache statistics."""
    try:
        stats = {
            "sets_count": len(cache.card_sets),
            "cards_count": sum(len(cards) for cards in cache.cards.values()),
            "last_updated": cache.last_updated.isoformat() if cache.last_updated else None,
            "is_expired": cache.is_expired(),
            "loaded_sets": list(cache.cards.keys())
        }
        return create_success_response(stats)
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return create_error_response(f"Failed to get cache stats: {str(e)}")

@app.route('/cache/refresh', methods=['POST'])
def refresh_cache():
    """Force refresh cache from TCGcsv."""
    try:
        # Refresh sets
        logger.info("Force refreshing card sets...")
        card_sets = fetch_card_sets()
        cache.update_sets(card_sets)
        
        # Optionally refresh cards
        refresh_cards = request.json and request.json.get('refresh_cards', False)
        cards_refreshed = 0
        
        if refresh_cards:
            logger.info("Force refreshing all card data...")
            for card_set in card_sets[:5]:  # Limit to first 5 sets to avoid timeout
                cards = fetch_cards_for_set(card_set.group_id)
                cache.update_cards(card_set.group_id, cards)
                cards_refreshed += 1
        
        return create_success_response({
            'sets_refreshed': len(card_sets),
            'cards_sets_refreshed': cards_refreshed
        }, "Cache refreshed successfully")
        
    except Exception as e:
        logger.error(f"Failed to refresh cache: {e}")
        return create_error_response(f"Failed to refresh cache: {str(e)}")

# =============================================================================
# DEBUG ENDPOINTS
# =============================================================================

if ENABLE_DEBUG_ENDPOINTS:
    @app.route('/debug/config', methods=['GET'])
    def debug_config():
        """Get configuration (debug only)."""
        config_validation = validate_config()
        return create_success_response(config_validation)

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

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    try:
        logger.info("Starting TCGcsv Yu-Gi-Oh API server...")
        logger.info(f"Port: {PORT}, Debug: {DEBUG}")
        
        # Validate configuration
        config_validation = validate_config()
        if not config_validation["valid"]:
            logger.error("Configuration validation failed:")
            for issue in config_validation["issues"]:
                logger.error(f"  - {issue}")
            sys.exit(1)
        
        # Test connectivity
        logger.info("Testing TCGcsv connectivity...")
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
        executor.shutdown(wait=True)