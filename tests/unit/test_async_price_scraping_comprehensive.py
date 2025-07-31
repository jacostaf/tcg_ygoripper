"""
Comprehensive test suite for async_price_scraping module.

This test suite aims for 100% coverage of the AsyncPriceScrapingService
and all related async price scraping functionality.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from ygoapi.async_price_scraping import AsyncPriceScrapingService, get_async_price_service


class TestAsyncPriceScrapingServiceComprehensive:
    """Comprehensive test cases for AsyncPriceScrapingService."""

    @pytest.fixture
    def service(self):
        """Create an AsyncPriceScrapingService instance for testing."""
        with patch('ygoapi.async_price_scraping.get_database'), \
             patch('ygoapi.async_price_scraping.get_browser_strategy', return_value='pool'), \
             patch('ygoapi.async_price_scraping.get_browser_pool'):
            return AsyncPriceScrapingService()

    def test_service_initialization_pool_strategy(self):
        """Test service initialization with pool strategy."""
        with patch('ygoapi.async_price_scraping.get_database'), \
             patch('ygoapi.async_price_scraping.get_browser_strategy', return_value='pool'), \
             patch('ygoapi.async_price_scraping.get_browser_pool') as mock_pool:
            
            service = AsyncPriceScrapingService()
            
            assert service.browser_strategy == 'pool'
            assert service.browser_pool is not None
            assert service.browser_manager is None
            assert service.optimized_pool is None
            mock_pool.assert_called_once()

    def test_service_initialization_optimized_strategy(self):
        """Test service initialization with optimized strategy."""
        with patch('ygoapi.async_price_scraping.get_database'), \
             patch('ygoapi.async_price_scraping.get_browser_strategy', return_value='optimized'), \
             patch('ygoapi.async_price_scraping.get_optimized_browser_pool') as mock_optimized:
            
            service = AsyncPriceScrapingService()
            
            assert service.browser_strategy == 'optimized'
            assert service.browser_pool is None
            assert service.browser_manager is None
            assert service.optimized_pool is not None
            mock_optimized.assert_called_once()

    def test_service_initialization_manager_strategy(self):
        """Test service initialization with manager strategy."""
        with patch('ygoapi.async_price_scraping.get_database'), \
             patch('ygoapi.async_price_scraping.get_browser_strategy', return_value='manager'), \
             patch('ygoapi.async_price_scraping.BrowserManager') as mock_manager:
            
            service = AsyncPriceScrapingService()
            
            assert service.browser_strategy == 'manager'
            assert service.browser_pool is None
            assert service.browser_manager is not None
            assert service.optimized_pool is None
            mock_manager.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_card_price_fresh_data(self, service):
        """Test scraping fresh card price data."""
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=None), \
             patch.object(service, '_validate_rarity_async', return_value=True), \
             patch.object(service, 'scrape_price_from_tcgplayer') as mock_scrape, \
             patch.object(service, 'save_price_data_async'):
            
            mock_scrape.return_value = {
                'tcgplayer_price': 10.50,
                'tcgplayer_market_price': 12.00,
                'tcgplayer_url': 'https://tcgplayer.com/test'
            }
            
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare'
            )
            
            assert result['success'] is True
            assert result['cached'] is False
            assert result['tcgplayer_price'] == 10.50
            assert result['tcgplayer_market_price'] == 12.00

    @pytest.mark.asyncio
    async def test_scrape_card_price_with_cache_hit(self, service):
        """Test scraping with cached data that is fresh."""
        cached_data = {
            'data': {
                'tcg_price': 25.99,
                'tcg_market_price': 28.50,
                'source_url': 'https://tcgplayer.com/cached',
                'last_price_updt': datetime.now(timezone.utc),
                'scrape_success': True
            },
            'is_stale': False
        }
        
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=cached_data):
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare'
            )
            
            assert result['success'] is True
            assert result['cached'] is True
            assert result['tcgplayer_price'] == 25.99
            assert result['tcgplayer_market_price'] == 28.50

    @pytest.mark.asyncio
    async def test_scrape_card_price_with_stale_cache(self, service):
        """Test scraping with stale cached data."""
        cached_data = {
            'data': {
                'tcg_price': 25.99,
                'tcg_market_price': 28.50,
                'source_url': 'https://tcgplayer.com/cached',
                'last_price_updt': datetime.now(timezone.utc),
                'scrape_success': True
            },
            'is_stale': True
        }
        
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=cached_data), \
             patch.object(service, '_validate_rarity_async', return_value=True), \
             patch.object(service, 'scrape_price_from_tcgplayer') as mock_scrape, \
             patch.object(service, 'save_price_data_async'):
            
            mock_scrape.return_value = {
                'tcgplayer_price': 15.00,
                'tcgplayer_market_price': 18.00,
                'tcgplayer_url': 'https://tcgplayer.com/fresh'
            }
            
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare'
            )
            
            assert result['success'] is True
            assert result['cached'] is False

    @pytest.mark.asyncio
    async def test_scrape_card_price_with_force_refresh(self, service):
        """Test scraping with force refresh flag."""
        with patch.object(service, '_validate_rarity_async', return_value=True), \
             patch.object(service, 'scrape_price_from_tcgplayer') as mock_scrape, \
             patch.object(service, 'save_price_data_async'):
            
            mock_scrape.return_value = {
                'tcgplayer_price': 20.00,
                'tcgplayer_market_price': 22.00,
                'tcgplayer_url': 'https://tcgplayer.com/forced'
            }
            
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', 
                force_refresh=True
            )
            
            assert result['success'] is True
            assert result['cached'] is False

    @pytest.mark.asyncio
    async def test_scrape_card_price_invalid_rarity_with_cache(self, service):
        """Test scraping with invalid rarity but valid cache."""
        cached_data = {
            'data': {
                'tcg_price': 15.99,
                'tcg_market_price': 18.50,
                'source_url': 'https://tcgplayer.com/cached',
                'last_price_updt': datetime.now(timezone.utc),
                'scrape_success': True
            },
            'is_stale': False
        }
        
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=cached_data), \
             patch.object(service, '_validate_rarity_async', return_value=False):
            
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Invalid Rarity'
            )
            
            assert result['success'] is True
            assert result['cached'] is True

    @pytest.mark.asyncio
    async def test_scrape_card_price_invalid_rarity_no_cache(self, service):
        """Test scraping with invalid rarity and no cache."""
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=None), \
             patch.object(service, '_validate_rarity_async', return_value=False):
            
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Invalid Rarity'
            )
            
            assert result['success'] is False
            assert 'not found with rarity' in result['error']

    @pytest.mark.asyncio
    async def test_scrape_card_price_no_card_name(self, service):
        """Test scraping without card name."""
        with patch.object(service, '_validate_rarity_async', return_value=True), \
             patch.object(service, '_get_card_info_from_ygo_api_async', return_value={'card_name': 'Found Card'}), \
             patch.object(service, 'scrape_price_from_tcgplayer') as mock_scrape, \
             patch.object(service, 'save_price_data_async'):
            
            mock_scrape.return_value = {
                'tcgplayer_price': 5.00,
                'tcgplayer_market_price': 6.00,
                'tcgplayer_url': 'https://tcgplayer.com/found'
            }
            
            result = await service.scrape_card_price(
                'LOB-001', '', 'Ultra Rare'
            )
            
            assert result['success'] is True

    @pytest.mark.asyncio
    async def test_scrape_card_price_null_prices_with_cache(self, service):
        """Test scraping that returns null prices but has cache fallback."""
        cached_data = {
            'data': {
                'tcg_price': 30.00,
                'tcg_market_price': 35.00,
                'source_url': 'https://tcgplayer.com/cached',
                'last_price_updt': datetime.now(timezone.utc),
                'scrape_success': True
            },
            'is_stale': False
        }
        
        with patch.object(service, '_find_cached_price_data_with_staleness_info', return_value=cached_data), \
             patch.object(service, '_validate_rarity_async', return_value=True), \
             patch.object(service, 'scrape_price_from_tcgplayer') as mock_scrape, \
             patch.object(service, 'save_price_data_async'):
            
            mock_scrape.return_value = {
                'tcgplayer_price': None,
                'tcgplayer_market_price': None,
                'tcgplayer_url': 'https://tcgplayer.com/test'
            }
            
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare'
            )
            
            assert result['success'] is True
            assert result['cached'] is True
            assert result['tcgplayer_price'] == 30.00

    @pytest.mark.asyncio
    async def test_scrape_card_price_exception_handling(self, service):
        """Test exception handling in scrape_card_price."""
        with patch.object(service, '_validate_rarity_async', side_effect=Exception('Test error')):
            result = await service.scrape_card_price(
                'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare'
            )
            
            assert result['success'] is False
            assert 'Test error' in result['error']

    @pytest.mark.asyncio
    async def test_scrape_price_from_tcgplayer_pool_strategy(self, service):
        """Test scraping from TCGPlayer using pool strategy."""
        service.browser_strategy = 'pool'
        service.browser_pool = AsyncMock()
        mock_context = AsyncMock()
        service.browser_pool.acquire_context.return_value.__aenter__.return_value = mock_context
        
        with patch.object(service, '_scrape_with_context') as mock_scrape:
            mock_scrape.return_value = {'tcgplayer_price': 10.00}
            
            result = await service.scrape_price_from_tcgplayer(
                'Blue-Eyes White Dragon', 'Ultra Rare'
            )
            
            assert result['tcgplayer_price'] == 10.00
            mock_scrape.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_price_from_tcgplayer_optimized_strategy(self, service):
        """Test scraping from TCGPlayer using optimized strategy."""
        service.browser_strategy = 'optimized'
        service.optimized_pool = AsyncMock()
        mock_context = AsyncMock()
        service.optimized_pool.acquire_context.return_value.__aenter__.return_value = mock_context
        
        with patch.object(service, '_scrape_with_context') as mock_scrape:
            mock_scrape.return_value = {'tcgplayer_price': 15.00}
            
            result = await service.scrape_price_from_tcgplayer(
                'Dark Magician', 'Secret Rare'
            )
            
            assert result['tcgplayer_price'] == 15.00
            mock_scrape.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_price_from_tcgplayer_manager_strategy(self, service):
        """Test scraping from TCGPlayer using manager strategy."""
        service.browser_strategy = 'manager'
        service.browser_manager = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        service.browser_manager.create_browser.return_value.__aenter__.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        
        with patch.object(service, '_scrape_with_context') as mock_scrape:
            mock_scrape.return_value = {'tcgplayer_price': 20.00}
            
            result = await service.scrape_price_from_tcgplayer(
                'Red-Eyes Black Dragon', 'Ultra Rare'
            )
            
            assert result['tcgplayer_price'] == 20.00
            mock_scrape.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_price_from_tcgplayer_exception(self, service):
        """Test exception handling in scrape_price_from_tcgplayer."""
        service.browser_strategy = 'pool'
        service.browser_pool = AsyncMock()
        service.browser_pool.acquire_context.side_effect = Exception('Browser error')
        
        result = await service.scrape_price_from_tcgplayer(
            'Blue-Eyes White Dragon', 'Ultra Rare'
        )
        
        assert result['tcgplayer_price'] is None
        assert result['error'] == 'Browser error'

    @pytest.mark.asyncio
    async def test_scrape_with_context_basic(self, service):
        """Test basic scraping with context."""
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_page.url = 'https://tcgplayer.com/result'
        
        with patch.object(service, '_wait_for_search_results', return_value=1), \
             patch.object(service, '_select_variant_async', return_value='https://tcgplayer.com/product'), \
             patch.object(service, '_wait_for_price_data'), \
             patch.object(service, 'extract_prices_from_tcgplayer_dom') as mock_extract:
            
            mock_extract.return_value = {
                'tcg_price': 25.00,
                'tcg_market_price': 30.00
            }
            
            result = await service._scrape_with_context(
                mock_context, 'Blue-Eyes White Dragon', 'Ultra Rare', None, 'LOB-001'
            )
            
            assert result['tcgplayer_price'] == 25.00
            assert result['tcgplayer_market_price'] == 30.00

    @pytest.mark.asyncio
    async def test_scrape_with_context_no_results(self, service):
        """Test scraping with context when no results found."""
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page.return_value = mock_page
        
        with patch.object(service, '_wait_for_search_results', return_value=0):
            result = await service._scrape_with_context(
                mock_context, 'Nonexistent Card', 'Ultra Rare', None, 'XXX-001'
            )
            
            assert result['tcgplayer_price'] is None
            assert 'No results found' in result['error']

    @pytest.mark.asyncio
    async def test_scrape_with_context_variant_selection_failed(self, service):
        """Test scraping when variant selection fails."""
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_page.evaluate.return_value = False  # Not on product page
        
        with patch.object(service, '_wait_for_search_results', return_value=1), \
             patch.object(service, '_select_variant_async', return_value=None):
            
            result = await service._scrape_with_context(
                mock_context, 'Blue-Eyes White Dragon', 'Ultra Rare', None, 'LOB-001'
            )
            
            assert result['tcgplayer_price'] is None
            assert 'Could not find matching variant' in result['error']

    @pytest.mark.asyncio
    async def test_scrape_with_context_art_variant_handling(self, service):
        """Test scraping with art variant handling."""
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_page.url = 'https://tcgplayer.com/result'
        
        with patch('ygoapi.async_price_scraping.extract_art_version', return_value='Alternate Art'), \
             patch.object(service, '_wait_for_search_results', return_value=1), \
             patch.object(service, '_select_variant_async', return_value='https://tcgplayer.com/product'), \
             patch.object(service, '_wait_for_price_data'), \
             patch.object(service, 'extract_prices_from_tcgplayer_dom') as mock_extract:
            
            mock_extract.return_value = {
                'tcg_price': 40.00,
                'tcg_market_price': 45.00
            }
            
            result = await service._scrape_with_context(
                mock_context, 'Blue-Eyes White Dragon (Alternate Art)', 'Ultra Rare', None, 'LOB-001'
            )
            
            assert result['tcgplayer_price'] == 40.00

    @pytest.mark.asyncio
    async def test_scrape_with_context_exception(self, service):
        """Test exception handling in _scrape_with_context."""
        mock_context = AsyncMock()
        mock_context.new_page.side_effect = Exception('Page creation failed')
        
        result = await service._scrape_with_context(
            mock_context, 'Blue-Eyes White Dragon', 'Ultra Rare', None, 'LOB-001'
        )
        
        assert result['tcgplayer_price'] is None
        assert 'Page creation failed' in result['error']

    @pytest.mark.asyncio
    async def test_wait_for_search_results_success(self, service):
        """Test waiting for search results successfully."""
        mock_page = AsyncMock()
        
        # Mock the page evaluation to return results count
        mock_page.evaluate.side_effect = [5, False]  # 5 results, no "no results" message
        
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.time.side_effect = [0, 1]  # Simulate time progression
            
            result = await service._wait_for_search_results(mock_page, 'Blue-Eyes White Dragon')
            
            assert result == 5

    @pytest.mark.asyncio
    async def test_wait_for_search_results_no_results(self, service):
        """Test waiting for search results when none found."""
        mock_page = AsyncMock()
        
        # Mock the page evaluation to return no results
        mock_page.evaluate.side_effect = [0, True]  # 0 results, "no results" message found
        
        result = await service._wait_for_search_results(mock_page, 'Nonexistent Card')
        
        assert result == 0

    @pytest.mark.asyncio
    async def test_wait_for_search_results_timeout(self, service):
        """Test waiting for search results with timeout."""
        mock_page = AsyncMock()
        
        # Mock continuous no results and time progression past timeout
        mock_page.evaluate.side_effect = lambda script: 0 if "results" in script else False
        
        with patch('asyncio.get_event_loop') as mock_loop, \
             patch('asyncio.sleep'):
            mock_loop.return_value.time.side_effect = [0, 20]  # Simulate timeout
            
            result = await service._wait_for_search_results(mock_page, 'Test Card', max_wait_seconds=15)
            
            assert result == 0

    @pytest.mark.asyncio
    async def test_wait_for_search_results_final_check(self, service):
        """Test waiting for search results with final element check."""
        mock_page = AsyncMock()
        
        # Mock the page evaluation: no initial results, but final check finds some
        mock_page.evaluate.side_effect = [0, False, 3]  # No results initially, no "no results" message, final check finds 3
        
        with patch('asyncio.get_event_loop') as mock_loop, \
             patch('asyncio.sleep'):
            mock_loop.return_value.time.side_effect = [0, 20]  # Simulate timeout for main loop
            
            result = await service._wait_for_search_results(mock_page, 'Test Card', max_wait_seconds=15)
            
            assert result == 3

    @pytest.mark.asyncio
    async def test_wait_for_search_results_exception(self, service):
        """Test exception handling in _wait_for_search_results."""
        mock_page = AsyncMock()
        mock_page.evaluate.side_effect = Exception('Evaluation error')
        
        result = await service._wait_for_search_results(mock_page, 'Test Card')
        
        assert result == 0

    @pytest.mark.asyncio
    async def test_wait_for_price_data_success(self, service):
        """Test waiting for price data successfully."""
        mock_page = AsyncMock()
        
        await service._wait_for_price_data(mock_page)
        
        mock_page.wait_for_selector.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_price_data_timeout(self, service):
        """Test waiting for price data with timeout."""
        mock_page = AsyncMock()
        mock_page.wait_for_selector.side_effect = Exception('Timeout')
        mock_page.screenshot.return_value = b'screenshot_data'
        
        await service._wait_for_price_data(mock_page)
        
        # Should not raise exception
        mock_page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_prices_from_tcgplayer_dom_success(self, service):
        """Test successful price extraction from DOM."""
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = {
            'tcg_price': 15.50,
            'tcg_market_price': 18.00,
            'debug_info': []
        }
        
        result = await service.extract_prices_from_tcgplayer_dom(mock_page)
        
        assert result['tcg_price'] == 15.50
        assert result['tcg_market_price'] == 18.00

    @pytest.mark.asyncio
    async def test_extract_prices_from_tcgplayer_dom_null_prices(self, service):
        """Test price extraction with null prices."""
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = {
            'tcg_price': None,
            'tcg_market_price': None,
            'debug_info': ['No prices found']
        }
        
        result = await service.extract_prices_from_tcgplayer_dom(mock_page)
        
        assert result['tcg_price'] is None
        assert result['tcg_market_price'] is None

    @pytest.mark.asyncio
    async def test_extract_prices_from_tcgplayer_dom_exception(self, service):
        """Test exception handling in price extraction."""
        mock_page = AsyncMock()
        mock_page.evaluate.side_effect = Exception('DOM error')
        
        result = await service.extract_prices_from_tcgplayer_dom(mock_page)
        
        assert result['tcg_price'] is None
        assert result['tcg_market_price'] is None

    @pytest.mark.asyncio
    async def test_select_variant_async_success(self, service):
        """Test successful variant selection."""
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = [
            {'url': 'https://tcgplayer.com/product/1', 'text': 'Blue-Eyes White Dragon - Ultra Rare'},
            {'url': 'https://tcgplayer.com/product/2', 'text': 'Blue-Eyes White Dragon - Secret Rare'}
        ]
        
        result = await service._select_variant_async(
            mock_page, 'Blue-Eyes White Dragon', 'Ultra Rare', 'LOB-001', None
        )
        
        assert result == 'https://tcgplayer.com/product/1'

    @pytest.mark.asyncio
    async def test_select_variant_async_no_links(self, service):
        """Test variant selection when no links found."""
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = []
        
        result = await service._select_variant_async(
            mock_page, 'Blue-Eyes White Dragon', 'Ultra Rare', 'LOB-001', None
        )
        
        assert result is None

    @pytest.mark.asyncio
    async def test_select_variant_async_exception(self, service):
        """Test exception handling in variant selection."""
        mock_page = AsyncMock()
        mock_page.evaluate.side_effect = Exception('Selection error')
        
        result = await service._select_variant_async(
            mock_page, 'Blue-Eyes White Dragon', 'Ultra Rare', 'LOB-001', None
        )
        
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_rarity_async(self, service):
        """Test async rarity validation."""
        result = await service._validate_rarity_async('LOB-001', 'Ultra Rare')
        
        # Should return True (simplified implementation)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_card_info_from_ygo_api_async(self, service):
        """Test getting card info from YGO API."""
        result = await service._get_card_info_from_ygo_api_async('LOB-001')
        
        # Should return None (simplified implementation)
        assert result is None

    def test_find_cached_price_data_with_staleness_info_success(self, service):
        """Test successful cache lookup with staleness info."""
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'tcg_price': 25.99,
            'last_price_updt': datetime.now(timezone.utc)
        }
        service.db = {'price_cache': mock_collection}
        
        result = service._find_cached_price_data_with_staleness_info(
            'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', None
        )
        
        assert result is not None
        assert result['data']['tcg_price'] == 25.99
        assert result['is_stale'] is False

    def test_find_cached_price_data_with_staleness_info_stale(self, service):
        """Test cache lookup with stale data."""
        old_time = datetime.now(timezone.utc) - timedelta(days=2)
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'tcg_price': 25.99,
            'last_price_updt': old_time
        }
        service.db = {'price_cache': mock_collection}
        
        result = service._find_cached_price_data_with_staleness_info(
            'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', None
        )
        
        assert result is not None
        assert result['is_stale'] is True

    def test_find_cached_price_data_with_staleness_info_not_found(self, service):
        """Test cache lookup when data not found."""
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        service.db = {'price_cache': mock_collection}
        
        result = service._find_cached_price_data_with_staleness_info(
            'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', None
        )
        
        assert result is None

    def test_find_cached_price_data_with_staleness_info_string_date(self, service):
        """Test cache lookup with string date format."""
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            'card_number': 'LOB-001',
            'tcg_price': 25.99,
            'last_price_updt': 'Thu, 31 Jul 2025 09:14:44 GMT'
        }
        service.db = {'price_cache': mock_collection}
        
        result = service._find_cached_price_data_with_staleness_info(
            'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', None
        )
        
        assert result is not None

    def test_find_cached_price_data_with_staleness_info_exception(self, service):
        """Test cache lookup exception handling."""
        mock_collection = MagicMock()
        mock_collection.find_one.side_effect = Exception('Database error')
        service.db = {'price_cache': mock_collection}
        
        result = service._find_cached_price_data_with_staleness_info(
            'LOB-001', 'Blue-Eyes White Dragon', 'Ultra Rare', None
        )
        
        assert result is None

    @pytest.mark.asyncio
    async def test_save_price_data_async_success(self, service):
        """Test successful async price data saving."""
        mock_collection = MagicMock()
        service.db = {'price_cache': mock_collection}
        
        price_data = {
            'card_number': 'LOB-001',
            'tcg_price': 25.99
        }
        
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_executor = MagicMock()
            mock_loop.return_value.run_in_executor.return_value = asyncio.Future()
            mock_loop.return_value.run_in_executor.return_value.set_result(None)
            
            await service.save_price_data_async(price_data, 'Alternate Art')
            
            mock_loop.return_value.run_in_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_price_data_async_exception(self, service):
        """Test exception handling in async price data saving."""
        mock_collection = MagicMock()
        service.db = {'price_cache': mock_collection}
        
        price_data = {'card_number': 'LOB-001'}
        
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.run_in_executor.side_effect = Exception('Save error')
            
            await service.save_price_data_async(price_data, None)
            
            # Should not raise exception


class TestGlobalAsyncPriceService:
    """Test the global async price service functions."""

    def test_get_async_price_service_singleton(self):
        """Test that get_async_price_service returns singleton."""
        with patch('ygoapi.async_price_scraping.AsyncPriceScrapingService') as mock_service:
            # Clear the global instance
            import ygoapi.async_price_scraping
            ygoapi.async_price_scraping._async_price_service = None
            
            service1 = get_async_price_service()
            service2 = get_async_price_service()
            
            # Should be the same instance
            assert service1 is service2
            # Service should be created only once
            mock_service.assert_called_once()

    def test_get_async_price_service_existing_instance(self):
        """Test getting existing async price service instance."""
        with patch('ygoapi.async_price_scraping.AsyncPriceScrapingService') as mock_service:
            # Set a mock instance
            import ygoapi.async_price_scraping
            mock_instance = MagicMock()
            ygoapi.async_price_scraping._async_price_service = mock_instance
            
            service = get_async_price_service()
            
            assert service is mock_instance
            # Should not create new instance
            mock_service.assert_not_called()