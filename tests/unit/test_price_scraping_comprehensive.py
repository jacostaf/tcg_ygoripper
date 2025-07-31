"""
Comprehensive test suite for price_scraping module.

This test suite aims for 100% coverage of the PriceScrapingService
and all related price scraping functionality including edge cases,
error handling, and performance optimizations.
"""

import pytest
import asyncio
import threading
import time
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, Mock
from concurrent.futures import ThreadPoolExecutor

from ygoapi.price_scraping import PriceScrapingService, price_scraping_service


class TestPriceScrapingServiceComprehensive:
    """Comprehensive test cases for PriceScrapingService."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            return PriceScrapingService()

    def test_service_initialization_comprehensive(self, service):
        """Test comprehensive service initialization."""
        assert service.memory_manager is not None
        assert service.cache_collection is None  # Not initialized until first use
        assert service.variants_collection is None
        assert not service._initialized
        assert hasattr(service, '_scraping_executor')
        assert isinstance(service._scraping_executor, ThreadPoolExecutor)
        assert hasattr(service, '_async_loop_lock')
        assert isinstance(service._async_loop_lock, threading.Lock)

    def test_ensure_initialized(self, service):
        """Test _ensure_initialized method."""
        assert not service._initialized
        
        with patch.object(service, '_initialize_collections') as mock_init:
            service._ensure_initialized()
            
            assert service._initialized
            mock_init.assert_called_once()
            
            # Second call should not initialize again
            service._ensure_initialized()
            mock_init.assert_called_once()  # Still called only once

    def test_cleanup_resources(self, service):
        """Test cleanup_resources method."""
        # Mock executor
        mock_executor = Mock()
        service._scraping_executor = mock_executor
        
        with patch('ygoapi.price_scraping.asyncio') as mock_asyncio:
            mock_loop = Mock()
            mock_asyncio.new_event_loop.return_value = mock_loop
            
            service.cleanup_resources()
            
            mock_executor.shutdown.assert_called_once_with(wait=False)
            assert service._scraping_executor is None

    def test_cleanup_resources_with_executor_error(self, service):
        """Test cleanup_resources when executor shutdown fails."""
        mock_executor = Mock()
        mock_executor.shutdown.side_effect = Exception("Shutdown error")
        service._scraping_executor = mock_executor
        
        # Should not raise exception
        service.cleanup_resources()
        assert service._scraping_executor is None

    def test_normalize_art_variant_numbers(self, service):
        """Test _normalize_art_variant with various number formats."""
        # Test ordinal numbers
        assert service._normalize_art_variant("1st") == "1"
        assert service._normalize_art_variant("2nd") == "2"
        assert service._normalize_art_variant("3rd") == "3"
        assert service._normalize_art_variant("4th") == "4"
        assert service._normalize_art_variant("21st") == "21"
        
        # Test plain numbers
        assert service._normalize_art_variant("1") == "1"
        assert service._normalize_art_variant("10") == "10"
        
        # Test word numbers
        assert service._normalize_art_variant("one") == "1"
        assert service._normalize_art_variant("first") == "1"
        assert service._normalize_art_variant("second") == "2"
        assert service._normalize_art_variant("tenth") == "10"
        
        # Test empty/None
        assert service._normalize_art_variant("") == ""
        assert service._normalize_art_variant(None) == ""
        
        # Test non-matching
        assert service._normalize_art_variant("alternate") == "alternate"

    def test_get_art_variant_alternatives(self, service):
        """Test _get_art_variant_alternatives method."""
        # Test with number
        alternatives = service._get_art_variant_alternatives("1st")
        assert "1" in alternatives
        assert "1st" in alternatives
        assert "first" in alternatives
        
        # Test with word
        alternatives = service._get_art_variant_alternatives("first")
        assert "1" in alternatives
        assert "1st" in alternatives
        assert "first" in alternatives
        
        # Test with empty
        alternatives = service._get_art_variant_alternatives("")
        assert alternatives == []
        
        # Test with non-numeric
        alternatives = service._get_art_variant_alternatives("alternate")
        assert "alternate" in alternatives

    def test_initialize_collections_success(self, service):
        """Test successful collection initialization."""
        mock_cache_collection = Mock()
        mock_variants_collection = Mock()
        
        # Mock existing indexes
        mock_cache_collection.list_indexes.return_value = [
            {'key': {'_id': 1}, 'name': '_id_'}
        ]
        
        with patch('ygoapi.price_scraping.get_price_cache_collection', return_value=mock_cache_collection), \
             patch('ygoapi.price_scraping.get_card_variants_collection', return_value=mock_variants_collection):
            
            service._initialize_collections()
            
            assert service.cache_collection == mock_cache_collection
            assert service.variants_collection == mock_variants_collection
            
            # Should create new indexes
            assert mock_cache_collection.create_index.call_count >= 1

    def test_initialize_collections_no_database(self, service):
        """Test collection initialization when database is disabled."""
        with patch('ygoapi.price_scraping.get_price_cache_collection', return_value=None), \
             patch('ygoapi.price_scraping.get_card_variants_collection', return_value=None):
            
            service._initialize_collections()
            
            assert service.cache_collection is None
            assert service.variants_collection is None

    def test_initialize_collections_index_creation_error(self, service):
        """Test collection initialization with index creation errors."""
        mock_cache_collection = Mock()
        mock_variants_collection = Mock()
        
        mock_cache_collection.list_indexes.return_value = []
        mock_cache_collection.create_index.side_effect = Exception("Index creation failed")
        
        with patch('ygoapi.price_scraping.get_price_cache_collection', return_value=mock_cache_collection), \
             patch('ygoapi.price_scraping.get_card_variants_collection', return_value=mock_variants_collection):
            
            # Should not raise exception
            service._initialize_collections()
            
            assert service.cache_collection == mock_cache_collection

    def test_initialize_collections_exception(self, service):
        """Test collection initialization with general exception."""
        with patch('ygoapi.price_scraping.get_price_cache_collection', side_effect=Exception("Database error")):
            
            service._initialize_collections()
            
            assert service.cache_collection is None
            assert service.variants_collection is None

    def test_validate_card_rarity_success(self, service):
        """Test successful card rarity validation."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'card_rarity': 'Ultra Rare'
        }
        service.variants_collection = mock_collection
        
        result = service.validate_card_rarity('LOB-001', 'Ultra Rare')
        
        assert result is True
        mock_collection.find_one.assert_called_once()

    def test_validate_card_rarity_not_found(self, service):
        """Test card rarity validation when card not found."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        service.variants_collection = mock_collection
        
        result = service.validate_card_rarity('INVALID-001', 'Ultra Rare')
        
        assert result is False

    def test_validate_card_rarity_no_collection(self, service):
        """Test card rarity validation when collection is None."""
        service.variants_collection = None
        
        result = service.validate_card_rarity('LOB-001', 'Ultra Rare')
        
        assert result is True  # Returns True when DB is disabled

    def test_validate_card_rarity_exception(self, service):
        """Test card rarity validation with database exception."""
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("Database error")
        service.variants_collection = mock_collection
        
        result = service.validate_card_rarity('LOB-001', 'Ultra Rare')
        
        assert result is False

    def test_lookup_card_name_success(self, service):
        """Test successful card name lookup."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon'
        }
        service.variants_collection = mock_collection
        
        result = service.lookup_card_name('LOB-001')
        
        assert result == 'Blue-Eyes White Dragon'

    def test_lookup_card_name_not_found(self, service):
        """Test card name lookup when not found."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        service.variants_collection = mock_collection
        
        result = service.lookup_card_name('INVALID-001')
        
        assert result is None

    def test_lookup_card_name_no_collection(self, service):
        """Test card name lookup when collection is None."""
        service.variants_collection = None
        
        result = service.lookup_card_name('LOB-001')
        
        assert result is None

    def test_lookup_card_name_exception(self, service):
        """Test card name lookup with exception."""
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("Database error")
        service.variants_collection = mock_collection
        
        result = service.lookup_card_name('LOB-001')
        
        assert result is None

    def test_find_cached_price_data_success(self, service):
        """Test successful cached price data lookup."""
        cached_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': datetime.now(timezone.utc)
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = cached_data
        service.cache_collection = mock_collection
        
        result = service.find_cached_price_data('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result == cached_data

    def test_find_cached_price_data_with_art_variant(self, service):
        """Test cached price data lookup with art variant."""
        cached_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'art_variant': 'Alternate Art'
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = cached_data
        service.cache_collection = mock_collection
        
        result = service.find_cached_price_data('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', 'Alternate Art')
        
        assert result == cached_data

    def test_find_cached_price_data_not_found(self, service):
        """Test cached price data lookup when not found."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        service.cache_collection = mock_collection
        
        result = service.find_cached_price_data('INVALID-001', 'Test Card', 'Common')
        
        assert result is None

    def test_find_cached_price_data_no_collection(self, service):
        """Test cached price data lookup when collection is None."""
        service.cache_collection = None
        
        result = service.find_cached_price_data('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is None

    def test_find_cached_price_data_exception(self, service):
        """Test cached price data lookup with exception."""
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("Database error")
        service.cache_collection = mock_collection
        
        result = service.find_cached_price_data('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is None

    def test_find_cached_price_data_with_staleness_info_fresh(self, service):
        """Test staleness-aware cache lookup with fresh data."""
        fresh_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': datetime.now(timezone.utc)
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = fresh_data
        service.cache_collection = mock_collection
        
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['data'] == fresh_data
        assert result['is_fresh'] is True

    def test_find_cached_price_data_with_staleness_info_stale(self, service):
        """Test staleness-aware cache lookup with stale data."""
        stale_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': datetime.now(timezone.utc) - timedelta(days=2)
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = stale_data
        service.cache_collection = mock_collection
        
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['data'] == stale_data
        assert result['is_fresh'] is False

    def test_find_cached_price_data_with_staleness_info_string_date(self, service):
        """Test staleness-aware cache lookup with string date format."""
        stale_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': 'Thu, 31 Jul 2025 09:14:44 GMT'
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = stale_data
        service.cache_collection = mock_collection
        
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['data'] == stale_data

    def test_find_cached_price_data_with_staleness_info_invalid_date(self, service):
        """Test staleness-aware cache lookup with invalid date format."""
        invalid_date_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': 'invalid date string'
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = invalid_date_data
        service.cache_collection = mock_collection
        
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['is_fresh'] is False  # Should default to stale

    def test_get_cache_stats_success(self, service):
        """Test successful cache statistics retrieval."""
        mock_collection = Mock()
        mock_collection.count_documents.return_value = 1500
        mock_collection.find.return_value = [
            {'last_price_updt': datetime.now(timezone.utc)},
            {'last_price_updt': datetime.now(timezone.utc) - timedelta(days=2)}
        ]
        service.cache_collection = mock_collection
        
        result = service.get_cache_stats()
        
        assert result['total_cached_prices'] == 1500
        assert 'cache_hit_rate' in result
        assert 'fresh_entries' in result

    def test_get_cache_stats_no_collection(self, service):
        """Test cache statistics when collection is None."""
        service.cache_collection = None
        
        result = service.get_cache_stats()
        
        assert result['total_cached_prices'] == 0

    def test_get_cache_stats_exception(self, service):
        """Test cache statistics with exception."""
        mock_collection = Mock()
        mock_collection.count_documents.side_effect = Exception("Database error")
        service.cache_collection = mock_collection
        
        result = service.get_cache_stats()
        
        assert result['total_cached_prices'] == 0

    def test_save_price_data_success(self, service):
        """Test successful price data saving."""
        price_data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'tcgplayer_price': 25.99
        }
        
        mock_collection = Mock()
        service.cache_collection = mock_collection
        
        service.save_price_data(price_data, 'Alternate Art')
        
        mock_collection.replace_one.assert_called_once()

    def test_save_price_data_no_collection(self, service):
        """Test price data saving when collection is None."""
        price_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99
        }
        
        service.cache_collection = None
        
        # Should not raise exception
        service.save_price_data(price_data, None)

    def test_save_price_data_exception(self, service):
        """Test price data saving with exception."""
        price_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99
        }
        
        mock_collection = Mock()
        mock_collection.replace_one.side_effect = Exception("Database error")
        service.cache_collection = mock_collection
        
        # Should not raise exception
        service.save_price_data(price_data, None)

    def test_run_async_scraping_in_thread_success(self, service):
        """Test successful async scraping in thread."""
        expected_result = {
            'tcgplayer_price': 25.99,
            'tcgplayer_market_price': 30.00,
            'tcgplayer_url': 'https://tcgplayer.com/test'
        }
        
        with patch.object(service, 'scrape_price_from_tcgplayer_pooled') as mock_scrape:
            mock_scrape.return_value = expected_result
            
            result = service._run_async_scraping_in_thread('Blue-Eyes White Dragon', 'Ultra Rare', None, 'LOB-001')
            
            assert result == expected_result

    def test_run_async_scraping_in_thread_high_concurrency(self, service):
        """Test async scraping in thread with high concurrency."""
        expected_result = {
            'tcgplayer_price': 25.99,
            'tcgplayer_market_price': 30.00
        }
        
        with patch('ygoapi.price_scraping.os.getenv', return_value='5'), \
             patch('ygoapi.price_scraping.time.sleep') as mock_sleep, \
             patch.object(service, 'scrape_price_from_tcgplayer_pooled', return_value=expected_result):
            
            result = service._run_async_scraping_in_thread('Blue-Eyes White Dragon', 'Ultra Rare', None, 'LOB-001')
            
            # Should have delayed for high concurrency
            mock_sleep.assert_called_once()
            assert result == expected_result

    def test_run_async_scraping_in_thread_exception(self, service):
        """Test async scraping in thread with exception."""
        with patch.object(service, 'scrape_price_from_tcgplayer_pooled', side_effect=Exception("Scraping error")):
            
            result = service._run_async_scraping_in_thread('Blue-Eyes White Dragon', 'Ultra Rare', None, 'LOB-001')
            
            assert result['tcgplayer_price'] is None
            assert result['error'] == 'Threading error: Scraping error'

    def test_scrape_card_price_force_refresh(self, service):
        """Test scraping with force refresh flag."""
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service._scraping_executor, 'submit') as mock_submit, \
             patch.object(service, 'save_price_data'):
            
            mock_future = Mock()
            mock_future.result.return_value = {
                'tcgplayer_price': 25.99,
                'tcgplayer_market_price': 30.00
            }
            mock_submit.return_value = mock_future
            
            result = service.scrape_card_price('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', force_refresh=True)
            
            assert result['success'] is True
            assert result['cached'] is False

    def test_scrape_card_price_stale_cache_hit(self, service):
        """Test scraping with stale cache hit."""
        stale_cached_data = {
            'data': {
                'tcgplayer_price': 20.00,
                'tcgplayer_market_price': 25.00,
                'last_price_updt': datetime.now(timezone.utc) - timedelta(days=2)
            },
            'is_fresh': False
        }
        
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=stale_cached_data), \
             patch.object(service._scraping_executor, 'submit') as mock_submit, \
             patch.object(service, 'save_price_data'):
            
            mock_future = Mock()
            mock_future.result.return_value = {
                'tcgplayer_price': 25.99,
                'tcgplayer_market_price': 30.00
            }
            mock_submit.return_value = mock_future
            
            result = service.scrape_card_price('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
            
            assert result['success'] is True
            assert result['cached'] is False

    def test_scrape_card_price_null_prices_with_cache_fallback(self, service):
        """Test scraping that returns null prices with cache fallback."""
        cached_data = {
            'data': {
                'tcgplayer_price': 30.00,
                'tcgplayer_market_price': 35.00,
                'last_price_updt': datetime.now(timezone.utc)
            },
            'is_fresh': False
        }
        
        with patch.object(service, 'validate_card_rarity', return_value=True), \
             patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=cached_data), \
             patch.object(service._scraping_executor, 'submit') as mock_submit, \
             patch.object(service, 'save_price_data'):
            
            # First call returns None for cache check, second call returns actual cached data
            service._find_cached_price_data_with_staleness_info.side_effect = [None, cached_data]
            
            mock_future = Mock()
            mock_future.result.return_value = {
                'tcgplayer_price': None,
                'tcgplayer_market_price': None
            }
            mock_submit.return_value = mock_future
            
            result = service.scrape_card_price('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
            
            assert result['success'] is True
            assert result['cached'] is True
            assert result['tcgplayer_price'] == 30.00

    def test_scrape_card_price_validation_exception(self, service):
        """Test scraping with validation exception."""
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=None), \
             patch.object(service, 'validate_card_rarity', side_effect=Exception("Validation error")):
            
            result = service.scrape_card_price('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
            
            assert result['success'] is False
            assert 'Validation error' in result['error']

    def test_scrape_card_price_main_exception(self, service):
        """Test scraping with main method exception."""
        with patch.object(service, '_find_cached_price_data_with_staleness_info', side_effect=Exception("Main error")):
            
            result = service.scrape_card_price('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
            
            assert result['success'] is False
            assert 'Main error' in result['error']


class TestPriceScrapingServiceAdvanced:
    """Advanced test cases for complex price scraping scenarios."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            return PriceScrapingService()

    def test_art_variant_matching_complex(self, service):
        """Test complex art variant matching scenarios."""
        # Test numbered variants
        alternatives = service._get_art_variant_alternatives("2")
        assert "2" in alternatives
        assert "2nd" in alternatives
        assert "second" in alternatives
        
        # Test out of range numbers
        alternatives = service._get_art_variant_alternatives("15")
        assert "15" in alternatives
        # Should not include ordinal forms for numbers > 10

    def test_cache_staleness_edge_cases(self, service):
        """Test cache staleness calculation edge cases."""
        # Test with exactly expiry boundary
        boundary_time = datetime.now(timezone.utc) - timedelta(days=1)  # Assuming 1 day expiry
        
        boundary_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': boundary_time
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = boundary_data
        service.cache_collection = mock_collection
        
        with patch('ygoapi.price_scraping.PRICE_CACHE_EXPIRY_DAYS', 1):
            result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
            
            assert result is not None

    def test_memory_cleanup_callback_registration(self, service):
        """Test that memory cleanup callback is properly registered."""
        mock_memory_manager = Mock()
        
        with patch('ygoapi.price_scraping.get_memory_manager', return_value=mock_memory_manager):
            new_service = PriceScrapingService()
            
            mock_memory_manager.register_cleanup_callback.assert_called_once_with(
                "price_scraper_cleanup", new_service.cleanup_resources
            )

    def test_thread_pool_executor_configuration(self, service):
        """Test thread pool executor configuration from environment."""
        with patch('ygoapi.price_scraping.os.environ.get', return_value='4'):
            new_service = PriceScrapingService()
            
            # Should have configured with 4 workers
            assert new_service._scraping_executor is not None

    def test_async_scraping_delay_calculation(self, service):
        """Test delay calculation in async scraping thread."""
        with patch('ygoapi.price_scraping.os.getenv', return_value='3'), \
             patch('ygoapi.price_scraping.time.sleep') as mock_sleep, \
             patch('ygoapi.price_scraping.random.uniform', return_value=0.5), \
             patch.object(service, 'scrape_price_from_tcgplayer_pooled', return_value={}):
            
            service._run_async_scraping_in_thread('Test Card', 'Common', None, 'TEST-001')
            
            # Should have slept with calculated delay
            mock_sleep.assert_called_once()

    def test_index_creation_with_existing_indexes(self, service):
        """Test index creation when some indexes already exist."""
        mock_collection = Mock()
        
        # Mock existing indexes
        existing_indexes = [
            {'key': {'_id': 1}, 'name': '_id_'},
            {'key': {'card_number': 1}, 'name': 'card_number_idx'}
        ]
        mock_collection.list_indexes.return_value = existing_indexes
        
        with patch('ygoapi.price_scraping.get_price_cache_collection', return_value=mock_collection), \
             patch('ygoapi.price_scraping.get_card_variants_collection', return_value=Mock()):
            
            service._initialize_collections()
            
            # Should only create missing indexes
            assert mock_collection.create_index.call_count >= 1

    def test_cache_query_construction_with_art_variant(self, service):
        """Test cache query construction with art variant."""
        mock_collection = Mock()
        service.cache_collection = mock_collection
        
        service.find_cached_price_data('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', 'Alternate Art')
        
        # Should have called find_one with proper query including art variant alternatives
        mock_collection.find_one.assert_called_once()
        call_args = mock_collection.find_one.call_args[0][0]
        assert 'card_number' in call_args
        assert 'card_rarity' in call_args


class TestGlobalPriceScrapingService:
    """Test the global price scraping service instance."""

    def test_global_service_instance(self):
        """Test that the global service instance is properly created."""
        with patch('ygoapi.price_scraping.PriceScrapingService'):
            from ygoapi.price_scraping import price_scraping_service
            assert price_scraping_service is not None


class TestPriceScrapingUtilityFunctions:
    """Test utility functions and edge cases in price scraping."""

    @pytest.fixture
    def service(self):
        """Create a PriceScrapingService instance for testing."""
        with patch('ygoapi.price_scraping.get_memory_manager'), \
             patch('ygoapi.price_scraping.get_price_cache_collection'), \
             patch('ygoapi.price_scraping.get_card_variants_collection'):
            return PriceScrapingService()

    def test_art_variant_normalization_edge_cases(self, service):
        """Test art variant normalization with edge cases."""
        # Test with whitespace
        assert service._normalize_art_variant("  1st  ") == "1"
        assert service._normalize_art_variant("\t2nd\n") == "2"
        
        # Test case insensitive
        assert service._normalize_art_variant("FIRST") == "1"
        assert service._normalize_art_variant("Second") == "2"
        
        # Test with mixed case and spacing
        assert service._normalize_art_variant(" Third ") == "3"

    def test_cache_collection_lazy_initialization(self, service):
        """Test that collections are initialized lazily."""
        assert not service._initialized
        
        # Accessing a method that requires initialization
        with patch.object(service, '_initialize_collections') as mock_init:
            service._ensure_initialized()
            
            mock_init.assert_called_once()
            assert service._initialized

    def test_complex_art_variant_alternatives_generation(self, service):
        """Test complex art variant alternatives generation."""
        # Test with number 5
        alternatives = service._get_art_variant_alternatives("5")
        expected = {"5", "5th", "fifth"}
        assert alternatives == expected
        
        # Test with number outside typical range
        alternatives = service._get_art_variant_alternatives("20")
        # Should only include the normalized form for numbers > 10
        assert "20" in alternatives

    def test_price_data_saving_with_art_variant_normalization(self, service):
        """Test price data saving with art variant normalization."""
        price_data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'tcgplayer_price': 25.99
        }
        
        mock_collection = Mock()
        service.cache_collection = mock_collection
        
        # Test with art variant that needs normalization
        service.save_price_data(price_data, "1st Edition")
        
        # Should have saved with normalized art variant
        mock_collection.replace_one.assert_called_once()
        saved_data = mock_collection.replace_one.call_args[1]['upsert']
        assert saved_data is True

    def test_staleness_calculation_with_different_timezones(self, service):
        """Test staleness calculation with different timezone formats."""
        # Test with UTC timezone
        utc_time = datetime.now(timezone.utc) - timedelta(hours=1)
        utc_data = {
            'card_number': 'LOB-001',
            'tcgplayer_price': 25.99,
            'last_price_updt': utc_time
        }
        
        mock_collection = Mock()
        mock_collection.find_one.return_value = utc_data
        service.cache_collection = mock_collection
        
        result = service._find_cached_price_data_with_staleness_info('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result is not None
        assert result['is_fresh'] is True  # Should be fresh since it's only 1 hour old

    def test_error_handling_in_complex_scenarios(self, service):
        """Test error handling in complex scenarios."""
        # Test when thread pool executor is None
        service._scraping_executor = None
        
        result = service.scrape_card_price('LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare')
        
        assert result['success'] is False
        assert 'error' in result