"""
Unit tests for routes.py module.

Tests all Flask routes and API endpoints with comprehensive coverage of
success cases, error handling, and edge scenarios.
"""

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
from flask import Flask

from ygoapi.routes import register_routes


class TestRouteRegistration:
    """Test route registration and Flask app integration."""

    def test_register_routes(self):
        """Test that routes are properly registered with Flask app."""
        # Create a fresh Flask app for testing route registration
        from flask import Flask
        test_app = Flask(__name__)

        # Get initial rule count
        initial_rules = len(test_app.url_map._rules)

        # Register routes
        register_routes(test_app)

        # Verify routes were added
        final_rules = len(test_app.url_map._rules)
        assert final_rules > initial_rules

        # Check for specific routes
        route_paths = [rule.rule for rule in test_app.url_map.iter_rules()]
        expected_routes = [
            "/health",
            "/cards/price",
            "/card-sets",
            "/memory/stats",
            "/cards/image",
        ]

        for route in expected_routes:
            assert route in route_paths


class TestHealthCheck:
    """Test health check endpoint."""

    @patch("ygoapi.routes.get_memory_stats")
    def test_health_check_success(self, mock_memory_stats, client):
        """Test successful health check."""
        mock_memory_stats.return_value = {"rss_mb": 256.5, "percent": 12.5}

        response = client.get("/health")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "YGO Card Sets API"
        assert "memory_stats" in data


class TestCardPriceEndpoint:
    """Test card price scraping endpoint."""

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_success(self, mock_service, client):
        """Test successful card price scraping."""
        # Setup mock service responses with serializable data
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"

        # Use serializable datetime string instead of datetime object
        mock_service.scrape_card_price.return_value = {
            "success": True,
            "tcgplayer_price": 25.99,
            "tcgplayer_market_price": 24.50,
            "tcgplayer_url": "https://tcgplayer.com/test",
            "last_updated": "2025-07-16T10:00:00Z",  # String instead of datetime
            "cached": False,
        }

        request_data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "force_refresh": False,
        }

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "data" in data
        assert data["data"]["tcg_price"] == 25.99
        assert data["is_cached"] is False

        # Verify service calls - validation and lookup happen in the service layer now
        mock_service.scrape_card_price.assert_called_once()
        # Note: validate_card_rarity and lookup_card_name are called within scrape_card_price
        # so we don't test them separately here since they're internal implementation details

    def test_scrape_card_price_missing_json(self, client):
        """Test price scraping with missing JSON body."""
        response = client.post("/cards/price")

        assert response.status_code == 500  # The new API returns 500 for missing content-type
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error" in data["error"]

    def test_scrape_card_price_missing_required_fields(self, client):
        """Test price scraping with missing required fields."""
        request_data = {
            "force_refresh": True
            # Missing card_number, card_name, and card_rarity
        }

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        # The API now requires either card_number OR card_name (line 56-61 in routes.py)
        # AND card_rarity (line 74-78 in routes.py)
        # Since we have neither card_number nor card_name, it should fail
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        # Should fail because we have neither card_number nor card_name
        assert "Either card_number or card_name is required" in data["error"]

    def test_scrape_card_price_empty_rarity(self, client):
        """Test price scraping with empty card rarity."""
        request_data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "",  # Empty rarity
        }

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "card_rarity" in data["error"]

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_invalid_rarity(self, mock_service, client):
        """Test price scraping with invalid rarity."""
        # Mock ALL methods that might be called to return serializable data
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"
        mock_service.scrape_card_price.return_value = {
            "success": False,
            "error": "Invalid rarity 'Invalid Rarity' for card LOB-001. This rarity does not exist for this card in its set.",
            "cached": False,
            "tcgplayer_price": None,
            "tcgplayer_market_price": None,
            "tcgplayer_url": None,
            "last_updated": None
        }

        request_data = {"card_number": "LOB-001", "card_rarity": "Invalid Rarity"}

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        # The error message is nested in the data object as error_message
        assert "Invalid rarity" in data["data"]["error_message"]

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_with_art_variant(self, mock_service, client):
        """Test price scraping with art variant."""
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"
        mock_service.scrape_card_price.return_value = {
            "success": True,
            "tcgplayer_price": 30.00,
            "cached": False,
            "last_updated": None,
            "tcgplayer_url": None,
        }

        request_data = {
            "card_number": "LOB-001",
            "card_rarity": "Ultra Rare",
            "art_variant": "Alternate Art",
        }

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_cached_response(self, mock_service, client):
        """Test price scraping with cached response."""
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"
        mock_service.scrape_card_price.return_value = {
            "success": True,
            "tcgplayer_price": 25.99,
            "last_updated": "2025-07-16T10:00:00Z",  # String instead of datetime
            "cached": True,
            "tcgplayer_url": None,
        }

        request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["is_cached"] is True
        assert "cache_age_hours" in data
        assert "Price data retrieved from cache" in data["message"]

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_not_found(self, mock_service, client):
        """Test price scraping when card not found."""
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = None
        mock_service.scrape_card_price.return_value = {
            "success": False,
            "error": "Card not found in TCGPlayer",
            "cached": False,
        }

        request_data = {"card_number": "INVALID", "card_rarity": "Ultra Rare"}

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_server_error(self, mock_service, client):
        """Test price scraping with server error."""
        mock_service.validate_card_rarity.side_effect = Exception("Database error")

        request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}

        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error" in data["error"]


class TestPriceCacheStatsEndpoint:
    """Test price cache statistics endpoint."""

    @patch("ygoapi.routes.price_scraping_service")
    def test_get_price_cache_stats_success(self, mock_service, client):
        """Test successful cache stats retrieval."""
        mock_service.get_cache_stats.return_value = {
            "total_documents": 150,
            "avg_age_hours": 12.5,
        }

        response = client.get("/cards/price/cache-stats")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "cache_stats" in data
        assert data["cache_stats"]["total_documents"] == 150

    @patch("ygoapi.routes.price_scraping_service")
    def test_get_price_cache_stats_error(self, mock_service, client):
        """Test cache stats with error."""
        mock_service.get_cache_stats.side_effect = Exception("Database error")

        response = client.get("/cards/price/cache-stats")

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False


class TestCardSetsEndpoints:
    """Test card sets related endpoints."""

    @patch("ygoapi.routes.card_set_service")
    def test_get_all_card_sets_success(self, mock_service, client):
        """Test successful retrieval of all card sets."""
        # Use proper serializable data instead of mock objects
        mock_sets = [
            {
                "set_name": "Legend of Blue Eyes",
                "set_code": "LOB",
                "tcg_date": "1999-01-01",
                "num_cards": 126
            },
            {
                "set_name": "Metal Raiders", 
                "set_code": "MRD",
                "tcg_date": "1999-04-01",
                "num_cards": 122
            },
        ]
        mock_service.fetch_all_card_sets.return_value = mock_sets

        response = client.get("/card-sets")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert len(data["data"]) == 2
        assert data["data"][0]["set_code"] == "LOB"

    @patch("ygoapi.routes.card_set_service")
    def test_search_card_sets_success(self, mock_service, client):
        """Test successful card set search."""
        mock_sets = [{"set_name": "Blue Eyes Set", "set_code": "BES"}]
        mock_service.search_card_sets.return_value = mock_sets

        response = client.get("/card-sets/search/blue%20eyes")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["search_term"] == "blue eyes"
        assert len(data["data"]) == 1

    @patch("ygoapi.routes.card_set_service")
    def test_upload_card_sets_success(self, mock_service, client):
        """Test successful card sets upload."""
        # Use serializable statistics instead of mock objects
        mock_service.upload_card_sets_to_cache.return_value = {
            "total_sets_uploaded": 50,
            "upload_timestamp": "2025-07-16T10:00:00Z",
            "previous_documents_cleared": 0,
            "collection_name": "YGO_SETS_CACHE_V1"
        }

        response = client.post("/card-sets/upload")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "statistics" in data
        assert data["statistics"]["total_sets_uploaded"] == 50

    @patch("ygoapi.routes.card_set_service")
    def test_get_card_sets_from_cache_success(self, mock_service, client):
        """Test successful retrieval from cache."""
        mock_sets = [{"set_name": "Cached Set", "set_code": "CS"}]
        mock_service.get_cached_card_sets.return_value = mock_sets

        response = client.get("/card-sets/from-cache")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["count"] == 1
        assert data["data"][0]["set_code"] == "CS"

    @patch("ygoapi.routes.card_set_service")
    def test_get_card_sets_count_success(self, mock_service, client):
        """Test successful card sets count retrieval."""
        mock_service.get_card_sets_count.return_value = 42

        response = client.get("/card-sets/count")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["count"] == 42


class TestCardSetsCardsEndpoint:
    """Test getting cards from specific sets."""

    @patch("ygoapi.routes.requests.get")
    def test_get_cards_from_specific_set_success(self, mock_get, client):
        """Test successful retrieval of cards from a specific set."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": 1, "name": "Card 1", "card_sets": [{"set_name": "Test Set"}]},
                {"id": 2, "name": "Card 2", "card_sets": [{"set_name": "Test Set"}]},
            ]
        }
        mock_get.return_value = mock_response

        response = client.get("/card-sets/Test%20Set/cards")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["set_name"] == "Test Set"
        assert "card_count" in data
        assert "data" in data

    @patch("ygoapi.routes.requests.get")
    def test_get_cards_from_specific_set_not_found(self, mock_get, client):
        """Test retrieval when set not found."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_get.return_value = mock_response

        response = client.get("/card-sets/Invalid%20Set/cards")

        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False
        assert "No cards found" in data["error"]

    @patch("ygoapi.routes.requests.get")
    def test_get_cards_from_specific_set_with_params(self, mock_get, client):
        """Test retrieval with query parameters."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_get.return_value = mock_response

        response = client.get(
            "/card-sets/Test%20Set/cards?filter_by_set=false&include_set_code=true"
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["filtered_by_set"] is False


class TestCardVariantsEndpoints:
    """Test card variants related endpoints."""

    @patch("ygoapi.routes.card_variant_service")
    def test_upload_card_variants_success(self, mock_service, client):
        """Test successful card variants upload."""
        # Use serializable response data
        mock_service.upload_card_variants_to_cache.return_value = {
            "total_variants_created": 100,
            "upload_timestamp": "2025-07-16T10:00:00Z",
            "processing_time_seconds": 45.2,
            "statistics": {
                "total_variants_created": 100,
                "success_rate": 100.0
            }
        }

        response = client.post("/cards/upload-variants")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "statistics" in data

    @patch("ygoapi.routes.card_variant_service")
    def test_get_card_variants_from_cache_success(self, mock_service, client):
        """Test successful card variants retrieval."""
        # Use proper serializable variant data
        mock_variants = [
            {
                "_variant_id": "variant_1",
                "card_name": "Blue-Eyes White Dragon",
                "card_id": 46986414,
                "set_name": "Legend of Blue Eyes",
                "set_code": "LOB-001",
                "rarity": "Ultra Rare"
            },
            {
                "_variant_id": "variant_2", 
                "card_name": "Dark Magician",
                "card_id": 46986415,
                "set_name": "Legend of Blue Eyes", 
                "set_code": "LOB-005",
                "rarity": "Ultra Rare"
            },
        ]
        mock_service.get_cached_card_variants.return_value = mock_variants

        response = client.get("/cards/variants")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["count"] == 2
        assert len(data["data"]) == 2


class TestMemoryEndpoints:
    """Test memory management endpoints."""

    @patch("ygoapi.routes.get_memory_stats")
    def test_get_memory_statistics_success(self, mock_get_stats, client):
        """Test successful memory stats retrieval."""
        mock_get_stats.return_value = {"rss_mb": 256.5, "percent": 12.5}

        response = client.get("/memory/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "memory_stats" in data

    @patch("ygoapi.routes.force_memory_cleanup")
    @patch("ygoapi.routes.get_memory_stats")
    def test_force_memory_cleanup_success(self, mock_get_stats, mock_cleanup, client):
        """Test successful memory cleanup."""
        mock_get_stats.return_value = {"rss_mb": 200.0}

        response = client.post("/memory/cleanup")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "Memory cleanup completed" in data["message"]
        mock_cleanup.assert_called_once()


class TestDebugEndpoints:
    """Test debug endpoints."""

    @patch("ygoapi.routes.price_scraping_service")
    @patch("ygoapi.database.get_price_cache_collection")
    def test_debug_cache_lookup_success(self, mock_get_collection, mock_service, client):
        """Test successful debug cache lookup."""
        # Setup mocks
        mock_service.get_cache_stats.return_value = {"total_documents": 100}
        mock_service.find_cached_price_data.return_value = {
            "card_number": "LOB-001",
            "tcgplayer_price": 25.99,
        }

        mock_collection_instance = Mock()
        mock_collection_instance.find.return_value = [
            {
                "card_number": "LOB-001",
                "card_name": "Blue-Eyes White Dragon",
                "card_rarity": "Ultra Rare",
                "tcgplayer_price": 25.99,
            }
        ]
        mock_get_collection.return_value = mock_collection_instance

        request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}

        response = client.post(
            "/debug/cache-lookup",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["cache_hit"] is True
        assert "cached_data" in data

    @patch("ygoapi.routes.extract_art_version")
    def test_debug_art_extraction_success(self, mock_extract, client):
        """Test successful art extraction debug."""
        mock_extract.side_effect = lambda x: x.upper()  # Simple mock behavior

        request_data = {"test_strings": ["test1", "test2"]}

        response = client.post(
            "/debug/art-extraction",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert len(data["results"]) == 2
        assert data["results"][0]["input"] == "test1"
        assert data["results"][0]["extracted_art"] == "TEST1"


class TestImageProxyEndpoints:
    """Test image proxy endpoints."""

    def test_proxy_card_image_missing_url(self, client):
        """Test image proxy with missing URL parameter."""
        response = client.get("/cards/image")

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "Missing 'url' parameter" in data["error"]

    def test_proxy_card_image_invalid_domain(self, client):
        """Test image proxy with invalid domain."""
        response = client.get("/cards/image?url=https://malicious.com/image.jpg")

        assert response.status_code == 403
        data = response.get_json()
        assert data["success"] is False
        assert "Only YGO API images are allowed" in data["error"]

    @patch("ygoapi.routes.requests.get")
    @patch("ygoapi.routes.time.sleep")
    def test_proxy_card_image_success(self, mock_sleep, mock_get, client):
        """Test successful image proxy."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"fake_image_data"]
        mock_get.return_value = mock_response

        url = "https://images.ygoprodeck.com/images/cards/12345.jpg"
        response = client.get(f"/cards/image?url={url}")

        assert response.status_code == 200
        assert response.content_type == "image/jpeg"
        assert b"fake_image_data" in response.data

    @patch("ygoapi.routes.requests.get")
    def test_proxy_card_image_timeout(self, mock_get, client):
        """Test image proxy with timeout."""
        import requests

        mock_get.side_effect = requests.exceptions.Timeout()

        url = "https://images.ygoprodeck.com/images/cards/12345.jpg"
        response = client.get(f"/cards/image?url={url}")

        assert response.status_code == 504
        data = response.get_json()
        assert data["success"] is False
        assert "Timeout" in data["error"]

    def test_get_card_image_by_id_success(self, client):
        """Test successful card image URL generation by ID."""
        response = client.get("/api/cards/image/12345")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["card_id"] == 12345
        assert "images.ygoprodeck.com" in data["image_url"]
        assert data["proxy_enabled"] is False

    def test_get_card_image_by_id_with_proxy(self, client):
        """Test card image URL generation with proxy enabled."""
        response = client.get("/api/cards/image/12345?proxy=true&size=small")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["proxy_enabled"] is True
        assert data["size"] == "small"
        assert "/api/image/proxy" in data["image_url"]


class TestErrorHandlers:
    """Test error handlers."""

    def test_404_handler(self, client):
        """Test 404 error handler."""
        response = client.get("/nonexistent-endpoint")

        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False
        assert "not found" in data["error"].lower()


class TestRateLimiting:
    """Test rate limiting functionality."""

    @patch("ygoapi.routes.requests.get")
    @patch("ygoapi.routes.time.sleep")
    def test_image_proxy_rate_limiting(self, mock_sleep, mock_get, client):
        """Test that rate limiting is applied to image proxy requests."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"fake_image_data"]
        mock_get.return_value = mock_response

        url = "https://images.ygoprodeck.com/images/cards/12345.jpg"

        # Make first request
        client.get(f"/cards/image?url={url}")

        # Make second request immediately - should trigger rate limiting
        client.get(f"/cards/image?url={url}")

        # Verify sleep was called for rate limiting
        mock_sleep.assert_called()


class TestRequestValidation:
    """Test request validation across endpoints."""

    def test_price_endpoint_force_refresh_conversion(self, client):
        """Test force_refresh boolean conversion in price endpoint."""
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("", False),
            ("invalid", False),
        ]

        for input_val, expected in test_cases:
            with patch("ygoapi.routes.price_scraping_service") as mock_service:
                mock_service.validate_card_rarity.return_value = True
                mock_service.scrape_card_price.return_value = {"success": True}

                request_data = {
                    "card_number": "LOB-001",
                    "card_rarity": "Ultra Rare",
                    "force_refresh": input_val,
                }

                response = client.post(
                    "/cards/price",
                    data=json.dumps(request_data),
                    content_type="application/json",
                )

                # Check that the service was called with correct boolean value
                call_args = mock_service.scrape_card_price.call_args
                assert call_args[1]["force_refresh"] == expected

    def test_art_variant_handling(self, client):
        """Test art_variant parameter handling in price endpoint."""
        test_cases = [
            (None, None),
            ("", ""),
            ("  ", ""),
            ("Alternate Art", "Alternate Art"),
            ("  Alternate Art  ", "Alternate Art"),
        ]

        for input_val, expected in test_cases:
            with patch("ygoapi.routes.price_scraping_service") as mock_service:
                mock_service.validate_card_rarity.return_value = True
                mock_service.scrape_card_price.return_value = {"success": True}

                request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}

                if input_val is not None:
                    request_data["art_variant"] = input_val

                response = client.post(
                    "/cards/price",
                    data=json.dumps(request_data),
                    content_type="application/json",
                )

                # Check that the service was called with correct art_variant value
                call_args = mock_service.scrape_card_price.call_args
                assert call_args[1]["art_variant"] == expected


class TestFetchAllCardsEndpoint:
    """Test fetch all cards endpoint."""

    def test_fetch_all_cards_simplified_response(self, client):
        """Test the simplified fetch all cards endpoint."""
        response = client.post("/card-sets/fetch-all-cards")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "simplified" in data["message"]
        assert "statistics" in data
        assert data["statistics"]["total_sets"] == 0


class TestErrorHandlingEnhancement:
    """Test error handling paths that were previously uncovered."""

    def test_scrape_card_price_invalid_json_content_type(self, client):
        """Test price endpoint with invalid content type (lines 198-204)."""
        response = client.post(
            "/cards/price",
            data="invalid json",
            content_type="text/plain",
        )

        assert response.status_code == 500  # Updated to match new API behavior
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error" in data["error"]

    def test_scrape_card_price_malformed_json(self, client):
        """Test price endpoint with malformed JSON (lines 206-208)."""
        response = client.post(
            "/cards/price",
            data="{ invalid json }",
            content_type="application/json",
        )

        assert response.status_code == 500  # Updated to match new API behavior
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error" in data["error"]

    def test_scrape_card_price_empty_request_body(self, client):
        """Test price endpoint with empty request body (line 231)."""
        response = client.post(
            "/cards/price",
            data=json.dumps(None),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "Request body must be JSON" in data["error"]

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_validation_error_classification(self, mock_service, client):
        """Test price endpoint error classification (lines 461-476)."""
        # Test "invalid" error -> 400
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"
        mock_service.scrape_card_price.return_value = {
            "success": False,
            "error": "Invalid card rarity specified",
            "cached": False
        }

        request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}
        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_not_found_error_classification(self, mock_service, client):
        """Test price endpoint 404 error classification (lines 508-510)."""
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"
        mock_service.scrape_card_price.return_value = {
            "success": False,
            "error": "Card not found in database",
            "cached": False
        }

        request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}
        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False

    @patch("ygoapi.routes.price_scraping_service")
    def test_scrape_card_price_server_error_classification(self, mock_service, client):
        """Test price endpoint 500 error classification (lines 533-535)."""
        mock_service.validate_card_rarity.return_value = True
        mock_service.lookup_card_name.return_value = "Blue-Eyes White Dragon"
        mock_service.scrape_card_price.return_value = {
            "success": False,
            "error": "Database connection timeout",
            "cached": False
        }

        request_data = {"card_number": "LOB-001", "card_rarity": "Ultra Rare"}
        response = client.post(
            "/cards/price",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

    def test_debug_cache_lookup_invalid_request_body(self, client):
        """Test debug cache lookup with invalid request body (lines 317-319)."""
        # Test the actual behavior when invalid JSON is sent
        response = client.post(
            "/debug/cache-lookup",
            data="invalid json {",
            content_type="application/json",
        )

        # The endpoint catches the exception and returns 500
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

    def test_debug_cache_lookup_empty_request_body(self, client):
        """Test debug cache lookup with empty request body (lines 339-341)."""
        response = client.post(
            "/debug/cache-lookup",
            data=json.dumps(None),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "Request body must be JSON" in data["error"]

    @patch("ygoapi.routes.price_scraping_service")
    def test_debug_cache_lookup_service_error(self, mock_service, client):
        """Test debug cache lookup with service error (lines 356-358)."""
        mock_service.get_cache_stats.side_effect = Exception("Database error")

        request_data = {"card_number": "LOB-001"}
        response = client.post(
            "/debug/cache-lookup",
            data=json.dumps(request_data),
            content_type="application/json",
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

    @patch("ygoapi.routes.card_set_service")
    def test_card_sets_service_exceptions(self, mock_service, client):
        """Test card sets endpoints with service exceptions."""
        # Test fetch all card sets error
        mock_service.fetch_all_card_sets.side_effect = Exception("API error")
        response = client.get("/card-sets")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error" in data["error"]

        # Test search card sets error
        mock_service.search_card_sets.side_effect = Exception("Search error")
        response = client.get("/card-sets/search/test")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

        # Test upload card sets error
        mock_service.upload_card_sets_to_cache.side_effect = Exception("Upload error")
        response = client.post("/card-sets/upload")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error during upload" in data["error"]

    @patch("ygoapi.routes.card_variant_service")
    def test_card_variants_service_exceptions(self, mock_service, client):
        """Test card variants endpoints with service exceptions."""
        # Test upload variants error
        mock_service.upload_card_variants_to_cache.side_effect = Exception("Upload error")
        response = client.post("/cards/upload-variants")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error during variant upload" in data["error"]

        # Test get variants error
        mock_service.get_cached_card_variants.side_effect = Exception("Cache error")
        response = client.get("/cards/variants")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

    @patch("ygoapi.routes.get_memory_stats")
    def test_memory_endpoints_exceptions(self, mock_get_stats, client):
        """Test memory endpoints with service exceptions."""
        # Test memory stats error
        mock_get_stats.side_effect = Exception("Memory error")
        response = client.get("/memory/stats")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

        # Test memory cleanup error
        with patch("ygoapi.routes.force_memory_cleanup") as mock_cleanup:
            mock_cleanup.side_effect = Exception("Cleanup error")
            response = client.post("/memory/cleanup")
            assert response.status_code == 500
            data = response.get_json()
            assert data["success"] is False

    @patch("ygoapi.routes.requests.get")
    def test_image_proxy_http_errors(self, mock_get, client):
        """Test image proxy with various HTTP errors."""
        # Test 404 error
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        url = "https://images.ygoprodeck.com/images/cards/12345.jpg"
        response = client.get(f"/cards/image?url={url}")
        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False
        assert "Failed to fetch image" in data["error"]

        # Test 500 error
        mock_response.status_code = 500
        response = client.get(f"/cards/image?url={url}")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False

    @patch("ygoapi.routes.requests.get")
    def test_cards_from_set_api_errors(self, mock_get, client):
        """Test cards from set endpoint with API errors."""
        # Test API 500 error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        response = client.get("/card-sets/Test%20Set/cards")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        # Updated to match the actual error message format
        assert "API returned status 500" in data["error"]

        # Test network exception
        mock_get.side_effect = Exception("Network error")
        response = client.get("/card-sets/Test%20Set/cards")
        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
        assert "Internal server error" in data["error"]

    def test_500_error_handler_trigger(self, client):
        """Test that 500 error handler is properly configured."""
        # This tests the error handler registration, not triggering it
        # since Flask test client doesn't trigger error handlers the same way
        from ygoapi.routes import register_routes
        from flask import Flask
        
        test_app = Flask(__name__)
        register_routes(test_app)
        
        # Verify error handler is registered
        assert 500 in test_app.error_handler_spec[None]
        assert 404 in test_app.error_handler_spec[None]
