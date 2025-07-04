"""
Price scraping service for YGO API

Handles price scraping from TCGPlayer and other sources.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from urllib.parse import quote

from ..database import get_database_manager
from ..utils import (
    extract_art_version,
    normalize_rarity,
    normalize_art_variant,
    clean_card_data,
    validate_card_rarity
)
from ..memory import get_memory_manager, memory_check_decorator
from ..config import (
    TCGPLAYER_MAX_PREFERRED_RESULTS,
    TCGPLAYER_MAX_ACCEPTABLE_RESULTS,
    TCGPLAYER_DEFAULT_VARIANT_LIMIT,
    TCGPLAYER_EARLY_TERMINATION_SCORE,
    TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION
)

logger = logging.getLogger(__name__)

class PriceScrapingService:
    """Service for scraping card prices from various sources."""
    
    def __init__(self):
        self.db_manager = get_database_manager()
        self.memory_manager = get_memory_manager()
    
    @memory_check_decorator("price_scraping")
    async def scrape_card_price(
        self,
        card_number: Optional[str] = None,
        card_name: Optional[str] = None,
        card_rarity: Optional[str] = None,
        art_variant: Optional[str] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Scrape price data for a card from TCGPlayer.
        
        Args:
            card_number: Card number (e.g., "RA04-EN016")
            card_name: Card name
            card_rarity: Card rarity
            art_variant: Art variant
            force_refresh: Force refresh of cached data
        
        Returns:
            Dictionary containing price data and metadata
        """
        
        # Validate input parameters
        if not card_number and not card_name:
            return {
                "success": False,
                "error": "Either card_number or card_name must be provided",
                "data": None
            }
        
        # Normalize inputs
        normalized_art_variant = normalize_art_variant(art_variant)
        
        # Check cache first (unless force refresh)
        if not force_refresh:
            cache_found, cached_data = self.db_manager.find_cached_price_data(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=normalized_art_variant
            )
            
            if cache_found and cached_data:
                logger.info(f"✅ Returning cached price data for {card_name or card_number}")
                return {
                    "success": True,
                    "data": clean_card_data(cached_data),
                    "source": "cache"
                }
        
        # Scrape fresh data
        try:
            scrape_result = await self._scrape_from_tcgplayer(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=normalized_art_variant
            )
            
            if scrape_result:
                # Save to cache
                save_success = self.db_manager.save_price_data(
                    scrape_result, 
                    requested_art_variant=normalized_art_variant
                )
                
                if save_success:
                    logger.info(f"✅ Successfully scraped and saved price data for {card_name or card_number}")
                    return {
                        "success": True,
                        "data": clean_card_data(scrape_result),
                        "source": "tcgplayer"
                    }
                else:
                    logger.warning(f"⚠️ Scraped data but failed to save to cache")
                    return {
                        "success": True,
                        "data": clean_card_data(scrape_result),
                        "source": "tcgplayer",
                        "warning": "Failed to save to cache"
                    }
            else:
                return {
                    "success": False,
                    "error": "Failed to scrape price data",
                    "data": None
                }
        
        except Exception as e:
            logger.error(f"Error scraping price data: {e}")
            return {
                "success": False,
                "error": f"Scraping error: {str(e)}",
                "data": None
            }
    
    async def _scrape_from_tcgplayer(
        self,
        card_number: Optional[str] = None,
        card_name: Optional[str] = None,
        card_rarity: Optional[str] = None,
        art_variant: Optional[str] = None
    ) -> Optional[Dict]:
        """Scrape price data from TCGPlayer using Playwright."""
        
        try:
            from playwright.async_api import async_playwright
            
            # Extract art version from card name if not provided
            if not art_variant and card_name:
                art_variant = extract_art_version(card_name)
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                try:
                    # Build search URL
                    search_name = card_name if card_name else card_number
                    if not search_name:
                        return None
                    
                    encoded_search = quote(search_name)
                    search_url = f"https://www.tcgplayer.com/search/yugioh/product?q={encoded_search}"
                    
                    logger.info(f"🔍 Searching TCGPlayer for: {search_name}")
                    
                    # Navigate to search page
                    await page.goto(search_url, wait_until="networkidle")
                    
                    # Wait for search results
                    await page.wait_for_selector('.search-result, .no-results, .product-card', timeout=10000)
                    
                    # Extract price data
                    prices = await self._extract_prices_from_page(page)
                    
                    if prices:
                        # Build result object
                        result = {
                            "card_number": card_number,
                            "card_name": card_name,
                            "card_rarity": card_rarity,
                            "card_art_variant": art_variant,
                            "tcg_price": prices.get("tcg_price"),
                            "tcg_market_price": prices.get("tcg_market_price"),
                            "source_url": search_url,
                            "last_price_updt": datetime.now(UTC),
                            "scrape_success": True
                        }
                        
                        logger.info(f"✅ Successfully scraped price data: TCG=${prices.get('tcg_price')}, Market=${prices.get('tcg_market_price')}")
                        return result
                    else:
                        logger.warning(f"⚠️ No price data found on TCGPlayer")
                        return {
                            "card_number": card_number,
                            "card_name": card_name,
                            "card_rarity": card_rarity,
                            "card_art_variant": art_variant,
                            "source_url": search_url,
                            "last_price_updt": datetime.now(UTC),
                            "scrape_success": False,
                            "error_message": "No price data found"
                        }
                
                finally:
                    await browser.close()
        
        except Exception as e:
            logger.error(f"Error scraping TCGPlayer: {e}")
            return None
    
    async def _extract_prices_from_page(self, page) -> Dict[str, Any]:
        """Extract price data from TCGPlayer page."""
        
        try:
            # Wait for price elements to load
            await page.wait_for_selector('.price, .market-price, .tcg-price', timeout=5000)
            
            # Extract prices using JavaScript
            prices = await page.evaluate("""
                () => {
                    const result = {};
                    
                    // Look for various price selectors
                    const priceSelectors = [
                        '.price',
                        '.market-price',
                        '.tcg-price', 
                        '.listing-price',
                        '[data-testid="price"]',
                        '.price-display'
                    ];
                    
                    for (const selector of priceSelectors) {
                        const elements = document.querySelectorAll(selector);
                        if (elements.length > 0) {
                            const priceText = elements[0].textContent.trim();
                            const priceMatch = priceText.match(/\\$([\\d,]+(?:\\.\\d{2})?)/);
                            if (priceMatch) {
                                const price = parseFloat(priceMatch[1].replace(',', ''));
                                if (!result.tcg_price) {
                                    result.tcg_price = price;
                                } else if (!result.tcg_market_price) {
                                    result.tcg_market_price = price;
                                }
                            }
                        }
                    }
                    
                    return result;
                }
            """)
            
            return prices
            
        except Exception as e:
            logger.error(f"Error extracting prices from page: {e}")
            return {}
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the price cache."""
        return self.db_manager.get_price_cache_stats()

# Global service instance
_price_service: Optional[PriceScrapingService] = None

def get_price_service() -> PriceScrapingService:
    """Get the global price scraping service instance."""
    global _price_service
    if _price_service is None:
        _price_service = PriceScrapingService()
    return _price_service