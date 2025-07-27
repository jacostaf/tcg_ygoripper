"""
Tests for Enhanced Rarity Validation with YGO API Integration

This test module covers the new validation logic that validates against
the original YGO API set data rather than just our potentially incomplete cache.
"""

import pytest
from unittest.mock import patch, MagicMock, Mock
import requests
from datetime import datetime, timezone, timedelta

from ygoapi.price_scraping import PriceScrapingService


class TestEnhancedRarityValidation:
    """Test suite for the enhanced rarity validation that uses YGO API as source of truth."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch("ygoapi.price_scraping.get_memory_manager"):
            return PriceScrapingService()

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_against_ygo_api_success(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test successful validation against YGO API set data."""
        # Setup mocks
        mock_extract_set.return_value = "BLTR"
        
        # Mock YGO API response with multiple rarities for the same card
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Test Card",
                    "card_sets": [
                        {
                            "set_code": "BLTR-EN051",
                            "set_rarity": "Secret Rare"
                        },
                        {
                            "set_code": "BLTR-EN051",
                            "set_rarity": "Quarter Century Secret Rare"
                        }
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # Setup database collection (should not be called since API validation succeeds)
        mock_get_collection.return_value = MagicMock()
        
        # Test: Request for "Secret Rare" should succeed even if cache only has "Quarter Century Secret Rare"
        result = service.validate_card_rarity("BLTR-EN051", "Secret Rare")
        
        assert result is True
        # Verify API was called
        mock_requests.assert_called_once()
        assert "cardset=BLTR" in mock_requests.call_args[0][0]

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_against_ygo_api_rarity_not_found(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test validation when rarity not found in YGO API but exists in cache."""
        # Setup mocks
        mock_extract_set.return_value = "LOB"
        
        # Mock YGO API response without the requested rarity
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Blue-Eyes White Dragon",
                    "card_sets": [
                        {
                            "set_code": "LOB-001",
                            "set_rarity": "Ultra Rare"
                        }
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # Setup cache fallback with the requested rarity
        mock_collection = MagicMock()
        mock_collection.find.return_value = [{"set_rarity": "Ghost Rare"}]  # Different rarity in cache
        mock_get_collection.return_value = mock_collection
        
        # Test: Request for "Ghost Rare" should fall back to cache validation
        result = service.validate_card_rarity("LOB-001", "Ghost Rare")
        
        assert result is True  # Should allow due to graceful fallback
        # Verify both API and cache were attempted
        mock_requests.assert_called_once()
        mock_collection.find.assert_called_once()

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_api_failure_fallback_to_cache(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test fallback to cache when YGO API fails."""
        # Setup mocks
        mock_extract_set.return_value = "LOB"
        
        # Mock API failure
        mock_requests.side_effect = requests.exceptions.RequestException("API unavailable")
        
        # Setup cache with valid rarity
        mock_collection = MagicMock()
        mock_collection.find.return_value = [{"set_rarity": "Ultra Rare"}]
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True
        # Verify fallback to cache was used
        mock_collection.find.assert_called_once()

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_equivalent_rarities_via_api(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test validation of equivalent rarities via API (e.g., Ultimate Rare vs Prismatic Ultimate Rare)."""
        # Setup mocks
        mock_extract_set.return_value = "BPT"
        
        # Mock API response with Prismatic Ultimate Rare
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Black Luster Soldier",
                    "card_sets": [
                        {
                            "set_code": "BPT-005",
                            "set_rarity": "Prismatic Ultimate Rare"
                        }
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # Test: Request for "Ultimate Rare" should match "Prismatic Ultimate Rare"
        result = service.validate_card_rarity("BPT-005", "Ultimate Rare")
        
        assert result is True
        mock_requests.assert_called_once()

    @patch("ygoapi.price_scraping.extract_set_code")
    def test_validate_invalid_card_number(self, mock_extract_set, service):
        """Test validation with invalid card number (no set code extractable)."""
        # Setup mock to return None (invalid card number)
        mock_extract_set.return_value = None
        
        result = service.validate_card_rarity("INVALID-FORMAT", "Ultra Rare")
        
        assert result is True  # Should allow scrape to proceed gracefully

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_api_timeout_fallback(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test graceful handling of API timeout."""
        # Setup mocks
        mock_extract_set.return_value = "LOB"
        
        # Mock API timeout
        mock_requests.side_effect = requests.exceptions.Timeout("Request timed out")
        
        # Setup cache fallback
        mock_collection = MagicMock()
        mock_collection.find.return_value = []  # Empty cache
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True  # Should allow due to graceful fallback

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_api_404_fallback(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test handling of API 404 response."""
        # Setup mocks
        mock_extract_set.return_value = "UNKNOWN"
        
        # Mock API 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_requests.return_value = mock_response
        
        # Setup cache fallback
        mock_collection = MagicMock()
        mock_collection.find.return_value = []
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("UNKNOWN-001", "Ultra Rare")
        
        assert result is True  # Should allow due to graceful fallback

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_api_malformed_response(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test handling of malformed API response."""
        # Setup mocks
        mock_extract_set.return_value = "LOB"
        
        # Mock malformed API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "Invalid request"}  # No 'data' field
        mock_requests.return_value = mock_response
        
        # Setup cache fallback
        mock_collection = MagicMock()
        mock_collection.find.return_value = [{"set_rarity": "Ultra Rare"}]
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True
        # Should fall back to cache
        mock_collection.find.assert_called_once()

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_database_disabled(self, mock_get_collection, service):
        """Test validation when database is completely disabled."""
        # Mock disabled database
        mock_get_collection.return_value = None
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True  # Should allow when database disabled

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_cache_incomplete_allows_scrape(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test that incomplete cache doesn't block valid scrapes."""
        # Setup mocks
        mock_extract_set.return_value = "BLTR"
        
        # Mock API failure (force fallback to cache)
        mock_requests.side_effect = Exception("API unavailable")
        
        # Setup incomplete cache (missing the requested rarity)
        mock_collection = MagicMock()
        mock_collection.find.return_value = [
            {"set_rarity": "Quarter Century Secret Rare"}  # Cache only has this rarity
        ]
        mock_get_collection.return_value = mock_collection
        
        # Test: Request for "Secret Rare" should still be allowed (cache might be incomplete)
        result = service.validate_card_rarity("BLTR-EN051", "Secret Rare")
        
        assert result is True  # Should allow due to graceful fallback

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_card_not_in_api_or_cache(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test validation for card not found in API or cache (new card scenario)."""
        # Setup mocks
        mock_extract_set.return_value = "NEW"
        
        # Mock API response with no data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}  # No cards found
        mock_requests.return_value = mock_response
        
        # Setup empty cache
        mock_collection = MagicMock()
        mock_collection.find.return_value = []
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("NEW-001", "Ultra Rare")
        
        assert result is True  # Should allow new cards

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_multiple_cards_same_set_code(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test validation when API returns multiple cards with same set code."""
        # Setup mocks
        mock_extract_set.return_value = "LOB"
        
        # Mock API response with multiple cards
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Blue-Eyes White Dragon",
                    "card_sets": [
                        {"set_code": "LOB-001", "set_rarity": "Ultra Rare"},
                        {"set_code": "LOB-002", "set_rarity": "Common"}
                    ]
                },
                {
                    "name": "Dark Magician",
                    "card_sets": [
                        {"set_code": "LOB-001", "set_rarity": "Secret Rare"}  # Same set code, different card
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # Test: Should find the correct rarity for the specific set code
        result = service.validate_card_rarity("LOB-001", "Secret Rare")
        
        assert result is True

    def test_are_rarities_equivalent_comprehensive(self, service):
        """Test comprehensive rarity equivalence rules."""
        # Test Ultimate Rare equivalences
        assert service._are_rarities_equivalent("ultimate rare", "prismatic ultimate rare") is True
        assert service._are_rarities_equivalent("prismatic ultimate rare", "ultimate rare") is True
        
        # Test Collector's Rare equivalences
        assert service._are_rarities_equivalent("collector's rare", "prismatic collector's rare") is True
        assert service._are_rarities_equivalent("prismatic collector's rare", "collector's rare") is True
        
        # Test non-equivalent rarities
        assert service._are_rarities_equivalent("secret rare", "ultra rare") is False
        assert service._are_rarities_equivalent("common", "rare") is False
        
        # Test case sensitivity
        assert service._are_rarities_equivalent("ULTIMATE RARE", "prismatic ultimate rare") is True
        assert service._are_rarities_equivalent("Collector's Rare", "PRISMATIC COLLECTOR'S RARE") is True


class TestValidationIntegrationScenarios:
    """Integration tests for the complete validation flow."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch("ygoapi.price_scraping.get_memory_manager"):
            return PriceScrapingService()

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_real_world_scenario_blmm_en035(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test the real-world scenario mentioned by the user: BLMM-EN035."""
        # Setup mocks to simulate the user's scenario
        mock_extract_set.return_value = "BLMM"
        
        # Mock API success with valid rarity
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Example Card",
                    "card_sets": [
                        {"set_code": "BLMM-EN035", "set_rarity": "Ultra Rare"}
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # This should now pass (was failing before the fix)
        result = service.validate_card_rarity("BLMM-EN035", "Ultra Rare")
        
        assert result is True
        # Verify API was called correctly
        mock_requests.assert_called_once()
        assert "cardset=BLMM" in mock_requests.call_args[0][0]

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_scenario_cache_has_qcsr_request_has_sr(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test scenario: Cache has Quarter Century Secret Rare, request asks for Secret Rare."""
        # Setup mocks
        mock_extract_set.return_value = "BLTR"
        
        # Mock API response showing both rarities exist
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Test Card",
                    "card_sets": [
                        {"set_code": "BLTR-EN051", "set_rarity": "Secret Rare"},
                        {"set_code": "BLTR-EN051", "set_rarity": "Quarter Century Secret Rare"}
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # Cache only has Quarter Century Secret Rare (incomplete)
        mock_collection = MagicMock()
        mock_collection.find.return_value = [{"set_rarity": "Quarter Century Secret Rare"}]
        mock_get_collection.return_value = mock_collection
        
        # Request for Secret Rare should succeed via API validation
        result = service.validate_card_rarity("BLTR-EN051", "Secret Rare")
        
        assert result is True
        # API should be checked first
        mock_requests.assert_called_once()

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code") 
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validation_performance_api_first_cache_second(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test that validation prioritizes API over cache for accuracy."""
        # Setup mocks
        mock_extract_set.return_value = "TEST"
        
        # Mock API with authoritative data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "Test Card",
                    "card_sets": [
                        {"set_code": "TEST-001", "set_rarity": "Correct Rarity"}
                    ]
                }
            ]
        }
        mock_requests.return_value = mock_response
        
        # Cache has incorrect/outdated data
        mock_collection = MagicMock()
        mock_collection.find.return_value = [{"set_rarity": "Wrong Rarity"}]
        mock_get_collection.return_value = mock_collection
        
        # Should validate against API (correct) not cache (wrong)
        result = service.validate_card_rarity("TEST-001", "Correct Rarity")
        
        assert result is True
        # API should be called
        mock_requests.assert_called_once()
        # Cache should NOT be called since API succeeded
        mock_collection.find.assert_not_called()


class TestValidationErrorHandling:
    """Test error handling and edge cases in validation."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch("ygoapi.price_scraping.get_memory_manager"):
            return PriceScrapingService()

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    def test_validate_extract_set_code_import_error(self, mock_extract_set, mock_requests, service):
        """Test handling of import errors in extract_set_code."""
        # Mock import to succeed but function to fail
        mock_extract_set.side_effect = ImportError("Module not found")
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True  # Should gracefully handle import errors

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_json_decode_error(self, mock_get_collection, mock_extract_set, mock_requests, service):
        """Test handling of JSON decode errors from API."""
        # Setup mocks
        mock_extract_set.return_value = "LOB"
        
        # Mock API response with invalid JSON
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_requests.return_value = mock_response
        
        # Setup cache fallback
        mock_collection = MagicMock()
        mock_collection.find.return_value = []
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True  # Should gracefully handle JSON errors

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_collection_exception(self, mock_get_collection, service):
        """Test handling of database collection exceptions."""
        # Mock collection to raise exception on find
        mock_collection = MagicMock()
        mock_collection.find.side_effect = Exception("Database error")
        mock_get_collection.return_value = mock_collection
        
        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        
        assert result is True  # Should gracefully handle DB errors

    def test_validate_empty_inputs(self, service):
        """Test validation with empty or None inputs."""
        # Empty card number
        result = service.validate_card_rarity("", "Ultra Rare")
        assert result is True
        
        # Empty rarity
        result = service.validate_card_rarity("LOB-001", "")
        assert result is True
        
        # None inputs
        result = service.validate_card_rarity(None, "Ultra Rare")
        assert result is True

    @patch("ygoapi.price_scraping.requests.get")
    @patch("ygoapi.price_scraping.extract_set_code")
    def test_validate_network_errors(self, mock_extract_set, mock_requests, service):
        """Test various network error scenarios."""
        mock_extract_set.return_value = "LOB"
        
        # Test different network exceptions
        network_exceptions = [
            requests.exceptions.ConnectionError("Connection failed"),
            requests.exceptions.Timeout("Request timed out"),
            requests.exceptions.HTTPError("HTTP error"),
            requests.exceptions.RequestException("Generic request error")
        ]
        
        for exception in network_exceptions:
            mock_requests.side_effect = exception
            result = service.validate_card_rarity("LOB-001", "Ultra Rare")
            assert result is True, f"Should handle {type(exception).__name__} gracefully"


class TestCacheStalenessHandling:
    """Test suite for the new cache staleness detection and handling."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch("ygoapi.price_scraping.get_memory_manager"):
            return PriceScrapingService()

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_fresh(self, mock_get_collection, service):
        """Test _find_cached_price_data_with_staleness_info with fresh data."""
        mock_collection = mock_get_collection.return_value
        now = datetime.now(timezone.utc)
        
        fresh_data = {
            "card_number": "LOB-001",
            "card_rarity": "ultra rare",
            "tcgplayer_price": 25.99,
            "last_price_updt": now,  # Fresh data
        }
        mock_collection.find.return_value = [fresh_data]
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-001", "Blue-Eyes White Dragon", "Ultra Rare"
        )
        
        assert result is not None
        assert result["is_fresh"] is True
        assert result["data"]["tcgplayer_price"] == 25.99
        assert result["last_updated"] == now

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_stale(self, mock_get_collection, service):
        """Test _find_cached_price_data_with_staleness_info with stale data."""
        mock_collection = mock_get_collection.return_value
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(days=10)  # Stale data
        
        stale_data = {
            "card_number": "LOB-001",
            "card_rarity": "ultra rare",
            "tcgplayer_price": 25.99,
            "last_price_updt": stale_time,
        }
        mock_collection.find.return_value = [stale_data]
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-001", "Blue-Eyes White Dragon", "Ultra Rare"
        )
        
        assert result is not None
        assert result["is_fresh"] is False
        assert result["data"]["tcgplayer_price"] == 25.99
        assert result["last_updated"] == stale_time

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_no_data(self, mock_get_collection, service):
        """Test _find_cached_price_data_with_staleness_info with no data found."""
        mock_collection = mock_get_collection.return_value
        mock_collection.find.return_value = []  # No data found
        
        result = service._find_cached_price_data_with_staleness_info(
            "MISSING-001", "Missing Card", "Ultra Rare"
        )
        
        assert result is None

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_missing_timestamp(self, mock_get_collection, service):
        """Test _find_cached_price_data_with_staleness_info with missing timestamp."""
        mock_collection = mock_get_collection.return_value
        
        data_without_timestamp = {
            "card_number": "LOB-001",
            "card_rarity": "ultra rare",
            "tcgplayer_price": 25.99,
            # Missing last_price_updt
        }
        mock_collection.find.return_value = [data_without_timestamp]
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-001", "Blue-Eyes White Dragon", "Ultra Rare"
        )
        
        assert result is None  # Should return None if timestamp is missing

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_with_art_variant(self, mock_get_collection, service):
        """Test staleness detection with art variants."""
        mock_collection = mock_get_collection.return_value
        now = datetime.now(timezone.utc)
        
        data_with_art = {
            "card_number": "LOB-005",
            "card_rarity": "secret rare",
            "art_variant": "7",
            "tcgplayer_price": 45.00,
            "last_price_updt": now,
        }
        mock_collection.find.return_value = [data_with_art]
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-005", "Dark Magician", "Secret Rare", "7th"
        )
        
        assert result is not None
        assert result["is_fresh"] is True
        assert result["data"]["art_variant"] == "7"

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_multiple_entries(self, mock_get_collection, service):
        """Test staleness detection with multiple cache entries (should pick most recent)."""
        mock_collection = mock_get_collection.return_value
        now = datetime.now(timezone.utc)
        older_time = now - timedelta(hours=1)
        
        # Multiple entries with different timestamps
        cache_entries = [
            {
                "card_number": "LOB-001",
                "card_rarity": "ultra rare",
                "tcgplayer_price": 20.00,
                "last_price_updt": older_time,  # Older entry
            },
            {
                "card_number": "LOB-001",
                "card_rarity": "ultra rare", 
                "tcgplayer_price": 25.99,
                "last_price_updt": now,  # Newer entry
            }
        ]
        mock_collection.find.return_value = cache_entries
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-001", "Blue-Eyes White Dragon", "Ultra Rare"
        )
        
        assert result is not None
        assert result["is_fresh"] is True
        assert result["data"]["tcgplayer_price"] == 25.99  # Should pick newer entry
        assert result["last_updated"] == now

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_database_disabled(self, mock_get_collection, service):
        """Test staleness detection when database is disabled."""
        mock_get_collection.return_value = None  # Database disabled
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-001", "Blue-Eyes White Dragon", "Ultra Rare"
        )
        
        assert result is None

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_with_staleness_info_exception_handling(self, mock_get_collection, service):
        """Test staleness detection with database exceptions."""
        mock_collection = mock_get_collection.return_value
        mock_collection.find.side_effect = Exception("Database error")
        
        result = service._find_cached_price_data_with_staleness_info(
            "LOB-001", "Blue-Eyes White Dragon", "Ultra Rare"
        )
        
        assert result is None  # Should handle exceptions gracefully