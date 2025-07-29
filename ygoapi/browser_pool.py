"""
Browser Pool for Playwright

Manages a pool of browser instances to reduce overhead of launching/closing browsers
for each request. This improves performance and reduces resource usage.
"""

import asyncio
import logging
import os
from typing import Optional, List
from playwright.async_api import Browser, async_playwright, Playwright
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class BrowserPool:
    """Simple browser pool that maintains a fixed number of browser instances."""
    
    def __init__(self, pool_size: int = 2, headless: bool = True):
        self.pool_size = pool_size
        self.headless = headless
        self._browsers: List[Optional[Browser]] = []
        self._playwright: Optional[Playwright] = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(pool_size)
        self._browser_usage = {}  # Track usage count per browser
        self._initialized = False
        
    async def initialize(self):
        """Initialize the browser pool."""
        async with self._lock:
            if self._initialized:
                return
                
            logger.info(f"Initializing browser pool with {self.pool_size} browsers")
            self._playwright = await async_playwright().start()
            
            # Pre-create browsers
            for i in range(self.pool_size):
                try:
                    browser = await self._create_browser()
                    self._browsers.append(browser)
                    self._browser_usage[id(browser)] = 0
                    logger.info(f"Created browser {i+1}/{self.pool_size}")
                except Exception as e:
                    logger.error(f"Failed to create browser {i+1}: {e}")
                    self._browsers.append(None)
                    
            self._initialized = True
            logger.info("Browser pool initialized")
    
    async def _create_browser(self) -> Browser:
        """Create a new browser instance."""
        return await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
    
    @asynccontextmanager
    async def acquire_browser(self):
        """Acquire a browser from the pool."""
        if not self._initialized:
            await self.initialize()
            
        async with self._semaphore:  # Limit concurrent usage
            browser = None
            browser_index = -1
            
            async with self._lock:
                # Find an available browser
                for i, b in enumerate(self._browsers):
                    if b and not b.is_connected():
                        # Browser disconnected, recreate it
                        logger.warning(f"Browser {i} disconnected, recreating...")
                        try:
                            self._browsers[i] = await self._create_browser()
                            self._browser_usage[id(self._browsers[i])] = 0
                        except Exception as e:
                            logger.error(f"Failed to recreate browser {i}: {e}")
                            self._browsers[i] = None
                    
                    if self._browsers[i]:
                        browser = self._browsers[i]
                        browser_index = i
                        self._browser_usage[id(browser)] += 1
                        break
                
                if not browser:
                    raise Exception("No available browsers in pool")
            
            logger.info(f"Acquired browser {browser_index} (usage: {self._browser_usage[id(browser)]})")
            
            try:
                yield browser
            finally:
                # Check if browser needs recycling (every 50 uses to prevent memory leaks)
                async with self._lock:
                    if id(browser) in self._browser_usage and self._browser_usage[id(browser)] > 50:
                        logger.info(f"Recycling browser {browser_index} after {self._browser_usage[id(browser)]} uses")
                        try:
                            await browser.close()
                        except:
                            pass
                        
                        try:
                            self._browsers[browser_index] = await self._create_browser()
                            self._browser_usage[id(self._browsers[browser_index])] = 0
                        except Exception as e:
                            logger.error(f"Failed to recycle browser {browser_index}: {e}")
                            self._browsers[browser_index] = None
                
                logger.info(f"Released browser {browser_index}")
    
    async def cleanup(self):
        """Clean up all browser instances."""
        logger.info("Cleaning up browser pool...")
        
        async with self._lock:
            for i, browser in enumerate(self._browsers):
                if browser:
                    try:
                        await browser.close()
                        logger.info(f"Closed browser {i}")
                    except Exception as e:
                        logger.error(f"Error closing browser {i}: {e}")
            
            self._browsers.clear()
            self._browser_usage.clear()
            
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.error(f"Error stopping playwright: {e}")
                self._playwright = None
                
            self._initialized = False
            
        logger.info("Browser pool cleaned up")

# Global browser pool instance
# Get pool size from environment variable, default to 2
PLAYWRIGHT_POOL_SIZE = int(os.environ.get('PLAYWRIGHT_POOL_SIZE', '2'))
PRICE_SCRAPING_MAX_WORKERS = int(os.environ.get('PRICE_SCRAPING_MAX_WORKERS', '2'))
HEADLESS_MODE = os.environ.get('PLAYWRIGHT_HEADLESS', 'true').lower() == 'true'

logger.info(f"Initializing browser pool with size={PLAYWRIGHT_POOL_SIZE}, headless={HEADLESS_MODE}")

# Warn if configuration is mismatched
if PLAYWRIGHT_POOL_SIZE != PRICE_SCRAPING_MAX_WORKERS:
    logger.warning(
        f"⚠️  Configuration mismatch detected! "
        f"PLAYWRIGHT_POOL_SIZE ({PLAYWRIGHT_POOL_SIZE}) != PRICE_SCRAPING_MAX_WORKERS ({PRICE_SCRAPING_MAX_WORKERS}). "
        f"For optimal performance, these should be equal."
    )

browser_pool = BrowserPool(pool_size=PLAYWRIGHT_POOL_SIZE, headless=HEADLESS_MODE)
