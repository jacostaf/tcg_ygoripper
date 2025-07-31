"""
Optimized async browser pool with memory-aware scaling.
"""
import asyncio
import os
import psutil
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, BrowserContext
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class OptimizedBrowserPool:
    """
    Memory-aware browser pool that can scale based on available resources.
    """
    
    def __init__(self, min_browsers: int = 1, max_browsers: int = 4, 
                 memory_threshold_mb: int = 100):
        self.min_browsers = min_browsers
        self.max_browsers = max_browsers
        self.memory_threshold_mb = memory_threshold_mb
        
        self._playwright = None
        self._browsers = []
        self._browser_queue = None
        self._semaphore = None
        self._initialized = False
        self._lock = asyncio.Lock()
        
        # Track usage for scaling decisions
        self._request_count = 0
        self._queue_wait_times = []
        
    async def initialize(self):
        """Initialize the pool with dynamic sizing based on memory."""
        if self._initialized:
            return
            
        async with self._lock:
            if self._initialized:
                return
                
            self._playwright = await async_playwright().start()
            
            # Determine optimal pool size based on available memory
            available_memory = self._get_available_memory_mb()
            optimal_size = self._calculate_optimal_pool_size(available_memory)
            
            logger.info(f"Initializing browser pool with {optimal_size} browsers "
                       f"(available memory: {available_memory}MB)")
            
            self._browser_queue = asyncio.Queue(maxsize=optimal_size)
            self._semaphore = asyncio.Semaphore(optimal_size)
            
            # Launch initial browsers
            for i in range(optimal_size):
                browser = await self._launch_browser()
                self._browsers.append(browser)
                await self._browser_queue.put(browser)
                
            self._initialized = True
            
    def _get_available_memory_mb(self) -> int:
        """Get available system memory in MB."""
        try:
            # Check if we're on Render with memory limit
            if os.getenv('RENDER'):
                # Render typically has 512MB total
                # Reserve 250MB for OS/Python/etc
                return 512 - 250
            
            # For other environments, use actual available memory
            vm = psutil.virtual_memory()
            return int(vm.available / 1024 / 1024)
        except:
            # Fallback to conservative estimate
            return 200
            
    def _calculate_optimal_pool_size(self, available_memory_mb: int) -> int:
        """Calculate optimal pool size based on available memory."""
        # Estimate ~100MB per browser
        browser_memory_mb = 100
        
        # Calculate how many browsers we can fit
        max_possible = available_memory_mb // browser_memory_mb
        
        # Apply min/max constraints
        optimal = max(self.min_browsers, min(max_possible, self.max_browsers))
        
        # On very constrained environments, be conservative
        if available_memory_mb < 200:
            optimal = 1
            
        return optimal
        
    async def _launch_browser(self) -> Browser:
        """Launch a browser with optimized settings."""
        return await self._playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',  # Important for Docker
                '--disable-gpu',
                '--no-zygote',
                '--single-process',  # Reduces memory usage
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                # Memory optimization flags
                '--memory-pressure-off',
                '--js-flags=--max-old-space-size=64',  # Further limit JS heap to 64MB
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                # Additional memory optimizations
                '--disable-extensions',
                '--disable-plugins',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--no-first-run',
                '--disable-background-networking',
                '--disable-component-extensions-with-background-pages',
                '--disable-client-side-phishing-detection',
                '--disable-component-update',
                '--disable-domain-reliability',
                # Limit disk cache
                '--disk-cache-size=1',
                '--media-cache-size=1'
            ]
        )
        
    @asynccontextmanager
    async def acquire_context(self, timeout: float = 600.0):
        """Acquire a browser context with timeout."""
        if not self._initialized:
            await self.initialize()
            
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Wait for available browser
            browser = await asyncio.wait_for(
                self._browser_queue.get(), 
                timeout=timeout
            )
            
            wait_time = asyncio.get_event_loop().time() - start_time
            self._queue_wait_times.append(wait_time)
            
            # Create isolated context
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            try:
                yield context
            finally:
                await context.close()
                
        finally:
            # Return browser to pool
            await self._browser_queue.put(browser)
            self._request_count += 1
            
            # Consider scaling if needed
            if self._request_count % 10 == 0:
                await self._consider_scaling()
                
    async def _consider_scaling(self):
        """Consider scaling the pool based on usage patterns."""
        if not self._queue_wait_times:
            return
            
        avg_wait = sum(self._queue_wait_times[-10:]) / min(10, len(self._queue_wait_times))
        
        # If average wait time is high and we have memory, scale up
        if avg_wait > 2.0 and len(self._browsers) < self.max_browsers:
            available_memory = self._get_available_memory_mb()
            if available_memory > self.memory_threshold_mb:
                logger.info(f"Scaling up browser pool due to high wait times ({avg_wait:.1f}s)")
                browser = await self._launch_browser()
                self._browsers.append(browser)
                await self._browser_queue.put(browser)
                
    async def get_stats(self):
        """Get pool statistics."""
        return {
            "initialized": self._initialized,
            "pool_size": len(self._browsers),
            "available": self._browser_queue.qsize() if self._browser_queue else 0,
            "total_requests": self._request_count,
            "avg_wait_time": sum(self._queue_wait_times[-10:]) / min(10, len(self._queue_wait_times)) if self._queue_wait_times else 0,
            "available_memory_mb": self._get_available_memory_mb()
        }
        
    async def shutdown(self):
        """Shutdown the browser pool."""
        if not self._initialized:
            return
            
        logger.info("Shutting down browser pool...")
        
        for browser in self._browsers:
            await browser.close()
            
        if self._playwright:
            await self._playwright.stop()
            
        self._initialized = False
        logger.info("Browser pool shutdown complete")


# Global instance
_optimized_pool = None


def get_optimized_browser_pool() -> OptimizedBrowserPool:
    """Get the global optimized browser pool instance."""
    global _optimized_pool
    if _optimized_pool is None:
        # Configure based on environment
        if os.getenv('RENDER'):
            # Conservative settings for Render
            _optimized_pool = OptimizedBrowserPool(
                min_browsers=1,
                max_browsers=2,
                memory_threshold_mb=50
            )
        else:
            # More aggressive settings for better servers
            _optimized_pool = OptimizedBrowserPool(
                min_browsers=2,
                max_browsers=8,
                memory_threshold_mb=200
            )
    return _optimized_pool
