"""
Async Routes Module

This module defines all the async API routes using Quart.
"""

import logging
import os
from datetime import datetime, timezone
from quart import Blueprint, jsonify, request, current_app

from .async_browser_pool import get_browser_pool
from .optimized_browser_pool import get_optimized_browser_pool
from .browser_strategy import get_browser_strategy
from .async_price_scraping import get_async_price_service
from .card_services import card_set_service, card_variant_service, card_lookup_service
from .config import get_debug_mode, API_RATE_LIMIT_DELAY, YGO_API_BASE_URL
from .database import get_database
from .memory_manager import get_memory_manager, get_memory_stats, force_memory_cleanup, monitor_memory
from .price_scraping import price_scraping_service
from .utils import clean_card_data, extract_art_version, extract_set_code, extract_booster_set_name, validate_card_input

logger = logging.getLogger(__name__)


def register_async_routes(app):
    """Register all async routes with the Quart application."""
    
    # Health check route
    @app.route('/health', methods=['GET'])
    async def health_check():
        """Health check endpoint."""
        # Get browser stats based on strategy
        browser_strategy = get_browser_strategy()
        if browser_strategy == 'pool':
            browser_pool = get_browser_pool()
            browser_stats = await browser_pool.get_stats()
        elif browser_strategy == 'optimized':
            optimized_pool = get_optimized_browser_pool()
            browser_stats = await optimized_pool.get_stats()
        else:
            browser_stats = {
                "strategy": "manager",
                "message": "Using BrowserManager for memory efficiency"
            }
        
        return jsonify({
            "status": "healthy",
            "service": "YGO Card Sets API (Async)",
            "memory_stats": get_memory_stats(),
            "browser_pool": browser_stats
        })
    
    # Price scraping route (ASYNC)
    @app.route('/cards/price', methods=['POST'])
    async def scrape_card_price():
        """Scrape price data for a specific card from TCGPlayer."""
        try:
            # Check browser pool capacity first
            browser_strategy = get_browser_strategy()
            capacity_available = True
            retry_after = 60  # Default retry after 60 seconds
            
            if browser_strategy == 'optimized':
                pool = get_optimized_browser_pool()
                stats = await pool.get_stats()
                # Check if all browsers are in use AND we're at max capacity
                if stats.get('initialized', False) and stats['available'] == 0 and stats['pool_size'] >= pool.max_browsers:
                    capacity_available = False
                    # Estimate retry time based on average wait time
                    if stats.get('avg_wait_time', 0) > 0:
                        retry_after = int(stats['avg_wait_time'] + 10)
            elif browser_strategy == 'pool':
                pool = get_browser_pool()
                stats = await pool.get_stats()
                if stats['available_browsers'] == 0:
                    capacity_available = False
            
            if not capacity_available:
                logger.warning("Browser pool at capacity, returning 503")
                return jsonify({
                    "success": False,
                    "error": "Service temporarily unavailable due to high load. Please retry later.",
                    "message": "Browser pool at capacity"
                }), 503, {
                    'Retry-After': str(retry_after),
                    'X-Pool-Status': 'at-capacity'
                }
            
            data = await request.get_json()
            
            if not data:
                return jsonify({
                    "success": False,
                    "error": "Request body must be JSON"
                }), 400
            
            card_number = data.get('card_number', '').strip() if data.get('card_number') else None
            card_name = data.get('card_name', '').strip() if data.get('card_name') else None
            
            # Validate required parameters
            if not card_number and not card_name:
                return jsonify({
                    "success": False,
                    "error": "Either card_number or card_name is required"
                }), 400
            
            card_rarity = data.get('card_rarity', '').strip() if data.get('card_rarity') else None
            
            # Handle art_variant parameter
            if 'art_variant' in data:
                if data['art_variant'] is None:
                    art_variant = None
                else:
                    art_variant = data['art_variant'].strip() if data['art_variant'] else ''
            else:
                art_variant = None
            
            # Convert force_refresh to boolean
            force_refresh = str(data.get('force_refresh', '')).lower() == 'true'
            
            # Validate card_rarity
            if not card_rarity:
                return jsonify({
                    "success": False,
                    "error": "card_rarity is required and cannot be empty"
                }), 400
            
            # SECURITY: Validate inputs for malicious content
            is_valid, error_msg = validate_card_input(
                card_number=card_number,
                card_rarity=card_rarity, 
                card_name=card_name,
                art_variant=art_variant
            )
            
            if not is_valid:
                return jsonify({
                    "success": False,
                    "error": error_msg
                }), 400
            
            logger.info(f"Price request for card: {card_number or 'None'}, name: {card_name or 'None'}, rarity: {card_rarity}, art: {art_variant}, force_refresh: {force_refresh}")
            
            # Look up card name if not provided
            if not card_name and card_number:
                card_name = price_scraping_service.lookup_card_name(card_number)
                if not card_name:
                    # In the original implementation, when card name lookup fails,
                    # we continue with the scraping process using just the card number
                    # and let the scraping service handle the fallback behavior
                    logger.warning(f"Could not find card name for card number: {card_number}, continuing with scraping anyway")
                    card_name = ""  # Continue with empty card name

            # Use async price scraping service
            async_price_service = get_async_price_service()
            result = await async_price_service.scrape_card_price(
                card_number=card_number or "",
                card_name=card_name or "",
                card_rarity=card_rarity,
                art_variant=art_variant,
                force_refresh=force_refresh
            )
            
            # Format response to match original API format
            # Create the data object that matches original implementation
            data_object = {
                "card_number": card_number or "",
                "card_name": card_name or "",
                "card_rarity": card_rarity,
                "set_code": extract_set_code(card_number) if card_number else None,
                "booster_set_name": extract_booster_set_name(result.get('tcgplayer_url', '')) if result.get('tcgplayer_url') else None,
                "tcg_price": result.get('tcgplayer_price'),
                "tcg_market_price": result.get('tcgplayer_market_price'),
                "source_url": result.get('tcgplayer_url'),
                "scrape_success": result.get('success', False) and result.get('tcgplayer_price') is not None,
                "last_price_updt": result.get('last_updated', ''),
            }
            
            # Format last_price_updt to match original format
            if result.get('last_updated'):
                last_updated = result['last_updated']
                if hasattr(last_updated, 'strftime'):
                    data_object['last_price_updt'] = last_updated.strftime("%a, %d %b %Y %H:%M:%S GMT")
                else:
                    data_object['last_price_updt'] = str(last_updated)
            
            # Add error if present
            if result.get('error'):
                data_object['error_message'] = result['error']
            
            # Calculate cache age if data is cached
            cache_age_hours = 0.0
            is_cached = result.get('cached', False)
            message = "Price data scraped and saved successfully"
            
            if is_cached and result.get('last_updated'):
                try:
                    last_updated = result['last_updated']
                    if hasattr(last_updated, 'timestamp'):
                        # It's already a datetime object
                        current_time = datetime.now(timezone.utc)
                        cache_age = current_time - last_updated.replace(tzinfo=timezone.utc) if last_updated.tzinfo is None else current_time - last_updated
                        cache_age_hours = cache_age.total_seconds() / 3600
                    message = "Price data retrieved from cache"
                except Exception as e:
                    logger.warning(f"Could not calculate cache age: {e}")
                    cache_age_hours = 0.0
            
            # Build final response matching original format
            has_prices = result.get('tcgplayer_price') is not None or result.get('tcgplayer_market_price') is not None
            response = {
                "success": result.get('success', False) and has_prices,
                "data": data_object,
                "message": message,
                "is_cached": is_cached,
                "cache_age_hours": cache_age_hours
            }
            
            if result.get('success') and has_prices:
                return jsonify(response)
            else:
                # Check if it's a user error (404) or server error (500)
                error_msg = result.get('error', '').lower()
                if 'not found' in error_msg or 'could not find' in error_msg or 'no card' in error_msg:
                    return jsonify(response), 404
                elif 'invalid' in error_msg or 'required' in error_msg:
                    return jsonify(response), 400
                else:
                    return jsonify(response), 500
                
        except Exception as e:
            logger.error(f"Error in scrape_card_price: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    # Browser pool stats route
    @app.route('/browser/stats', methods=['GET'])
    async def browser_pool_stats():
        """Get browser statistics."""
        try:
            browser_strategy = get_browser_strategy()
            
            if browser_strategy == 'pool':
                browser_pool = get_browser_pool()
                stats = await browser_pool.get_stats()
            elif browser_strategy == 'optimized':
                optimized_pool = get_optimized_browser_pool()
                stats = await optimized_pool.get_stats()
            else:
                stats = {
                    "strategy": "manager",
                    "pool_size": int(os.getenv('PLAYWRIGHT_POOL_SIZE', '2')),
                    "message": "Using BrowserManager - browsers created on demand"
                }
            
            return jsonify({
                "success": True,
                "stats": stats
            })
            
        except Exception as e:
            logger.error(f"Error getting browser pool stats: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    # Card sets routes (keeping synchronous for now)
    @app.route('/card-sets', methods=['GET'])
    async def get_card_sets():
        """Get all card sets."""
        try:
            limit = request.args.get('limit', type=int)
            offset = request.args.get('offset', 0, type=int)
            
            card_sets = card_set_service.get_all_card_sets(limit=limit, offset=offset)
            
            return jsonify({
                "success": True,
                "data": card_sets,
                "count": len(card_sets)
            })
            
        except Exception as e:
            logger.error(f"Error fetching card sets: {e}")
            return jsonify({
                "success": False,
                "error": str(e),
                "data": []
            }), 500
    
    @app.route('/card-sets/search/<set_name>', methods=['GET'])
    async def search_card_sets(set_name):
        """Search card sets by name."""
        try:
            card_sets = card_set_service.search_card_sets(set_name)
            
            return jsonify({
                "success": True,
                "data": card_sets,
                "count": len(card_sets)
            })
            
        except Exception as e:
            logger.error(f"Error searching card sets: {e}")
            return jsonify({
                "success": False,
                "error": str(e),
                "data": []
            }), 500
    
    @app.route('/card-sets/count', methods=['GET'])
    async def get_card_sets_count():
        """Get total count of card sets."""
        try:
            count = card_set_service.get_card_sets_count()
            
            return jsonify({
                "success": True,
                "count": count
            })
            
        except Exception as e:
            logger.error(f"Error getting card sets count: {e}")
            return jsonify({
                "success": False,
                "error": str(e),
                "count": 0
            }), 500
    
    @app.route('/card-sets/from-cache', methods=['GET'])
    async def get_card_sets_from_cache():
        """Get card sets from MongoDB cache."""
        try:
            card_sets = card_set_service.get_cached_card_sets()
            
            return jsonify({
                "success": True,
                "data": card_sets,
                "count": len(card_sets),
                "source": "cache"
            })
            
        except Exception as e:
            logger.error(f"Error fetching cached card sets: {e}")
            return jsonify({
                "success": False,
                "error": str(e),
                "data": []
            }), 500
    
    @app.route('/card-sets/<set_name>/cards', methods=['GET'])
    async def get_cards_from_set(set_name):
        """Get all cards from a specific set."""
        try:
            cards = card_variant_service.fetch_cards_from_set(set_name)
            
            return jsonify({
                "success": True,
                "set_name": set_name,
                "data": cards,
                "count": len(cards)
            })
            
        except Exception as e:
            logger.error(f"Error fetching cards from set {set_name}: {e}")
            return jsonify({
                "success": False,
                "error": str(e),
                "data": []
            }), 500
    
    @app.route('/memory/stats', methods=['GET'])
    async def memory_stats():
        """Get memory usage statistics."""
        stats = get_memory_stats()
        return jsonify({
            "success": True,
            "stats": stats
        })
    
    @app.route('/memory/cleanup', methods=['POST'])
    async def force_memory_cleanup_endpoint():
        """Force memory cleanup."""
        force_memory_cleanup()
        stats = get_memory_stats()
        
        return jsonify({
            "success": True,
            "message": "Memory cleanup completed",
            "stats": stats
        })
    
    logger.info("Async routes registered successfully")
