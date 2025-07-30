"""
Async Browser Pool for Playwright

This module provides a true browser pool that reuses browser instances
across async requests, eliminating startup overhead and improving performance.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)


class AsyncBrowserPool:
    """
    Async browser pool that maintains a fixed number of browser instances
    and provides them to requests on demand.
    """
    
    def __init__(self, pool_size: int = 2, headless: bool = True):
        self.pool_size = pool_size
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browsers: list[Browser] = []
        self._browser_queue: Optional[asyncio.Queue] = None
        self._lock = asyncio.Lock()
        self._initialized = False
        self._closing = False
        
        logger.info(f"AsyncBrowserPool configured with size={pool_size}, headless={headless}")
    
    async def initialize(self):
        """Initialize the browser pool."""
        async with self._lock:
            if self._initialized:
                return
                
            logger.info("Initializing async browser pool...")
            
            # Start playwright
            self._playwright = await async_playwright().start()
            
            # Create browser queue
            self._browser_queue = asyncio.Queue(maxsize=self.pool_size)
            
            # Launch browsers
            for i in range(self.pool_size):
                browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process'
                    ]
                )
                self._browsers.append(browser)
                await self._browser_queue.put(browser)
                logger.info(f"Launched browser {i+1}/{self.pool_size}")
            
            self._initialized = True
            logger.info("Async browser pool initialized successfully")
    
    @asynccontextmanager
    async def acquire_context(self):
        """
        Acquire a browser context from the pool.
        This creates a new context from a pooled browser instance.
        """
        if not self._initialized:
            await self.initialize()
        
        browser = None
        context = None
        
        try:
            # Get a browser from the pool (will wait if none available)
            browser = await self._browser_queue.get()
            logger.debug(f"Acquired browser from pool (queue size: {self._browser_queue.qsize()})")
            
            # Create a new context with stealth settings
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                timezone_id='America/New_York'
            )
            
            yield context
            
        finally:
            # Clean up context
            if context:
                try:
                    await context.close()
                except Exception as e:
                    logger.error(f"Error closing context: {e}")
            
            # Return browser to pool
            if browser and not self._closing:
                await self._browser_queue.put(browser)
                logger.debug(f"Returned browser to pool (queue size: {self._browser_queue.qsize()})")
    
    async def close(self):
        """Close all browsers and cleanup resources."""
        async with self._lock:
            if not self._initialized or self._closing:
                return
            
            self._closing = True
            logger.info("Closing async browser pool...")
            
            # Close all browsers
            for i, browser in enumerate(self._browsers):
                try:
                    await browser.close()
                    logger.info(f"Closed browser {i+1}/{len(self._browsers)}")
                except Exception as e:
                    logger.error(f"Error closing browser {i+1}: {e}")
            
            # Stop playwright
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.error(f"Error stopping playwright: {e}")
            
            self._browsers.clear()
            self._initialized = False
            logger.info("Async browser pool closed")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        if not self._initialized:
            return {
                "initialized": False,
                "pool_size": self.pool_size,
                "available_browsers": 0,
                "active_requests": 0
            }
        
        available = self._browser_queue.qsize() if self._browser_queue else 0
        return {
            "initialized": True,
            "pool_size": self.pool_size,
            "available_browsers": available,
            "active_requests": self.pool_size - available
        }


# Global browser pool instance
_browser_pool: Optional[AsyncBrowserPool] = None


def get_browser_pool() -> AsyncBrowserPool:
    """Get or create the global browser pool instance."""
    global _browser_pool
    
    if _browser_pool is None:
        pool_size = int(os.getenv('PLAYWRIGHT_POOL_SIZE', '2'))
        headless = os.getenv('PLAYWRIGHT_HEADLESS', 'true').lower() == 'true'
        _browser_pool = AsyncBrowserPool(pool_size=pool_size, headless=headless)
        logger.info(f"Created global browser pool with size={pool_size}")
    
    return _browser_pool


async def cleanup_browser_pool():
    """Cleanup the global browser pool."""
    global _browser_pool
    
    if _browser_pool:
        await _browser_pool.close()
        _browser_pool = None
