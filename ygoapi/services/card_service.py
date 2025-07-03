"""
Card Service

This module provides business logic for card-related operations,
including fetching, searching, and processing card data.
"""
from typing import Dict, List, Optional, Any, Tuple, Generator
from datetime import datetime, timedelta
import logging
from bson import ObjectId
from pymongo.collection import Collection
from pymongo.cursor import Cursor
from pymongo import ASCENDING, DESCENDING

from ..extensions import mongo, cache
from ..utils.memory import MemoryOptimizer

# Configure logging
logger = logging.getLogger(__name__)

class CardService:
    """
    Service class for card-related business logic and data access.
    
    This class encapsulates all business logic related to Yu-Gi-Oh! cards,
    including retrieval, search, and synchronization with external data sources.
    It acts as a facade to the underlying data store, providing a clean API
    for the route handlers to interact with card data.
    """
    
    # Cache TTL in seconds (1 hour)
    CACHE_TTL = 3600
    
    @classmethod
    def get_card_by_id(cls, card_id: str) -> Optional[Dict]:
        """
        Retrieve a single card by its unique identifier.
        
        This method fetches a card document from the database using its MongoDB _id.
        It includes error handling for malformed IDs and database errors.
        
        Args:
            card_id: The 24-character hexadecimal string representing the card's MongoDB _id
            
        Returns:
            Optional[Dict]: A dictionary containing the card data if found, None otherwise.
                The dictionary includes all card attributes as stored in the database.
                
        Example:
            >>> card = CardService.get_card_by_id("507f1f77bcf86cd799439011")
            >>> print(card['name'])
            "Dark Magician"
            
        Raises:
            Does not raise exceptions but logs them to the application logger.
        """
        try:
            # Validate card_id format before querying
            if not ObjectId.is_valid(card_id):
                logger.warning(f"Invalid card ID format: {card_id}")
                return None
                
            # Use a consistent field name for the query
            card = mongo.get_collection('cards').find_one({"_id": ObjectId(card_id)})
            
            if not card:
                logger.debug(f"Card not found with ID: {card_id}")
                return None
                
            # Convert ObjectId to string for JSON serialization
            card['id'] = str(card.pop('_id'))
            return card
            
        except Exception as e:
            logger.error(f"Error retrieving card {card_id}: {str(e)}", exc_info=True)
            return None
    
    @classmethod
    def get_card_by_number(cls, card_number: str) -> Optional[Dict]:
        """
        Retrieve a single card by its card number.
        Get a card by its card number.
        
        Args:
            card_number: The card number (e.g., 'BLAR-EN001')
            
        Returns:
            Card document or None if not found
        """
        try:
            card = mongo.get_collection('cards').find_one({"card_number": card_number.upper()})
            return card
        except Exception as e:
            logger.error(f"Error getting card by number {card_number}: {str(e)}")
            return None
    
    @classmethod
    def search_cards(
        cls,
        query: str = None,
        set_code: str = None,
        rarity: str = None,
        card_type: str = None,
        attribute: str = None,
        race: str = None,
        page: int = 1,
        per_page: int = 20,
        sort_field: str = "name",
        sort_order: str = "asc"
    ) -> Tuple[List[Dict], int]:
        """
        Search for cards with filtering and pagination.
        
        Args:
            query: Search query string
            set_code: Filter by set code
            rarity: Filter by rarity
            card_type: Filter by card type
            attribute: Filter by attribute
            race: Filter by race
            page: Page number (1-based)
            per_page: Number of results per page
            sort_field: Field to sort by
            sort_order: Sort order ('asc' or 'desc')
            
        Returns:
            Tuple of (list of cards, total count)
        """
        try:
            collection = mongo.get_collection('cards')
            
            # Build query
            query_filter = {}
            
            # Text search
            if query:
                query_filter["$text"] = {"$search": query}
                
            # Additional filters
            if set_code:
                query_filter["set_code"] = set_code.upper()
                
            if rarity:
                normalized_rarity = normalize_rarity(rarity)
                query_filter["rarity"] = {"$in": [normalized_rarity]}
                
            if card_type:
                query_filter["type"] = {"$regex": f"(?i){card_type}"}
                
            if attribute:
                query_filter["attribute"] = {"$regex": f"(?i)^{attribute}$"}
                
            if race:
                query_filter["race"] = {"$regex": f"(?i)^{race}$"}
            
            # Count total matching documents
            total = collection.count_documents(query_filter)
            
            # Determine sort order
            sort_direction = ASCENDING if sort_order.lower() == "asc" else DESCENDING
            sort = [(sort_field, sort_direction)]
            
            # If doing a text search, sort by text score
            if query and "$text" in query_filter:
                sort.insert(0, ("score", {"$meta": "textScore"}))
            
            # Apply pagination
            skip = (page - 1) * per_page
            
            # Execute query
            cursor = collection.find(query_filter)
            cursor = cursor.sort(sort).skip(skip).limit(per_page)
            
            # Convert cursor to list
            cards = list(cursor)
            
            return cards, total
            
        except Exception as e:
            logger.error(f"Error searching cards: {str(e)}")
            return [], 0
    
    @classmethod
    def get_card_variants(cls, card_number: str) -> List[Dict]:
        """
        Get all variants of a card by its card number.
        
        Args:
            card_number: The card number (e.g., 'BLAR-EN001')
            
        Returns:
            List of card variants
        """
        try:
            # Extract base card number (without variant suffix)
            base_number = card_number.split('-')[0]
            
            # Find all cards with the same base number
            variants = list(mongo.get_collection('cards').find({
                "card_number": {"$regex": f"^{re.escape(base_number)}-"}
            }))
            
            return variants
            
        except Exception as e:
            logger.error(f"Error getting card variants for {card_number}: {str(e)}")
            return []
    
    @classmethod
    def sync_card_from_ygo_api(cls, card_data: Dict) -> Dict:
        """
        Sync a card from YGO API data to the database.
        
        Args:
            card_data: Raw card data from YGO API
            
        Returns:
            The synced card document
        """
        try:
            collection = mongo.get_collection('cards')
            
            # Extract card number and set code
            card_number = card_data.get('card_number', '').upper()
            set_code = extract_set_code(card_number)
            
            # Extract art version if present
            card_name = card_data.get('name', '')
            clean_name, art_version = extract_art_version(card_name)
            
            # Prepare card document
            card_doc = {
                "name": clean_name,
                "card_number": card_number,
                "set_code": set_code,
                "art_version": art_version,
                "rarity": card_data.get('rarity', ''),
                "type": card_data.get('type', ''),
                "attribute": card_data.get('attribute', ''),
                "race": card_data.get('race', ''),
                "atk": card_data.get('atk'),
                "def": card_data.get('def'),
                "level": card_data.get('level'),
                "linkval": card_data.get('linkval'),
                "linkmarkers": card_data.get('linkmarkers', []),
                "scale": card_data.get('scale'),
                "archetype": card_data.get('archetype', ''),
                "desc": card_data.get('desc', ''),
                "image_url": card_data.get('card_images', [{}])[0].get('image_url', ''),
                "image_url_small": card_data.get('card_images', [{}])[0].get('image_url_small', ''),
                "price_data": {},
                "last_updated": datetime.now(timezone.utc),
                "source": "ygoapi"
            }
            
            # Update or insert the card
            result = collection.update_one(
                {"card_number": card_number},
                {"$set": card_doc},
                upsert=True
            )
            
            # Get the updated/inserted document
            if result.upserted_id:
                card_doc["_id"] = result.upserted_id
            else:
                card_doc["_id"] = collection.find_one({"card_number": card_number})["_id"]
            
            return card_doc
            
        except Exception as e:
            logger.error(f"Error syncing card {card_number}: {str(e)}")
            raise
    
    @classmethod
    def get_card_price(cls, card_number: str) -> Optional[Dict]:
        """
        Get the latest price data for a card.
        
        Args:
            card_number: The card number
            
        Returns:
            Price data or None if not found
        """
        try:
            price_data = mongo.get_collection('prices').find_one(
                {"card_number": card_number.upper()},
                sort=[("last_updated", -1)]
            )
            
            return price_data
            
        except Exception as e:
            logger.error(f"Error getting price for card {card_number}: {str(e)}")
            return None

    @classmethod
    def update_card_price(
        cls,
        card_number: str,
        price_data: Dict,
        source: str = "tcgplayer"
    ) -> bool:
        """
        Update price data for a card.
        
        Args:
            card_number: The card number
            price_data: The price data to store
            source: Data source (e.g., 'tcgplayer', 'pricecharting')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare price document
            price_doc = {
                "card_number": card_number.upper(),
                "source": source,
                "prices": price_data,
                "last_updated": datetime.now(timezone.utc)
            }
            
            # Insert new price record
            result = mongo.get_collection('prices').insert_one(price_doc)
            
            # Also update the card's price data
            mongo.get_collection('cards').update_one(
                {"card_number": card_number.upper()},
                {"$set": {"price_data": price_data, "last_updated": datetime.now(timezone.utc)}}
            )
            
            return result.acknowledged
            
        except Exception as e:
            logger.error(f"Error updating price for card {card_number}: {str(e)}")
            return False
