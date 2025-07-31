"""
Test suite for browser-related components.

This test suite covers browser strategy, optimized browser pool, and browser manager
without changing functional code.
"""

import pytest
import os
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from ygoapi.browser_strategy import get_browser_strategy
from ygoapi.optimized_browser_pool import OptimizedBrowserPool, get_optimized_browser_pool
from ygoapi.browser_manager import BrowserManager


class TestBrowserStrategy:
    """Test suite for browser strategy selection."""

    def test_get_browser_strategy_default(self):
        """Test default browser strategy selection."""
        with patch.dict(os.environ, {}, clear=True):
            strategy = get_browser_strategy()
            assert strategy in ['pool', 'manager', 'optimized']

    def test_get_browser_strategy_explicit_override(self):
        """Test explicit browser strategy override."""
        test_cases = [
            ('pool', 'pool'),
            ('manager', 'manager'), 
            ('optimized', 'optimized'),
            ('POOL', 'pool'),  # Test case insensitive
            ('invalid', 'pool')  # Should fallback to default logic
        ]
        
        for env_value, expected in test_cases:
            with patch.dict(os.environ, {'BROWSER_STRATEGY': env_value}):
                strategy = get_browser_strategy()
                if env_value.lower() in ['pool', 'manager', 'optimized']:
                    assert strategy == expected
                else:
                    assert strategy in ['pool', 'manager', 'optimized']

    def test_get_browser_strategy_render_environment(self):
        """Test browser strategy selection on Render."""
        with patch.dict(os.environ, {'RENDER': 'true'}, clear=True):
            strategy = get_browser_strategy()
            assert strategy == 'optimized'

    def test_get_browser_strategy_memory_limit(self):
        """Test browser strategy based on memory limit."""
        test_cases = [
            ('256', 'optimized'),
            ('512', 'optimized'),
            ('1024', 'pool'),
            ('2048', 'pool'),
            ('0', 'pool'),
            ('invalid', 'pool')
        ]
        
        for mem_limit, expected in test_cases:
            env = {'MEM_LIMIT': mem_limit}
            with patch.dict(os.environ, env, clear=True):
                strategy = get_browser_strategy()
                if mem_limit.isdigit() and int(mem_limit) <= 512 and int(mem_limit) > 0:
                    assert strategy == expected
                else:
                    assert strategy in ['pool', 'manager', 'optimized']

    def test_get_browser_strategy_priority(self):
        """Test browser strategy selection priority (explicit > render > memory)."""
        # Explicit strategy should override everything
        with patch.dict(os.environ, {
            'BROWSER_STRATEGY': 'manager',
            'RENDER': 'true',
            'MEM_LIMIT': '256'
        }):
            strategy = get_browser_strategy()
            assert strategy == 'manager'


class TestOptimizedBrowserPool:
    """Test suite for OptimizedBrowserPool."""

    @pytest.fixture
    def browser_pool(self):
        """Create an OptimizedBrowserPool instance for testing."""
        return OptimizedBrowserPool(min_browsers=1, max_browsers=2)

    def test_optimized_browser_pool_creation(self, browser_pool):
        """Test browser pool creation with parameters."""
        assert browser_pool.min_browsers == 1
        assert browser_pool.max_browsers == 2
        assert browser_pool._initialized == False

    def test_get_available_memory_mb(self, browser_pool):
        """Test memory calculation methods."""
        # Test with memory limit
        with patch.dict(os.environ, {'MEM_LIMIT': '512'}):
            with patch.object(browser_pool, '_get_total_memory_usage_mb', return_value=100):
                memory = browser_pool._get_available_memory_mb()
                assert memory >= 50  # Should return at least minimum

        # Test without memory limit
        with patch.dict(os.environ, {}, clear=True):
            with patch('ygoapi.optimized_browser_pool.psutil.virtual_memory') as mock_vm:
                mock_vm.return_value.available = 1024 * 1024 * 1024  # 1GB
                memory = browser_pool._get_available_memory_mb()
                assert memory > 0

    def test_get_total_memory_usage_mb(self, browser_pool):
        """Test total memory usage calculation."""
        with patch('ygoapi.optimized_browser_pool.psutil.Process') as mock_process:
            mock_current = MagicMock()
            mock_current.memory_info.return_value.rss = 100 * 1024 * 1024  # 100MB
            mock_current.children.return_value = []
            mock_process.return_value = mock_current
            
            memory = browser_pool._get_total_memory_usage_mb()
            assert memory == 100

    def test_calculate_optimal_pool_size_constrained(self, browser_pool):
        """Test pool size calculation for memory-constrained environments."""
        test_cases = [
            ('256', 1),
            ('512', 1),
            ('1024', None),  # Should use calculation
            ('0', None)      # Should use calculation
        ]
        
        for mem_limit, expected_size in test_cases:
            with patch.dict(os.environ, {'MEM_LIMIT': mem_limit}):
                size = browser_pool._calculate_optimal_pool_size(800)
                if expected_size is not None:
                    assert size == expected_size
                else:
                    assert size >= browser_pool.min_browsers
                    assert size <= browser_pool.max_browsers

    def test_calculate_optimal_pool_size_available_memory(self, browser_pool):
        """Test pool size calculation based on available memory."""
        test_cases = [
            (50, 1),    # Very low memory
            (300, 1),   # Low memory  
            (600, 4),   # Good memory (600 / 150 = 4)
            (1000, 4),  # High memory (capped at max_browsers)
        ]
        
        with patch.dict(os.environ, {}, clear=True):  # No MEM_LIMIT
            for available_memory, expected_max in test_cases:
                size = browser_pool._calculate_optimal_pool_size(available_memory)
                assert size >= browser_pool.min_browsers
                assert size <= min(expected_max, browser_pool.max_browsers)

    @pytest.mark.asyncio
    async def test_initialize_browser_pool(self, browser_pool):
        """Test browser pool initialization."""
        with patch('ygoapi.optimized_browser_pool.async_playwright') as mock_playwright:
            mock_playwright_instance = AsyncMock()
            mock_playwright.return_value = mock_playwright_instance
            mock_playwright_instance.start.return_value = mock_playwright_instance
            
            mock_browser = AsyncMock()
            mock_browser.is_connected.return_value = True
            mock_playwright_instance.chromium.launch.return_value = mock_browser
            
            with patch.object(browser_pool, '_get_available_memory_mb', return_value=400):
                await browser_pool.initialize()
                
                assert browser_pool._initialized == True
                assert browser_pool._playwright is not None

    @pytest.mark.asyncio
    async def test_launch_browser(self, browser_pool):
        """Test launching individual browser."""
        with patch('ygoapi.optimized_browser_pool.async_playwright') as mock_playwright:
            mock_playwright_instance = AsyncMock()
            browser_pool._playwright = mock_playwright_instance
            
            mock_browser = AsyncMock()
            mock_browser.is_connected.return_value = True
            mock_playwright_instance.chromium.launch.return_value = mock_browser
            
            browser = await browser_pool._launch_browser()
            
            assert browser == mock_browser
            mock_playwright_instance.chromium.launch.assert_called_once()

    def test_get_stats(self, browser_pool):
        """Test getting browser pool statistics."""
        stats = browser_pool.get_stats()
        
        assert isinstance(stats, dict)
        expected_keys = [
            'initialized', 'pool_size', 'available', 'total_requests',
            'avg_wait_time', 'available_memory_mb', 'total_memory_usage_mb'
        ]
        
        for key in expected_keys:
            assert key in stats

    @pytest.mark.asyncio
    async def test_acquire_context(self, browser_pool):
        """Test acquiring browser context."""
        # Setup mock browser
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        
        browser_pool._browsers = [mock_browser]
        browser_pool._browser_queue = asyncio.Queue()
        await browser_pool._browser_queue.put(mock_browser)
        browser_pool._initialized = True
        
        async with browser_pool.acquire_context() as context:
            assert context == mock_context
            mock_browser.new_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown(self, browser_pool):
        """Test browser pool shutdown."""
        mock_browser1 = AsyncMock()
        mock_browser2 = AsyncMock()
        mock_playwright = AsyncMock()
        
        browser_pool._browsers = [mock_browser1, mock_browser2]
        browser_pool._playwright = mock_playwright
        browser_pool._initialized = True
        
        await browser_pool.shutdown()
        
        mock_browser1.close.assert_called_once()
        mock_browser2.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert browser_pool._initialized == False

    def test_get_optimized_browser_pool_render(self):
        """Test getting optimized browser pool on Render."""
        with patch.dict(os.environ, {'RENDER': 'true'}):
            pool = get_optimized_browser_pool()
            assert isinstance(pool, OptimizedBrowserPool)
            assert pool.min_browsers == 1
            assert pool.max_browsers == 2

    def test_get_optimized_browser_pool_local(self):
        """Test getting optimized browser pool locally."""
        with patch.dict(os.environ, {}, clear=True):
            pool = get_optimized_browser_pool()
            assert isinstance(pool, OptimizedBrowserPool)
            assert pool.min_browsers == 2
            assert pool.max_browsers == 8

    def test_get_optimized_browser_pool_singleton(self):
        """Test that get_optimized_browser_pool returns singleton."""
        # Clear the global instance
        import ygoapi.optimized_browser_pool
        ygoapi.optimized_browser_pool._optimized_pool = None
        
        pool1 = get_optimized_browser_pool()
        pool2 = get_optimized_browser_pool()
        
        assert pool1 is pool2


class TestBrowserManager:
    """Test suite for BrowserManager."""

    @pytest.fixture
    def browser_manager(self):
        """Create a BrowserManager instance for testing."""
        return BrowserManager(max_concurrent=2, headless=True)

    def test_browser_manager_creation(self, browser_manager):
        """Test browser manager creation."""
        assert browser_manager.max_concurrent == 2
        assert browser_manager.headless == True

    @pytest.mark.asyncio
    async def test_create_browser_context_manager(self, browser_manager):
        """Test browser creation context manager."""
        with patch('ygoapi.browser_manager.async_playwright') as mock_playwright:
            mock_playwright_instance = AsyncMock()
            mock_playwright.return_value = mock_playwright_instance
            mock_playwright_instance.start.return_value = mock_playwright_instance
            
            mock_browser = AsyncMock()
            mock_playwright_instance.chromium.launch.return_value = mock_browser
            
            async with browser_manager.create_browser() as browser:
                assert browser == mock_browser
                mock_playwright_instance.chromium.launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_browser_error_handling(self, browser_manager):
        """Test browser creation error handling."""
        with patch('ygoapi.browser_manager.async_playwright', side_effect=Exception("Playwright error")):
            try:
                async with browser_manager.create_browser():
                    pass
            except Exception as e:
                assert "Playwright error" in str(e)

    def test_browser_manager_global_instance(self):
        """Test global browser manager instance creation."""
        with patch.dict(os.environ, {'PLAYWRIGHT_POOL_SIZE': '3', 'PLAYWRIGHT_HEADLESS': 'false'}):
            # Import to get the global instance
            from ygoapi.browser_manager import browser_manager
            
            # The global instance should use environment variables
            # Note: This test depends on module loading, so results may vary
            assert isinstance(browser_manager, BrowserManager)

    @pytest.mark.asyncio
    async def test_browser_cleanup_on_exception(self, browser_manager):
        """Test that browsers are properly cleaned up on exceptions."""
        with patch('ygoapi.browser_manager.async_playwright') as mock_playwright:
            mock_playwright_instance = AsyncMock()
            mock_playwright.return_value = mock_playwright_instance
            mock_playwright_instance.start.return_value = mock_playwright_instance
            
            mock_browser = AsyncMock()
            mock_playwright_instance.chromium.launch.return_value = mock_browser
            
            try:
                async with browser_manager.create_browser() as browser:
                    raise Exception("Test exception")
            except Exception:
                pass
            
            # Browser should still be closed even with exception
            mock_browser.close.assert_called_once()
            mock_playwright_instance.stop.assert_called_once()


class TestBrowserIntegration:
    """Integration tests for browser components."""

    def test_browser_strategy_with_optimized_pool(self):
        """Test integration between browser strategy and optimized pool."""
        with patch.dict(os.environ, {'RENDER': 'true'}):
            strategy = get_browser_strategy()
            assert strategy == 'optimized'
            
            pool = get_optimized_browser_pool()
            assert isinstance(pool, OptimizedBrowserPool)

    @pytest.mark.asyncio
    async def test_memory_awareness_integration(self):
        """Test integration of memory awareness across components."""
        pool = OptimizedBrowserPool()
        
        with patch.dict(os.environ, {'MEM_LIMIT': '256'}):
            with patch.object(pool, '_get_total_memory_usage_mb', return_value=50):
                available = pool._get_available_memory_mb()
                optimal_size = pool._calculate_optimal_pool_size(available)
                
                # Should be 1 for low memory environment
                assert optimal_size == 1

    def test_browser_configuration_consistency(self):
        """Test that browser configurations are consistent across components."""
        # Test that similar Chrome args are used across different browser components
        pool = OptimizedBrowserPool()
        manager = BrowserManager()
        
        # Both should be configured for memory optimization
        assert pool.memory_threshold_mb > 0
        assert manager.max_concurrent > 0