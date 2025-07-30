"""
Price Scraping Module

Handles price data collection from TCGPlayer with caching and validation.
This module provides synchronous price scraping functionality with memory optimization.
"""

import asyncio
import logging
import os
import re
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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
    TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION,
    YGO_API_BASE_URL,
    PLAYWRIGHT_PAGE_TIMEOUT_MS,
    PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
    PLAYWRIGHT_DEFAULT_TIMEOUT_MS
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
from .browser_manager import browser_manager

logger = logging.getLogger(__name__)

class PriceScrapingService:
    """Service for managing price scraping operations with proper concurrency handling."""
    
    def __init__(self):
        self.memory_manager = get_memory_manager()
        self.cache_collection = None
        self.variants_collection = None
        self._initialized = False
        
        # Get max workers from env var, default to 2
        # This should match PLAYWRIGHT_POOL_SIZE for optimal performance
        max_workers = int(os.environ.get('PRICE_SCRAPING_MAX_WORKERS', '2'))
        logger.info(f"Initializing ThreadPoolExecutor with {max_workers} workers")
        self._scraping_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="price_scraper")
        
        self._async_loop_lock = threading.Lock()
        # Register cleanup callback with memory manager
        self.memory_manager.register_cleanup_callback("price_scraper_cleanup", self.cleanup_resources)
    
    def _ensure_initialized(self):
        """Ensure collections are initialized before use."""
        if not self._initialized:
            self._initialize_collections()
            self._initialized = True
            
    def cleanup_resources(self):
        """Force cleanup of all resources."""
        try:
            logger.info("Cleaning up price scraping resources...")
            
            # Shutdown executor
            if hasattr(self, '_scraping_executor') and self._scraping_executor:
                try:
                    self._scraping_executor.shutdown(wait=False)
                except Exception as e:
                    logger.warning(f"Error shutting down executor: {e}")
                finally:
                    self._scraping_executor = None
            
            # Cleanup browser pool
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # No cleanup needed for browser manager - each browser is closed after use
                loop.close()
                logger.info("Browser pool cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up browser pool: {e}")
                    
            # Force garbage collection
            import gc
            gc.collect()
            
            logger.info("Price scraping resources cleaned up")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def _run_async_scraping_in_thread(self, card_name: str, card_rarity: str, art_variant: Optional[str], card_number: Optional[str]) -> Dict[str, Any]:
        """
        Run async scraping in a dedicated thread with proper event loop handling.
        This prevents race conditions when multiple requests come in parallel.
        """
        try:
            logger.info(f"🔄 Starting threaded async scraping for {card_name} ({card_rarity})")
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Add small random delay to stagger concurrent browser launches
                delay = random.uniform(0.1, 0.5)
                time.sleep(delay)
                logger.info(f"Delayed {delay:.2f}s before browser launch for {card_name}")
                
                # Run the async function in this thread's event loop
                result = loop.run_until_complete(
                    self.scrape_price_from_tcgplayer_pooled(card_name, card_rarity, art_variant, card_number)
                )
                
                logger.info(f"✅ Threaded async scraping completed for {card_name}: {result.get('tcgplayer_price', 'No price')} / {result.get('tcgplayer_market_price', 'No market price')}")
                return result
                
            finally:
                # Always close the loop when done
                try:
                    loop.close()
                except Exception as loop_error:
                    logger.warning(f"Error closing event loop: {loop_error}")
                
        except Exception as e:
            logger.error(f"❌ Error in threaded async scraping for {card_name}: {e}", exc_info=True)
            return {
                "tcgplayer_price": None,
                "tcgplayer_market_price": None,
                "tcgplayer_url": None,
                "tcgplayer_product_id": None,
                "tcgplayer_variant_selected": None,
                "error": f"Threading error: {str(e)}"
            }

    def _initialize_collections(self):
        """Initialize MongoDB collections for price scraping."""
        try:
            self.cache_collection = get_price_cache_collection()
            self.variants_collection = get_card_variants_collection()
            
            # Check if database is disabled
            if self.cache_collection is None or self.variants_collection is None:
                logger.info("Database connections disabled, price scraping will run in offline mode")
                return
            
            # Get existing indexes
            existing_indexes = {}
            for idx in self.cache_collection.list_indexes():
                # Convert the index key to a string for easier comparison
                key = tuple(sorted([(k, v) for k, v in idx['key'].items() if k != '_id']))
                existing_indexes[key] = idx['name']
            
            # Define the indexes we want (field name, unique, sparse, etc.)
            desired_indexes = [
                {'fields': [('card_number', 1)], 'name': 'card_number_idx'},
                {'fields': [('card_name', 1)], 'name': 'card_name_idx'},
                {'fields': [('card_rarity', 1)], 'name': 'card_rarity_idx'},
                {'fields': [('last_price_updt', 1)], 'name': 'last_price_updt_idx'},
                {'fields': [('card_number', 1), ('card_rarity', 1)], 'name': 'card_number_rarity_idx'}
            ]
            
            # Create only the indexes that don't already exist
            for idx_spec in desired_indexes:
                # Convert fields to the format used in existing_indexes
                fields = tuple(sorted(idx_spec['fields']))
                
                # Check if an index with these fields already exists
                if fields not in existing_indexes:
                    try:
                        self.cache_collection.create_index(
                            idx_spec['fields'],
                            name=idx_spec['name'],
                            background=True
                        )
                        logger.info(f"Created index {idx_spec['name']} on {idx_spec['fields']}")
                    except Exception as e:
                        logger.warning(f"Could not create index {idx_spec['name']}: {str(e)}")
            
            logger.info("Successfully initialized price scraping collections")
            
        except Exception as e:
            logger.error(f"Failed to initialize price scraping collections: {e}")
            self.cache_collection = None
            self.variants_collection = None
    
    def _normalize_art_variant(self, art_variant: str) -> str:
        """
        Normalize art variant to handle numbered variants flexibly.
        
        Args:
            art_variant: The art variant to normalize
            
        Returns:
            str: Normalized art variant
        """
        if not art_variant:
            return ""
            
        art_variant = art_variant.lower().strip()
        
        # Handle numbered variants (1st, 2nd, 3rd, etc.)
        number_match = re.match(r'^(\d+)(?:st|nd|rd|th)?$', art_variant)
        if number_match:
            return number_match.group(1)  # Return just the number
        
        # Handle word numbers
        number_words = {
            'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
            'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
            'first': '1', 'second': '2', 'third': '3', 'fourth': '4', 'fifth': '5',
            'sixth': '6', 'seventh': '7', 'eighth': '8', 'ninth': '9', 'tenth': '10'
        }
        
        # Check for word numbers at the start of the string
        for word, num in number_words.items():
            if art_variant.startswith(word):
                return num
        
        # Default to lowercase version
        return art_variant

    def _get_art_variant_alternatives(self, art_variant: str) -> List[str]:
        """
        Get alternative forms of an art variant for flexible matching.
        
        Args:
            art_variant: The art variant to get alternatives for
            
        Returns:
            List[str]: List of alternative forms of the art variant
        """
        if not art_variant:
            return []
            
        normalized = self._normalize_art_variant(art_variant)
        alternatives = {normalized}
        
        # Add ordinal forms if it's a number
        if normalized.isdigit():
            num = int(normalized)
            if 1 <= num <= 10:
                ordinals = ['th'] * 10
                ordinals[0] = 'st'  # 1st
                ordinals[1] = 'nd'  # 2nd
                ordinals[2] = 'rd'  # 3rd
                # 4th-10th handled by default 'th'
                
                alternatives.add(f"{num}{ordinals[num-1]}")
                
                # Add word forms for small numbers
                number_words = {
                    1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five',
                    6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten'
                }
                if num in number_words:
                    alternatives.add(number_words[num])
                    alternatives.add(f"{number_words[num]}th")
        
        return list(alternatives)

    @monitor_memory
    def find_cached_price_data(
        self,
        card_number: str,
        card_name: str,  # Kept for backward compatibility but not used in query
        card_rarity: str,
        art_variant: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find cached price data for a card using card number, rarity, and art variant.
        Handles numbered art variants flexibly (e.g., "7", "7th", "seven", "seventh").
        
        Args:
            card_number: Card number (required)
            card_name: Card name (for logging only)
            card_rarity: Card rarity (case-insensitive)
            art_variant: Art variant (optional, handles numbered variants flexibly)
            
        Returns:
            Optional[Dict]: Cached price data if found and fresh
        """
        try:
            self._ensure_initialized()
            
            if self.cache_collection is None:
                logger.debug("Database disabled, skipping cache lookup")
                return None
            
            # Normalize inputs
            normalized_rarity = card_rarity.lower().strip()
            normalized_art_variant = self._normalize_art_variant(art_variant) if art_variant else None
            
            logger.debug(f"Searching cache - Number: {card_number}, Rarity: {normalized_rarity}, "
                        f"Art Variant: {normalized_art_variant or 'None'}")
            
            # Build base query with card number and rarity
            query = {
                "card_number": card_number,
                "card_rarity": {"$regex": f"^{re.escape(normalized_rarity)}$", "$options": "i"}
            }
            
            # Handle art variant if provided
            if normalized_art_variant:
                # Match either the exact variant or any document without an art variant
                query["$or"] = [
                    {"art_variant": {"$exists": False}},
                    {"art_variant": ""},
                    {"art_variant": {"$in": self._get_art_variant_alternatives(normalized_art_variant)}}
                ]
            
            # Find all matching documents
            documents = list(self.cache_collection.find(query))
            
            if not documents:
                logger.info(f"No cached price data found for {card_number} (no matches)")
                return None
                
            # Sort by last_price_updt in descending order to get the most recent
            documents.sort(key=lambda x: x.get('last_price_updt', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            
            # Get the most recent document
            document = documents[0]
            last_updated = document.get('last_price_updt')
            
            if not last_updated:
                logger.info(f"Found cached data for {card_number} but missing last_price_updt")
                return None
                
            if is_cache_fresh(last_updated, PRICE_CACHE_EXPIRY_DAYS):
                logger.info(f"Found fresh cached price data for {card_number} (updated: {last_updated})")
                return document
            else:
                logger.info(f"Found stale cached price data for {card_number} (updated: {last_updated})")
                return None
                
        except Exception as e:
            logger.error(f"Error finding cached price data for {card_number}: {e}")
            return None
    
    @monitor_memory
    def validate_card_rarity(self, card_number: str, card_rarity: str) -> bool:
        """
        Validate that a card rarity exists for a given card number in its specific set.
        
        IMPORTANT: This validates against the ORIGINAL SET DATA, not our cache.
        Our cache may be incomplete - missing some rarities that actually exist.
        
        Args:
            card_number: Card number to validate (e.g., "LOB-001")
            card_rarity: Card rarity to validate (e.g., "Ultra Rare")
            
        Returns:
            bool: True if rarity is valid for the card in that specific set, or if card not in database
        """
        try:
            self._ensure_initialized()
            
            # Check if database is disabled
            if self.variants_collection is None:
                logger.info("Database disabled, allowing scrape to proceed")
                return True  # Allow validation to pass when database is disabled
            
            # Extract set code from card number to validate against original set data
            set_code = extract_set_code(card_number)
            if not set_code:
                logger.info(f"Could not extract set code from {card_number} - allowing scrape to proceed")
                return True
            
            # Try to validate against YGO API set data (original source of truth)
            try:
                api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={quote(set_code)}"
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    api_data = response.json()
                    if 'data' in api_data and api_data['data']:
                        # Find our specific card in the API results
                        for card in api_data['data']:
                            card_sets = card.get('card_sets', [])
                            for card_set in card_sets:
                                if card_set.get('set_code') == card_number:
                                    set_rarity = card_set.get('set_rarity', '')
                                    if normalize_rarity(card_rarity) == normalize_rarity(set_rarity):
                                        logger.info(f"✓ Rarity '{card_rarity}' validated against YGO API for {card_number}")
                                        return True
                                    elif self._are_rarities_equivalent(normalize_rarity(card_rarity), normalize_rarity(set_rarity)):
                                        logger.info(f"✓ Rarity '{card_rarity}' validated as equivalent to '{set_rarity}' for {card_number}")
                                        return True
                
                logger.info(f"Card {card_number} rarity '{card_rarity}' not found in YGO API - checking cache as fallback")
            except Exception as api_error:
                logger.warning(f"YGO API validation failed for {card_number}: {api_error} - falling back to cache")
            
            # Fallback: Check our cache (but acknowledge it may be incomplete)
            # Find ALL entries for this card number (cards can have multiple rarities)
            query = {"set_code": card_number}
            all_card_entries = list(self.variants_collection.find(query))
            
            if not all_card_entries:
                logger.info(f"Card {card_number} not found in cache - allowing scrape to proceed (fallback behavior)")
                # If card is not found in our database, allow the scrape to proceed
                # This handles cases where our database might not be complete
                return True
            
            # Extract all available rarities for this specific card number from cache
            available_rarities = []
            for entry in all_card_entries:
                card_set_rarity = entry.get('set_rarity')
                if card_set_rarity:
                    available_rarities.append(card_set_rarity)
            
            if not available_rarities:
                logger.info(f"No rarities found for card {card_number} in cache - allowing scrape to proceed")
                return True
            
            # Normalize the requested rarity for comparison
            normalized_requested = normalize_rarity(card_rarity)
            
            # Check if the normalized requested rarity matches any available rarity in cache
            for available_rarity in available_rarities:
                normalized_available = normalize_rarity(available_rarity)
                
                # Check for exact match
                if normalized_requested == normalized_available:
                    logger.info(f"✓ Rarity '{card_rarity}' validated for card {card_number} in cache (matches '{available_rarity}')")
                    return True
                
                # Check for special equivalences (e.g., Ultimate Rare vs Prismatic Ultimate Rare)
                if self._are_rarities_equivalent(normalized_requested, normalized_available):
                    logger.info(f"✓ Rarity '{card_rarity}' validated for card {card_number} (equivalent to '{available_rarity}' in cache)")
                    return True
            
            # Cache validation failed - but cache might be incomplete
            # Log warning but allow scrape with caution
            logger.warning(f"⚠ Rarity '{card_rarity}' not found in cache for card {card_number}")
            logger.warning(f"Available rarities in cache: {', '.join(available_rarities)}")
            logger.warning(f"Allowing scrape to proceed - cache may be incomplete")
            
            # CHANGED: Allow scrape to proceed even if not in cache, since cache may be incomplete
            return True
            
        except Exception as e:
            logger.error(f"Error validating card rarity: {e}")
            # On exception, allow scrape to proceed rather than blocking
            logger.info(f"Validation error for {card_number} - allowing scrape to proceed as fallback")
            return True
    
    def _are_rarities_equivalent(self, rarity1: str, rarity2: str) -> bool:
        """
        Check if two rarities are equivalent based on special rules.
        
        Args:
            rarity1: First rarity (normalized)
            rarity2: Second rarity (normalized)
            
        Returns:
            bool: True if rarities are equivalent
        """
        # Normalize inputs to lowercase for comparison
        rarity1 = rarity1.lower().strip()
        rarity2 = rarity2.lower().strip()
        
        # Ultimate Rare and Prismatic Ultimate Rare should be treated the same
        if ((rarity1 == 'ultimate rare' and rarity2 == 'prismatic ultimate rare') or
            (rarity1 == 'prismatic ultimate rare' and rarity2 == 'ultimate rare')):
            return True
        
        # Collector's Rare and Prismatic Collector's Rare should be treated the same
        if ((rarity1 == "collector's rare" and rarity2 == "prismatic collector's rare") or
            (rarity1 == "prismatic collector's rare" and rarity2 == "collector's rare")):
            return True
        
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
        Look up card name from YGO API as fallback using cardsetsinfo endpoint.
        
        Args:
            card_number: Card number to look up
            
        Returns:
            Optional[str]: Card name if found
        """
        try:
            # Use the correct cardsetsinfo endpoint as mentioned in the user's comment
            api_url = f"{YGO_API_BASE_URL}/cardsetsinfo.php?setcode={quote(card_number)}"
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # The response is a single object, not an array
                card_name = data.get('name')
                if card_name:
                    logger.info(f"Found card name '{card_name}' for card number {card_number} via YGO cardsetsinfo API")
                    return card_name.strip()
            
            logger.warning(f"Card {card_number} not found in YGO cardsetsinfo API")
            return None
            
        except Exception as e:
            logger.error(f"Error looking up card name from cardsetsinfo API: {e}")
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
    async def _wait_for_search_results(self, page, card_name: str, max_wait_seconds: int = 15) -> int:
        """
        Wait for TCGPlayer search results to load dynamically.
        
        TCGPlayer uses AJAX to load search results after the initial page load.
        This method implements a polling mechanism to wait for results to appear.
        
        Args:
            page: Playwright page object
            card_name: Card name being searched (for logging)
            max_wait_seconds: Maximum time to wait for results
            
        Returns:
            int: Number of results found (0 if no results after waiting)
        """
        try:
            start_time = asyncio.get_event_loop().time()
            check_interval = 0.5  # Check every 500ms
            
            logger.info(f"⏳ Waiting for search results to load for '{card_name}'...")
            
            while True:
                # Check current results count
                results_count = await page.evaluate("""
                    () => {
                        // Try multiple selectors to find results count
                        const selectors = [
                            'h1', 
                            '[data-testid="results-count"]',
                            '.search-results-header',
                            '.results-header'
                        ];
                        
                        for (const selector of selectors) {
                            const element = document.querySelector(selector);
                            if (element) {
                                const text = element.textContent || '';
                                const match = text.match(/(\\d+)\\s+results?\\s+for/i);
                                if (match) {
                                    return parseInt(match[1]);
                                }
                            }
                        }
                        
                        // Fallback: count visible product links
                        const productLinks = document.querySelectorAll('a[href*="/product/"]');
                        const visibleLinks = Array.from(productLinks).filter(link => {
                            const rect = link.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        });
                        
                        return visibleLinks.length;
                    }
                """)
                
                elapsed_time = asyncio.get_event_loop().time() - start_time
                
                # If we found results, return immediately
                if results_count > 0:
                    logger.info(f"✅ Found {results_count} results after {elapsed_time:.1f}s")
                    return results_count
                
                # If we've exceeded max wait time, give up
                if elapsed_time >= max_wait_seconds:
                    logger.warning(f"⏰ Timeout waiting for results after {elapsed_time:.1f}s")
                    break
                
                # Log progress every few seconds
                if int(elapsed_time) % 3 == 0 and elapsed_time > 0:
                    logger.info(f"⏳ Still waiting for results... ({elapsed_time:.1f}s elapsed)")
                
                # Wait before next check
                await asyncio.sleep(check_interval)
            
            # Final check for any content that might indicate results
            final_check = await page.evaluate("""
                () => {
                    // Check for any product-related content
                    const productElements = document.querySelectorAll([
                        'a[href*="/product/"]',
                        '[class*="product"]',
                        '[data-testid*="product"]'
                    ].join(','));
                    
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
            card_number: Card number (optional, used for set filtering)
            
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
                
                # Configure context timeouts to match our configuration
                context.set_default_timeout(PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
                context.set_default_navigation_timeout(PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
                page = await context.new_page()
                
                # Set page-specific timeouts as well
                page.set_default_timeout(PLAYWRIGHT_PAGE_TIMEOUT_MS)
                page.set_default_navigation_timeout(PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
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
                
                # IMPROVED: Add set filtering when we have a card number to prevent cross-set contamination
                if card_number:
                    set_code = extract_set_code(card_number)
                    if set_code:
                        # Map set code to TCGPlayer set name for filtering
                        tcgplayer_set_name = map_set_code_to_tcgplayer_name(set_code)
                        if tcgplayer_set_name:
                            search_url += f"&setName={quote(tcgplayer_set_name)}"
                            logger.info(f"🎯 Added set filter for {set_code} -> {tcgplayer_set_name}")
                        else:
                            # Try to use the card number itself in the search query for better specificity
                            search_card_name += f" {card_number}"
                            search_url = f"https://www.tcgplayer.com/search/yugioh/product?Language=English&productLineName=yugioh&q={quote(search_card_name)}&view=grid"
                            if card_rarity:
                                tcgplayer_rarity_filter = map_rarity_to_tcgplayer_filter(card_rarity)
                                if tcgplayer_rarity_filter:
                                    search_url += f"&Rarity={quote(tcgplayer_rarity_filter)}"
                            logger.info(f"🎯 Added card number to search query: {search_card_name}")
                
                logger.info(f"Searching TCGPlayer: {search_url}")
                
                # Use configured timeout for navigation
                await page.goto(search_url, wait_until='networkidle', timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                
                # Wait for search results to load with retry mechanism
                results_count = await self._wait_for_search_results(page, card_name)
                
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
                        # Use configured timeout for navigation to variant page
                        await page.goto(best_variant_url, wait_until='networkidle', timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
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
    async def scrape_price_from_tcgplayer_pooled(
        self,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None,
        card_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Price scraping from TCGPlayer using browser pool for efficiency.
        This version reuses browser instances from a pool instead of launching new ones.
        """
        try:
            logger.info(f"Scraping price for {card_name} ({card_rarity}) using browser pool")
            
            # Extract art version from card name if not provided
            if not art_variant and card_name:
                art_variant = extract_art_version(card_name)
            
            # Acquire browser from pool
            async with browser_manager.create_browser() as browser:
                # Create new context for this request
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                )
                
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
                        # Select best variant
                        best_variant_url = await self.select_best_tcgplayer_variant(
                            page, card_number, card_name, card_rarity, art_variant
                        )
                        
                        if best_variant_url:
                            logger.info(f"Selected variant: {best_variant_url}")
                            await page.goto(best_variant_url, wait_until='networkidle', timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)
                        else:
                            logger.warning(f"No suitable variant found")
                            return {
                                "tcgplayer_price": None,
                                "tcgplayer_market_price": None,
                                "tcgplayer_url": None,
                                "tcgplayer_product_id": None,
                                "tcgplayer_variant_selected": None,
                                "error": "No suitable variant found"
                            }
                    
                    # Wait for price data to load - wait for market price elements
                    try:
                        # Wait for any element containing market price text
                        await page.wait_for_function(
                            """() => {
                                const elements = Array.from(document.querySelectorAll('*'));
                                return elements.some(el => {
                                    const text = el.textContent?.toLowerCase() || '';
                                    return (text.includes('market price') || text.includes('tcg low')) && text.includes('$');
                                });
                            }""",
                            timeout=1000000
                        )
                        # Additional wait for dynamic content to fully render
                        await page.wait_for_timeout(2000)
                        logger.info("Price data elements found")
                    except Exception as e:
                        logger.warning(f"Timeout waiting for price elements: {e}")
                        # Take a screenshot for debugging
                        try:
                            screenshot_path = f"/tmp/debug_screenshot_{card_number or card_name}.png"
                            await page.screenshot(path=screenshot_path)
                            logger.info(f"Debug screenshot saved: {screenshot_path}")
                        except:
                            pass
                    
                    # Extract prices
                    price_data = await self.extract_prices_from_tcgplayer_dom(page)
                    
                    # Get final URL
                    final_url = page.url
                    
                    return {
                        "tcgplayer_price": price_data.get('tcg_price'),
                        "tcgplayer_market_price": price_data.get('tcg_market_price'),
                        "tcgplayer_url": final_url,
                        "tcgplayer_product_id": None,
                        "tcgplayer_variant_selected": None
                    }
                    
                finally:
                    # Always close context to prevent resource leaks
                    await context.close()
                
        except Exception as e:
            logger.error(f"Error in pooled scraping: {e}")
            return {
                "tcgplayer_price": None,
                "tcgplayer_market_price": None,
                "tcgplayer_url": None,
                "tcgplayer_product_id": None,
                "tcgplayer_variant_selected": None,
                "error": str(e)
            }

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
        Scrape price for a card with intelligent caching and validation logic.
        
        Flow:
        1. Cache Hit (Fresh) → Return immediately 
        2. Cache Hit (Stale) → Skip validation (rarity proven valid) → Scrape fresh
        3. Cache Miss → Validate rarity → If valid scrape, if invalid fail
        
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
            cache_status = "miss"  # Track what happened with cache
            
            # STEP 1: Check cache first (unless force refresh)
            if not force_refresh:
                logger.info(f"🚀 Checking cache for {card_number} ({card_rarity})")
                
                # Check cache including stale data
                cached_data = self._find_cached_price_data_with_staleness_info(
                    card_number, card_name, card_rarity, art_variant
                )
                
                if cached_data:
                    if cached_data["is_fresh"]:
                        # CASE 1: Cache Hit (Fresh) - Return immediately
                        logger.info(f"✓ Fresh cache hit for {card_number} - returning immediately")
                        cache_status = "fresh_hit"
                        cleaned_data = clean_card_data(cached_data["data"])
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
                        # CASE 2: Cache Hit (Stale) - Rarity already proven valid, skip validation
                        logger.info(f"⏰ Stale cache hit for {card_number} - rarity already validated, proceeding to fresh scrape")
                        cache_status = "stale_hit"
                        # Continue to scraping without validation
                else:
                    # CASE 3: Cache Miss - Need to validate rarity
                    logger.info(f"❌ Cache miss for {card_number} - will validate rarity before scraping")
                    cache_status = "miss"
            else:
                logger.info(f"🔄 Force refresh requested for {card_number} - skipping cache")
                cache_status = "force_refresh"

            # STEP 2: Rarity validation (only for cache miss or force refresh)
            if cache_status in ["miss", "force_refresh"] and card_number:
                logger.info(f"🔍 Validating rarity '{card_rarity}' for card {card_number} (cache {cache_status})")
                try:
                    is_valid_rarity = self.validate_card_rarity(card_number, card_rarity)
                    if not is_valid_rarity:
                        logger.warning(f"✗ Invalid rarity '{card_rarity}' for card {card_number} - stopping price scraping")
                        return {
                            "success": False,
                            "card_number": card_number,
                            "card_name": card_name,
                            "card_rarity": card_rarity,
                            "art_variant": art_variant,
                            "error": f"Invalid rarity '{card_rarity}' for card {card_number}. This rarity does not exist for this card in its set."
                        }
                    else:
                        logger.info(f"✓ Rarity validation passed for {card_number} - proceeding with fresh scrape")
                except Exception as validation_error:
                    logger.error(f"Error during rarity validation for {card_number}: {validation_error}")
                    return {
                        "success": False,
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        "art_variant": art_variant,
                        "error": f"Validation error: {str(validation_error)}"
                    }
            elif cache_status == "stale_hit":
                logger.info(f"⚡ Skipping validation for {card_number} - rarity already proven valid by stale cache")
            
            # STEP 3: Scrape from source (validation passed or proven valid by stale cache)
            logger.info(f"🌐 Scraping fresh price data from TCGPlayer for {card_name} ({card_rarity})")
            try:
                # Use thread pool executor for proper concurrency handling
                logger.info(f"📋 Submitting scraping task to thread pool for {card_name}")
                future = self._scraping_executor.submit(
                    self._run_async_scraping_in_thread, card_name, card_rarity, art_variant, card_number
                )
                
                # Get the result with timeout to prevent hanging
                price_data = future.result(timeout=3600)  # 1 hour timeout
                logger.info(f"🎯 Received scraping result for {card_name}: success={not bool(price_data.get('error'))}")
                
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
                    
                    # If prices are null, check if we have valid data in cache/DB
                    # This handles cases where scraping succeeds but price extraction fails
                    if price_data.get('tcgplayer_price') is None or price_data.get('tcgplayer_market_price') is None:
                        logger.info(f"⚠️ Null prices detected after scraping for {card_number} - checking cache for existing data")
                        cached_data = self._find_cached_price_data_with_staleness_info(
                            card_number, card_name, card_rarity, art_variant
                        )
                        if cached_data and cached_data["data"].get('tcgplayer_price') is not None:
                            logger.info(f"✓ Found valid prices in cache for {card_number} - returning cached data instead of nulls")
                            cleaned_data = clean_card_data(cached_data["data"])
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
                logger.error(f"❌ Error in thread pool execution for {card_number}: {e}", exc_info=True)
                return {
                    "success": False,
                    "card_number": card_number,
                    "card_name": card_name,
                    "card_rarity": card_rarity,
                    "art_variant": art_variant,
                    "cached": False,
                    "error": f"Thread pool execution error: {str(e)}"
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

    def _find_cached_price_data_with_staleness_info(
        self,
        card_number: str,
        card_name: str,
        card_rarity: str,
        art_variant: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find cached price data and return both the data and staleness information.
        
        Returns:
            Optional[Dict]: {
                "data": cached_document,
                "is_fresh": bool,
                "last_updated": datetime
            } or None if not found
        """
        try:
            self._ensure_initialized()
            
            if self.cache_collection is None:
                logger.debug("Database disabled, skipping cache lookup")
                return None
            
            # Normalize inputs
            normalized_rarity = card_rarity.lower().strip()
            normalized_art_variant = self._normalize_art_variant(art_variant) if art_variant else None
            
            logger.debug(f"Searching cache with staleness check - Number: {card_number}, Rarity: {normalized_rarity}, "
                        f"Art Variant: {normalized_art_variant or 'None'}")
            
            # Build base query with card number and rarity
            query = {
                "card_number": card_number,
                "card_rarity": {"$regex": f"^{re.escape(normalized_rarity)}$", "$options": "i"}
            }
            
            # Handle art variant if provided
            if normalized_art_variant:
                query["$or"] = [
                    {"art_variant": {"$exists": False}},
                    {"art_variant": ""},
                    {"art_variant": {"$in": self._get_art_variant_alternatives(normalized_art_variant)}}
                ]
            
            # Find all matching documents
            documents = list(self.cache_collection.find(query))
            
            if not documents:
                logger.debug(f"No cached data found for {card_number}")
                return None
                
            # Sort by last_price_updt in descending order to get the most recent
            documents.sort(key=lambda x: x.get('last_price_updt', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            
            # Get the most recent document
            document = documents[0]
            last_updated = document.get('last_price_updt')
            
            if not last_updated:
                logger.debug(f"Found cached data for {card_number} but missing last_price_updt")
                return None
            
            # Check if data is fresh
            is_fresh = is_cache_fresh(last_updated, PRICE_CACHE_EXPIRY_DAYS)
            
            logger.debug(f"Found cached data for {card_number} - Fresh: {is_fresh}, Updated: {last_updated}")
            
            return {
                "data": document,
                "is_fresh": is_fresh,
                "last_updated": last_updated
            }
                
        except Exception as e:
            logger.error(f"Error finding cached price data with staleness info for {card_number}: {e}")
            return None
    
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
                    target_art = str(target_art_version).strip().lower();
                    
                    # Extract art variant from this variant's title and URL
                    variant_art = extract_art_version(variant['title']);
                    if not variant_art:
                        variant_art = extract_art_version(variant['url']);
                    
                    if variant_art:
                        variant_art_normalized = str(variant_art).strip().lower();
                        # Remove ordinal suffixes for comparison
                        target_art_clean = re.sub(r'(st|nd|rd|th)$', '', target_art);
                        variant_art_clean = re.sub(r'(st|nd|rd|th)$', '', variant_art_normalized);
                        
                        if target_art_clean == variant_art_clean:
                            # Exact art variant match - high score
                            art_version_score = 100;
                            logger.info(f"✓ EXACT art variant match: '{target_art_version}' == '{variant_art}'");
                        else:
                            # Art variant mismatch - penalty
                            art_version_score = -50;
                            logger.warning(f"✗ Art variant mismatch: '{target_art_version}' != '{variant_art}'");
                    else:
                        # No art variant found in title - check for basic presence in text
                        if target_art in title_lower or target_art in url_lower:
                            art_version_score = 25;
                            logger.info(f"⚠ Weak art variant match for '{target_art_version}' found in text");
                        else:
                            # No art variant info available - small penalty
                            art_version_score = -10;
                            logger.info(f"⚠ No art variant info found for comparison");
                    
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
                logger.info(f"URL: {best_variant['url']}");
                return best_variant['url'];
            else:
                logger.warning("No good variant match found, using first variant if available");
                if variants:
                    return variants[0]['url'];
                
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
            
            # Add debug logging
            logger.info(f"Price extraction result: tcg_price=${prices.get('tcg_price')}, market=${prices.get('tcg_market_price')}")
            if prices.get('tcg_price') is None or prices.get('tcg_market_price') is None:
                logger.warning(f"NULL PRICES DETECTED during extraction - debug_info: {prices.get('debug_info', [])}")
                # Try to capture page content for debugging
                try:
                    page_title = await page.title()
                    page_url = page.url
                    logger.warning(f"Page title: {page_title}, URL: {page_url}")
                except:
                    pass
            
            return prices
            
        except Exception as e:
            logger.error(f"Error extracting prices from TCGPlayer DOM: {e}")
            return {"tcg_price": None, "tcg_market_price": None}

# Global service instance
price_scraping_service = PriceScrapingService()