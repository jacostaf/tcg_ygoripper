"""
Simple Browser Manager for Playwright
Uses a semaphore to limit concurrent browser instances without complex pooling.
"""

import asyncio
import logging
import os
import threading
from typing import Optional
from playwright.async_api import Browser, async_playwright
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class BrowserManager:
    """Simple browser manager that limits concurrent browser instances."""
    
    def __init__(self, max_concurrent: int = 2, headless: bool = True):
        self.max_concurrent = max_concurrent
        self.headless = headless
        # Use threading.Semaphore for thread safety
        self._semaphore = threading.Semaphore(max_concurrent)
        logger.info(f"Initialized BrowserManager with max_concurrent={max_concurrent}")
    
    @asynccontextmanager
    async def create_browser(self):
        """Create a browser instance within concurrency limits."""
        # Acquire semaphore (thread-safe)
        self._semaphore.acquire()
        browser = None
        playwright = None
        
        try:
            logger.debug("Creating new browser instance")
            
            # Start playwright
            playwright = await async_playwright().start()
            
            # Launch browser with stealth settings
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                '--disable-web-security',
                '--disable-setuid-sandbox',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--window-size=1280,720',
            ]
            
            if self.headless:
                launch_args.extend(['--headless=new'])
            
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=launch_args,
                ignore_default_args=['--enable-automation'],
            )
            
            logger.debug(f"Browser instance created (headless={self.headless})")
            yield browser
            
        finally:
            # Clean up browser
            if browser:
                try:
                    await browser.close()
                    logger.debug("Browser instance closed")
                except Exception as e:
                    logger.error(f"Error closing browser: {e}")
            
            # Stop playwright
            if playwright:
                try:
                    await playwright.stop()
                except Exception as e:
                    logger.error(f"Error stopping playwright: {e}")
            
            # Release semaphore
            self._semaphore.release()
            logger.debug("Browser resources released")

# Global browser manager instance
BROWSER_MAX_CONCURRENT = int(os.environ.get('PLAYWRIGHT_POOL_SIZE', '2'))
HEADLESS_MODE = os.environ.get('PLAYWRIGHT_HEADLESS', 'true').lower() == 'true'

logger.info(f"Creating global browser manager with max_concurrent={BROWSER_MAX_CONCURRENT}, headless={HEADLESS_MODE}")
browser_manager = BrowserManager(max_concurrent=BROWSER_MAX_CONCURRENT, headless=HEADLESS_MODE)
