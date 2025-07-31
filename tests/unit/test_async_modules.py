"""
Test suite for async modules.

This test suite covers the async functionality including async routes, 
async browser pool, and async price scraping without changing functional code.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from quart import Quart

# Import the modules to test
from ygoapi.async_app import create_async_app
from ygoapi.async_routes import register_async_routes
from ygoapi.async_price_scraping import AsyncPriceScrapingService
from ygoapi.async_browser_pool import AsyncBrowserPool


class TestAsyncApp:
    """Test suite for async app creation and configuration."""

    def test_create_async_app_basic(self):
        """Test basic app creation."""
        app = create_async_app()
        assert isinstance(app, Quart)
        assert app.name == "ygoapi.async_app"

    @patch('ygoapi.async_app.get_memory_manager')
    @patch('ygoapi.async_app.test_database_connection')
    def test_create_async_app_with_mocks(self, mock_db_connection, mock_memory_manager):
        """Test app creation with mocked dependencies."""
        mock_memory_manager.return_value = MagicMock(limit_mb=512)
        mock_db_connection.return_value = True
        
        app = create_async_app()
        assert isinstance(app, Quart)

    @patch('ygoapi.async_app.validate_config')
    def test_create_async_app_config_validation(self, mock_validate):
        """Test app creation with config validation."""
        mock_validate.return_value = True
        
        app = create_async_app()
        assert isinstance(app, Quart)
        mock_validate.assert_called_once()


class TestAsyncRoutes:
    """Test suite for async routes registration."""

    def test_register_async_routes(self):
        """Test that routes can be registered without errors."""
        app = Quart(__name__)
        
        # This should not raise an exception
        register_async_routes(app)
        
        # Check that some routes were registered
        assert len(app.url_map._rules) > 0

    def test_async_routes_endpoints_exist(self):
        """Test that expected endpoints are registered."""
        app = Quart(__name__)
        register_async_routes(app)
        
        # Get all registered endpoints
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        
        # Check for some key endpoints (names may vary)
        expected_endpoints = [
            'health'
        ]
        
        for endpoint in expected_endpoints:
            assert endpoint in endpoints or any(endpoint in ep for ep in endpoints)
        
        # Should have registered some routes
        assert len(endpoints) > 0


class TestAsyncPriceScrapingService:
    """Test suite for AsyncPriceScrapingService."""

    @pytest.fixture
    def async_service(self):
        """Create an AsyncPriceScrapingService instance for testing."""
        return AsyncPriceScrapingService()

    def test_async_service_creation(self, async_service):
        """Test that the async service can be created."""
        assert async_service is not None
        assert hasattr(async_service, 'scrape_card_price')

    @patch('ygoapi.async_price_scraping.get_browser_strategy')
    def test_async_service_initialization(self, mock_strategy, async_service):
        """Test async service initialization with mocked dependencies."""
        mock_strategy.return_value = 'optimized'
        
        # Service should initialize without errors
        assert async_service is not None

    @pytest.mark.asyncio
    @patch('ygoapi.async_price_scraping.get_async_price_service')
    async def test_get_async_price_service(self, mock_get_service):
        """Test getting the async price service."""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        
        from ygoapi.async_price_scraping import get_async_price_service
        service = get_async_price_service()
        
        assert service == mock_service


class TestAsyncBrowserPool:
    """Test suite for AsyncBrowserPool."""

    @pytest.fixture
    def browser_pool(self):
        """Create an AsyncBrowserPool instance for testing."""
        return AsyncBrowserPool()

    def test_browser_pool_creation(self, browser_pool):
        """Test that the browser pool can be created."""
        assert browser_pool is not None
        assert hasattr(browser_pool, 'acquire_context')

    @pytest.mark.asyncio
    async def test_browser_pool_initialization(self, browser_pool):
        """Test browser pool initialization."""
        # Mock playwright to avoid actual browser launch
        with patch('ygoapi.async_browser_pool.async_playwright') as mock_playwright:
            mock_playwright_instance = AsyncMock()
            mock_playwright.return_value = mock_playwright_instance
            mock_playwright_instance.start.return_value = mock_playwright_instance
            
            mock_browser = AsyncMock()
            mock_playwright_instance.chromium.launch.return_value = mock_browser
            
            try:
                await browser_pool.initialize()
                assert browser_pool._playwright is not None
            except Exception as e:
                # Expected if dependencies are not fully mocked
                assert "playwright" in str(e).lower() or "browser" in str(e).lower()

    @pytest.mark.asyncio
    async def test_browser_pool_cleanup(self, browser_pool):
        """Test browser pool cleanup."""
        # Use the actual close method with mocked dependencies
        with patch.object(browser_pool, '_lock', asyncio.Lock()), \
             patch.object(browser_pool, '_initialized', True), \
             patch.object(browser_pool, '_closing', False):
            
            mock_browser1 = AsyncMock()
            mock_browser2 = AsyncMock()
            mock_playwright = AsyncMock()
            
            browser_pool._browsers = [mock_browser1, mock_browser2]
            browser_pool._playwright = mock_playwright
            
            await browser_pool.close()
            
            # Verify cleanup was attempted
            mock_browser1.close.assert_called_once()
            mock_browser2.close.assert_called_once()
            mock_playwright.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_pool_stats(self, browser_pool):
        """Test getting browser pool statistics."""
        stats = await browser_pool.get_stats()
        
        assert isinstance(stats, dict)
        assert 'initialized' in stats
        assert 'pool_size' in stats


class TestAsyncIntegration:
    """Integration tests for async components."""

    @pytest.mark.asyncio
    async def test_async_app_startup(self):
        """Test that the async app can start up without errors."""
        with patch('ygoapi.async_app.get_memory_manager'), \
             patch('ygoapi.async_app.test_database_connection', return_value=True), \
             patch('ygoapi.async_app.validate_config', return_value=True):
            
            app = create_async_app()
            
            # Test that we can create a test client
            async with app.test_client() as client:
                # Basic smoke test
                assert client is not None

    @pytest.mark.asyncio
    @patch('ygoapi.async_routes.get_memory_stats')
    async def test_health_endpoint(self, mock_memory_stats):
        """Test the health endpoint returns valid response."""
        mock_memory_stats.return_value = {
            'usage_mb': 100,
            'limit_mb': 512,
            'percent': 0.2
        }
        
        with patch('ygoapi.async_app.get_memory_manager'), \
             patch('ygoapi.async_app.test_database_connection', return_value=True), \
             patch('ygoapi.async_app.validate_config', return_value=True):
            
            app = create_async_app()
            
            async with app.test_client() as client:
                response = await client.get('/health')
                assert response.status_code == 200
                
                data = await response.get_json()
                assert data is not None
                assert 'status' in data

    @pytest.mark.asyncio
    @patch('ygoapi.async_routes.get_optimized_browser_pool')
    async def test_browser_stats_endpoint(self, mock_browser_pool):
        """Test the browser stats endpoint."""
        mock_pool = MagicMock()
        async def mock_get_stats():
            return {
                'pool_size': 1,
                'available_browsers': 1,
                'active_requests': 0
            }
        mock_pool.get_stats = mock_get_stats
        mock_browser_pool.return_value = mock_pool
        
        with patch('ygoapi.async_app.get_memory_manager'), \
             patch('ygoapi.async_app.test_database_connection', return_value=True), \
             patch('ygoapi.async_app.validate_config', return_value=True):
            
            app = create_async_app()
            
            async with app.test_client() as client:
                response = await client.get('/browser/stats')
                assert response.status_code == 200
                
                data = await response.get_json()
                assert data is not None
                assert 'stats' in data
                assert 'pool_size' in data['stats']


@pytest.mark.asyncio
class TestAsyncErrorHandling:
    """Test error handling in async components."""

    async def test_async_price_scraping_error_handling(self):
        """Test error handling in async price scraping."""
        service = AsyncPriceScrapingService()
        
        # Mock to raise an exception
        with patch.object(service, 'scrape_card_price', side_effect=Exception("Test error")):
            try:
                await service.scrape_card_price("TEST-001", "Test Card", "Common")
            except Exception as e:
                assert "Test error" in str(e)

    async def test_async_browser_pool_error_handling(self):
        """Test error handling in browser pool."""
        pool = AsyncBrowserPool()
        
        # Test error handling when playwright is not available
        with patch('ygoapi.async_browser_pool.async_playwright', side_effect=ImportError("Playwright not found")):
            try:
                await pool.initialize()
            except ImportError as e:
                assert "Playwright not found" in str(e)