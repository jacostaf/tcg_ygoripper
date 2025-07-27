"""
Unit tests for price_scraping.py module.

Tests PriceScrapingService class and all price scraping functionality with comprehensive
coverage of success cases, error handling, and edge scenarios.
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from ygoapi.price_scraping import PriceScrapingService


class TestPriceScrapingService:
    """Test cases for PriceScrapingService class."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        return PriceScrapingService()

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_init_with_disabled_db(self, service):
        """Test PriceScrapingService initialization with disabled database."""
        assert service is not None

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_card_rarity_success(self, mock_get_collection, service):
        """Test successful card rarity validation."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "card_name": "Blue-Eyes White Dragon",
            "set_rarity": "Ultra Rare"
        }
        mock_collection.find.return_value = [
            {"set_rarity": "Ultra Rare"},
            {"set_rarity": "Secret Rare"}
        ]
        mock_get_collection.return_value = mock_collection

        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        assert result is True

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_card_rarity_not_found(self, mock_get_collection, service):
        """Test card rarity validation when card not found."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        mock_get_collection.return_value = mock_collection

        result = service.validate_card_rarity("INVALID", "Ultra Rare")
        assert result is True  # Returns True for fallback behavior

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_validate_card_rarity_disabled_db(self, mock_get_collection, service):
        """Test card rarity validation with disabled database."""
        mock_get_collection.return_value = None

        result = service.validate_card_rarity("LOB-001", "Ultra Rare")
        assert result is True  # Returns True when DB disabled

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_lookup_card_name_success(self, mock_get_collection, service):
        """Test successful card name lookup."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "set_code": "LOB-001",
            "card_name": "Blue-Eyes White Dragon"
        }
        mock_get_collection.return_value = mock_collection

        result = service.lookup_card_name("LOB-001")
        assert result == "Blue-Eyes White Dragon"

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    def test_lookup_card_name_not_found(self, mock_get_collection, service):
        """Test card name lookup when card not found."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        mock_get_collection.return_value = mock_collection

        # Mock the API fallback as well
        with patch("ygoapi.price_scraping.requests.get") as mock_api:
            mock_api.side_effect = requests.exceptions.RequestException("API error")
            result = service.lookup_card_name("INVALID")
            assert result is None

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_success(self, mock_get_collection, service):
        """Test successful cached price data retrieval."""
        mock_collection = Mock()
        mock_collection.find.return_value = [{
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "ultra rare",
            "tcgplayer_price": 25.99,
            "last_price_updt": datetime.now(timezone.utc)
        }]
        mock_get_collection.return_value = mock_collection

        result = service.find_cached_price_data("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")
        assert result is not None
        assert result["tcgplayer_price"] == 25.99

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_find_cached_price_data_not_found(self, mock_get_collection, service):
        """Test cached price data when not found."""
        mock_collection = Mock()
        mock_collection.find.return_value = []
        mock_get_collection.return_value = mock_collection

        result = service.find_cached_price_data("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")
        assert result is None

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_get_cache_stats_success(self, mock_get_collection, service):
        """Test successful cache statistics retrieval."""
        mock_collection = Mock()
        mock_collection.count_documents.return_value = 150
        mock_collection.distinct.return_value = ["LOB-001", "SDK-001", "MRD-001"]
        mock_get_collection.return_value = mock_collection

        result = service.get_cache_stats()
        assert result["total_entries"] == 150
        assert result["unique_cards"] == 3

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_get_cache_stats_disabled_db(self, mock_get_collection, service):
        """Test cache statistics with disabled database."""
        mock_get_collection.return_value = None

        result = service.get_cache_stats()
        assert result["total_entries"] == 0
        assert result["database_status"] == "disabled"

    def test_scrape_card_price_success(self, service):
        """Test successful card price scraping."""
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, 'find_cached_price_data', return_value=None), \
             patch.object(service, 'save_price_data', return_value=True), \
             patch('ygoapi.price_scraping.asyncio.run') as mock_run:

            # Mock the async scraping result
            mock_run.return_value = {
                "tcgplayer_price": 25.99,
                "tcgplayer_market_price": 28.50,
                "tcgplayer_url": "https://tcgplayer.com/test"
            }

            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")

            assert result["success"] is True
            assert result["cached"] is False

    def test_scrape_card_price_cached(self, service):
        """Test card price scraping with cached data."""
        cached_data = {
            "card_number": "LOB-001",
            "tcgplayer_price": 25.99,
            "last_price_updt": datetime.now(timezone.utc),
        }

        # Mock the new staleness-aware cache method
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, '_find_cached_price_data_with_staleness_info', return_value={
                 "data": cached_data,
                 "is_fresh": True,
                 "last_updated": datetime.now(timezone.utc)
             }):

            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")

            assert result["success"] is True
            assert result["cached"] is True

    def test_scrape_card_price_request_failure(self, service):
        """Test card price scraping with request failure."""
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, 'find_cached_price_data', return_value=None), \
             patch('ygoapi.price_scraping.asyncio.run') as mock_run:

            # Mock asyncio.run to raise an exception
            mock_run.side_effect = Exception("Network error")

            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")

            assert result["success"] is False
            assert "error" in result

    def test_scrape_card_price_invalid_rarity(self, service):
        """Test card price scraping with invalid rarity."""
        # Mock the new staleness-aware cache method to return no cache
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=None), \
             patch.object(service, 'validate_card_rarity', return_value=False):
            
            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Invalid Rarity")

            # Should fail due to validation in the new implementation
            assert result["success"] is False
            assert "error" in result
            assert "Invalid rarity" in result["error"]

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_save_price_to_cache_success(self, mock_get_collection, service):
        """Test successful price data saving to cache."""
        mock_collection = Mock()
        mock_collection.replace_one.return_value = Mock(upserted_id="123", modified_count=1)
        mock_get_collection.return_value = mock_collection

        price_data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "tcgplayer_price": 25.99
        }

        result = service.save_price_data(price_data)
        assert result is True

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_save_price_to_cache_disabled_db(self, mock_get_collection, service):
        """Test price data saving with disabled database."""
        mock_get_collection.return_value = None

        price_data = {
            "card_number": "LOB-001",
            "tcgplayer_price": 25.99
        }

        result = service.save_price_data(price_data)
        assert result is True  # Returns True when DB disabled


class TestPriceScrapingIntegration:
    """Test price scraping integration scenarios."""

    @patch("ygoapi.price_scraping.get_card_variants_collection")
    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_complete_scraping_workflow(self, mock_cache, mock_variants):
        """Test complete price scraping workflow."""
        # Setup mocks
        mock_variants_collection = Mock()
        mock_variants_collection.find_one.return_value = {
            "card_name": "Blue-Eyes White Dragon",
            "set_rarity": "Ultra Rare"
        }
        mock_variants_collection.find.return_value = [{"set_rarity": "Ultra Rare"}]
        mock_variants.return_value = mock_variants_collection

        mock_cache_collection = Mock()
        mock_cache_collection.find.return_value = []  # No cached data
        mock_cache_collection.replace_one.return_value = Mock(upserted_id="123")
        mock_cache.return_value = mock_cache_collection

        service = PriceScrapingService()
        
        with patch('ygoapi.price_scraping.asyncio.run') as mock_run:
            mock_run.return_value = {
                "tcgplayer_price": 25.99,
                "tcgplayer_market_price": 28.50
            }
            
            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")

        assert result["success"] is True
        assert result["cached"] is False

    @patch("ygoapi.price_scraping.get_price_cache_collection")
    def test_cache_hit_workflow(self, mock_cache):
        """Test workflow when cache hit occurs."""
        mock_cache_collection = Mock()
        cached_data = {
            "card_number": "LOB-001",
            "tcgplayer_price": 25.99,
            "last_price_updt": datetime.now(timezone.utc)
        }
        mock_cache_collection.find.return_value = [cached_data]
        mock_cache.return_value = mock_cache_collection

        service = PriceScrapingService()
        
        with patch.object(service, 'validate_card_rarity', return_value=True):
            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")

        assert result["success"] is True
        assert result["cached"] is True


class TestPriceScrapingErrorHandling:
    """Test error handling in price scraping."""

    def test_network_timeout_handling(self, service=None):
        """Test handling of network timeouts."""
        if service is None:
            service = PriceScrapingService()
        
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, 'find_cached_price_data', return_value=None), \
             patch('ygoapi.price_scraping.asyncio.run') as mock_run:
            
            mock_run.side_effect = Exception("timeout")
            
            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")
            
            assert result["success"] is False
            assert "error" in result

    def test_invalid_html_handling(self, service=None):
        """Test handling of invalid HTML responses."""
        if service is None:
            service = PriceScrapingService()
        
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, 'find_cached_price_data', return_value=None), \
             patch('ygoapi.price_scraping.asyncio.run') as mock_run:
            
            mock_run.return_value = {"error": "No price data found"}
            
            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")
            
            assert result["success"] is False

    def test_http_error_handling(self, service=None):
        """Test handling of HTTP errors."""
        if service is None:
            service = PriceScrapingService()
        
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, 'find_cached_price_data', return_value=None), \
             patch('ygoapi.price_scraping.asyncio.run') as mock_run:
            
            mock_run.side_effect = Exception("HTTP 404 error")
            
            result = service.scrape_card_price("LOB-001", "Blue-Eyes White Dragon", "Ultra Rare")
            
            assert result["success"] is False
            assert "error" in result