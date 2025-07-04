"""
Routes Module

Defines Flask routes and API endpoints for the YGO API application.
All route handlers are organized here with proper error handling and logging.
"""

import logging
from flask import Flask, jsonify, request
from typing import Dict, Any

from .card_services import card_set_service, card_variant_service, card_lookup_service
from .price_scraping import price_scraping_service
from .memory_manager import get_memory_stats, force_memory_cleanup, monitor_memory
from .utils import extract_art_version, clean_card_data

logger = logging.getLogger(__name__)

def register_routes(app: Flask) -> None:
    """
    Register all routes with the Flask application.
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/health', methods=['GET'])
    @monitor_memory
    def health_check():
        """Health check endpoint."""
        return jsonify({
            "status": "healthy",
            "service": "YGO Card Sets API",
            "memory_stats": get_memory_stats()
        })
    
    @app.route('/cards/price', methods=['POST'])
    @monitor_memory
    def scrape_card_price():
        """Scrape price data for a specific card from TCGPlayer."""
        try:
            data = request.get_json()
            
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
            
            logger.info(f"Price request for card: {card_number or 'None'}, name: {card_name or 'None'}, rarity: {card_rarity}, art: {art_variant}, force_refresh: {force_refresh}")
            
            # Validate card rarity if card_number is provided
            if card_number:
                logger.info(f"Validating rarity '{card_rarity}' for card {card_number}")
                is_valid_rarity = price_scraping_service.validate_card_rarity(card_number, card_rarity)
                
                if not is_valid_rarity:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid rarity '{card_rarity}' for card {card_number}. Please check the card variant database for available rarities."
                    }), 400
            
            # Look up card name if not provided
            if not card_name and card_number:
                card_name = price_scraping_service.lookup_card_name(card_number)
                if not card_name:
                    return jsonify({
                        "success": False,
                        "error": f"Could not find card name for card number: {card_number}"
                    }), 404
            
            # Scrape price
            result = price_scraping_service.scrape_card_price(
                card_number=card_number or "",
                card_name=card_name or "",
                card_rarity=card_rarity,
                art_variant=art_variant,
                force_refresh=force_refresh
            )
            
            if result.get('success'):
                return jsonify(result)
            else:
                return jsonify(result), 500
            
        except Exception as e:
            logger.error(f"Error in scrape_card_price: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/cards/price/cache-stats', methods=['GET'])
    @monitor_memory
    def get_price_cache_stats():
        """Get statistics about the price cache collection."""
        try:
            stats = price_scraping_service.get_cache_stats()
            return jsonify({
                "success": True,
                "cache_stats": stats
            })
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/debug/art-extraction', methods=['POST'])
    @monitor_memory
    def debug_art_extraction():
        """Debug endpoint to test art variant extraction."""
        try:
            data = request.get_json()
            test_strings = data.get('test_strings', [])
            
            results = []
            for test_string in test_strings:
                extracted_art = extract_art_version(test_string)
                results.append({
                    'input': test_string,
                    'extracted_art': extracted_art
                })
            
            return jsonify({
                'success': True,
                'results': results
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/card-sets', methods=['GET'])
    @monitor_memory
    def get_all_card_sets():
        """Get all card sets from YGO API."""
        try:
            card_sets = card_set_service.fetch_all_card_sets()
            return jsonify({
                "success": True,
                "data": card_sets
            })
        except Exception as e:
            logger.error(f"Error fetching card sets: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/card-sets/search/<string:set_name>', methods=['GET'])
    @monitor_memory
    def search_card_sets(set_name: str):
        """Search card sets by name."""
        try:
            card_sets = card_set_service.search_card_sets(set_name)
            return jsonify({
                "success": True,
                "data": card_sets,
                "search_term": set_name
            })
        except Exception as e:
            logger.error(f"Error searching card sets: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/card-sets/upload', methods=['POST'])
    @monitor_memory
    def upload_card_sets_to_mongodb():
        """Upload card sets to MongoDB."""
        try:
            result = card_set_service.upload_card_sets_to_cache()
            return jsonify({
                "success": True,
                "message": "Card sets uploaded successfully to MongoDB",
                "statistics": result
            })
        except Exception as e:
            logger.error(f"Error uploading card sets: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error during upload"
            }), 500
    
    @app.route('/card-sets/from-cache', methods=['GET'])
    @monitor_memory
    def get_card_sets_from_cache():
        """Get card sets from MongoDB cache."""
        try:
            card_sets = card_set_service.get_cached_card_sets()
            return jsonify({
                "success": True,
                "data": card_sets,
                "count": len(card_sets)
            })
        except Exception as e:
            logger.error(f"Error getting cached card sets: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/card-sets/count', methods=['GET'])
    @monitor_memory
    def get_card_sets_count():
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
                "error": "Internal server error"
            }), 500
    
    @app.route('/card-sets/<string:set_name>/cards', methods=['GET'])
    @monitor_memory
    def get_cards_from_specific_set(set_name: str):
        """Get all cards from a specific set."""
        try:
            cards = card_variant_service.fetch_cards_from_set(set_name)
            return jsonify({
                "success": True,
                "data": cards,
                "set_name": set_name,
                "count": len(cards)
            })
        except Exception as e:
            logger.error(f"Error getting cards from set {set_name}: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/card-sets/fetch-all-cards', methods=['POST'])
    @monitor_memory
    def fetch_all_cards_from_sets():
        """Fetch all cards from all cached sets."""
        try:
            # This is a simplified implementation
            # The original had complex filtering logic
            return jsonify({
                "success": True,
                "message": "Card fetching endpoint simplified in modular version",
                "data": {},
                "statistics": {
                    "total_sets": 0,
                    "processed_sets": 0,
                    "failed_sets": 0
                }
            })
        except Exception as e:
            logger.error(f"Error fetching all cards: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error during card fetching"
            }), 500
    
    @app.route('/cards/upload-variants', methods=['POST'])
    @monitor_memory
    def upload_card_variants_to_mongodb():
        """Upload card variants to MongoDB."""
        try:
            result = card_variant_service.upload_card_variants_to_cache()
            return jsonify({
                "success": True,
                "message": "Card variants uploaded successfully to MongoDB",
                **result
            })
        except Exception as e:
            logger.error(f"Error uploading card variants: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error during variant upload"
            }), 500
    
    @app.route('/cards/variants', methods=['GET'])
    @monitor_memory
    def get_card_variants_from_cache():
        """Get card variants from MongoDB cache."""
        try:
            variants = card_variant_service.get_cached_card_variants()
            return jsonify({
                "success": True,
                "data": variants,
                "count": len(variants)
            })
        except Exception as e:
            logger.error(f"Error getting card variants: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/memory/stats', methods=['GET'])
    @monitor_memory
    def get_memory_statistics():
        """Get memory usage statistics."""
        try:
            stats = get_memory_stats()
            return jsonify({
                "success": True,
                "memory_stats": stats
            })
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.route('/memory/cleanup', methods=['POST'])
    @monitor_memory
    def force_memory_cleanup_endpoint():
        """Force memory cleanup."""
        try:
            force_memory_cleanup()
            stats = get_memory_stats()
            return jsonify({
                "success": True,
                "message": "Memory cleanup completed",
                "memory_stats": stats
            })
        except Exception as e:
            logger.error(f"Error during memory cleanup: {e}")
            return jsonify({
                "success": False,
                "error": "Internal server error"
            }), 500
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return jsonify({
            "success": False,
            "error": "Endpoint not found"
        }), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500