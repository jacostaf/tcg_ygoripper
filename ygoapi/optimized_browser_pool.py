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
                # Get total memory usage including browser processes
                total_usage = self._get_total_memory_usage_mb()
                memory_limit = int(os.getenv('MEMORY_LIMIT_MB', '512'))
                available = memory_limit - total_usage
                logger.debug(f"Render memory: {total_usage}MB used, {available}MB available of {memory_limit}MB")
                return max(0, available)
            
            # For other environments, use actual available memory
            vm = psutil.virtual_memory()
            return int(vm.available / 1024 / 1024)
        except:
            # Fallback to conservative estimate
            return 200
    
    def _get_total_memory_usage_mb(self) -> int:
        """Get total memory usage including browser subprocesses."""
        try:
            total_mb = 0
            # Get current process memory
            current_process = psutil.Process()
            total_mb += current_process.memory_info().rss / 1024 / 1024
            
            # Get all child processes (browsers)
            for child in current_process.children(recursive=True):
                try:
                    total_mb += child.memory_info().rss / 1024 / 1024
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            return int(total_mb)
        except Exception as e:
            logger.error(f"Error calculating total memory: {e}")
            # Return conservative estimate
            return 300
            
    def _calculate_optimal_pool_size(self, available_memory_mb: int) -> int:
        """Calculate optimal pool size based on available memory."""
        # Estimate ~150MB per browser (more realistic with all processes)
        browser_memory_mb = 150
        
        # Ensure we have positive available memory
        available_memory_mb = max(available_memory_mb, 50)
        
        # Calculate how many browsers we can fit
        max_possible = available_memory_mb // browser_memory_mb
        
        # Apply min/max constraints
        optimal = max(self.min_browsers, min(max_possible, self.max_browsers))
        
        # On very constrained environments, be conservative
        if available_memory_mb < 200:
            optimal = 1
            
        logger.info(f"Calculated optimal pool size: {optimal} (available: {available_memory_mb}MB, per-browser: {browser_memory_mb}MB)")
        return optimal
        
    async def _launch_browser(self) -> Browser:
        """Launch a browser with optimized settings."""
        args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',  # Important for Docker
            '--disable-gpu',
            '--no-zygote',
            # Removed --single-process as it can cause instability
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
        
        logger.info(f"Launching browser with args: {' '.join(args[:5])}...")
        
        browser = await self._playwright.chromium.launch(
            headless=True,
            args=args
        )
        
        # Verify browser is connected
        if not browser.is_connected():
            raise Exception("Browser failed to launch properly")
            
        logger.info("Browser launched successfully")
        return browser
        
    @asynccontextmanager
    async def acquire_context(self, timeout: float = 600.0):
        """Acquire a browser context with timeout."""
        if not self._initialized:
            await self.initialize()
            
        start_time = asyncio.get_event_loop().time()
        browser = None
        context = None
        
        try:
            # Wait for available browser
            browser = await asyncio.wait_for(
                self._browser_queue.get(), 
                timeout=timeout
            )
            
            wait_time = asyncio.get_event_loop().time() - start_time
            self._queue_wait_times.append(wait_time)
            
            # Check if browser is still connected
            if not browser.is_connected():
                logger.error("Browser disconnected, creating new one")
                # Remove dead browser from pool
                if browser in self._browsers:
                    self._browsers.remove(browser)
                # Launch replacement browser
                browser = await self._launch_browser()
                self._browsers.append(browser)
            
            
            # Create isolated context
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            yield context
            
        except Exception as e:
            logger.error(f"Error in acquire_context: {e}")
            raise
        finally:
            # Clean up context
            if context:
                try:
                    await context.close()
                except Exception as e:
                    logger.error(f"Error closing context: {e}")
            
            # Return browser to pool only if valid
            if browser and browser.is_connected():
                await self._browser_queue.put(browser)
            else:
                logger.warning("Browser disconnected, not returning to pool")
                # Launch replacement if needed
                if len(self._browsers) < self.min_browsers:
                    try:
                        new_browser = await self._launch_browser()
                        self._browsers.append(new_browser)
                        await self._browser_queue.put(new_browser)
                    except Exception as e:
                        logger.error(f"Failed to launch replacement browser: {e}")
            
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
            "available_memory_mb": self._get_available_memory_mb(),
            "total_memory_usage_mb": self._get_total_memory_usage_mb(),
            "memory_limit_mb": int(os.getenv('MEMORY_LIMIT_MB', '512')) if os.getenv('RENDER') else None
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
