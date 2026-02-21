"""
TCGcsv Server - Main Entry Point for Yu-Gi-Oh Card API
Thread-safe Flask server using TCGcsv.com as data source
"""

import asyncio
import logging
import sys
import threading
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Blueprint, jsonify, request
from flask_cors import CORS

from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from tcgcsv_config import (
    PORT, DEBUG, LOG_LEVEL, get_cors_origins,
    ENABLE_DEBUG_ENDPOINTS, validate_config,
    SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY,
    RATE_LIMIT_DEFAULT, RATE_LIMIT_SEARCH, RATE_LIMIT_BULK,
    RATE_LIMIT_ADMIN, RATE_LIMIT_STORAGE_URI
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Create API v1 Blueprint
api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# CORS origins from configuration (no more hardcoded list)
allowed_origins = get_cors_origins()
CORS(app,
     origins=allowed_origins,
     supports_credentials=True,
     methods=['GET', 'POST', 'OPTIONS'],
     allow_headers=['Content-Type', 'Accept', 'Origin', 'Authorization'],
     expose_headers=['Content-Type', 'Content-Length'])

# Rate limiter configuration
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[RATE_LIMIT_DEFAULT],
    storage_uri=RATE_LIMIT_STORAGE_URI,
    strategy="fixed-window",
    headers_enabled=True  # Adds X-RateLimit headers to responses
)

# Custom error handler for rate limit exceeded
@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "success": False,
        "error": "Rate limit exceeded. Please slow down your requests.",
        "retry_after": e.description
    }), 429

# =============================================================================
# ADMIN AUTHENTICATION
# =============================================================================

def require_admin_auth(f):
    """
    Decorator that validates Supabase JWT and checks if user is an admin.
    Requires valid Authorization: Bearer <token> header.
    User must have is_admin=true in their profiles table.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"success": False, "error": "Missing authorization header"}), 401

        if not auth_header.startswith('Bearer '):
            return jsonify({"success": False, "error": "Invalid authorization format. Use: Bearer <token>"}), 401

        token = auth_header[7:]  # Remove "Bearer " prefix

        # Check if Supabase is configured (use anon key, fallback to service key)
        api_key = SUPABASE_ANON_KEY or SUPABASE_SERVICE_KEY
        if not SUPABASE_URL or not api_key:
            logger.error("Supabase not configured - admin endpoints disabled")
            return jsonify({"success": False, "error": "Admin authentication not configured"}), 503

        try:
            # Validate JWT by calling Supabase to get user's profile
            # The JWT token is used to authenticate, and RLS ensures we only get our own profile
            response = requests.get(
                f"{SUPABASE_URL}/rest/v1/profiles?select=is_admin",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": api_key,
                    "Content-Type": "application/json"
                },
                timeout=10
            )

            if response.status_code == 401:
                return jsonify({"success": False, "error": "Invalid or expired token"}), 401

            if response.status_code != 200:
                logger.error(f"Supabase auth check failed: {response.status_code} - {response.text}")
                return jsonify({"success": False, "error": f"Authentication failed: {response.status_code}"}), 401

            profiles = response.json()

            # Check if we got a profile and if user is admin
            if not profiles or len(profiles) == 0:
                return jsonify({"success": False, "error": "User profile not found"}), 403

            if not profiles[0].get('is_admin', False):
                logger.warning(f"Non-admin user attempted to access admin endpoint")
                return jsonify({"success": False, "error": "Admin access required"}), 403

            # User is authenticated and is an admin
            return f(*args, **kwargs)

        except requests.exceptions.Timeout:
            logger.error("Supabase auth check timed out")
            return jsonify({"success": False, "error": "Authentication service timeout"}), 503
        except requests.exceptions.RequestException as e:
            logger.error(f"Supabase auth check failed: {e}")
            return jsonify({"success": False, "error": "Authentication service unavailable"}), 503
        except Exception as e:
            logger.error(f"Unexpected error in admin auth: {e}")
            return jsonify({"success": False, "error": "Authentication error"}), 500

    return decorated_function

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=4)

# Simple synchronous version of the service
from tcg_core import (
    cache, CardSet, Card, fetch_card_sets, fetch_cards_for_set,
    get_effective_set_code
)
import re

# Pre-compiled regex for card name cleaning - avoids recompilation on each request
_RARITY_SUFFIX_PATTERN = re.compile(r'\s*\([^)]*\)\s*$')

def clean_card_name(name: str) -> str:
    """
    Clean card name by removing rarity suffix in parentheses.
    TCGcsv names often include rarity like "Card Name (Quarter Century Secret Rare)"
    """
    if not name:
        return name
    return _RARITY_SUFFIX_PATTERN.sub('', name).strip().lower()


def get_set_lookup_maps():
    """
    Build lookup maps for sets - O(1) lookups instead of O(n) iteration.
    Returns (by_set_code, by_group_id, by_name) dicts.
    Uses get_effective_set_code() to include YGOProDeck fallback codes.
    """
    sets = cache.get_sets()
    if not sets:
        sets = fetch_card_sets()
        cache.update_sets(sets)

    by_set_code = {}
    by_group_id = {}
    by_name = {}

    for card_set in sets:
        # Use effective set code (includes YGOProDeck fallback)
        effective_code = get_effective_set_code(card_set)
        if effective_code:
            by_set_code[effective_code.upper()] = card_set
        by_group_id[str(card_set.group_id)] = card_set
        by_name[card_set.name.upper()] = card_set

    return sets, by_set_code, by_group_id, by_name


def find_set_by_identifier(set_identifier: str):
    """
    Find a set by set_code (incl. YGOProDeck fallback), group_id, or name with O(1) lookups.
    Returns (CardSet, sets_list) or (None, sets_list).
    """
    sets, by_set_code, by_gid, by_name = get_set_lookup_maps()

    upper_id = set_identifier.upper()
    target_set = (
        by_set_code.get(upper_id) or
        by_gid.get(set_identifier) or
        by_name.get(upper_id)
    )

    return target_set, sets

def initialize_global_index():
    """Background task to load all cards into the global index."""
    logger.info("Starting global index initialization...")
    try:
        sets = cache.get_sets()
        if not sets:
            sets = fetch_card_sets()
            cache.update_sets(sets)
        
        total_sets = len(sets)
        logger.info(f"Found {total_sets} sets. Loading cards...")
        
        for i, card_set in enumerate(sets):
            # Check if cards are already loaded
            if not cache.get_cards(card_set.group_id):
                cards = fetch_cards_for_set(card_set.group_id)
                cache.update_cards(card_set.group_id, cards)
            
            if (i + 1) % 10 == 0:
                logger.info(f"Loaded cards for {i + 1}/{total_sets} sets")
                
        logger.info("Global index initialization complete.")
    except Exception as e:
        logger.error(f"Global index initialization failed: {e}")

# Start global index initialization in background
threading.Thread(target=initialize_global_index, daemon=True).start()

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
# CORS PREFLIGHT HANDLER
# =============================================================================

@app.after_request
def after_request(response):
    """Add CORS headers to every response for allowed origins only."""
    origin = request.headers.get('Origin')
    # Only set CORS headers if origin is in allowed list
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Max-Age'] = '3600'
    return response

# =============================================================================
# HEALTH AND STATUS ENDPOINTS
# =============================================================================

@api_v1.route('/health', methods=['GET'])
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

@api_v1.route('/status', methods=['GET'])
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

@api_v1.route('/card-sets', methods=['GET'])
@api_v1.route('/card-sets/from-cache', methods=['GET'])
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
            effective_code = get_effective_set_code(card_set)
            set_dict.update({
                'id': effective_code,
                'set_name': card_set.name,
                'set_code': effective_code,
                'tcg_date': card_set.published_on,
                'group_id': card_set.group_id
            })
            sets_data.append(set_dict)
        
        return create_success_response(sets_data, f"Retrieved {len(sets_data)} card sets")
        
    except Exception as e:
        logger.error(f"Failed to get card sets: {e}")
        return create_error_response(f"Failed to retrieve card sets: {str(e)}")

@api_v1.route('/card-sets/<set_identifier>/cards', methods=['GET'])
def get_set_cards(set_identifier: str):
    """Get all cards for a specific set."""
    try:
        # Find the set using O(1) lookup maps
        target_set, _ = find_set_by_identifier(set_identifier)

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
            # Get YGOProDeck ID for image fallback
            ygoprodeck_id = syncer.get_ygoprodeck_id(card.product_id)
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
                'tcg_price': card.low_price or card.mid_price or card.market_price,
                'market_price': card.market_price,
                'low_price': card.low_price,
                'mid_price': card.mid_price,
                'high_price': card.high_price,
                'ygoprodeck_id': ygoprodeck_id  # For image fallback when TCGPlayer CDN fails
            })
            cards_data.append(card_dict)
        
        return create_success_response({
            'set_info': target_set.to_dict(),
            'cards': cards_data
        }, f"Retrieved {len(cards_data)} cards for set {set_identifier}")
        
    except Exception as e:
        logger.error(f"Failed to get cards for set {set_identifier}: {e}")
        return create_error_response(f"Failed to retrieve cards for set: {str(e)}")

@api_v1.route('/card-sets/search/<query>', methods=['GET'])
@limiter.limit(RATE_LIMIT_SEARCH)
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
            effective_code = get_effective_set_code(card_set)
            set_dict.update({
                'id': effective_code,
                'set_name': card_set.name,
                'set_code': effective_code,
                'tcg_date': card_set.published_on
            })
            sets_data.append(set_dict)
        
        return create_success_response(sets_data, f"Found {len(sets_data)} matching sets")
        
    except Exception as e:
        logger.error(f"Failed to search card sets: {e}")
        return create_error_response(f"Failed to search card sets: {str(e)}")

# =============================================================================
# CARD SEARCH ENDPOINTS
# =============================================================================

@api_v1.route('/cards/search', methods=['GET'])
@limiter.limit(RATE_LIMIT_SEARCH)
def search_cards():
    """Enhanced card search by name, card number, or other criteria."""
    try:
        query = request.args.get('q', '').strip()
        set_filter = request.args.get('set', '').strip()
        search_type = request.args.get('type', 'name').lower()  # name, number, or all

        if not query:
            return create_error_response("Query parameter 'q' is required", 400, "bad_request")

        # Find target set if specified using O(1) lookup
        target_group_id = None
        target_set_code = None
        if set_filter:
            target_set, _ = find_set_by_identifier(set_filter)
            if target_set:
                target_group_id = target_set.group_id
                target_set_code = get_effective_set_code(target_set)
        
        # Search for cards
        matching_cards = []
        query_lower = query.lower()
        
        if target_group_id:
            # Search in specific set
            cards = cache.get_cards(target_group_id)
            if not cards:
                cards = fetch_cards_for_set(target_group_id)
                cache.update_cards(target_group_id, cards)
            
            for card in cards:
                if search_type == 'number':
                    # Search by card number
                    if card.ext_number and query_lower in card.ext_number.lower():
                        matching_cards.append((card, target_set_code))
                elif search_type == 'name':
                    # Search by name only
                    if query_lower in card.name.lower():
                        matching_cards.append((card, target_set_code))
                else:  # search_type == 'all'
                    # Search by name or card number  
                    if (query_lower in card.name.lower()) or \
                       (card.ext_number and query_lower in card.ext_number.lower()):
                        matching_cards.append((card, target_set_code))
        else:
            # Search across all sets using global index
            global_matches = cache.search_global_index(query)
            
            for card in global_matches:
                card_set = cache.get_set_by_id(card.group_id)
                set_code = get_effective_set_code(card_set) if card_set else "UNKNOWN"
                
                if search_type == 'number':
                    if card.ext_number and query_lower in card.ext_number.lower():
                        matching_cards.append((card, set_code))
                elif search_type == 'name':
                    if query_lower in card.name.lower():
                        matching_cards.append((card, set_code))
                else:  # search_type == 'all'
                    if (query_lower in card.name.lower()) or \
                       (card.ext_number and query_lower in card.ext_number.lower()):
                        matching_cards.append((card, set_code))
            
            # Limit results to avoid timeout
            if len(matching_cards) > 50:
                matching_cards = matching_cards[:50]
        
        # Convert to frontend format
        cards_data = []
        for card, set_code in matching_cards:
            card_dict = {
                'id': str(card.product_id),
                'name': card.name,
                'rarity': card.ext_rarity,
                'card_number': card.ext_number,
                'set_code': set_code,
                'attack': card.ext_attack,
                'defense': card.ext_defense,
                'attribute': card.ext_attribute,
                'type': card.ext_card_type,
                'race': card.ext_monster_type,
                'image_url': card.image_url,
                'tcg_price': card.low_price or card.mid_price or card.market_price,
                'market_price': card.market_price,
                'low_price': card.low_price,
                'mid_price': card.mid_price,
                'high_price': card.high_price,
                'group_id': card.group_id
            }
            cards_data.append(card_dict)
        
        return create_success_response(cards_data, f"Found {len(cards_data)} matching cards")
        
    except Exception as e:
        logger.error(f"Failed to search cards: {e}")
        return create_error_response(f"Failed to search cards: {str(e)}")

@api_v1.route('/cards/bulk-search', methods=['POST'])
@limiter.limit(RATE_LIMIT_BULK)
def bulk_card_search():
    """Search for multiple cards at once."""
    try:
        data = request.get_json()
        if not data:
            return create_error_response("JSON data required", 400, "bad_request")
        
        queries = data.get('queries', [])
        search_type = data.get('type', 'name').lower()
        set_filter = data.get('set', '').strip()
        
        if not queries or not isinstance(queries, list):
            return create_error_response("'queries' array is required", 400, "bad_request")
        
        if len(queries) > 20:
            return create_error_response("Maximum 20 queries allowed", 400, "bad_request")

        results = {}

        # Find target set ONCE before the loop (was being done per query - O(n*m) -> O(n))
        target_group_id = None
        target_set_code = None
        target_set_cards = None
        if set_filter:
            target_set, _ = find_set_by_identifier(set_filter)
            if target_set:
                target_group_id = target_set.group_id
                target_set_code = get_effective_set_code(target_set)
                # Pre-fetch cards for the set once
                target_set_cards = cache.get_cards(target_group_id)
                if not target_set_cards:
                    target_set_cards = fetch_cards_for_set(target_group_id)
                    cache.update_cards(target_group_id, target_set_cards)

        for query in queries:
            if not query or not isinstance(query, str):
                continue

            query = query.strip()
            if not query:
                continue

            # Reuse the search logic
            matching_cards = []
            query_lower = query.lower()

            if target_group_id and target_set_cards:
                # Search in pre-fetched set cards (no re-fetch needed)
                for card in target_set_cards:
                    if search_type == 'number':
                        if card.ext_number and query_lower in card.ext_number.lower():
                            matching_cards.append((card, target_set_code))
                    elif search_type == 'name':
                        if query_lower in card.name.lower():
                            matching_cards.append((card, target_set_code))
                    else:  # search_type == 'all'
                        if (query_lower in card.name.lower()) or \
                           (card.ext_number and query_lower in card.ext_number.lower()):
                            matching_cards.append((card, target_set_code))
            else:
                # Search using global index for bulk operations
                global_matches = cache.search_global_index(query)
                
                for card in global_matches:
                    card_set = cache.get_set_by_id(card.group_id)
                    set_code = get_effective_set_code(card_set) if card_set else "UNKNOWN"

                    if search_type == 'number':
                        if card.ext_number and query_lower in card.ext_number.lower():
                            matching_cards.append((card, set_code))
                    elif search_type == 'name':
                        if query_lower in card.name.lower():
                            matching_cards.append((card, set_code))
                    else:  # search_type == 'all'
                        if (query_lower in card.name.lower()) or \
                           (card.ext_number and query_lower in card.ext_number.lower()):
                            matching_cards.append((card, set_code))
                    
                    # Limit results per query for bulk operations
                    if len(matching_cards) >= 5:
                        break
            
            # Convert to frontend format
            cards_data = []
            for card, set_code in matching_cards[:5]:  # Limit to 5 results per query
                card_dict = {
                    'id': str(card.product_id),
                    'name': card.name,
                    'rarity': card.ext_rarity,
                    'card_number': card.ext_number,
                    'set_code': set_code,
                    'tcg_price': card.low_price or card.mid_price or card.market_price,
                    'image_url': card.image_url
                }
                cards_data.append(card_dict)
            
            results[query] = cards_data
        
        return create_success_response(results, f"Processed {len(queries)} queries")
        
    except Exception as e:
        logger.error(f"Failed to perform bulk search: {e}")
        return create_error_response(f"Failed to perform bulk search: {str(e)}")

@api_v1.route('/cards/by-number/<card_number>', methods=['GET'])
def get_card_by_number(card_number: str):
    """Get card by card number (e.g., BLMM-EN001)."""
    try:
        set_filter = request.args.get('set', '').strip()
        
        # Extract set code from card number if not provided
        if not set_filter and '-' in card_number:
            potential_set_code = card_number.split('-')[0]
            set_filter = potential_set_code
        
        # Search for the card
        matching_cards = []
        
        if set_filter:
            # Search in specific set
            sets = cache.get_sets()
            if not sets:
                sets = fetch_card_sets()
                cache.update_sets(sets)
            
            target_set = None
            for card_set in sets:
                if card_set.abbreviation and card_set.abbreviation.upper() == set_filter.upper():
                    target_set = card_set
                    break
            
            if target_set:
                cards = cache.get_cards(target_set.group_id)
                if not cards:
                    cards = fetch_cards_for_set(target_set.group_id)
                    cache.update_cards(target_set.group_id, cards)
                
                for card in cards:
                    if card.ext_number and card.ext_number.upper() == card_number.upper():
                        matching_cards.append((card, target_set.abbreviation))
                        break
        
        if not matching_cards:
            return create_error_response(f"Card with number '{card_number}' not found", 404, "not_found")
        
        # Return the first (and should be only) match
        card, set_code = matching_cards[0]
        
        card_data = {
            'id': str(card.product_id),
            'name': card.name,
            'rarity': card.ext_rarity,
            'card_number': card.ext_number,
            'set_code': set_code,
            'attack': card.ext_attack,
            'defense': card.ext_defense,
            'attribute': card.ext_attribute,
            'type': card.ext_card_type,
            'race': card.ext_monster_type,
            'image_url': card.image_url,
            'tcg_price': card.market_price or card.mid_price or card.low_price,
            'market_price': card.market_price,
            'low_price': card.low_price,
            'mid_price': card.mid_price,
            'high_price': card.high_price,
            'group_id': card.group_id
        }
        
        return create_success_response(card_data, f"Found card {card_number}")
        
    except Exception as e:
        logger.error(f"Failed to get card by number {card_number}: {e}")
        return create_error_response(f"Failed to get card by number: {str(e)}")

# =============================================================================
# CARD PRICING ENDPOINT (COMPATIBILITY)
# =============================================================================

@api_v1.route('/cards/price', methods=['POST'])
def get_card_price():
    """Get price information for a specific card (maintains compatibility)."""
    try:
        data = request.get_json()
        if not data:
            return create_error_response("JSON data required", 400, "bad_request")

        # FAST PATH: Direct lookup by product_id (O(1))
        product_id = data.get('product_id') or data.get('tcgcsv_product_id')
        if product_id:
            try:
                product_id = int(product_id)
                found_card = cache.get_card_by_product_id(product_id)
                if found_card:
                    logger.info(f"Direct lookup by product_id={product_id}: {found_card.name}")
                    # Get set info for response
                    card_set = cache.get_set_by_id(found_card.group_id)
                    set_code = get_effective_set_code(card_set) if card_set else ''

                    price_data = {
                        'card_name': found_card.name,
                        'card_number': found_card.ext_number,
                        'card_rarity': found_card.ext_rarity,
                        'set_code': set_code,
                        'tcg_price': found_card.low_price or found_card.mid_price or found_card.market_price,
                        'tcg_market_price': found_card.market_price,
                        'tcg_low_price': found_card.low_price,
                        'tcg_mid_price': found_card.mid_price,
                        'tcg_high_price': found_card.high_price,
                        'product_id': found_card.product_id,
                        'image_url': found_card.image_url,
                    }
                    return create_success_response(price_data, f"Found card by product_id")
            except (ValueError, TypeError):
                pass  # Invalid product_id, fall through to name-based lookup

        card_name = (data.get('cardName') or data.get('card_name') or '').strip()
        card_number = (data.get('card_number') or '').strip()
        card_rarity = (data.get('card_rarity') or '').strip()
        set_code = (data.get('setCode') or '').strip()

        # Accept either cardName or card_number (backward compatibility)
        if not card_name and not card_number:
            return create_error_response("Either 'cardName', 'card_number', or 'product_id' is required", 400, "bad_request")

        # If we have a card number, try to find the card by number first
        if card_number:
            # Extract set code from card number if not provided (e.g., BLMM-EN001 -> BLMM)
            if not set_code and '-' in card_number:
                potential_set_code = card_number.split('-')[0]
                set_code = potential_set_code

        # Find set if provided using O(1) lookup
        target_group_id = None
        if set_code:
            target_set, _ = find_set_by_identifier(set_code)
            if target_set:
                target_group_id = target_set.group_id
            logger.info(f"Set search: code='{set_code}', group_id={target_group_id}")
        
        # Search for card with rarity consideration
        found_card = None

        # Note: clean_card_name is now defined at module level for performance

        if target_group_id:
            # Search in specific set
            cards = cache.get_cards(target_group_id)
            if not cards:
                cards = fetch_cards_for_set(target_group_id)
                cache.update_cards(target_group_id, cards)

            logger.info(f"Searching in set {target_group_id}, found {len(cards)} cards")

            # Normalize search name once
            search_name = clean_card_name(card_name) if card_name else None

            # STEP 1: Try EXACT match first (name/number + rarity)
            # This is the fast path for collection cards where we have full metadata
            if card_rarity:
                for card in cards:
                    rarity_match = card.ext_rarity and card.ext_rarity.lower() == card_rarity.lower()
                    number_match = card_number and card.ext_number and card.ext_number.upper() == card_number.upper()
                    # Compare cleaned names (without rarity suffix)
                    cache_name = clean_card_name(card.name)
                    name_match = search_name and cache_name == search_name

                    if rarity_match and (number_match or name_match):
                        found_card = card
                        logger.info(f"Exact match found: {card.name} ({card.ext_rarity})")
                        break

            # STEP 2: If no exact match, fall back to fuzzy candidate scoring
            # This is for pack openings or searches with incomplete data
            if not found_card:
                candidate_cards = []
                for card in cards:
                    cache_name = clean_card_name(card.name)
                    if card_number and card.ext_number and card.ext_number.upper() == card_number.upper():
                        candidate_cards.append((card, 'number'))
                    elif search_name and cache_name == search_name:
                        candidate_cards.append((card, 'name'))
                    elif search_name and search_name in cache_name:
                        candidate_cards.append((card, 'partial_name'))

                if candidate_cards:
                    logger.info(f"No exact match, found {len(candidate_cards)} candidates for '{card_name}'")

                    if card_rarity:
                        # Score candidates by rarity similarity
                        best_match = None
                        best_score = 0

                        for card, match_type in candidate_cards:
                            score = 0
                            if card.ext_rarity and card.ext_rarity.lower() == card_rarity.lower():
                                score += 100
                            elif card.ext_rarity and (card_rarity.lower() in card.ext_rarity.lower() or card.ext_rarity.lower() in card_rarity.lower()):
                                score += 50

                            if match_type == 'number': score += 50
                            elif match_type == 'name': score += 40
                            elif match_type == 'partial_name': score += 10

                            logger.debug(f"Candidate: {card.name} ({card.ext_rarity}), Score: {score}")

                            if score > best_score:
                                best_match = card
                                best_score = score

                        if best_match:
                            found_card = best_match

                    # No rarity specified - prefer number matches
                    if not found_card:
                        candidate_cards.sort(key=lambda x: 0 if x[1] == 'number' else 1)
                        found_card = candidate_cards[0][0]
        else:
             logger.info("Set not found or not provided, falling back to global search")
             # ... (global search logic)

        if not found_card:
            search_term = card_number if card_number else card_name
            logger.warning(f"Card '{search_term}' not found in set {set_code}")
            return create_error_response(f"Card '{search_term}' not found", 404, "not_found")
        
        # Format response with both camelCase and snake_case for compatibility
        # Frontend expects snake_case properties wrapped in data object
        price_data = {
            # snake_case for frontend compatibility
            'card_name': found_card.name,
            'card_number': found_card.ext_number,
            'card_rarity': found_card.ext_rarity,
            'set_code': set_code,
            'tcg_price': found_card.low_price or found_card.mid_price or found_card.market_price,
            'tcg_market_price': found_card.market_price,
            'low_price': found_card.low_price,
            'mid_price': found_card.mid_price,
            'high_price': found_card.high_price,
            'image_url': found_card.image_url,
            # camelCase for backward compatibility
            'cardName': found_card.name,
            'setCode': set_code,
            'rarity': found_card.ext_rarity,
            'tcgPrice': found_card.low_price or found_card.mid_price or found_card.market_price,
            'marketPrice': found_card.market_price,
            'lowPrice': found_card.low_price,
            'midPrice': found_card.mid_price,
            'highPrice': found_card.high_price,
            'imageUrl': found_card.image_url,
            'source': 'tcgcsv',
            'productId': found_card.product_id
        }

        # Use create_success_response to wrap data consistently
        return create_success_response(price_data, f"Price data for {found_card.name}")
        
    except Exception as e:
        logger.error(f"Failed to get card price: {e}")
        return create_error_response(f"Failed to get card price: {str(e)}")

# =============================================================================
# CACHE ENDPOINTS
# =============================================================================

@api_v1.route('/cache/stats', methods=['GET'])
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

@api_v1.route('/cache/refresh', methods=['POST'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def refresh_cache():
    """Force refresh the cache."""
    try:
        # Run refresh in background to avoid blocking
        threading.Thread(target=cache.refresh, daemon=True).start()
        return create_success_response(None, "Cache refresh started in background")
    except Exception as e:
        logger.error(f"Failed to refresh cache: {e}")
        return create_error_response(f"Failed to refresh cache: {str(e)}")

# =============================================================================
# DEBUG ENDPOINTS
# =============================================================================

# ... (existing debug endpoints if any)

# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

from supabase_sync import syncer, get_progress
from tcg_core import cache as tcg_cache

# Catalog refresh progress tracking (similar to supabase_sync)
_catalog_progress_lock = threading.Lock()
catalog_refresh_progress = {
    "status": "idle",  # idle, running, complete, error
    "phase": "",
    "current": 0,
    "total": 0,
    "message": "",
    "started_at": None,
    "completed_at": None
}

def update_catalog_progress(**kwargs):
    """Thread-safe update of catalog refresh progress."""
    global catalog_refresh_progress
    with _catalog_progress_lock:
        catalog_refresh_progress.update(kwargs)

def get_catalog_progress():
    """Thread-safe get of catalog refresh progress."""
    with _catalog_progress_lock:
        return dict(catalog_refresh_progress)

@api_v1.route('/admin/refresh-catalog', methods=['POST'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_refresh_catalog():
    """Refresh the card catalog from TCGcsv (fetches all sets and cards)."""
    try:
        def do_refresh():
            from datetime import datetime, timezone
            try:
                update_catalog_progress(
                    status="running",
                    phase="starting",
                    current=0,
                    total=0,
                    message="Initializing catalog refresh...",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=None
                )
                logger.info("Starting TCGcsv catalog refresh...")

                # Pass progress callback to get real-time updates during refresh
                tcg_cache.refresh(progress_callback=update_catalog_progress)

                total_cards = sum(len(cards) for cards in tcg_cache.cards.values())
                update_catalog_progress(
                    status="complete",
                    phase="done",
                    current=len(tcg_cache.card_sets),
                    total=len(tcg_cache.card_sets),
                    message=f"Refresh complete. {len(tcg_cache.card_sets)} sets, {total_cards} cards loaded.",
                    completed_at=datetime.now(timezone.utc).isoformat()
                )
                logger.info(f"Catalog refresh complete. Sets: {len(tcg_cache.card_sets)}, Cards: {total_cards}")

            except Exception as e:
                update_catalog_progress(
                    status="error",
                    message=f"Refresh failed: {str(e)}"
                )
                logger.error(f"Catalog refresh failed: {e}")

        # Run in background (this can take several minutes)
        threading.Thread(target=do_refresh, daemon=True).start()
        return create_success_response({
            "current_sets": len(tcg_cache.card_sets),
            "current_cards": sum(len(cards) for cards in tcg_cache.cards.values())
        }, "Catalog refresh started in background. Check progress via /admin/catalog-progress")
    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        return create_error_response(f"Failed to start catalog refresh: {str(e)}")

@api_v1.route('/admin/catalog-progress', methods=['GET'])
@limiter.limit("30 per minute")
@require_admin_auth
def admin_catalog_progress():
    """Get catalog refresh progress."""
    return create_success_response(get_catalog_progress())

@api_v1.route('/admin/catalog-status', methods=['GET'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_catalog_status():
    """Get current catalog cache status."""
    try:
        total_cards = sum(len(cards) for cards in tcg_cache.cards.values())
        return create_success_response({
            "sets_count": len(tcg_cache.card_sets),
            "cards_count": total_cards,
            "last_updated": tcg_cache.last_updated.isoformat() if tcg_cache.last_updated else None
        }, "Catalog status")
    except Exception as e:
        return create_error_response(f"Failed to get catalog status: {str(e)}")

@api_v1.route('/admin/sync-prices', methods=['POST'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_sync_prices():
    """Trigger manual price sync to Supabase (uploads local cache to DB)."""
    try:
        # Run in background
        threading.Thread(target=syncer.run_sync, daemon=True).start()
        return create_success_response({
            "cache_sets": len(tcg_cache.card_sets),
            "cache_cards": sum(len(cards) for cards in tcg_cache.cards.values())
        }, "Price sync started in background")
    except Exception as e:
        return create_error_response(f"Failed to start sync: {str(e)}")

@api_v1.route('/admin/sync-progress', methods=['GET'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_sync_progress():
    """Get current sync progress."""
    return create_success_response(get_progress())

@api_v1.route('/admin/refresh-leaderboards', methods=['POST'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_refresh_leaderboards():
    """Trigger manual leaderboard refresh."""
    try:
        # Call RPC with explicit parameters (Supabase RPC requires JSON body)
        result = syncer._request("POST", "rpc/refresh_leaderboards", data={
            "p_limit": 100,
            "p_source": "admin",
            "p_include_snapshots": True
        })
        logger.info(f"Leaderboard refresh result: {result}")

        # Also fetch the latest computed_at from the leaderboard view to verify refresh worked
        computed_at_check = syncer._request("GET", "leaderboard_value", params={
            "select": "computed_at",
            "limit": "1"
        })
        logger.info(f"Leaderboard computed_at after refresh: {computed_at_check}")

        return create_success_response({
            "snapshots_inserted": result,
            "computed_at": computed_at_check[0]["computed_at"] if computed_at_check else None
        }, "Leaderboard refresh triggered")
    except Exception as e:
        logger.error(f"Leaderboard refresh failed: {e}")
        return create_error_response(f"Failed to refresh leaderboards: {str(e)}")

@api_v1.route('/admin/force-refresh-leaderboards', methods=['POST'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_force_refresh_leaderboards():
    """Force refresh leaderboard materialized views (uses simpler non-concurrent refresh)."""
    try:
        # Call the new simpler RPC that shows before/after timestamps
        result = syncer._request("POST", "rpc/force_refresh_leaderboards", data={})
        logger.info(f"Force refresh result: {result}")

        if result and result.get("success"):
            return create_success_response(result, "Leaderboards force-refreshed successfully")
        else:
            error_msg = result.get("error", "Unknown error") if result else "No response from RPC"
            logger.error(f"Force refresh failed: {error_msg}")
            return create_error_response(f"Refresh failed: {error_msg}")
    except Exception as e:
        logger.error(f"Force refresh exception: {e}")
        return create_error_response(f"Failed to force refresh: {str(e)}")

@api_v1.route('/admin/leaderboard-debug', methods=['GET'])
@limiter.limit(RATE_LIMIT_ADMIN)
@require_admin_auth
def admin_leaderboard_debug():
    """Debug endpoint to check leaderboard state."""
    try:
        # Check each materialized view's computed_at
        value_check = syncer._request("GET", "leaderboard_value", params={
            "select": "user_id,computed_at",
            "limit": "5"
        })
        quantity_check = syncer._request("GET", "leaderboard_quantity", params={
            "select": "user_id,computed_at",
            "limit": "5"
        })
        rarity_check = syncer._request("GET", "leaderboard_rarity", params={
            "select": "user_id,computed_at",
            "limit": "5"
        })

        # Check recent snapshots
        snapshots = syncer._request("GET", "leaderboard_snapshots", params={
            "select": "leaderboard_type,captured_at,user_id",
            "order": "captured_at.desc",
            "limit": "10"
        })

        return create_success_response({
            "value_entries": value_check,
            "quantity_entries": quantity_check,
            "rarity_entries": rarity_check,
            "recent_snapshots": snapshots
        }, "Leaderboard debug info")
    except Exception as e:
        logger.error(f"Leaderboard debug failed: {e}")
        return create_error_response(f"Failed to get debug info: {str(e)}")

# =============================================================================
# SCHEDULER
# =============================================================================

def run_scheduler():
    """Background scheduler for periodic tasks."""
    import time
    logger.info("Scheduler started.")
    while True:
        # Wait for 24 hours (or config)
        # For now, hardcoded to 24h = 86400s
        time.sleep(86400)
        logger.info("Scheduler waking up for daily sync...")
        try:
            syncer.run_sync()
        except Exception as e:
            logger.error(f"Scheduled sync failed: {e}")

# Start scheduler in background
threading.Thread(target=run_scheduler, daemon=True).start()

if ENABLE_DEBUG_ENDPOINTS:
    @api_v1.route('/debug/config', methods=['GET'])
    def debug_config():
        """Get configuration (debug only)."""
        config_validation = validate_config()
        return create_success_response(config_validation)

# Register the API v1 blueprint with the app
app.register_blueprint(api_v1)

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
# CACHE PRE-WARMING
# =============================================================================

def prewarm_caches():
    """Pre-warm TCGcsv caches on server startup for faster first requests."""
    logger.info("Pre-warming TCGcsv caches...")

    # Pre-load TCGcsv sets if not cached (this is our primary data source)
    if not cache.get_sets():
        logger.info("Loading TCGcsv sets...")
        sets = fetch_card_sets()
        cache.update_sets(sets)
        logger.info(f"TCGcsv sets loaded: {len(sets)} sets")
    else:
        logger.info(f"TCGcsv sets already cached: {len(cache.get_sets())} sets")

    # Note: YGOProDeck data is loaded lazily only when a set is missing an abbreviation
    # This keeps startup fast and only fetches fallback data when actually needed

    logger.info("Cache pre-warming complete")

# Pre-warm caches when module is imported (runs when server starts)
prewarm_caches()

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='TCGcsv Yu-Gi-Oh API Server')
    parser.add_argument('--port', type=int, help='Port to run the server on')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    # Override config with command line args
    server_port = args.port if args.port else PORT
    debug_mode = args.debug if args.debug else DEBUG

    try:
        logger.info("Starting TCGcsv Yu-Gi-Oh API server...")
        logger.info(f"Port: {server_port}, Debug: {debug_mode}")
        
        # Validate configuration
        config_validation = validate_config()
        if not config_validation["valid"]:
            logger.error("Configuration validation failed:")
            for issue in config_validation["issues"]:
                logger.error(f"  - {issue}")
            sys.exit(1)
        
        # Test connectivity
        logger.info("Testing TCGcsv connectivity...")
        try:
            test_response = requests.get("https://tcgcsv.com/tcgplayer/2/Groups.csv", timeout=10)
            if test_response.status_code == 200:
                logger.info("✅ TCGcsv connectivity test passed")
            else:
                logger.warning(f"⚠️ TCGcsv returned status {test_response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ TCGcsv connectivity test failed: {e}")

        # Load YGOProDeck ID mapping for image fallback
        logger.info("Loading YGOProDeck ID mapping...")
        try:
            syncer.load_ygoprodeck_id_map()
            logger.info("✅ YGOProDeck ID mapping loaded")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load YGOProDeck ID mapping: {e}")

        app.run(
            host='0.0.0.0',
            port=server_port,
            debug=debug_mode,
            threaded=True
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)
    finally:
        executor.shutdown(wait=True)