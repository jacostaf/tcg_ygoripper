"""
Additional test suite for price_scraping module.

This test suite focuses on specific missing coverage areas
in the PriceScrapingService to increase overall coverage.
"""

import pytest
import asyncio
import threading
import time
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, Mock, AsyncMock
from concurrent.futures import ThreadPoolExecutor

from ygoapi.price_scraping import PriceScrapingService


class TestPriceScrapingServiceAdditional:
    """Additional test cases focusing on missing coverage areas."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            return PriceScrapingService()

    def test_normalize_art_variant_edge_cases(self, service):
        """Test _normalize_art_variant with edge cases."""
        # Test None input
        assert service._normalize_art_variant(None) == ""
        
        # Test empty string
        assert service._normalize_art_variant("") == ""
        
        # Test whitespace
        assert service._normalize_art_variant("  1st  ") == "1"
        
        # Test case insensitive
        assert service._normalize_art_variant("FIRST") == "1"
        assert service._normalize_art_variant("Second") == "2"
        
        # Test word numbers
        assert service._normalize_art_variant("three") == "3"
        assert service._normalize_art_variant("fourth") == "4"
        assert service._normalize_art_variant("fifth") == "5"
        assert service._normalize_art_variant("sixth") == "6"
        assert service._normalize_art_variant("seventh") == "7"
        assert service._normalize_art_variant("eighth") == "8"
        assert service._normalize_art_variant("ninth") == "9"
        assert service._normalize_art_variant("tenth") == "10"
        
        # Test non-matching
        assert service._normalize_art_variant("alternate") == "alternate"
        assert service._normalize_art_variant("special") == "special"

    def test_get_art_variant_alternatives_comprehensive(self, service):
        """Test _get_art_variant_alternatives comprehensively."""
        # Test with ordinal number
        alternatives = service._get_art_variant_alternatives("1st")
        assert "1" in alternatives
        assert "1st" in alternatives
        assert "first" in alternatives
        
        # Test with number in range 1-10
        alternatives = service._get_art_variant_alternatives("5")
        assert "5" in alternatives
        assert "5th" in alternatives
        assert "fifth" in alternatives
        
        # Test with number outside range
        alternatives = service._get_art_variant_alternatives("15")
        assert "15" in alternatives
        # Should not include ordinal forms for numbers > 10
        
        # Test with empty string
        alternatives = service._get_art_variant_alternatives("")
        assert alternatives == []
        
        # Test with None
        alternatives = service._get_art_variant_alternatives(None)
        assert alternatives == []
        
        # Test with non-numeric string
        alternatives = service._get_art_variant_alternatives("alternate")
        assert "alternate" in alternatives

    def test_ensure_initialized_method(self, service):
        """Test the _ensure_initialized method."""
        assert not service._initialized
        
        with patch.object(service, '_initialize_collections') as mock_init:
            service._ensure_initialized()
            
            assert service._initialized
            mock_init.assert_called_once()
            
            # Calling again should not reinitialize
            service._ensure_initialized()
            mock_init.assert_called_once()  # Still only called once

    def test_cleanup_resources_comprehensive(self, service):
        """Test cleanup_resources method comprehensively."""
        # Setup mock executor
        mock_executor = Mock()
        service._scraping_executor = mock_executor
        
        # Test successful cleanup
        service.cleanup_resources()
        
        mock_executor.shutdown.assert_called_once_with(wait=False)
        assert service._scraping_executor is None

    def test_cleanup_resources_with_error(self, service):
        """Test cleanup_resources when executor shutdown fails."""
        mock_executor = Mock()
        mock_executor.shutdown.side_effect = Exception("Shutdown failed")
        service._scraping_executor = mock_executor
        
        # Should not propagate exception
        service.cleanup_resources()
        assert service._scraping_executor is None

    def test_cleanup_resources_without_executor(self, service):
        """Test cleanup_resources when executor is None."""
        service._scraping_executor = None
        
        # Should not raise exception
        service.cleanup_resources()

    def test_are_rarities_equivalent_method(self, service):
        """Test _are_rarities_equivalent method."""
        # Test exact match
        assert service._are_rarities_equivalent("Ultra Rare", "Ultra Rare") is True
        
        # Test different rarities
        assert service._are_rarities_equivalent("Ultra Rare", "Secret Rare") is False
        
        # Test with normalization
        assert service._are_rarities_equivalent("ultra rare", "Ultra Rare") is True
        assert service._are_rarities_equivalent("ULTRA RARE", "ultra rare") is True
        
        # Test with None values
        assert service._are_rarities_equivalent(None, "Ultra Rare") is False
        assert service._are_rarities_equivalent("Ultra Rare", None) is False
        assert service._are_rarities_equivalent(None, None) is True

    def test_lookup_card_name_from_cache_method(self, service):
        """Test lookup_card_name_from_cache method."""
        service._ensure_initialized()
        
        # Test successful lookup
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            'card_name': 'Blue-Eyes White Dragon'
        }
        service.variants_collection = mock_collection
        
        result = service.lookup_card_name_from_cache('LOB-001')
        assert result == 'Blue-Eyes White Dragon'
        
        # Test not found
        mock_collection.find_one.return_value = None
        result = service.lookup_card_name_from_cache('INVALID-001')
        assert result is None
        
        # Test with no collection
        service.variants_collection = None
        result = service.lookup_card_name_from_cache('LOB-001')
        assert result is None
        
        # Test with exception
        service.variants_collection = mock_collection
        mock_collection.find_one.side_effect = Exception("Database error")
        result = service.lookup_card_name_from_cache('LOB-001')
        assert result is None

    def test_lookup_card_name_from_ygo_api_method(self, service):
        """Test lookup_card_name_from_ygo_api method."""
        # Test successful API call
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': [{'name': 'Blue-Eyes White Dragon'}]
        }
        
        with patch('ygoapi.price_scraping.requests.get', return_value=mock_response):
            result = service.lookup_card_name_from_ygo_api('4007')
            assert result == 'Blue-Eyes White Dragon'
        
        # Test API error
        mock_response.status_code = 404
        with patch('ygoapi.price_scraping.requests.get', return_value=mock_response):
            result = service.lookup_card_name_from_ygo_api('INVALID')
            assert result is None
        
        # Test network error
        with patch('ygoapi.price_scraping.requests.get', side_effect=Exception("Network error")):
            result = service.lookup_card_name_from_ygo_api('4007')
            assert result is None
        
        # Test empty response
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        with patch('ygoapi.price_scraping.requests.get', return_value=mock_response):
            result = service.lookup_card_name_from_ygo_api('4007')
            assert result is None

    def test_lookup_card_name_method(self, service):
        """Test lookup_card_name method that tries cache first, then API."""
        # Test cache hit
        with patch.object(service, 'lookup_card_name_from_cache', return_value='Cached Name'):
            result = service.lookup_card_name('LOB-001')
            assert result == 'Cached Name'
        
        # Test cache miss, API hit
        with patch.object(service, 'lookup_card_name_from_cache', return_value=None), \
             patch.object(service, 'lookup_card_name_from_ygo_api', return_value='API Name'):
            result = service.lookup_card_name('LOB-001')
            assert result == 'API Name'
        
        # Test both miss
        with patch.object(service, 'lookup_card_name_from_cache', return_value=None), \
             patch.object(service, 'lookup_card_name_from_ygo_api', return_value=None):
            result = service.lookup_card_name('LOB-001')
            assert result is None

    def test_lookup_card_info_from_cache_method(self, service):
        """Test lookup_card_info_from_cache method."""
        service._ensure_initialized()
        
        # Test successful lookup
        mock_collection = Mock()
        card_info = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'set_rarity': 'Ultra Rare'
        }
        mock_collection.find_one.return_value = card_info
        service.variants_collection = mock_collection
        
        result = service.lookup_card_info_from_cache('LOB-001')
        assert result == card_info
        
        # Test not found
        mock_collection.find_one.return_value = None
        result = service.lookup_card_info_from_cache('INVALID-001')
        assert result is None
        
        # Test with no collection
        service.variants_collection = None
        result = service.lookup_card_info_from_cache('LOB-001')
        assert result is None
        
        # Test with exception
        service.variants_collection = mock_collection
        mock_collection.find_one.side_effect = Exception("Database error")
        result = service.lookup_card_info_from_cache('LOB-001')
        assert result is None

    def test_get_cache_stats_comprehensive(self, service):
        """Test get_cache_stats method comprehensively."""
        service._ensure_initialized()
        
        # Test successful stats retrieval
        mock_collection = Mock()
        mock_collection.count_documents.return_value = 1500
        
        # Mock cursor for iteration
        recent_time = datetime.now(timezone.utc)
        old_time = datetime.now(timezone.utc) - timedelta(days=5)
        
        mock_collection.find.return_value = [
            {'last_price_updt': recent_time},
            {'last_price_updt': old_time},
            {'last_price_updt': recent_time}
        ]
        
        service.cache_collection = mock_collection
        
        result = service.get_cache_stats()
        
        assert result['total_cached_prices'] == 1500
        assert 'fresh_entries' in result
        assert 'stale_entries' in result
        assert 'cache_hit_rate' in result
        
        # Test with no collection
        service.cache_collection = None
        result = service.get_cache_stats()
        assert result['total_cached_prices'] == 0
        
        # Test with exception
        service.cache_collection = mock_collection
        mock_collection.count_documents.side_effect = Exception("Database error")
        result = service.get_cache_stats()
        assert result['total_cached_prices'] == 0

    def test_save_price_data_comprehensive(self, service):
        """Test save_price_data method comprehensively."""
        service._ensure_initialized()
        
        price_data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'tcgplayer_price': 25.99
        }
        
        # Test successful save
        mock_collection = Mock()
        service.cache_collection = mock_collection
        
        result = service.save_price_data(price_data, 'Alternate Art')
        
        assert result is True
        mock_collection.replace_one.assert_called_once()
        
        # Test with no collection
        service.cache_collection = None
        result = service.save_price_data(price_data, None)
        assert result is False
        
        # Test with exception
        service.cache_collection = mock_collection
        mock_collection.replace_one.side_effect = Exception("Database error")
        result = service.save_price_data(price_data, None)
        assert result is False

    def test_validate_card_rarity_comprehensive(self, service):
        """Test validate_card_rarity method comprehensively."""
        service._ensure_initialized()
        
        # Test successful validation
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'set_rarity': 'Ultra Rare'
        }
        service.variants_collection = mock_collection
        
        result = service.validate_card_rarity('LOB-001', 'Ultra Rare')
        assert result is True
        
        # Test rarity not found
        mock_collection.find_one.return_value = None
        result = service.validate_card_rarity('LOB-001', 'Invalid Rarity')
        assert result is False
        
        # Test with no collection (offline mode)
        service.variants_collection = None
        result = service.validate_card_rarity('LOB-001', 'Ultra Rare')
        assert result is True  # Returns True in offline mode
        
        # Test with exception
        service.variants_collection = mock_collection
        mock_collection.find_one.side_effect = Exception("Database error")
        result = service.validate_card_rarity('LOB-001', 'Ultra Rare')
        assert result is False

    def test_find_cached_price_data_with_art_variant_query(self, service):
        """Test find_cached_price_data with art variant query construction."""
        service._ensure_initialized()
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99
        }
        service.cache_collection = mock_collection
        
        # Test with art variant
        service.find_cached_price_data('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', '1st')
        
        # Verify the query was constructed with art variant alternatives
        mock_collection.find_one.assert_called_once()
        call_args = mock_collection.find_one.call_args[0][0]
        assert 'card_number' in call_args
        assert 'card_rarity' in call_args

    @pytest.mark.asyncio
    async def test_wait_for_search_results_method(self, service):
        """Test _wait_for_search_results async method."""
        mock_page = AsyncMock()
        
        # Test successful results found
        mock_page.evaluate.side_effect = [5, False]  # 5 results found, no "no results" message
        
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.time.side_effect = [0, 1]  # Time progression
            
            result = await service._wait_for_search_results(mock_page, 'Blue-Eyes White Dragon')
            assert result == 5
        
        # Test no results found
        mock_page.evaluate.side_effect = [0, True]  # 0 results, "no results" message found
        result = await service._wait_for_search_results(mock_page, 'Nonexistent Card')
        assert result == 0
        
        # Test timeout scenario
        mock_page.evaluate.side_effect = lambda script: 0  # Always return 0 results
        
        with patch('asyncio.get_event_loop') as mock_loop, \
             patch('asyncio.sleep'):
            mock_loop.return_value.time.side_effect = [0, 20]  # Simulate timeout
            
            result = await service._wait_for_search_results(mock_page, 'Test Card', max_wait_seconds=15)
            assert result == 0
        
        # Test exception handling
        mock_page.evaluate.side_effect = Exception('Page error')
        result = await service._wait_for_search_results(mock_page, 'Test Card')
        assert result == 0

    @pytest.mark.asyncio
    async def test_extract_prices_from_tcgplayer_dom_method(self, service):
        """Test extract_prices_from_tcgplayer_dom async method."""
        mock_page = AsyncMock()
        
        # Test successful price extraction
        price_data = {
            'tcg_price': 25.99,
            'tcg_market_price': 30.00,
            'debug_info': []
        }
        mock_page.evaluate.return_value = price_data
        
        result = await service.extract_prices_from_tcgplayer_dom(mock_page)
        
        assert result['tcg_price'] == 25.99
        assert result['tcg_market_price'] == 30.00
        
        # Test with null prices
        price_data['tcg_price'] = None
        price_data['tcg_market_price'] = None
        mock_page.evaluate.return_value = price_data
        
        result = await service.extract_prices_from_tcgplayer_dom(mock_page)
        assert result['tcg_price'] is None
        assert result['tcg_market_price'] is None
        
        # Test with exception
        mock_page.evaluate.side_effect = Exception('DOM error')
        result = await service.extract_prices_from_tcgplayer_dom(mock_page)
        assert result['tcg_price'] is None
        assert result['tcg_market_price'] is None

    def test_run_async_scraping_in_thread_delay_calculation(self, service):
        """Test delay calculation in _run_async_scraping_in_thread."""
        with patch('ygoapi.price_scraping.os.getenv', return_value='3'), \
             patch('ygoapi.price_scraping.time.sleep') as mock_sleep, \
             patch('ygoapi.price_scraping.random.uniform', return_value=0.5), \
             patch.object(service, 'scrape_price_from_tcgplayer_pooled', return_value={}):
            
            service._run_async_scraping_in_thread('Test Card', 'Common', None, 'TEST-001')
            
            # Should have calculated delay for concurrency > 2
            mock_sleep.assert_called_once_with(0.5)

    def test_run_async_scraping_in_thread_loop_cleanup(self, service):
        """Test event loop cleanup in _run_async_scraping_in_thread."""
        with patch('ygoapi.price_scraping.asyncio.new_event_loop') as mock_new_loop, \
             patch('ygoapi.price_scraping.asyncio.set_event_loop'), \
             patch.object(service, 'scrape_price_from_tcgplayer_pooled', return_value={}):
            
            mock_loop = Mock()
            mock_new_loop.return_value = mock_loop
            
            service._run_async_scraping_in_thread('Test Card', 'Common', None, 'TEST-001')
            
            # Should have closed the loop
            mock_loop.close.assert_called_once()

    def test_run_async_scraping_in_thread_loop_cleanup_error(self, service):
        """Test event loop cleanup error handling."""
        with patch('ygoapi.price_scraping.asyncio.new_event_loop') as mock_new_loop, \
             patch('ygoapi.price_scraping.asyncio.set_event_loop'), \
             patch.object(service, 'scrape_price_from_tcgplayer_pooled', return_value={}):
            
            mock_loop = Mock()
            mock_loop.close.side_effect = Exception("Close error")
            mock_new_loop.return_value = mock_loop
            
            # Should not propagate exception
            result = service._run_async_scraping_in_thread('Test Card', 'Common', None, 'TEST-001')
            assert 'error' not in result or 'Close error' not in result.get('error', '')

    def test_memory_manager_callback_registration(self, service):
        """Test that cleanup callback is registered with memory manager."""
        mock_memory_manager = Mock()
        
        with patch('ygoapi.price_scraping.get_memory_manager', return_value=mock_memory_manager):
            new_service = PriceScrapingService()
            
            mock_memory_manager.register_cleanup_callback.assert_called_once_with(
                "price_scraper_cleanup", new_service.cleanup_resources
            )

    def test_thread_pool_executor_max_workers_configuration(self, service):
        """Test ThreadPoolExecutor configuration with different worker counts."""
        with patch('ygoapi.price_scraping.os.environ.get', return_value='4'):
            # The service is already created, but let's test that a new one would use the env var
            assert service._scraping_executor is not None


class TestPriceScrapingInitializationEdgeCases:
    """Test edge cases in price scraping service initialization."""

    def test_initialization_with_custom_worker_count(self):
        """Test initialization with custom worker count from environment."""
        with patch('ygoapi.price_scraping.os.environ.get', return_value='8'), \
             patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            
            service = PriceScrapingService()
            assert service._scraping_executor is not None

    def test_initialization_with_invalid_worker_count(self):
        """Test initialization with invalid worker count from environment."""
        with patch('ygoapi.price_scraping.os.environ.get', return_value='invalid'), \
             patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            
            # Should fall back to default (2) and not raise exception
            service = PriceScrapingService()
            assert service._scraping_executor is not None

    def test_global_service_instance_creation(self):
        """Test that global service instance is created correctly."""
        with patch('ygoapi.price_scraping.PriceScrapingService') as mock_service_class:
            # Import the global instance (this triggers creation)
            from ygoapi.price_scraping import price_scraping_service
            
            # Verify the service class was instantiated
            mock_service_class.assert_called_once()


class TestPriceScrapingDateHandling:
    """Test date handling in price scraping methods."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            return PriceScrapingService()

    def test_staleness_info_with_various_date_formats(self, service):
        """Test staleness calculation with various date formats."""
        service._ensure_initialized()
        
        # Test with datetime object
        recent_datetime = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': recent_datetime
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = recent_data
        service.cache_collection = mock_collection
        
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['is_fresh'] is True  # Should be fresh (1 hour old)
        
        # Test with string date
        string_date_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': 'Thu, 31 Jul 2025 09:14:44 GMT'
        }
        
        mock_collection.find_one.return_value = string_date_data
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        # The exact freshness depends on the current date vs the string date
        assert 'is_fresh' in result
        
        # Test with invalid date string
        invalid_date_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': 'invalid date format'
        }
        
        mock_collection.find_one.return_value = invalid_date_data
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['is_fresh'] is False  # Should default to stale for invalid dates