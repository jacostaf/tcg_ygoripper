"""
Set Service Module

This module provides business logic and data access for Yu-Gi-Oh! card sets.
It handles set retrieval, synchronization with external sources, and provides
methods for querying and filtering sets based on various criteria.
"""
from typing import Dict, List, Optional, Any, Tuple, Generator
from datetime import datetime, timedelta, timezone
import logging
from functools import lru_cache

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, TEXT

from ..extensions import mongo, cache
from ..utils.memory import MemoryOptimizer

# Configure logging
logger = logging.getLogger(__name__)

class SetService:
    """
    Service class for set-related business logic and data access.
    
    This class handles all operations related to Yu-Gi-Oh! card sets, including:
    - Retrieving sets with pagination and filtering
    - Synchronizing set data with external sources
    - Managing set metadata and statistics
    - Caching set data for improved performance
    
    The service implements efficient query patterns and caching strategies
    to ensure responsive performance even with large datasets.
    """
    
    # Default pagination settings
    DEFAULT_PAGE = 1
    DEFAULT_PER_PAGE = 20
    MAX_PER_PAGE = 100
    
    # Cache settings
    CACHE_TTL = 3600  # 1 hour
    
    @classmethod
    @MemoryOptimizer.memory_profiler
    def get_all_sets(
        cls, 
        page: int = None, 
        per_page: int = None,
        sort_field: str = "release_date",
        sort_order: str = "desc"
    ) -> Tuple[List[Dict], int]:
        """
        Retrieve a paginated list of all Yu-Gi-Oh! card sets.
        
        This method provides a paginated view of all card sets in the database,
        with support for sorting and filtering. Results are cached to improve
        performance for frequently accessed pages.
        
        Args:
            page: Page number (1-based). Defaults to 1.
            per_page: Number of items per page. Defaults to 20, max 100.
            sort_field: Field to sort by. Defaults to "release_date".
                      Supported fields: 'name', 'code', 'release_date', 'card_count'
            sort_order: Sort order. Either 'asc' or 'desc'. Defaults to 'desc'.
            
        Returns:
            Tuple containing:
                - List of set documents (with _id converted to string)
                - Total count of all sets matching the criteria
                
        Example:
            >>> sets, total = SetService.get_all_sets(page=1, per_page=10)
            >>> print(f"Found {total} sets")
            >>> for set_data in sets:
            ...     print(f"{set_data['name']} ({set_data['code']})")
            
        Notes:
            - Results are cached for 1 hour
            - Pagination is 1-based (first page is 1, not 0)
            - The _id field is converted to string for JSON serialization
        """
        try:
            # Set default values if not provided
            page = page or cls.DEFAULT_PAGE
            per_page = min(per_page or cls.DEFAULT_PER_PAGE, cls.MAX_PER_PAGE)
            
            # Generate cache key based on query parameters
            cache_key = f"sets:page_{page}:per_{per_page}:sort_{sort_field}_{sort_order}"
            
            # Check cache first
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_result
            
            # Calculate pagination
            skip = (page - 1) * per_page
            
            # Determine sort direction
            sort_direction = DESCENDING if sort_order.lower() == 'desc' else ASCENDING
            
            # Get total count (not cached as it's fast in MongoDB with count_documents)
            total = mongo.get_collection('sets').count_documents({})
            return sets, total
            
        except Exception as e:
            logger.error(f"Error getting all sets: {str(e)}")
            return [], 0
    
    @classmethod
    @MemoryOptimizer.memory_profiler
    def get_set_by_id(cls, set_id: str) -> Optional[Dict]:
        """
        Retrieve a single Yu-Gi-Oh! card set by its unique identifier.
        
        This method fetches a set document from the database using its MongoDB _id.
        It includes comprehensive error handling and supports caching to improve
        performance for frequently accessed sets.
        
        Args:
            set_id: The 24-character hexadecimal string representing the set's MongoDB _id.
                   Can be either a string or ObjectId.
                   
        Returns:
            Optional[Dict]: A dictionary containing the set data if found, None otherwise.
                The dictionary includes all set attributes as stored in the database,
                with the _id field converted to a string for JSON serialization.
                
        Example:
            >>> set_data = SetService.get_set_by_id("507f1f77bcf86cd799439011")
            >>> if set_data:
            ...     print(f"Found set: {set_data['name']} ({set_data['code']})")
            ... else:
            ...     print("Set not found")
            
        Notes:
            - The method is decorated with @memory_profiler to track memory usage
            - Invalid ObjectId formats are caught and logged
            - Database errors are caught and logged, but not propagated
            - The _id field is converted to string for JSON serialization
        """
        try:
            # Validate set_id format before querying
            if not ObjectId.is_valid(set_id):
                logger.warning(f"Invalid set ID format: {set_id}")
                return None
                
            # Generate cache key
            cache_key = f"set:{set_id}"
            
            # Check cache first
            cached_set = cache.get(cache_key)
            if cached_set:
                logger.debug(f"Cache hit for set {set_id}")
                return cached_set
            
            # Query the database
            set_data = mongo.get_collection('sets').find_one({"_id": ObjectId(set_id)})
            
            if not set_data:
                logger.debug(f"Set not found with ID: {set_id}")
                return None
                
            # Convert ObjectId to string for JSON serialization
            set_data['id'] = str(set_data.pop('_id'))
            
            # Update cache
            cache.set(cache_key, set_data, timeout=cls.CACHE_TTL)
            
            return set_data
            
        except Exception as e:
            logger.error(f"Error retrieving set {set_id}: {str(e)}", exc_info=True)
            return None
    
    @classmethod
    @MemoryOptimizer.memory_profiler
    def get_cards_in_set(
        cls,
        set_code: str,
        page: int = None,
        per_page: int = None,
        sort_by: str = "card_number",
        sort_order: str = "asc"
    ) -> Tuple[List[Dict], int]:
        """
        Retrieve a paginated list of all cards belonging to a specific Yu-Gi-Oh! set.
        
        This method provides efficient pagination and sorting of cards within a set,
        with support for various sorting criteria. Results are cached to improve
        performance for frequently accessed pages.
        
        Args:
            set_code: The official set code (e.g., 'LOD' for Legacy of Darkness).
                     Case-insensitive as it will be converted to uppercase.
            page: Page number (1-based). Defaults to 1.
            per_page: Number of items per page. Defaults to 100, maximum 250.
            sort_by: Field to sort by. Supported fields: 'card_number', 'name', 'rarity', 'price'.
                   Defaults to 'card_number'.
            sort_order: Sort order. Either 'asc' (ascending) or 'desc' (descending).
                      Defaults to 'asc'.
                      
        Returns:
            Tuple containing:
                - List of card documents (with _id converted to string)
                - Total count of all cards in the set
                
        Example:
            >>> cards, total = SetService.get_cards_in_set("LOD", page=1, per_page=10)
            >>> print(f"Found {total} cards in set")
            >>> for card in cards:
            ...     print(f"{card['card_number']} - {card['name']}")
            
        Notes:
            - Results are cached for 1 hour
            - Pagination is 1-based (first page is 1, not 0)
            - The _id field is converted to string for JSON serialization
            - Invalid set codes will return an empty list with count 0
        """
        try:
            # Set default values if not provided
            page = page or cls.DEFAULT_PAGE
            per_page = min(per_page or cls.DEFAULT_PER_PAGE, 250)  # Cap at 250 per page
            
            # Normalize set code
            set_code = set_code.upper()
            
            # Generate cache key
            cache_key = f"set_cards:{set_code}:page_{page}:per_{per_page}:sort_{sort_by}_{sort_order}"
            
            # Check cache first
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_result
            
            # Get database collection
            cards_col = mongo.get_collection('cards')
            
            # Build query
            query = {"set_code": set_code}
            
            # Get total count (not cached as it's fast in MongoDB with count_documents)
            total = cards_col.count_documents(query)
            
            # If no cards found, return early
            if total == 0:
                return [], 0
            
            # Determine sort direction
            sort_direction = DESCENDING if sort_order.lower() == 'desc' else ASCENDING
            
            # Handle special sort cases
            sort_field = sort_by
            if sort_field == 'price':
                sort_field = 'prices.market'  # Assuming price data is stored in a nested structure
            
            # Get paginated results
            cursor = (cards_col
                     .find(query)
                     .sort(sort_field, sort_direction)
                     .skip((page - 1) * per_page)
                     .limit(per_page))
            
            # Process results
            cards = []
            for card in cursor:
                # Convert ObjectId to string for JSON serialization
                card['id'] = str(card.pop('_id'))
                
                # Add any additional processing here if needed
                
                cards.append(card)
            
            # Prepare result
            result = (cards, total)
            
            # Cache the result
            cache.set(cache_key, result, timeout=cls.CACHE_TTL)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting cards in set {set_code}: {str(e)}", exc_info=True)
            return [], 0
    
    @classmethod
    def sync_sets_from_ygo_api(cls) -> Dict[str, Any]:
        """
        Sync all sets from the YGO API to the local database.
        
        Returns:
            Dictionary with sync results
        """
        try:
            # Fetch all sets from YGO API
            sets_data = fetch_ygo_api("cardsets.php")
            if not sets_data or not isinstance(sets_data, list):
                return {"success": False, "message": "Failed to fetch sets from YGO API"}
            
            collection = mongo.get_collection('sets')
            
            # Track stats
            stats = {
                "total": len(sets_data),
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 0
            }
            
            # Process each set
            for set_data in sets_data:
                try:
                    set_code = set_data.get("set_code", "").upper()
                    if not set_code:
                        stats["skipped"] += 1
                        continue
                    
                    # Prepare set document
                    set_doc = {
                        "set_name": set_data.get("set_name", ""),
                        "set_code": set_code,
                        "num_of_cards": int(set_data.get("num_of_cards", 0)),
                        "tcg_date": set_data.get("tcg_date", ""),
                        "set_image": set_data.get("set_image", ""),
                        "set_rarity": set_data.get("set_rarity", ""),
                        "set_rarity_code": set_data.get("set_rarity_code", ""),
                        "set_price": set_data.get("set_price", ""),
                        "last_updated": datetime.now(timezone.utc)
                    }
                    
                    # Check if set already exists
                    existing = collection.find_one({"set_code": set_code})
                    
                    if existing:
                        # Update existing set
                        result = collection.update_one(
                            {"_id": existing["_id"]},
                            {"$set": set_doc}
                        )
                        if result.modified_count > 0:
                            stats["updated"] += 1
                        else:
                            stats["skipped"] += 1
                    else:
                        # Insert new set
                        collection.insert_one(set_doc)
                        stats["created"] += 1
                    
                except Exception as e:
                    logger.error(f"Error processing set {set_data.get('set_code', 'unknown')}: {str(e)}")
                    stats["errors"] += 1
            
            return {
                "success": True,
                "message": f"Synced {stats['total']} sets ({stats['created']} created, {stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors)",
                "stats": stats
            }
            
        except Exception as e:
            logger.error(f"Error syncing sets from YGO API: {str(e)}")
            return {"success": False, "message": f"Error syncing sets: {str(e)}"}
    
    @classmethod
    def get_set_statistics(cls, set_code: str) -> Dict[str, Any]:
        """
        Get statistics for a set.
        
        Args:
            set_code: The set code
            
        Returns:
            Dictionary with set statistics
        """
        try:
            cards_collection = mongo.get_collection('cards')
            
            # Get total cards in set
            total_cards = cards_collection.count_documents({"set_code": set_code.upper()})
            
            if total_cards == 0:
                return {"success": False, "message": "No cards found in set"}
            
            # Get rarity distribution
            pipeline = [
                {"$match": {"set_code": set_code.upper()}},
                {"$group": {"_id": "$rarity", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            
            rarity_dist = list(cards_collection.aggregate(pipeline))
            
            # Get price statistics
            pipeline = [
                {"$match": {"set_code": set_code.upper(), "price_data.prices.market": {"$exists": True}}},
                {"$group": {
                    "_id": None,
                    "avg_price": {"$avg": "$price_data.prices.market"},
                    "min_price": {"$min": "$price_data.prices.market"},
                    "max_price": {"$max": "$price_data.prices.market"},
                    "total_value": {"$sum": "$price_data.prices.market"}
                }}
            ]
            
            price_stats = list(cards_collection.aggregate(pipeline))
            
            # Get most expensive cards
            most_expensive = list(cards_collection.find(
                {"set_code": set_code.upper(), "price_data.prices.market": {"$exists": True}},
                {"name": 1, "card_number": 1, "rarity": 1, "price_data.prices.market": 1, "image_url": 1},
                sort=[("price_data.prices.market", -1)],
                limit=5
            ))
            
            return {
                "success": True,
                "set_code": set_code.upper(),
                "total_cards": total_cards,
                "rarity_distribution": rarity_dist,
                "price_statistics": price_stats[0] if price_stats else {},
                "most_expensive_cards": most_expensive
            }
            
        except Exception as e:
            logger.error(f"Error getting statistics for set {set_code}: {str(e)}")
            return {"success": False, "message": f"Error getting set statistics: {str(e)}"}
