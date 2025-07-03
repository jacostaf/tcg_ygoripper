"""
Price Service Module

This module provides business logic and data access for Yu-Gi-Oh! card pricing.
It handles price fetching, caching, and aggregation from multiple sources including
TCGPlayer and PriceCharting APIs. The service implements intelligent caching to
minimize external API calls and ensure responsive performance.
"""
from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime, timedelta
import logging
import time
import json
from functools import lru_cache
from bson import ObjectId
from pymongo import UpdateOne, ReturnDocument

from ..extensions import mongo, cache
from ..utils.memory import MemoryOptimizer

# Configure logging
logger = logging.getLogger(__name__)

class PriceService:
    """
    Service class for price-related business logic and data access.
    
    This class handles all pricing operations including:
    - Fetching current market prices from external APIs
    - Caching price data with configurable TTL
    - Aggregating price history
    - Calculating price trends and statistics
    - Managing rate limiting and API quotas
    
    The service uses a multi-layered caching strategy with both in-memory
    and database caches to optimize performance.
    """
    
    # Cache TTL in seconds (24 hours)
    CACHE_TTL = 24 * 60 * 60
    
    # Maximum number of price history entries to keep per card
    MAX_PRICE_HISTORY = 30
    
    # Default price data structure
    DEFAULT_PRICE = {
        'market_price': None,
        'retail_price': None,
        'low_price': None,
        'trend': None,  # 'up', 'down', or 'stable'
        'last_updated': None,
        'source': None
    }
    
    @classmethod
    @MemoryOptimizer.memory_profiler
    def get_card_price(cls, card_number: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Retrieve the current market price for a specific Yu-Gi-Oh! card.
        
        This method implements a multi-level caching strategy:
        1. In-memory cache (fastest, per-worker process)
        2. Database cache (persistent across workers)
        3. External API (fallback, rate-limited)
        
        Args:
            card_number: The card's unique identifier (e.g., "LOD-001")
            force_refresh: If True, bypass all caches and fetch fresh data
            
        Returns:
            Optional[Dict]: A dictionary containing price information with the following structure:
                {
                    'card_number': str,           # The card identifier
                    'market_price': float,        # Current market price
                    'retail_price': float,        # Retail/suggested price
                    'low_price': float,           # Lowest available price
                    'trend': str,                 # Price trend ('up', 'down', 'stable')
                    'last_updated': datetime,     # When the price was last updated
                    'source': str,                # Data source (e.g., 'tcgplayer')
                    'history': List[Dict],        # Price history (if available)
                    'expires_at': datetime        # Cache expiration time
                }
                
        Example:
            >>> price = PriceService.get_card_price("SDK-001")
            >>> print(f"Market price: ${price['market_price']:.2f}")
            Market price: $4.99
            
        Notes:
            - Prices are cached for 24 hours by default
            - The method is decorated with @memory_profiler to track memory usage
            - All database operations are wrapped in try/except blocks
        """
        cache_key = f"price:{card_number}"
        prices_col = mongo.get_collection('prices')
        
        try:
            # Check in-memory cache first (fastest)
            cached_price = cache.get(cache_key)
            if cached_price and not force_refresh:
                logger.debug(f"Cache hit for card {card_number}")
                return json.loads(cached_price)
            
            # Check database cache if not forcing refresh
            if not force_refresh:
                cached_price = prices_col.find_one({
                    "card_number": card_number,
                    "expires_at": {"$gt": datetime.utcnow()}
                })
                
                if cached_price:
                    # Update in-memory cache
                    cache.set(cache_key, json.dumps(cached_price, default=str), 
                            timeout=cls.CACHE_TTL)
                    
                    # Convert ObjectId to string for JSON serialization
                    cached_price['_id'] = str(cached_price['_id'])
                    return cached_price
            
            # If we get here, fetch from external API (pseudo-code)
            logger.info(f"Fetching fresh price for card {card_number} from external API")
            price_data = cls._fetch_from_external_api(card_number)
            
            if not price_data:
                logger.warning(f"No price data available for card {card_number}")
                return None
            
            # Add metadata
            price_data.update({
                'card_number': card_number,
                'last_updated': datetime.utcnow(),
                'expires_at': datetime.utcnow() + timedelta(seconds=cls.CACHE_TTL)
            })
            
            # Update database cache
            result = prices_col.find_one_and_update(
                {"card_number": card_number},
                {"$set": price_data},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            
            # Update in-memory cache
            cache.set(cache_key, json.dumps(result, default=str), 
                     timeout=cls.CACHE_TTL)
            
            # Convert ObjectId to string for JSON serialization
            if result and '_id' in result:
                result['_id'] = str(result['_id'])
                
            return result
            
        except Exception as e:
            logger.error(f"Error getting price for card {card_number}: {str(e)}", 
                        exc_info=True)
            return None
    
    @classmethod
    def _fetch_from_external_api(cls, card_number: str) -> Dict[str, Any]:
        """
        Fetch price data from external APIs.
        
        This is a placeholder method that would contain the actual API integration
        with TCGPlayer, PriceCharting, etc. In a real implementation, this would:
        - Handle API authentication
        - Make HTTP requests with proper error handling
        - Parse and normalize the response
        - Implement rate limiting
        - Fall back to alternative sources if primary fails
        
        Args:
            card_number: The card identifier to fetch prices for
            
        Returns:
            Dict containing normalized price data
        """
        # This is a simplified example - actual implementation would make real API calls
        return {
            'market_price': 4.99,
            'retail_price': 5.99,
            'low_price': 3.99,
            'trend': 'stable',
            'source': 'tcgplayer',
            'history': [
                {'date': '2023-01-01', 'price': 5.50, 'source': 'tcgplayer'},
                {'date': '2023-01-15', 'price': 5.25, 'source': 'tcgplayer'},
                {'date': '2023-02-01', 'price': 4.99, 'source': 'tcgplayer'}
            ]
        }
    
    @classmethod
    def _fetch_price_data(cls, card_number: str) -> Optional[Dict]:
        """
        Fetch price data from various sources.
        
        Args:
            card_number: The card number
            
        Returns:
            Price data or None if not found
        """
        # Try TCGPlayer first
        tcg_data = cls._fetch_tcgplayer_price(card_number)
        if tcg_data:
            tcg_data["source"] = "tcgplayer"
            return tcg_data
        
        # Fall back to PriceCharting
        pc_data = cls._fetch_pricecharting_price(card_number)
        if pc_data:
            pc_data["source"] = "pricecharting"
            return pc_data
        
        return None
    
    @classmethod
    def _fetch_tcgplayer_price(cls, card_number: str) -> Optional[Dict]:
        """
        Fetch price data from TCGPlayer.
        
        Args:
            card_number: The card number
            
        Returns:
            Price data or None if not found
        """
        try:
            # This is a placeholder - in a real implementation, you would:
            # 1. Search for the card on TCGPlayer
            # 2. Extract the product ID
            # 3. Use the TCGPlayer API to get pricing data
            
            # For now, return a mock response
            return {
                "prices": {
                    "market": 4.99,
                    "low": 3.50,
                    "mid": 5.25,
                    "high": 7.00,
                    "direct_low": 4.75,
                    "currency": "USD",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                },
                "source_url": f"https://www.tcgplayer.com/search/yugioh/product?q={card_number}",
                "last_updated": datetime.now(timezone.utc)
            }
            
        except Exception as e:
            logger.error(f"Error fetching TCGPlayer price for {card_number}: {str(e)}")
            return None
    
    @classmethod
    def _fetch_pricecharting_price(cls, card_number: str) -> Optional[Dict]:
        """
        Fetch price data from PriceCharting.
        
        Args:
            card_number: The card number
            
        Returns:
            Price data or None if not found
        """
        try:
            # This is a placeholder - in a real implementation, you would:
            # 1. Search for the card on PriceCharting
            # 2. Extract the price data from the page
            
            # For now, return a mock response
            return {
                "prices": {
                    "market": 4.25,
                    "low": 3.00,
                    "trend": 4.50,
                    "sold": 5.00,
                    "currency": "USD",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                },
                "source_url": f"https://www.pricecharting.com/game/yugioh/{card_number}",
                "last_updated": datetime.now(timezone.utc)
            }
            
        except Exception as e:
            logger.error(f"Error fetching PriceCharting price for {card_number}: {str(e)}")
            return None
    
    @classmethod
    def get_price_history(
        cls,
        card_number: str,
        days: int = 30,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get price history for a card.
        
        Args:
            card_number: The card number
            days: Number of days of history to retrieve
            limit: Maximum number of records to return
            
        Returns:
            List of price history records
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            history = list(mongo.get_collection('prices').find(
                {
                    "card_number": card_number.upper(),
                    "last_updated": {"$gte": cutoff_date}
                },
                sort=[("last_updated", ASCENDING)],
                limit=limit
            ))
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting price history for {card_number}: {str(e)}")
            return []
    
    @classmethod
    def batch_update_prices(cls, card_numbers: List[str]) -> Dict[str, bool]:
        """
        Update prices for multiple cards in a batch.
        
        Args:
            card_numbers: List of card numbers to update
            
        Returns:
            Dictionary mapping card numbers to success status
        """
        results = {}
        
        for card_number in card_numbers:
            try:
                price_data = cls.get_card_price(card_number, force_refresh=True)
                results[card_number] = price_data is not None
            except Exception as e:
                logger.error(f"Error updating price for {card_number}: {str(e)}")
                results[card_number] = False
        
        return results
    
    @classmethod
    def get_average_prices(cls, card_numbers: List[str]) -> Dict[str, Dict]:
        """
        Get average prices for multiple cards.
        
        Args:
            card_numbers: List of card numbers
            
        Returns:
            Dictionary mapping card numbers to price data
        """
        results = {}
        
        for card_number in card_numbers:
            try:
                price_data = cls.get_card_price(card_number)
                if price_data and "prices" in price_data:
                    results[card_number] = {
                        "market": price_data["prices"].get("market"),
                        "low": price_data["prices"].get("low"),
                        "high": price_data["prices"].get("high"),
                        "last_updated": price_data.get("last_updated")
                    }
                else:
                    results[card_number] = None
            except Exception as e:
                logger.error(f"Error getting average price for {card_number}: {str(e)}")
                results[card_number] = None
        
        return results
