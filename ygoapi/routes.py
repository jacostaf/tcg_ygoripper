"""
Routes Module

Defines Flask routes and API endpoints for the YGO API application.
All route handlers are organized here with proper error handling and logging.
"""

import logging
import time
from typing import Any, Dict
from urllib.parse import unquote

import requests
from flask import Flask, Response, jsonify, request

from .card_services import card_lookup_service, card_set_service, card_variant_service
from .config import API_RATE_LIMIT_DELAY, YGO_API_BASE_URL
from .memory_manager import force_memory_cleanup, get_memory_stats, monitor_memory
from .price_scraping import price_scraping_service
from .utils import clean_card_data, extract_art_version, extract_booster_set_name, extract_set_code

logger = logging.getLogger(__name__)


def register_routes(app: Flask) -> None:
    """
    Register all routes with the Flask application.

    Args:
        app: Flask application instance
    """

    @app.route("/health", methods=["GET"])
    @monitor_memory
    def health_check():
        """Health check endpoint."""
        return jsonify(
            {
                "status": "healthy",
                "service": "YGO Card Sets API",
                "memory_stats": get_memory_stats(),
            }
        )

    @app.route("/cards/price", methods=["POST"])
    @monitor_memory
    def scrape_card_price():
        """Scrape price data for a specific card from TCGPlayer."""
        try:
            # Handle different types of invalid JSON requests
            if request.content_type != 'application/json':
                return (
                    jsonify({"success": False, "error": "Request body must be JSON"}),
                    400,
                )
            
            try:
                data = request.get_json(force=True)
            except Exception:
                return (
                    jsonify({"success": False, "error": "Request body must be JSON"}),
                    400,
                )

            if not data:
                return (
                    jsonify({"success": False, "error": "Request body must be JSON"}),
                    400,
                )

            card_number = data.get("card_number", "").strip() if data.get("card_number") else None
            card_name = data.get("card_name", "").strip() if data.get("card_name") else None

            # Validate required parameters
            if not card_number and not card_name:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Either card_number or card_name is required",
                        }
                    ),
                    400,
                )

            card_rarity = data.get("card_rarity", "").strip() if data.get("card_rarity") else None

            # Handle art_variant parameter
            if "art_variant" in data:
                if data["art_variant"] is None:
                    art_variant = None
                else:
                    art_variant = data["art_variant"].strip() if data["art_variant"] else ""
            else:
                art_variant = None

            # Convert force_refresh to boolean
            force_refresh = str(data.get("force_refresh", "")).lower() == "true"

            # Validate card_rarity
            if not card_rarity:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "card_rarity is required and cannot be empty",
                        }
                    ),
                    400,
                )

            logger.info(
                f"Price request for card: {card_number or 'None'}, name: {card_name or 'None'}, rarity: {card_rarity}, art: {art_variant}, force_refresh: {force_refresh}"
            )

            # Validate card rarity if card_number is provided
            if card_number:
                logger.info(f"Validating rarity '{card_rarity}' for card {card_number}")
                is_valid_rarity = price_scraping_service.validate_card_rarity(
                    card_number, card_rarity
                )

                if not is_valid_rarity:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Invalid rarity '{card_rarity}' for card {card_number}. Please check the card variant database for available rarities.",
                            }
                        ),
                        400,
                    )

            # Look up card name if not provided
            if not card_name and card_number:
                card_name = price_scraping_service.lookup_card_name(card_number)
                if not card_name:
                    # In the original implementation, when card name lookup fails,
                    # we continue with the scraping process using just the card number
                    # and let the scraping service handle the fallback behavior
                    logger.warning(
                        f"Could not find card name for card number: {card_number}, continuing with scraping anyway"
                    )
                    card_name = ""  # Continue with empty card name

            # Scrape price
            result = price_scraping_service.scrape_card_price(
                card_number=card_number or "",
                card_name=card_name or "",
                card_rarity=card_rarity,
                art_variant=art_variant,
                force_refresh=force_refresh,
            )

            # Format response to match original API format
            # Create the data object that matches original implementation
            data_object = {
                "card_number": card_number or "",
                "card_name": card_name or "",
                "card_rarity": card_rarity,
                "set_code": extract_set_code(card_number) if card_number else None,
                "booster_set_name": extract_booster_set_name(result.get("tcgplayer_url", ""))
                if result.get("tcgplayer_url")
                else None,
                "tcg_price": result.get("tcgplayer_price"),
                "tcg_market_price": result.get("tcgplayer_market_price"),
                "source_url": result.get("tcgplayer_url"),
                "scrape_success": result.get("success", False),
                "last_price_updt": result.get("last_updated", ""),
            }

            # Format last_price_updt to match original format
            if result.get("last_updated"):
                last_updated = result["last_updated"]
                if hasattr(last_updated, "strftime"):
                    data_object["last_price_updt"] = last_updated.strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    )
                else:
                    data_object["last_price_updt"] = str(last_updated)

            # Add error if present
            if result.get("error"):
                data_object["error_message"] = result["error"]

            # Calculate cache age if data is cached
            cache_age_hours = 0.0
            is_cached = result.get("cached", False)
            message = "Price data scraped and saved successfully"

            if is_cached and result.get("last_updated"):
                from datetime import datetime, timezone

                try:
                    last_updated = result["last_updated"]
                    if hasattr(last_updated, "timestamp"):
                        # It's already a datetime object
                        current_time = datetime.now(timezone.utc)
                        cache_age = (
                            current_time - last_updated.replace(tzinfo=timezone.utc)
                            if last_updated.tzinfo is None
                            else current_time - last_updated
                        )
                        cache_age_hours = cache_age.total_seconds() / 3600
                    message = "Price data retrieved from cache"
                except Exception as e:
                    logger.warning(f"Could not calculate cache age: {e}")
                    cache_age_hours = 0.0

            # Build final response matching original format
            response = {
                "success": result.get("success", False),
                "data": data_object,
                "message": message,
                "is_cached": is_cached,
                "cache_age_hours": cache_age_hours,
            }

            if result.get("success"):
                return jsonify(response)
            else:
                # Check if it's a user error (404) or server error (500)
                error_msg = result.get("error", "").lower()
                if (
                    "not found" in error_msg
                    or "could not find" in error_msg
                    or "no card" in error_msg
                ):
                    return jsonify(response), 404
                elif "invalid" in error_msg or "required" in error_msg:
                    return jsonify(response), 400
                else:
                    return jsonify(response), 500

        except Exception as e:
            logger.error(f"Error in scrape_card_price: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/cards/price/cache-stats", methods=["GET"])
    @monitor_memory
    def get_price_cache_stats():
        """Get statistics about the price cache collection."""
        try:
            stats = price_scraping_service.get_cache_stats()
            return jsonify({"success": True, "cache_stats": stats})
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/debug/cache-lookup", methods=["POST"])
    @monitor_memory
    def debug_cache_lookup():
        """Debug endpoint to test cache lookup behavior."""
        try:
            data = request.get_json()

            if not data:
                return (
                    jsonify({"success": False, "error": "Request body must be JSON"}),
                    400,
                )

            card_number = data.get("card_number", "").strip() if data.get("card_number") else ""
            card_name = data.get("card_name", "").strip() if data.get("card_name") else ""
            card_rarity = data.get("card_rarity", "").strip() if data.get("card_rarity") else ""
            art_variant = data.get("art_variant", "").strip() if data.get("art_variant") else None

            # Get cache collection stats
            cache_stats = price_scraping_service.get_cache_stats()

            # Try cache lookup
            cached_data = price_scraping_service.find_cached_price_data(
                card_number, card_name, card_rarity, art_variant
            )

            # Check all documents for this card (ignoring freshness)
            from .database import get_price_cache_collection

            cache_collection = get_price_cache_collection()

            all_documents = []
            if cache_collection:
                # Find all documents matching card number
                if card_number:
                    all_docs = list(cache_collection.find({"card_number": card_number}))
                    all_documents.extend(
                        [
                            {
                                "card_number": doc.get("card_number"),
                                "card_name": doc.get("card_name"),
                                "card_rarity": doc.get("card_rarity"),
                                "art_variant": doc.get("art_variant"),
                                "last_price_updt": str(doc.get("last_price_updt")),
                                "tcgplayer_price": doc.get("tcgplayer_price"),
                            }
                            for doc in all_docs
                        ]
                    )

            return jsonify(
                {
                    "success": True,
                    "lookup_params": {
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        "art_variant": art_variant,
                    },
                    "cache_hit": cached_data is not None,
                    "cached_data": clean_card_data(cached_data) if cached_data else None,
                    "cache_stats": cache_stats,
                    "all_matching_documents": all_documents,
                    "total_matching_docs": len(all_documents),
                }
            )

        except Exception as e:
            logger.error(f"Error in debug cache lookup: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/card-sets", methods=["GET"])
    @monitor_memory
    def get_all_card_sets():
        """Get all card sets from YGO API."""
        try:
            card_sets = card_set_service.fetch_all_card_sets()
            return jsonify({"success": True, "data": card_sets})
        except Exception as e:
            logger.error(f"Error fetching card sets: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/card-sets/search/<string:set_name>", methods=["GET"])
    @monitor_memory
    def search_card_sets(set_name: str):
        """Search card sets by name."""
        try:
            card_sets = card_set_service.search_card_sets(set_name)
            return jsonify({"success": True, "data": card_sets, "search_term": set_name})
        except Exception as e:
            logger.error(f"Error searching card sets: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/card-sets/upload", methods=["POST"])
    @monitor_memory
    def upload_card_sets_to_mongodb():
        """Upload card sets to MongoDB."""
        try:
            result = card_set_service.upload_card_sets_to_cache()
            return jsonify(
                {
                    "success": True,
                    "message": "Card sets uploaded successfully to MongoDB",
                    "statistics": result,
                }
            )
        except Exception as e:
            logger.error(f"Error uploading card sets: {e}")
            return (
                jsonify({"success": False, "error": "Internal server error during upload"}),
                500,
            )

    @app.route("/card-sets/from-cache", methods=["GET"])
    @monitor_memory
    def get_card_sets_from_cache():
        """Get card sets from MongoDB cache."""
        try:
            card_sets = card_set_service.get_cached_card_sets()
            return jsonify({"success": True, "data": card_sets, "count": len(card_sets)})
        except Exception as e:
            logger.error(f"Error getting cached card sets: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/card-sets/count", methods=["GET"])
    @monitor_memory
    def get_card_sets_count():
        """Get total count of card sets."""
        try:
            count = card_set_service.get_card_sets_count()
            return jsonify({"success": True, "count": count})
        except Exception as e:
            logger.error(f"Error getting card sets count: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/card-sets/<string:set_name>/cards", methods=["GET"])
    @monitor_memory
    def get_cards_from_specific_set(set_name: str):
        """Get all cards from a specific set, filtered to only show variants from that set."""
        try:
            # Get optional query parameters
            filter_by_set = request.args.get("filter_by_set", "true").lower() == "true"
            include_set_code = request.args.get("include_set_code", "false").lower() == "true"

            # First get unfiltered cards to track total count
            from urllib.parse import quote

            import requests

            from .config import YGO_API_BASE_URL

            # URL encode the set name for the API call
            encoded_set_name = quote(set_name)

            # Make request to YGO API for cards in this set
            logger.info(f"Fetching cards from set: {set_name}")
            api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
            response = requests.get(api_url, timeout=15)

            if response.status_code == 200:
                cards_data = response.json()
                cards_list = cards_data.get("data", [])

                logger.info(f"Retrieved {len(cards_list)} cards from YGO API for {set_name}")

                # Filter cards by set if requested (default: true)
                if filter_by_set:
                    from .utils import filter_cards_by_set

                    filtered_cards = filter_cards_by_set(cards_list, set_name)
                else:
                    filtered_cards = cards_list

                # Get set code if requested
                set_code_info = {}
                if include_set_code:
                    # This would need to be implemented if needed
                    pass

                logger.info(f"Returning {len(filtered_cards)} filtered cards from {set_name}")

                response_data = {
                    "success": True,
                    "set_name": set_name,
                    "data": filtered_cards,
                    "card_count": len(filtered_cards),
                    "total_cards_before_filter": len(cards_list),
                    "message": f"Successfully fetched {len(filtered_cards)} cards from {set_name}",
                    "filtered_by_set": filter_by_set,
                }

                # Add set code info if requested
                if set_code_info:
                    response_data.update(set_code_info)

                return jsonify(response_data)

            elif response.status_code == 400:
                return (
                    jsonify(
                        {
                            "success": False,
                            "set_name": set_name,
                            "error": "No cards found for this set or invalid set name",
                            "card_count": 0,
                            "data": [],
                        }
                    ),
                    404,
                )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "set_name": set_name,
                            "error": f"API returned status {response.status_code}",
                            "card_count": 0,
                            "data": [],
                        }
                    ),
                    500,
                )

        except Exception as e:
            logger.error(f"Error getting cards from set {set_name}: {e}")
            return (
                jsonify(
                    {
                        "success": False,
                        "set_name": set_name,
                        "error": "Internal server error",
                        "card_count": 0,
                        "data": [],
                    }
                ),
                500,
            )

    @app.route("/card-sets/fetch-all-cards", methods=["POST"])
    @monitor_memory
    def fetch_all_cards_from_sets():
        """Fetch all cards from all cached sets."""
        try:
            # This is a simplified implementation
            # The original had complex filtering logic
            return jsonify(
                {
                    "success": True,
                    "message": "Card fetching endpoint simplified in modular version",
                    "data": {},
                    "statistics": {
                        "total_sets": 0,
                        "processed_sets": 0,
                        "failed_sets": 0,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Error fetching all cards: {e}")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Internal server error during card fetching",
                    }
                ),
                500,
            )

    @app.route("/cards/upload-variants", methods=["POST"])
    @monitor_memory
    def upload_card_variants_to_mongodb():
        """Upload card variants to MongoDB."""
        try:
            result = card_variant_service.upload_card_variants_to_cache()
            return jsonify(
                {
                    "success": True,
                    "message": "Card variants uploaded successfully to MongoDB",
                    **result,
                }
            )
        except Exception as e:
            logger.error(f"Error uploading card variants: {e}")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Internal server error during variant upload",
                    }
                ),
                500,
            )

    @app.route("/cards/variants", methods=["GET"])
    @monitor_memory
    def get_card_variants_from_cache():
        """Get card variants from MongoDB cache."""
        try:
            variants = card_variant_service.get_cached_card_variants()
            return jsonify({"success": True, "data": variants, "count": len(variants)})
        except Exception as e:
            logger.error(f"Error getting card variants: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/memory/stats", methods=["GET"])
    @monitor_memory
    def get_memory_statistics():
        """Get memory usage statistics."""
        try:
            stats = get_memory_stats()
            return jsonify({"success": True, "memory_stats": stats})
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/memory/cleanup", methods=["POST"])
    @monitor_memory
    def force_memory_cleanup_endpoint():
        """Force memory cleanup."""
        try:
            force_memory_cleanup()
            stats = get_memory_stats()
            return jsonify(
                {
                    "success": True,
                    "message": "Memory cleanup completed",
                    "memory_stats": stats,
                }
            )
        except Exception as e:
            logger.error(f"Error during memory cleanup: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/debug/art-extraction", methods=["POST"])
    @monitor_memory
    def debug_art_extraction():
        """Debug endpoint to test art variant extraction."""
        try:
            data = request.get_json()
            test_strings = data.get("test_strings", [])

            results = []
            for test_string in test_strings:
                extracted_art = extract_art_version(test_string)
                results.append({"input": test_string, "extracted_art": extracted_art})

            return jsonify({"success": True, "results": results})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # Rate limiting storage for image proxy
    last_image_request_time = {"time": 0}

    @app.route("/cards/image", methods=["GET"])
    @monitor_memory
    def proxy_card_image_legacy():
        """
        Proxy images from YGO API to avoid CORS issues and provide rate limiting.
        This is the legacy endpoint that matches the original main.py implementation.

        Query parameters:
        - url: The image URL to proxy (must be from images.ygoprodeck.com)
        """
        try:
            image_url = request.args.get("url")
            if not image_url:
                return (
                    jsonify({"success": False, "error": "Missing 'url' parameter"}),
                    400,
                )

            # Decode URL if it's encoded
            image_url = unquote(image_url)

            # Security check: only allow YGO API images
            if not image_url.startswith(
                ("https://images.ygoprodeck.com/", "http://images.ygoprodeck.com/")
            ):
                return (
                    jsonify({"success": False, "error": "Only YGO API images are allowed"}),
                    403,
                )

            # Rate limiting: ensure minimum delay between image requests
            current_time = time.time()
            time_since_last = current_time - last_image_request_time["time"]
            if time_since_last < API_RATE_LIMIT_DELAY:
                time.sleep(API_RATE_LIMIT_DELAY - time_since_last)

            last_image_request_time["time"] = time.time()

            # Fetch the image from YGO API
            response = requests.get(image_url, timeout=10, stream=True)

            if response.status_code == 200:
                # Determine content type
                content_type = response.headers.get("content-type", "image/jpeg")

                # Create response with proper headers
                def generate():
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk

                return Response(
                    generate(),
                    content_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET",
                        "Access-Control-Allow-Headers": "Content-Type",
                    },
                )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to fetch image: HTTP {response.status_code}",
                        }
                    ),
                    response.status_code,
                )

        except requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "Timeout fetching image"}), 504
        except Exception as e:
            logger.error(f"Error proxying image: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/image/proxy", methods=["GET"])
    @monitor_memory
    def proxy_card_image_new():
        """
        Proxy images from YGO API to avoid CORS issues and provide rate limiting.
        This is the new API endpoint with enhanced functionality.

        Query parameters:
        - url: The image URL to proxy (must be from images.ygoprodeck.com)
        """
        try:
            image_url = request.args.get("url")
            if not image_url:
                return (
                    jsonify({"success": False, "error": "Missing 'url' parameter"}),
                    400,
                )

            # Decode URL if it's encoded
            image_url = unquote(image_url)

            # Security check: only allow YGO API images
            if not image_url.startswith(
                ("https://images.ygoprodeck.com/", "http://images.ygoprodeck.com/")
            ):
                return (
                    jsonify({"success": False, "error": "Only YGO API images are allowed"}),
                    403,
                )

            # Rate limiting: ensure minimum delay between image requests
            current_time = time.time()
            time_since_last = current_time - last_image_request_time["time"]
            if time_since_last < API_RATE_LIMIT_DELAY:
                time.sleep(API_RATE_LIMIT_DELAY - time_since_last)

            last_image_request_time["time"] = time.time()

            # Fetch the image from YGO API
            response = requests.get(image_url, timeout=10, stream=True)

            if response.status_code == 200:
                # Determine content type
                content_type = response.headers.get("content-type", "image/jpeg")

                # Create response with proper headers
                def generate():
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk

                return Response(
                    generate(),
                    content_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET",
                        "Access-Control-Allow-Headers": "Content-Type",
                    },
                )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to fetch image: HTTP {response.status_code}",
                        }
                    ),
                    response.status_code,
                )

        except requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "Timeout fetching image"}), 504
        except Exception as e:
            logger.error(f"Error proxying image: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/cards/image/<int:card_id>", methods=["GET"])
    @monitor_memory
    def get_card_image_by_id(card_id: int):
        """
        Get card image URL by card ID with built-in proxy option.

        Query parameters:
        - proxy: If 'true', returns proxied URL through this server
        - size: 'small', 'normal', or 'cropped' (default: 'normal')
        """
        try:
            proxy_enabled = request.args.get("proxy", "false").lower() == "true"
            size = request.args.get("size", "normal").lower()

            # Construct YGO API image URL based on size
            if size == "small":
                image_url = f"https://images.ygoprodeck.com/images/cards_small/{card_id}.jpg"
            elif size == "cropped":
                image_url = f"https://images.ygoprodeck.com/images/cards_cropped/{card_id}.jpg"
            else:  # normal
                image_url = f"https://images.ygoprodeck.com/images/cards/{card_id}.jpg"

            if proxy_enabled:
                # Return proxied URL
                from urllib.parse import quote

                proxied_url = f"/api/image/proxy?url={quote(image_url)}"
                return jsonify(
                    {
                        "success": True,
                        "card_id": card_id,
                        "image_url": proxied_url,
                        "direct_url": image_url,
                        "proxy_enabled": True,
                        "size": size,
                    }
                )
            else:
                # Return direct URL
                return jsonify(
                    {
                        "success": True,
                        "card_id": card_id,
                        "image_url": image_url,
                        "proxy_enabled": False,
                        "size": size,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting card image for ID {card_id}: {e}")
            return (
                jsonify({"success": False, "error": "Failed to get card image URL"}),
                500,
            )

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return jsonify({"success": False, "error": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        return jsonify({"success": False, "error": "Internal server error"}), 500
