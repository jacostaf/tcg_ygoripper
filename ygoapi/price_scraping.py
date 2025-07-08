"""
Price Scraping Module

Handles price data collection from TCGPlayer with caching and validation.
This module provides synchronous price scraping functionality with memory optimization.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, UTC
from typing import Dict, List, Optional, Any, Tuple
from playwright.async_api import async_playwright
from urllib.parse import quote
import requests

from .config import (
    PRICE_CACHE_EXPIRY_DAYS,
    PRICE_SCRAPING_TIMEOUT_SECONDS,
    PRICE_SCRAPING_MAX_RETRIES,
    PRICE_SCRAPING_RETRY_DELAY,
    TCGPLAYER_BASE_URL,
    TCGPLAYER_SEARCH_PATH,
    TCGPLAYER_MAX_PREFERRED_RESULTS,
    TCGPLAYER_MAX_ACCEPTABLE_RESULTS,
    TCGPLAYER_DEFAULT_VARIANT_LIMIT,
    TCGPLAYER_EARLY_TERMINATION_SCORE,
    TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION
)
from .database import get_price_cache_collection, get_card_variants_collection
from .models import CardPriceModel, PriceScrapingRequest, PriceScrapingResponse
from .utils import (
    normalize_rarity,
    normalize_rarity_for_matching,
    normalize_art_variant,
    clean_card_data,
    is_cache_fresh,
    get_current_utc_datetime,
    extract_art_version,
    extract_set_code,
    map_rarity_to_tcgplayer_filter,
    extract_booster_set_name,
    map_set_code_to_tcgplayer_name
)
from .memory_manager import monitor_memory, get_memory_manager

logger = logging.getLogger(__name__)

class PriceScrapingService:
    """Service for managing price scraping operations."""
    
    def __init__(self):
        self.memory_manager = get_memory_manager()
        self.cache_collection = None
        self.variants_collection = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Ensure collections are initialized before use."""
        if not self._initialized:
            self._initialize_collections()
            self._initialized = True
    
    def _initialize_collections(self):
        """Initialize MongoDB collections for price scraping."""
        try:
            self.cache_collection = get_price_cache_collection()
            self.variants_collection = get_card_variants_collection()
            
            # Check if database is disabled
            if self.cache_collection is None or self.variants_collection is None:
                logger.info("Database connections disabled, price scraping will run in offline mode")
                return
            
            # Create indexes for better query performance
            self.cache_collection.create_index("card_number", background=True)
            self.cache_collection.create_index("card_name", background=True)
            self.cache_collection.create_index("card_rarity", background=True)
            self.cache_collection.create_index("last_price_updt", background=True)
            
            logger.info("Successfully initialized price scraping collections")
            
        except Exception as e:
            logger.error(f"Failed to initialize price scraping collections: {e}")
            self.cache_collection = None
            self.variants_collection = None
    
    @monitor_memory
    def find_cached_price_data(
        self,
        card_number: str,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find cached price data for a card.
        
        Args:
            card_number: Card number
            card_name: Card name
            card_rarity: Card rarity
            art_variant: Art variant (optional)
            
        Returns:
            Optional[Dict]: Cached price data if found and fresh
        """
        try:
            self._ensure_initialized()
            
            # Check if database is disabled
            if self.cache_collection is None:
                logger.debug("Database disabled, skipping cache lookup")
                return None
            
            # Build query
            query = {
                "card_number": card_number,
                "card_name": card_name,
                "card_rarity": card_rarity
            }
            
            # Add art variant to query if provided
            if art_variant is not None:
                query["art_variant"] = art_variant
            
            logger.debug(f"Cache query: {query}")
            
            # Find document
            document = self.cache_collection.find_one(query)
            
            if document:
                # Check if cache is fresh
                last_updated = document.get('last_price_updt')
                if last_updated and is_cache_fresh(last_updated, PRICE_CACHE_EXPIRY_DAYS):
                    logger.info(f"Found fresh cached price data for {card_number} (updated: {last_updated})")
                    return document
                else:
                    logger.info(f"Found stale cached price data for {card_number} (updated: {last_updated})")
                    logger.info(f"Cache expiry: {PRICE_CACHE_EXPIRY_DAYS} days")
            else:
                logger.info(f"No cached price data found for {card_number}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding cached price data for {card_number}: {e}")
            return None
    
    @monitor_memory
    def validate_card_rarity(self, card_number: str, card_rarity: str) -> bool:
        """
        Validate that a card rarity exists for a given card number.
        
        Args:
            card_number: Card number to validate
            card_rarity: Card rarity to validate
            
        Returns:
            bool: True if rarity is valid for the card
        """
        try:
            self._ensure_initialized()
            
            # Check if database is disabled
            if self.variants_collection is None:
                logger.info("Database disabled, skipping rarity validation")
                return True  # Allow validation to pass when database is disabled
            
            # Get normalized rarity variants
            rarity_variants = normalize_rarity_for_matching(card_rarity)
            
            # Search for any matching variant
            for variant in rarity_variants:
                query = {
                    "set_code": {"$regex": card_number, "$options": "i"},
                    "set_rarity": {"$regex": variant, "$options": "i"}
                }
                
                if self.variants_collection.find_one(query):
                    logger.info(f"Found matching rarity '{variant}' for card {card_number}")
                    return True
            
            logger.warning(f"No matching rarity found for card {card_number} with rarity {card_rarity}")
            return False
            
        except Exception as e:
            logger.error(f"Error validating card rarity: {e}")
            return False
    
    @monitor_memory
    def save_price_data(self, price_data: Dict[str, Any], requested_art_variant: Optional[str] = None) -> bool:
        """
        Save price data to cache.
        
        Args:
            price_data: Price data to save
            requested_art_variant: Art variant that was requested
            
        Returns:
            bool: True if saved successfully
        """
        try:
            self._ensure_initialized()
            
            # Check if database is disabled
            if self.cache_collection is None:
                logger.info("Database disabled, skipping price data save")
                return True  # Return True to indicate success even when disabled
            
            # Prepare document for insertion
            document = {
                "card_number": price_data.get("card_number"),
                "card_name": price_data.get("card_name"),
                "card_rarity": price_data.get("card_rarity"),
                "art_variant": requested_art_variant,
                "tcgplayer_price": price_data.get("tcgplayer_price"),
                "tcgplayer_market_price": price_data.get("tcgplayer_market_price"),
                "tcgplayer_url": price_data.get("tcgplayer_url"),
                "tcgplayer_product_id": price_data.get("tcgplayer_product_id"),
                "tcgplayer_variant_selected": price_data.get("tcgplayer_variant_selected"),
                "last_price_updt": get_current_utc_datetime(),
                "created_at": get_current_utc_datetime(),
                "source": "tcgplayer"
            }
            
            # Use upsert to replace existing document
            query = {
                "card_number": document["card_number"],
                "card_name": document["card_name"],
                "card_rarity": document["card_rarity"],
                "art_variant": document["art_variant"]
            }
            
            result = self.cache_collection.replace_one(
                query,
                document,
                upsert=True
            )
            
            if result.upserted_id or result.modified_count > 0:
                logger.info(f"Successfully saved price data for {document['card_number']}")
                return True
            else:
                logger.warning(f"No changes made when saving price data for {document['card_number']}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving price data: {e}")
            return False
    
    @monitor_memory
    def lookup_card_info_from_cache(self, card_number: str) -> Optional[Dict[str, Any]]:
        """
        Look up card information from cached variants.
        
        Args:
            card_number: Card number to look up
            
        Returns:
            Optional[Dict]: Card information if found
        """
        try:
            self._ensure_initialized()
            
            # Check if database is disabled
            if self.variants_collection is None:
                logger.info("Database disabled, skipping card info lookup")
                return None
            
            # Try to find by set code matching
            query = {"set_code": {"$regex": card_number, "$options": "i"}}
            result = self.variants_collection.find_one(query, {"_id": 0})
            
            if result:
                return result
            
            # Try broader search by card name
            query = {"card_name": {"$regex": card_number, "$options": "i"}}
            result = self.variants_collection.find_one(query, {"_id": 0})
            
            return result
            
        except Exception as e:
            logger.error(f"Error looking up card info: {e}")
            return None
    
    @monitor_memory
    def lookup_card_name_from_cache(self, card_number: str) -> Optional[str]:
        """
        Look up card name from cached variants.
        
        Args:
            card_number: Card number to look up
            
        Returns:
            Optional[str]: Card name if found
        """
        card_info = self.lookup_card_info_from_cache(card_number)
        if card_info:
            return card_info.get('card_name')
        return None
    
    @monitor_memory
    def lookup_card_name_from_ygo_api(self, card_number: str) -> Optional[str]:
        """
        Look up card name from YGO API as fallback.
        
        Args:
            card_number: Card number to look up
            
        Returns:
            Optional[str]: Card name if found
        """
        try:
            # Try different API endpoints
            endpoints = [
                f"https://db.ygoprodeck.com/api/v7/cardinfo.php?num={card_number}",
                f"https://db.ygoprodeck.com/api/v7/cardinfo.php?name={card_number}"
            ]
            
            for endpoint in endpoints:
                try:
                    response = requests.get(endpoint, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        cards = data.get('data', [])
                        if cards:
                            return cards[0].get('name')
                except Exception:
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error looking up card name from API: {e}")
            return None
    
    @monitor_memory
    def lookup_card_name(self, card_number: str) -> Optional[str]:
        """
        Look up card name from cache first, then API.
        
        Args:
            card_number: Card number to look up
            
        Returns:
            Optional[str]: Card name if found
        """
        # Try cache first
        card_name = self.lookup_card_name_from_cache(card_number)
        if card_name:
            return card_name
        
        # Fallback to API
        return self.lookup_card_name_from_ygo_api(card_number)
    
    @monitor_memory
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get price cache statistics.
        
        Returns:
            Dict: Cache statistics
        """
        try:
            self._ensure_initialized()
            
            # Check if database is disabled
            if self.cache_collection is None:
                logger.info("Database disabled, returning empty cache stats")
                return {
                    "total_entries": 0,
                    "fresh_entries": 0,
                    "stale_entries": 0,
                    "unique_cards": 0,
                    "cache_hit_rate": 0.0,
                    "database_status": "disabled"
                }
            
            total_entries = self.cache_collection.count_documents({})
            
            # Count fresh vs stale entries
            fresh_cutoff = get_current_utc_datetime() - timedelta(days=PRICE_CACHE_EXPIRY_DAYS)
            fresh_entries = self.cache_collection.count_documents({
                "last_price_updt": {"$gte": fresh_cutoff}
            })
            stale_entries = total_entries - fresh_entries
            
            # Get unique cards count
            unique_cards = len(self.cache_collection.distinct("card_number"))
            
            return {
                "total_entries": total_entries,
                "fresh_entries": fresh_entries,
                "stale_entries": stale_entries,
                "unique_cards": unique_cards,
                "cache_expiry_days": PRICE_CACHE_EXPIRY_DAYS
            }
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}
    
    @monitor_memory
    async def scrape_price_from_tcgplayer_basic(
        self,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None,
        card_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Price scraping from TCGPlayer using Playwright.
        
        Args:
            card_name: Card name to search for
            card_rarity: Card rarity
            art_variant: Art variant (optional)
            
        Returns:
            Dict: Scraped price data
        """
        try:
            logger.info(f"Scraping price for {card_name} ({card_rarity})")
            
            # Extract art version from card name if not provided
            if not art_variant and card_name:
                art_variant = extract_art_version(card_name)
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                # Build search URL for TCGPlayer  
                search_card_name = card_name
                
                # Include art variant in search if provided
                if art_variant:
                    # Try to build a more specific search query with art variant
                    art_search_terms = []
                    
                    # Handle numbered art variants (like "8", "7", "1st", etc.)
                    if art_variant.isdigit():
                        art_search_terms = [
                            f"{card_name} {art_variant}th art",
                            f"{card_name} {art_variant}th",
                            f"{card_name} {art_variant}",
                        ]
                    elif art_variant.lower() in ["arkana", "kaiba", "joey wheeler", "pharaoh"]:
                        # Handle named art variants
                        art_search_terms = [
                            f"{card_name} {art_variant}",
                            f"{card_name}-{art_variant}",
                        ]
                    else:
                        # Generic handling for other art variants
                        art_search_terms = [
                            f"{card_name} {art_variant}",
                            f"{card_name} {art_variant} art",
                        ]
                    
                    # Use the first art variant search term as our primary search
                    if art_search_terms:
                        search_card_name = art_search_terms[0]
                        logger.info(f"Searching with art variant: '{search_card_name}' (original: '{card_name}', art: '{art_variant}')")
                
                search_url = f"https://www.tcgplayer.com/search/yugioh/product?Language=English&productLineName=yugioh&q={quote(search_card_name)}&view=grid"
                
                # Add rarity filter if available
                if card_rarity:
                    tcgplayer_rarity_filter = map_rarity_to_tcgplayer_filter(card_rarity)
                    if tcgplayer_rarity_filter:
                        search_url += f"&Rarity={quote(tcgplayer_rarity_filter)}"
                
                logger.info(f"Searching TCGPlayer: {search_url}")
                
                await page.goto(search_url, wait_until='networkidle', timeout=60000)
                
                # Check if we got results
                results_count = await page.evaluate("""
                    () => {
                        const resultText = document.querySelector('h1')?.textContent || '';
                        const match = resultText.match(/(\\d+)\\s+results?\\s+for/);
                        return match ? parseInt(match[1]) : 0;
                    }
                """)
                
                if results_count == 0:
                    logger.warning(f"No results found for {card_name}")
                    await browser.close()
                    return {
                        "tcgplayer_price": None,
                        "tcgplayer_market_price": None,
                        "tcgplayer_url": None,
                        "tcgplayer_product_id": None,
                        "tcgplayer_variant_selected": None,
                        "error": "No results found on TCGPlayer"
                    }
                
                # Check if we landed directly on a product page or on search results
                is_product_page = await page.evaluate("() => document.querySelector('.product-details, .product-title, h1[data-testid=\"product-name\"]') !== null")
                
                if not is_product_page:
                    # We're on search results, select best variant
                    best_variant_url = await self.select_best_tcgplayer_variant(
                        page, card_number, card_name, card_rarity, art_variant
                    )
                    
                    if best_variant_url:
                        logger.info(f"Selected best variant: {best_variant_url}")
                        await page.goto(best_variant_url, wait_until='networkidle', timeout=60000)
                    else:
                        logger.warning(f"No suitable variant found for {card_name}")
                        await browser.close()
                        return {
                            "tcgplayer_price": None,
                            "tcgplayer_market_price": None,
                            "tcgplayer_url": None,
                            "tcgplayer_product_id": None,
                            "tcgplayer_variant_selected": None,
                            "error": "No suitable variant found"
                        }
                
                # Extract prices from the product page
                price_data = await self.extract_prices_from_tcgplayer_dom(page)
                
                # Get final URL
                final_url = page.url
                
                await browser.close()
                
                return {
                    "tcgplayer_price": price_data.get('tcg_price'),
                    "tcgplayer_market_price": price_data.get('tcg_market_price'),
                    "tcgplayer_url": final_url,
                    "tcgplayer_product_id": None,  # Could be extracted from URL if needed
                    "tcgplayer_variant_selected": None
                }
                
        except Exception as e:
            logger.error(f"Error scraping price from TCGPlayer: {e}")
            return {
                "tcgplayer_price": None,
                "tcgplayer_market_price": None,
                "tcgplayer_url": None,
                "tcgplayer_product_id": None,
                "tcgplayer_variant_selected": None,
                "error": str(e)
            }
    
    @monitor_memory
    def scrape_card_price(
        self,
        card_number: str,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Scrape price for a card with caching.
        
        Args:
            card_number: Card number
            card_name: Card name
            card_rarity: Card rarity
            art_variant: Art variant (optional)
            force_refresh: Force refresh from source
            
        Returns:
            Dict: Price scraping response
        """
        try:
            # Check cache first unless force refresh
            if not force_refresh:
                logger.info(f"Checking cache for card: {card_number}, name: {card_name}, rarity: {card_rarity}, art: {art_variant}")
                cached_data = self.find_cached_price_data(
                    card_number, card_name, card_rarity, art_variant
                )
                if cached_data:
                    logger.info(f"✓ Using cached price data for {card_number} - cache hit!")
                    cleaned_data = clean_card_data(cached_data)
                    return {
                        "success": True,
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        "art_variant": art_variant,
                        "cached": True,
                        "last_updated": cached_data.get('last_price_updt'),
                        **cleaned_data
                    }
                else:
                    logger.info(f"No cached data found for {card_number} - will scrape fresh data")
            else:
                logger.info(f"Force refresh requested for {card_number} - skipping cache")
            
            # Scrape from source
            logger.info(f"Scraping fresh price data from TCGPlayer for {card_name} ({card_rarity})")
            try:
                # Use asyncio to run the async scraping function
                price_data = asyncio.run(
                    self.scrape_price_from_tcgplayer_basic(card_name, card_rarity, art_variant, card_number)
                )
                
                # Save to cache if successful
                if price_data and not price_data.get('error'):
                    logger.info(f"✓ Successfully scraped price for {card_number} - saving to cache")
                    full_price_data = {
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        **price_data
                    }
                    self.save_price_data(full_price_data, art_variant)
                else:
                    logger.warning(f"Price scraping failed for {card_number}: {price_data.get('error', 'Unknown error')}")
                
                return {
                    "success": not bool(price_data.get('error')),
                    "card_number": card_number,
                    "card_name": card_name,
                    "card_rarity": card_rarity,
                    "art_variant": art_variant,
                    "cached": False,
                    "last_updated": get_current_utc_datetime(),
                    **price_data
                }
                
            except Exception as e:
                logger.error(f"Error scraping price for {card_number}: {e}")
                return {
                    "success": False,
                    "card_number": card_number,
                    "card_name": card_name,
                    "card_rarity": card_rarity,
                    "art_variant": art_variant,
                    "cached": False,
                    "error": str(e)
                }
                
        except Exception as e:
            logger.error(f"Error in scrape_card_price: {e}")
            return {
                "success": False,
                "card_number": card_number,
                "card_name": card_name,
                "card_rarity": card_rarity,
                "art_variant": art_variant,
                "error": str(e)
            }
    
    @monitor_memory
    async def select_best_tcgplayer_variant(
        self,
        page, 
        card_number: Optional[str], 
        card_name: Optional[str], 
        card_rarity: Optional[str], 
        target_art_version: Optional[str],
        max_variants_to_process: int = None
    ) -> Optional[str]:
        """Select best card variant from TCGPlayer search results with comprehensive art variant scoring."""
        if max_variants_to_process is None:
            max_variants_to_process = TCGPLAYER_DEFAULT_VARIANT_LIMIT
        
        try:
            logger.info("="*80)
            logger.info("STARTING TCGPLAYER VARIANT SELECTION")
            logger.info(f"Target Card Number: {card_number}")
            logger.info(f"Target Rarity: {card_rarity}")
            logger.info(f"Target Art Version: {target_art_version}")
            logger.info("="*80)
            
            # Extract product links from TCGPlayer search results
            variants = await page.evaluate("""
                (maxVariants) => {
                    const variants = [];
                    const productLinks = Array.from(document.querySelectorAll('a[href*="/product/"]'));
                    
                    const linksToProcess = productLinks.slice(0, maxVariants);
                    
                    linksToProcess.forEach(link => {
                        const href = link.getAttribute('href');
                        
                        // Extract product information
                        let cardName = '';
                        let setName = '';
                        let rarity = '';
                        let cardNumber = '';
                        
                        // Get title from the link text
                        const title = link.textContent ? link.textContent.trim() : '';
                        
                        // Extract from structured elements
                        const heading = link.querySelector('h4');
                        if (heading) {
                            setName = heading.textContent ? heading.textContent.trim() : '';
                        }
                        
                        const generics = link.querySelectorAll('generic');
                        generics.forEach(generic => {
                            const text = generic.textContent ? generic.textContent.trim() : '';
                            
                            if (text.startsWith('#')) {
                                cardNumber = text.replace('#', '').trim();
                            } else if (text.match(/quarter\\s+century\\s+secret\\s+rare/i)) {
                                rarity = 'Quarter Century Secret Rare';
                            } else if (text.match(/platinum\\s+secret\\s+rare/i)) {
                                rarity = 'Platinum Secret Rare';
                            } else if (text.match(/secret\\s+rare/i)) {
                                rarity = 'Secret Rare';
                            } else if (text.match(/ultra\\s+rare/i)) {
                                rarity = 'Ultra Rare';
                            } else if (text.match(/super\\s+rare/i)) {
                                rarity = 'Super Rare';
                            } else if (text.match(/\\bcommon\\b/i)) {
                                rarity = 'Common';
                            } else if (text.match(/\\brare\\b/i) && !text.includes('$')) {
                                rarity = 'Rare';
                            } else if (text.length > 3 && /[a-zA-Z]/.test(text) && 
                                     !text.includes('listings') && !text.includes('$') && 
                                     !text.startsWith('#') && text !== setName) {
                                if (text.length > cardName.length) {
                                    cardName = text;
                                }
                            }
                        });
                        
                        variants.push({
                            url: href.startsWith('http') ? href : 'https://www.tcgplayer.com' + href,
                            title: title,
                            card_name: cardName,
                            set_name: setName,
                            rarity: rarity,
                            card_number: cardNumber
                        });
                    });
                    
                    return variants;
                }
            """, max_variants_to_process)
            
            if not variants:
                logger.warning("No variants found")
                return None
            
            # Score and select best variant with comprehensive scoring
            scored_variants = []
            
            for variant in variants:
                score = 0
                title_lower = variant.get('title', '').lower()
                url_lower = variant.get('url', '').lower()
                
                logger.info(f"\\n--- Evaluating variant: {variant['title'][:100]}...")
                
                # Score by card number match (highest priority)
                if card_number and variant.get('card_number'):
                    if variant['card_number'].lower() == card_number.lower():
                        score += 200
                        logger.info(f"✓ EXACT card number match: {card_number}")
                    elif card_number.lower() in variant['card_number'].lower():
                        score += 100
                        logger.info(f"✓ Partial card number match: {card_number}")
                elif card_number and (card_number.lower() in title_lower or card_number.lower() in url_lower):
                    score += 75
                    logger.info(f"✓ Card number found in title/URL: {card_number}")
                
                # Score by rarity match (high priority)
                if card_rarity and variant.get('rarity'):
                    if variant['rarity'].lower() == card_rarity.lower():
                        score += 100
                        logger.info(f"✓ EXACT rarity match: {card_rarity}")
                    elif card_rarity.lower() in variant['rarity'].lower():
                        score += 50
                        logger.info(f"✓ Partial rarity match: {card_rarity}")
                    else:
                        score -= 50
                        logger.warning(f"✗ Rarity mismatch: {card_rarity} vs {variant['rarity']}")
                
                # Score by name match
                if card_name and variant.get('card_name'):
                    if variant['card_name'].lower() == card_name.lower():
                        score += 100
                        logger.info(f"✓ EXACT name match: {card_name}")
                    elif card_name.lower() in variant['card_name'].lower():
                        score += 50
                        logger.info(f"✓ Partial name match: {card_name}")
                
                # Score for art variant match (CRITICAL for this bug fix)
                if target_art_version:
                    art_version_score = 0
                    target_art = str(target_art_version).strip().lower()
                    
                    # Extract art variant from this variant's title and URL
                    variant_art = extract_art_version(variant['title'])
                    if not variant_art:
                        variant_art = extract_art_version(variant['url'])
                    
                    if variant_art:
                        variant_art_normalized = str(variant_art).strip().lower()
                        # Remove ordinal suffixes for comparison
                        target_art_clean = re.sub(r'(st|nd|rd|th)$', '', target_art)
                        variant_art_clean = re.sub(r'(st|nd|rd|th)$', '', variant_art_normalized)
                        
                        if target_art_clean == variant_art_clean:
                            # Exact art variant match - high score
                            art_version_score = 100
                            logger.info(f"✓ EXACT art variant match: '{target_art_version}' == '{variant_art}'")
                        else:
                            # Art variant mismatch - penalty
                            art_version_score = -50
                            logger.warning(f"✗ Art variant mismatch: '{target_art_version}' != '{variant_art}'")
                    else:
                        # No art variant found in title - check for basic presence in text
                        if target_art in title_lower or target_art in url_lower:
                            art_version_score = 25
                            logger.info(f"⚠ Weak art variant match for '{target_art_version}' found in text")
                        else:
                            # No art variant info available - small penalty
                            art_version_score = -10
                            logger.info(f"⚠ No art variant info found for comparison")
                    
                    score += art_version_score
                
                # Small bonus for detailed titles
                score += min(len(variant['title']) // 20, 5)
                
                scored_variants.append((score, variant))
                logger.info(f"Final Score: {score} | Variant: {variant['title'][:80]}...")
            
            # Sort by score and return the best match
            scored_variants.sort(reverse=True, key=lambda x: x[0])
            
            if scored_variants and scored_variants[0][0] > 0:
                best_variant = scored_variants[0][1]
                best_score = scored_variants[0][0]
                logger.info(f"\\n✓ SELECTED BEST VARIANT (Score: {best_score}): {best_variant['title'][:100]}...")
                logger.info(f"URL: {best_variant['url']}")
                return best_variant['url']
            else:
                logger.warning("No good variant match found, using first variant if available")
                if variants:
                    return variants[0]['url']
                
            return None
            
        except Exception as e:
            logger.error(f"Error selecting TCGPlayer variant: {e}")
            return None
    
    @monitor_memory
    async def extract_prices_from_tcgplayer_dom(self, page) -> Dict[str, Any]:
        """Extract price data from TCGPlayer product page DOM."""
        try:
            prices = await page.evaluate("""
                () => {
                    const extractPrice = (text) => {
                        if (!text) return null;
                        const match = text.match(/\\$([\\d,]+(?:\\.\\d{2})?)/);
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
            
            return prices
            
        except Exception as e:
            logger.error(f"Error extracting prices from TCGPlayer DOM: {e}")
            return {"tcg_price": None, "tcg_market_price": None}

# Global service instance
price_scraping_service = PriceScrapingService()