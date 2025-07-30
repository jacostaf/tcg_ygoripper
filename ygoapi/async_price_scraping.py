"""
Async Price Scraping Service

This module provides async price scraping using the browser pool,
eliminating thread/event loop conflicts and improving performance.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import quote
import aiohttp

from .async_browser_pool import get_browser_pool, AsyncBrowserPool
from .browser_manager import BrowserManager
from .optimized_browser_pool import get_optimized_browser_pool
from .browser_strategy import get_browser_strategy
from .config import (
    PLAYWRIGHT_DEFAULT_TIMEOUT_MS,
    PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
    PLAYWRIGHT_PAGE_TIMEOUT_MS,
    PRICE_CACHE_COLLECTION
)
from .utils import (
    clean_card_data,
    extract_art_version,
    extract_booster_set_name,
    extract_set_code,
    get_current_utc_datetime,
    map_rarity_to_tcgplayer_filter,
    map_set_code_to_tcgplayer_name,
)
from .database import get_database

logger = logging.getLogger(__name__)


class AsyncPriceScrapingService:
    """Async service for scraping card prices from TCGPlayer."""
    
    def __init__(self):
        self.db = get_database()
        
        # Select browser strategy based on environment
        self.browser_strategy = get_browser_strategy()
        if self.browser_strategy == 'pool':
            self.browser_pool = get_browser_pool()
            self.browser_manager = None
            self.optimized_pool = None
        elif self.browser_strategy == 'optimized':
            self.browser_pool = None
            self.browser_manager = None
            self.optimized_pool = get_optimized_browser_pool()
        else:
            self.browser_pool = None
            self.browser_manager = BrowserManager()
            self.optimized_pool = None
        
        self._ygo_api_cache = {}
        self._price_cache_ttl = timedelta(hours=24)
        
        logger.info(f"AsyncPriceScrapingService initialized with {self.browser_strategy} strategy")
    
    async def scrape_card_price(
        self,
        card_number: str,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Main async entry point for price scraping.
        Checks cache first, then scrapes if needed.
        """
        try:
            # Check cache first unless force refresh
            if not force_refresh:
                cached_data = self._find_cached_price_data_with_staleness_info(
                    card_number, card_name, card_rarity, art_variant
                )
                
                if cached_data and not cached_data["is_stale"]:
                    # Validate cached data has actual prices
                    cached_prices = cached_data["data"].get('tcg_price')
                    if cached_prices is not None and cached_data["data"].get('scrape_success', False):
                        logger.info(f"Returning cached price data for {card_number}")
                        # Map MongoDB field names to API field names
                        mapped_data = cached_data["data"].copy()
                        mapped_data['tcgplayer_price'] = mapped_data.pop('tcg_price', None)
                        mapped_data['tcgplayer_market_price'] = mapped_data.pop('tcg_market_price', None)
                        mapped_data['tcgplayer_url'] = mapped_data.pop('source_url', None)
                        
                        cleaned_data = clean_card_data(mapped_data)
                        return {
                            "success": True,
                            "card_number": card_number,
                            "card_name": card_name,
                            "card_rarity": card_rarity,
                            "art_variant": art_variant,
                            "cached": True,
                            "last_updated": cached_data["data"].get('last_price_updt'),
                            **cleaned_data
                        }
                    else:
                        logger.info(f"Cached data for {card_number} has no prices, re-scraping")
            
            # Validate rarity
            is_valid_rarity = await self._validate_rarity_async(card_number, card_rarity)
            if not is_valid_rarity:
                # Check cache as fallback
                cached_data = self._find_cached_price_data_with_staleness_info(
                    card_number, card_name, card_rarity, art_variant
                )
                if cached_data:
                    # Validate cached data has actual prices
                    cached_prices = cached_data["data"].get('tcg_price')
                    if cached_prices is not None and cached_data["data"].get('scrape_success', False):
                        logger.info(f"Using cached data for invalid rarity {card_rarity}")
                        # Map MongoDB field names to API field names
                        mapped_data = cached_data["data"].copy()
                        mapped_data['tcgplayer_price'] = mapped_data.pop('tcg_price', None)
                        mapped_data['tcgplayer_market_price'] = mapped_data.pop('tcg_market_price', None)
                        mapped_data['tcgplayer_url'] = mapped_data.pop('source_url', None)
                        
                        cleaned_data = clean_card_data(mapped_data)
                        return {
                            "success": True,
                            "card_number": card_number,
                            "card_name": card_name,
                            "card_rarity": card_rarity,
                            "art_variant": art_variant,
                            "cached": True,
                            "last_updated": cached_data["data"].get('last_price_updt'),
                            **cleaned_data
                        }
                    else:
                        logger.info(f"Cached data for {card_number} has no valid prices")
                else:
                    return {
                        "success": False,
                        "error": f"Card {card_number} not found with rarity '{card_rarity}'",
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        "art_variant": art_variant
                    }
            
            # Scrape fresh data
            logger.info(f"🌐 Scraping fresh price data from TCGPlayer for {card_name} ({card_rarity})")
            
            # Get card name from YGO API if not provided
            if not card_name:
                card_info = await self._get_card_info_from_ygo_api_async(card_number)
                if card_info:
                    card_name = card_info.get('card_name', '')
            
            # Perform the actual scraping
            price_data = await self.scrape_price_from_tcgplayer(
                card_name, card_rarity, art_variant, card_number
            )
            
            # Prepare full data for saving
            full_price_data = {
                'card_number': card_number,
                'card_name': card_name,
                'card_rarity': card_rarity,
                'set_code': extract_set_code(card_number) if card_number else None,
                'booster_set_name': extract_booster_set_name(price_data.get('tcgplayer_url', '')) if price_data.get('tcgplayer_url') else None,
                'tcg_price': price_data.get('tcgplayer_price'),
                'tcg_market_price': price_data.get('tcgplayer_market_price'),
                'source_url': price_data.get('tcgplayer_url'),
                'scrape_success': not bool(price_data.get('error')),
                'last_price_updt': get_current_utc_datetime()
            }
            
            # Save to database
            await self.save_price_data_async(full_price_data, art_variant)
            
            # Handle null prices by checking cache
            if price_data.get('tcgplayer_price') is None or price_data.get('tcgplayer_market_price') is None:
                logger.info(f"⚠️ Null prices detected after scraping for {card_number} - checking cache")
                cached_data = self._find_cached_price_data_with_staleness_info(
                    card_number, card_name, card_rarity, art_variant
                )
                if cached_data and cached_data["data"].get('tcg_price') is not None:
                    logger.info(f"✓ Found valid prices in cache for {card_number}")
                    # Map MongoDB field names to API field names
                    mapped_data = cached_data["data"].copy()
                    mapped_data['tcgplayer_price'] = mapped_data.pop('tcg_price', None)
                    mapped_data['tcgplayer_market_price'] = mapped_data.pop('tcg_market_price', None)
                    mapped_data['tcgplayer_url'] = mapped_data.pop('source_url', None)
                    
                    cleaned_data = clean_card_data(mapped_data)
                    return {
                        "success": True,
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        "art_variant": art_variant,
                        "cached": True,
                        "last_updated": cached_data["data"].get('last_price_updt'),
                        **cleaned_data
                    }
            
            # Return the scraping result
            # Success requires both no error AND actual prices
            has_prices = price_data.get('tcgplayer_price') is not None or price_data.get('tcgplayer_market_price') is not None
            return {
                "success": not bool(price_data.get('error')) and has_prices,
                "card_number": card_number,
                "card_name": card_name,
                "card_rarity": card_rarity,
                "art_variant": art_variant,
                "cached": False,
                "last_updated": get_current_utc_datetime(),
                **price_data
            }
            
        except Exception as e:
            logger.error(f"❌ Error in async price scraping for {card_number}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "card_number": card_number,
                "card_name": card_name,
                "card_rarity": card_rarity,
                "art_variant": art_variant
            }
    
    async def scrape_price_from_tcgplayer(
        self,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None,
        card_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape price from TCGPlayer using the configured browser strategy.
        """
        try:
            logger.info(f"Scraping price for {card_name} ({card_rarity}) using {self.browser_strategy} strategy")
            
            # Extract art version from card name if not provided
            if not art_variant and card_name:
                art_variant = extract_art_version(card_name)
            
            # Use appropriate browser strategy
            if self.browser_strategy == 'pool':
                # Use browser pool for performance
                async with self.browser_pool.acquire_context() as context:
                    return await self._scrape_with_context(context, card_name, card_rarity, art_variant, card_number)
            elif self.browser_strategy == 'optimized':
                # Use optimized pool with memory awareness
                async with self.optimized_pool.acquire_context() as context:
                    return await self._scrape_with_context(context, card_name, card_rarity, art_variant, card_number)
            else:
                # Use browser manager for memory efficiency
                async with self.browser_manager.acquire_browser() as browser:
                    context = await browser.new_context()
                    try:
                        return await self._scrape_with_context(context, card_name, card_rarity, art_variant, card_number)
                    finally:
                        await context.close()
                        
        except Exception as e:
            logger.error(f"Error in async scraping: {e}")
            return {
                "tcgplayer_price": None,
                "tcgplayer_market_price": None,
                "tcgplayer_url": None,
                "tcgplayer_product_id": None,
                "tcgplayer_variant_selected": None,
                "error": str(e)
            }
    
    async def _scrape_with_context(self, context, card_name: str, card_rarity: str, art_variant: Optional[str], card_number: Optional[str]) -> Dict[str, Any]:
        """Perform the actual scraping with a browser context."""
        try:
                # Configure context timeouts
                context.set_default_timeout(PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
                context.set_default_navigation_timeout(PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
                page = await context.new_page()
                
                # Set page-specific timeouts
                page.set_default_timeout(PLAYWRIGHT_PAGE_TIMEOUT_MS)
                page.set_default_navigation_timeout(PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
                # Build search URL
                search_card_name = card_name
                
                # Include art variant in search if provided
                if art_variant:
                    art_search_terms = []
                    
                    if art_variant.isdigit():
                        art_search_terms = [
                            f"{card_name} {art_variant}th art",
                            f"{card_name} {art_variant}th",
                            f"{card_name} {art_variant}",
                        ]
                    elif art_variant.lower() in ["arkana", "kaiba", "joey wheeler", "pharaoh"]:
                        art_search_terms = [
                            f"{card_name} {art_variant}",
                            f"{card_name}-{art_variant}",
                        ]
                    else:
                        art_search_terms = [
                            f"{card_name} {art_variant}",
                            f"{card_name} {art_variant} art",
                        ]
                    
                    if art_search_terms:
                        search_card_name = art_search_terms[0]
                        logger.info(f"Searching with art variant: '{search_card_name}'")
                
                search_url = f"https://www.tcgplayer.com/search/yugioh/product?Language=English&productLineName=yugioh&q={quote(search_card_name)}&view=grid"
                
                # Add rarity filter
                if card_rarity:
                    tcgplayer_rarity_filter = map_rarity_to_tcgplayer_filter(card_rarity)
                    if tcgplayer_rarity_filter:
                        search_url += f"&Rarity={quote(tcgplayer_rarity_filter)}"
                
                # Add set filtering
                if card_number:
                    set_code = extract_set_code(card_number)
                    if set_code:
                        tcgplayer_set_name = map_set_code_to_tcgplayer_name(set_code)
                        if tcgplayer_set_name:
                            search_url += f"&setName={quote(tcgplayer_set_name)}"
                            logger.info(f"Added set filter: {set_code} -> {tcgplayer_set_name}")
                
                logger.info(f"Searching TCGPlayer: {search_url}")
                
                # Navigate to search page
                await page.goto(search_url, wait_until='networkidle', timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
                # Wait for search results
                results_count = await self._wait_for_search_results(page, card_name)
                
                if results_count == 0:
                    logger.warning(f"No results found for {card_name}")
                    return {
                        "tcgplayer_price": None,
                        "tcgplayer_market_price": None,
                        "tcgplayer_url": None,
                        "tcgplayer_product_id": None,
                        "tcgplayer_variant_selected": None,
                        "error": "No results found on TCGPlayer"
                    }
                
                # Check if on product page or search results
                is_product_page = await page.evaluate("() => document.querySelector('.product-details, .product-title, h1[data-testid=\"product-name\"]') !== null")
                
                if not is_product_page:
                    # On search results page - select appropriate variant
                    selected_link = await self._select_variant_async(
                        page, card_name, card_rarity, card_number, art_variant
                    )
                    
                    if not selected_link:
                        logger.error(f"Could not find matching variant for {card_name}")
                        return {
                            "tcgplayer_price": None,
                            "tcgplayer_market_price": None,
                            "tcgplayer_url": None,
                            "tcgplayer_product_id": None,
                            "tcgplayer_variant_selected": None,
                            "error": "Could not find matching variant on TCGPlayer"
                        }
                    
                    # Navigate to product page
                    logger.info(f"Navigating to product page: {selected_link}")
                    await page.goto(selected_link, wait_until='networkidle', timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
                # Extract prices from product page
                logger.info("Extracting prices from TCGPlayer product page")
                
                # Wait for price data to load
                await self._wait_for_price_data(page)
                
                # Extract prices
                price_data = await self.extract_prices_from_tcgplayer_dom(page)
                
                # Get final URL
                final_url = page.url
                
                result = {
                    "tcgplayer_price": price_data.get('tcg_price'),
                    "tcgplayer_market_price": price_data.get('tcg_market_price'),
                    "tcgplayer_url": final_url,
                    "tcgplayer_product_id": None,
                    "tcgplayer_variant_selected": None
                }
                
                logger.info(f"Returning from async scraping: tcg=${result['tcgplayer_price']}, market=${result['tcgplayer_market_price']}")
                
                return result
                
        except Exception as e:
            logger.error(f"Error in scraping with context: {e}")
            return {
                "tcgplayer_price": None,
                "tcgplayer_market_price": None,
                "tcgplayer_url": None,
                "tcgplayer_product_id": None,
                "tcgplayer_variant_selected": None,
                "error": str(e)
            }
    
    async def _wait_for_search_results(self, page, card_name: str, max_wait_seconds: int = 15) -> int:
        """Wait for search results to load dynamically with polling."""
        try:
            start_time = asyncio.get_event_loop().time()
            check_interval = 0.5  # Check every 500ms
            
            logger.info(f"⏳ Waiting for search results to load for '{card_name}'...")
            
            while True:
                # Check current results count
                results_count = await page.evaluate(r"""
                    () => {
                        // Look for search results count in various possible locations
                        const countElements = document.querySelectorAll('.search-results__count, .search-count, [data-testid="search-count"]');
                        for (const elem of countElements) {
                            const text = elem.textContent || '';
                            const match = text.match(/(\d+)\s+results?\s+for/i);
                            if (match) {
                                return parseInt(match[1], 10);
                            }
                        }
                        
                        // Alternative: check if product listings are present
                        const productCards = document.querySelectorAll('[data-testid="product-tile"], .product-card, .search-result__product');
                        return productCards.length;
                    }
                """)
                
                # Check if results loaded (count > 0) or explicitly no results
                no_results = await page.evaluate("""
                    () => {
                        const noResultsSelectors = [
                            'text=/No results found/',
                            'text=/0 results/',
                            '.no-results',
                            '[data-testid="no-results"]'
                        ];
                        
                        for (const selector of noResultsSelectors) {
                            try {
                                const element = selector.startsWith('text=') 
                                    ? document.evaluate(
                                        `//text()[contains(., '${selector.substring(6, selector.length-1)}')]`,
                                        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                                      ).singleNodeValue
                                    : document.querySelector(selector);
                                if (element) return true;
                            } catch (e) {}
                        }
                        return false;
                    }
                """)
                
                if results_count > 0:
                    logger.info(f"📦 Found {results_count} search results")
                    return results_count
                
                if no_results:
                    logger.info(f"❌ TCGPlayer shows no results for '{card_name}'")
                    return 0
                
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > max_wait_seconds:
                    break
                
                # Wait before next check
                await asyncio.sleep(check_interval)
            
            # Final check for product elements
            final_check = await page.evaluate("""
                () => {
                    const productElements = document.querySelectorAll(
                        'a[href*="/product/"]:not([href*="/seller/"]):not([href*="/condition/"])'
                    );
                    
                    return productElements.length;
                }
            """)
            
            if final_check > 0:
                logger.info(f"📦 Found {final_check} product elements in final check")
                return final_check
            
            logger.warning(f"❌ No results found for '{card_name}' after {max_wait_seconds}s")
            return 0
            
        except Exception as e:
            logger.error(f"Error waiting for search results: {e}")
            return 0
    
    async def _wait_for_price_data(self, page):
        """Wait for price data to load on product page."""
        try:
            # Wait for price section
            await page.wait_for_selector(
                'section.price-points, div.price-guide-container, div[class*="price-point"]',
                timeout=30000
            )
            
            # Additional wait for dynamic content
            await asyncio.sleep(1)
            
            logger.info("✓ Price data loaded")
            
        except Exception as e:
            logger.warning(f"Timeout waiting for price data: {e}")
            # Take screenshot on failure
            try:
                screenshot = await page.screenshot()
                logger.info(f"Screenshot captured: {len(screenshot)} bytes")
            except:
                pass
    
    async def extract_prices_from_tcgplayer_dom(self, page) -> Dict[str, Any]:
        """Extract price data from TCGPlayer product page DOM."""
        try:
            prices = await page.evaluate(r"""
                () => {
                    const extractPrice = (text) => {
                        if (!text) return null;
                        const match = text.match(/\$([\d,]+(?:\.\d{2})?)/);
                        if (match) {
                            const price = parseFloat(match[1].replace(/,/g, ''));
                            return (price >= 0.01 && price <= 10000) ? price : null;
                        }
                        return null;
                    };
                    
                    const result = {
                        tcg_price: null,
                        tcg_market_price: null,
                        debug_info: []
                    };
                    
                    // Look for Market Price in table rows
                    const marketPriceRows = Array.from(document.querySelectorAll('tr')).filter(row => {
                        const text = row.textContent?.toLowerCase() || '';
                        return text.includes('market price') && text.includes('$');
                    });
                    
                    for (const row of marketPriceRows) {
                        const cells = Array.from(row.querySelectorAll('td'));
                        const labelCell = cells.find(cell => 
                            cell.textContent?.toLowerCase().includes('market price'));
                        
                        if (labelCell) {
                            const labelIndex = cells.indexOf(labelCell);
                            for (let i = labelIndex + 1; i < cells.length; i++) {
                                const priceCell = cells[i];
                                const price = extractPrice(priceCell.textContent);
                                if (price !== null) {
                                    result.tcg_market_price = price;
                                    break;
                                }
                            }
                        }
                        
                        if (result.tcg_market_price !== null) break;
                    }
                    
                    // Look for TCG Low/Low Price in table rows
                    const tcgLowRows = Array.from(document.querySelectorAll('tr')).filter(row => {
                        const text = row.textContent?.toLowerCase() || '';
                        return (text.includes('tcg low') || text.includes('low price') || 
                                text.includes('tcg direct low') || 
                                (text.includes('low') && !text.includes('market'))) && text.includes('$');
                    });
                    
                    for (const row of tcgLowRows) {
                        const cells = Array.from(row.querySelectorAll('td'));
                        const labelCell = cells.find(cell => {
                            const text = cell.textContent?.toLowerCase() || '';
                            return text.includes('tcg low') || text.includes('low price') || 
                                   (text.includes('low') && !text.includes('market'));
                        });
                        
                        if (labelCell) {
                            const labelIndex = cells.indexOf(labelCell);
                            for (let i = labelIndex + 1; i < cells.length; i++) {
                                const priceCell = cells[i];
                                const price = extractPrice(priceCell.textContent);
                                if (price !== null) {
                                    result.tcg_price = price;
                                    break;
                                }
                            }
                        }
                        
                        if (result.tcg_price !== null) break;
                    }
                    
                    // Fallback: search all elements for prices
                    if (!result.tcg_market_price || !result.tcg_price) {
                        const allElements = Array.from(document.querySelectorAll('*')).filter(el => {
                            const style = window.getComputedStyle(el);
                            return style.display !== 'none' && style.visibility !== 'hidden' && 
                                   el.offsetHeight > 0 && el.offsetWidth > 0 && el.textContent?.trim();
                        });
                        
                        for (const element of allElements) {
                            const text = element.textContent?.toLowerCase() || '';
                            if (text.includes('market price') && text.includes('$')) {
                                const price = extractPrice(element.textContent);
                                if (price !== null && result.tcg_market_price === null) {
                                    result.tcg_market_price = price;
                                }
                            }
                            
                            if (text.includes('tcg low') && text.includes('$')) {
                                const price = extractPrice(element.textContent);
                                if (price !== null && result.tcg_price === null) {
                                    result.tcg_price = price;
                                }
                            }
                        }
                    }
                    
                    return result;
                }
            """)
            
            logger.info(f"Price extraction result: tcg_price=${prices.get('tcg_price')}, market=${prices.get('tcg_market_price')}")
            
            if prices.get('tcg_price') is None or prices.get('tcg_market_price') is None:
                logger.warning(f"NULL PRICES DETECTED during extraction - debug_info: {prices.get('debug_info', [])}")
            
            return prices
            
        except Exception as e:
            logger.error(f"Error extracting prices from TCGPlayer DOM: {e}")
            return {"tcg_price": None, "tcg_market_price": None}
    
    async def _select_variant_async(
        self, page, card_name: str, card_rarity: str, 
        card_number: Optional[str], art_variant: Optional[str]
    ) -> Optional[str]:
        """Select the appropriate variant from search results."""
        # Simplified variant selection for async version
        try:
            # Get all product links
            product_links = await page.evaluate("""
                () => {
                    const links = [];
                    const linkSelectors = [
                        'a[class*="product-card"]',
                        'div.search-result__product a',
                        'a[href*="/product/"]'
                    ];
                    
                    for (const selector of linkSelectors) {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el.href && el.href.includes('/product/')) {
                                links.push({
                                    url: el.href,
                                    text: el.textContent.trim()
                                });
                            }
                        });
                    }
                    
                    return links;
                }
            """)
            
            if not product_links:
                logger.warning("No product links found")
                return None
            
            # For now, just select the first link
            # TODO: Implement more sophisticated variant matching
            selected = product_links[0]['url']
            logger.info(f"Selected variant: {product_links[0]['text']}")
            
            return selected
            
        except Exception as e:
            logger.error(f"Error selecting variant: {e}")
            return None
    
    async def _validate_rarity_async(self, card_number: str, card_rarity: str) -> bool:
        """Validate if the card exists with the specified rarity."""
        # Simplified validation for async version
        # In production, this would check against YGO API
        return True
    
    async def _get_card_info_from_ygo_api_async(self, card_number: str) -> Optional[Dict[str, Any]]:
        """Get card info from YGO API."""
        # Simplified for async version
        # In production, this would make an async HTTP request
        return None
    
    def _find_cached_price_data_with_staleness_info(
        self, card_number: str, card_name: str, 
        card_rarity: str, art_variant: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Find cached price data and check if it's stale."""
        try:
            collection = self.db[PRICE_CACHE_COLLECTION]
            
            # Build query
            query = {
                'card_number': card_number,
                'card_rarity': card_rarity
            }
            
            if art_variant:
                query['art_variant'] = art_variant
            
            # Find in cache
            cached_data = collection.find_one(query)
            
            if not cached_data:
                return None
            
            # Check staleness with proper timezone handling
            try:
                last_updated = cached_data.get('last_price_updt')
                if isinstance(last_updated, str):
                    last_updated = datetime.strptime(last_updated, "%a, %d %b %Y %H:%M:%S GMT")
                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                elif isinstance(last_updated, datetime):
                    # If it's already a datetime but without timezone, add UTC
                    if last_updated.tzinfo is None:
                        last_updated = last_updated.replace(tzinfo=timezone.utc)
            
                current_time = datetime.now(timezone.utc)
                age = current_time - last_updated
                is_stale = age > self._price_cache_ttl
                
                return {
                    "data": cached_data,
                    "is_stale": is_stale,
                    "age_hours": age.total_seconds() / 3600
                }
            except (TypeError, ValueError) as e:
                # If any datetime operation fails, treat as stale
                logger.warning(f"Datetime handling error for cached data: {e}, treating as stale")
                return None
            
        except Exception as e:
            logger.error(f"Error checking cache: {e}", exc_info=True)
            return None
    
    async def save_price_data_async(self, price_data: Dict[str, Any], art_variant: Optional[str]):
        """Save price data to database asynchronously."""
        try:
            collection = self.db[PRICE_CACHE_COLLECTION]
            
            # Prepare document
            doc = price_data.copy()
            if art_variant:
                doc['art_variant'] = art_variant
            
            # Use asyncio to run in executor for non-blocking save
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: collection.replace_one(
                    {
                        'card_number': doc['card_number'],
                        'card_rarity': doc['card_rarity'],
                        'art_variant': doc.get('art_variant')
                    },
                    doc,
                    upsert=True
                )
            )
            
            logger.info(f"✓ Saved price data for {doc['card_number']} ({doc['card_rarity']})")
            
        except Exception as e:
            logger.error(f"Error saving price data: {e}")


# Global service instance
_async_price_service: Optional[AsyncPriceScrapingService] = None


def get_async_price_service() -> AsyncPriceScrapingService:
    """Get or create the global async price service instance."""
    global _async_price_service
    
    if _async_price_service is None:
        _async_price_service = AsyncPriceScrapingService()
    
    return _async_price_service
