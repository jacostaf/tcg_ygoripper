"""
Price Scraping Module

Handles price data collection from TCGPlayer with caching and validation.
This module provides synchronous price scraping functionality with memory optimization.
"""

import asyncio
import logging
from datetime import datetime, timedelta, UTC
from typing import Dict, List, Optional, Any, Tuple
from playwright.async_api import async_playwright
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
    get_current_utc_datetime
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
            
            # Create indexes for better query performance
            self.cache_collection.create_index("card_number", background=True)
            self.cache_collection.create_index("card_name", background=True)
            self.cache_collection.create_index("card_rarity", background=True)
            self.cache_collection.create_index("last_price_updt", background=True)
            
            logger.info("Successfully initialized price scraping collections")
            
        except Exception as e:
            logger.error(f"Failed to initialize price scraping collections: {e}")
            raise
    
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
            
            # Build query
            query = {
                "card_number": card_number,
                "card_name": card_name,
                "card_rarity": card_rarity
            }
            
            # Add art variant to query if provided
            if art_variant is not None:
                query["art_variant"] = art_variant
            
            # Find document
            document = self.cache_collection.find_one(query)
            
            if document:
                # Check if cache is fresh
                last_updated = document.get('last_price_updt')
                if last_updated and is_cache_fresh(last_updated, PRICE_CACHE_EXPIRY_DAYS):
                    logger.info(f"Found fresh cached price data for {card_number}")
                    return document
                else:
                    logger.info(f"Cached price data for {card_number} is stale")
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding cached price data: {e}")
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
        art_variant: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Basic price scraping from TCGPlayer (simplified implementation).
        
        Args:
            card_name: Card name to search for
            card_rarity: Card rarity
            art_variant: Art variant (optional)
            
        Returns:
            Dict: Scraped price data
        """
        try:
            # This is a simplified implementation
            # In production, this would use Playwright to scrape TCGPlayer
            logger.info(f"Scraping price for {card_name} ({card_rarity})")
            
            # Return mock data for now (would be replaced with actual scraping)
            return {
                "tcgplayer_price": None,
                "tcgplayer_market_price": None,
                "tcgplayer_url": None,
                "tcgplayer_product_id": None,
                "tcgplayer_variant_selected": None,
                "error": "Price scraping not fully implemented in this version"
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
                cached_data = self.find_cached_price_data(
                    card_number, card_name, card_rarity, art_variant
                )
                if cached_data:
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
            
            # Scrape from source
            try:
                # Use asyncio to run the async scraping function
                price_data = asyncio.run(
                    self.scrape_price_from_tcgplayer_basic(card_name, card_rarity, art_variant)
                )
                
                # Save to cache if successful
                if price_data and not price_data.get('error'):
                    full_price_data = {
                        "card_number": card_number,
                        "card_name": card_name,
                        "card_rarity": card_rarity,
                        **price_data
                    }
                    self.save_price_data(full_price_data, art_variant)
                
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
                logger.error(f"Error scraping price: {e}")
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

# Global service instance
price_scraping_service = PriceScrapingService()