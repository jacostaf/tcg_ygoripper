"""
Card Services Module

Provides card-related services including card set management, card variant processing,
and card data operations with memory optimization.
"""

import logging
import time
from typing import Dict, List, Optional, Any, Generator
from datetime import datetime, UTC
from urllib.parse import quote
import requests

from .config import (
    YGO_API_BASE_URL,
    API_RATE_LIMIT_DELAY,
    CARD_PROCESSING_BATCH_SIZE,
    CARD_PROCESSING_DELAY
)
from .database import (
    get_card_sets_collection,
    get_card_variants_collection,
    get_database_manager
)
from .models import ProcessingStats, CardModel, CardVariantModel
from .utils import (
    generate_variant_id,
    extract_art_version,
    normalize_rarity,
    batch_process_generator,
    get_current_utc_datetime
)
from .memory_manager import monitor_memory, get_memory_manager

logger = logging.getLogger(__name__)

class CardSetService:
    """Service for managing card sets."""
    
    def __init__(self):
        self.memory_manager = get_memory_manager()
        self.db_manager = get_database_manager()
    
    @monitor_memory
    def fetch_all_card_sets(self) -> List[Dict[str, Any]]:
        """
        Fetch all card sets from YGO API.
        
        Returns:
            List[Dict]: List of card sets
        """
        try:
            logger.info("Fetching all card sets from YGO API")
            
            response = requests.get(
                f"{YGO_API_BASE_URL}/cardsets.php",
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"API returned status {response.status_code}")
            
            card_sets = response.json()
            logger.info(f"Retrieved {len(card_sets)} card sets from API")
            
            return card_sets
            
        except Exception as e:
            logger.error(f"Error fetching card sets: {e}")
            raise
    
    @monitor_memory
    def upload_card_sets_to_cache(self) -> Dict[str, Any]:
        """
        Upload card sets to MongoDB cache.
        
        Returns:
            Dict: Upload results and statistics
        """
        try:
            # Fetch card sets from API
            card_sets_data = self.fetch_all_card_sets()
            
            # Get collection
            collection = get_card_sets_collection()
            
            # Add metadata to each document
            upload_timestamp = get_current_utc_datetime()
            for card_set in card_sets_data:
                card_set['_uploaded_at'] = upload_timestamp
                card_set['_source'] = 'ygoprodeck_api'
            
            # Clear existing data
            delete_result = collection.delete_many({})
            logger.info(f"Cleared {delete_result.deleted_count} existing documents")
            
            # Insert new data in batches to manage memory
            inserted_count = 0
            for batch in batch_process_generator(card_sets_data, CARD_PROCESSING_BATCH_SIZE):
                insert_result = collection.insert_many(batch)
                inserted_count += len(insert_result.inserted_ids)
                
                # Check memory usage during batch processing
                self.memory_manager.check_memory_and_cleanup()
            
            # Create indexes
            collection.create_index("set_code")
            collection.create_index("set_name")
            collection.create_index("_uploaded_at")
            
            logger.info(f"Successfully uploaded {inserted_count} card sets to MongoDB")
            
            return {
                "total_sets_uploaded": inserted_count,
                "previous_documents_cleared": delete_result.deleted_count,
                "upload_timestamp": upload_timestamp.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error uploading card sets: {e}")
            raise
    
    @monitor_memory
    def get_cached_card_sets(self) -> List[Dict[str, Any]]:
        """
        Get card sets from MongoDB cache.
        
        Returns:
            List[Dict]: Cached card sets
        """
        try:
            collection = get_card_sets_collection()
            
            # Check if database is disabled
            if collection is None:
                logger.info("Database disabled, returning empty card sets")
                return []
            
            # Use projection to limit data returned
            cursor = collection.find({}, {"_id": 0})
            
            # Convert cursor to list with memory monitoring
            card_sets = []
            for doc in cursor:
                card_sets.append(doc)
                
                # Check memory periodically
                if len(card_sets) % 1000 == 0:
                    self.memory_manager.check_memory_and_cleanup()
            
            logger.info(f"Retrieved {len(card_sets)} card sets from cache")
            return card_sets
            
        except Exception as e:
            logger.error(f"Error getting cached card sets: {e}")
            raise
    
    @monitor_memory
    def get_card_sets_count(self) -> int:
        """
        Get total count of cached card sets.
        
        Returns:
            int: Number of cached card sets
        """
        try:
            collection = get_card_sets_collection()
            
            # Check if database is disabled
            if collection is None:
                logger.info("Database disabled, returning count of 0")
                return 0
            
            return collection.count_documents({})
        except Exception as e:
            logger.error(f"Error getting card sets count: {e}")
            raise
    
    @monitor_memory
    def search_card_sets(self, set_name: str) -> List[Dict[str, Any]]:
        """
        Search card sets by name.
        
        Args:
            set_name: Name to search for
            
        Returns:
            List[Dict]: Matching card sets
        """
        try:
            collection = get_card_sets_collection()
            
            # Check if database is disabled
            if collection is None:
                logger.info("Database disabled, returning empty search results")
                return []
            
            # Case-insensitive search
            query = {"set_name": {"$regex": set_name, "$options": "i"}}
            cursor = collection.find(query, {"_id": 0})
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"Error searching card sets: {e}")
            raise

class CardVariantService:
    """Service for managing card variants."""
    
    def __init__(self):
        self.memory_manager = get_memory_manager()
        self.db_manager = get_database_manager()
    
    @monitor_memory
    def fetch_cards_from_set(self, set_name: str) -> List[Dict[str, Any]]:
        """
        Fetch cards from a specific set using YGO API.
        
        Args:
            set_name: Name of the set
            
        Returns:
            List[Dict]: List of cards in the set
        """
        try:
            # URL encode the set name
            encoded_set_name = quote(set_name)
            
            # Make request to YGO API
            api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
            response = requests.get(api_url, timeout=15)
            
            if response.status_code == 200:
                cards_data = response.json()
                return cards_data.get('data', [])
            elif response.status_code == 400:
                # No cards found for this set
                logger.warning(f"No cards found for set: {set_name}")
                return []
            else:
                raise Exception(f"API returned status {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching cards from set {set_name}: {e}")
            raise
    
    @monitor_memory
    def create_card_variants(self, cards: List[Dict[str, Any]]) -> Generator[Dict[str, Any], None, None]:
        """
        Create card variants from card data.
        
        Args:
            cards: List of card data
            
        Yields:
            Dict: Card variant data
        """
        upload_timestamp = get_current_utc_datetime()
        
        for card in cards:
            card_id = card.get('id')
            card_name = card.get('name', '')
            card_sets = card.get('card_sets', [])
            
            # Create variant for each card set
            for card_set_info in card_sets:
                set_name = card_set_info.get('set_name', '')
                set_code = card_set_info.get('set_code', '')
                set_rarity = card_set_info.get('set_rarity', '')
                set_rarity_code = card_set_info.get('set_rarity_code', '')
                set_price = card_set_info.get('set_price', '')
                
                # Extract art variant if present
                art_variant = extract_art_version(card_name)
                
                # Generate unique variant ID
                variant_id = generate_variant_id(card_id, set_code, set_rarity, art_variant)
                
                # Create variant document
                variant = {
                    "_variant_id": variant_id,
                    "_uploaded_at": upload_timestamp,
                    "_source": "ygoprodeck_api",
                    
                    # Card basic info
                    "card_id": card_id,
                    "card_name": card_name,
                    "card_type": card.get('type'),
                    "card_frameType": card.get('frameType'),
                    "card_desc": card.get('desc'),
                    "ygoprodeck_url": card.get('ygoprodeck_url'),
                    
                    # Monster specific stats
                    "atk": card.get('atk'),
                    "def": card.get('def'),
                    "level": card.get('level'),
                    "race": card.get('race'),
                    "attribute": card.get('attribute'),
                    "scale": card.get('scale'),
                    "linkval": card.get('linkval'),
                    "linkmarkers": card.get('linkmarkers'),
                    "archetype": card.get('archetype'),
                    
                    # Set specific info
                    "set_name": set_name,
                    "set_code": set_code,
                    "set_rarity": set_rarity,
                    "set_rarity_code": set_rarity_code,
                    "set_price": set_price,
                    
                    # Art variant info
                    "art_variant": art_variant
                }
                
                yield variant
    
    @monitor_memory
    def upload_card_variants_to_cache(self) -> Dict[str, Any]:
        """
        Upload card variants to MongoDB cache.
        
        Returns:
            Dict: Upload results and statistics
        """
        try:
            # Get cached sets
            card_set_service = CardSetService()
            cached_sets = card_set_service.get_cached_card_sets()
            
            if not cached_sets:
                raise Exception("No cached card sets found. Please upload sets first.")
            
            logger.info(f"Found {len(cached_sets)} cached sets to process for card variants")
            
            # Initialize processing statistics
            processing_stats = ProcessingStats(total_sets=len(cached_sets))
            
            # Get collection
            variants_collection = get_card_variants_collection()
            
            # Clear existing data
            delete_result = variants_collection.delete_many({})
            logger.info(f"Cleared {delete_result.deleted_count} existing variants")
            
            # Track unique variants
            all_variants = []
            variant_ids_seen = set()
            
            # Process each set
            for index, card_set in enumerate(cached_sets):
                set_name = card_set.get('set_name', '')
                set_code = card_set.get('set_code', '')
                
                try:
                    logger.info(f"Processing set {index + 1}/{len(cached_sets)}: {set_name}")
                    
                    # Fetch cards from this set
                    cards_list = self.fetch_cards_from_set(set_name)
                    
                    # Create variants for each card
                    for variant in self.create_card_variants(cards_list):
                        variant_id = variant["_variant_id"]
                        
                        # Check for duplicates
                        if variant_id not in variant_ids_seen:
                            all_variants.append(variant)
                            variant_ids_seen.add(variant_id)
                        else:
                            processing_stats.duplicate_variants_skipped += 1
                    
                    processing_stats.processed_sets += 1
                    processing_stats.total_cards_processed += len(cards_list)
                    
                    logger.info(f"Successfully processed {len(cards_list)} cards from {set_name}")
                    
                    # Rate limiting delay
                    time.sleep(API_RATE_LIMIT_DELAY)
                    
                    # Check memory usage periodically
                    if index % 10 == 0:
                        self.memory_manager.check_memory_and_cleanup()
                    
                except Exception as e:
                    error_msg = f"Error processing set {set_name}: {str(e)}"
                    logger.error(error_msg)
                    processing_stats.failed_sets += 1
                    processing_stats.processing_errors.append({
                        "set_name": set_name,
                        "error": error_msg
                    })
            
            # Insert variants in batches
            inserted_total = 0
            for batch in batch_process_generator(all_variants, CARD_PROCESSING_BATCH_SIZE):
                try:
                    insert_result = variants_collection.insert_many(batch, ordered=False)
                    inserted_total += len(insert_result.inserted_ids)
                    logger.info(f"Inserted batch: {len(insert_result.inserted_ids)} variants")
                except Exception as e:
                    logger.error(f"Error inserting batch: {str(e)}")
                    processing_stats.processing_errors.append({
                        "error": f"Batch insert error: {str(e)}"
                    })
            
            processing_stats.unique_variants_created = inserted_total
            
            # Create indexes for better query performance
            try:
                variants_collection.create_index("_variant_id", unique=True)
                variants_collection.create_index("card_id")
                variants_collection.create_index("card_name")
                variants_collection.create_index("set_code")
                variants_collection.create_index("set_name")
                variants_collection.create_index("set_rarity")
                variants_collection.create_index("art_variant")
                variants_collection.create_index("_uploaded_at")
                logger.info("Successfully created indexes for variants collection")
            except Exception as e:
                logger.warning(f"Failed to create indexes: {e}")
            
            # Calculate success rate
            if processing_stats.total_sets > 0:
                processing_stats.success_rate = (
                    processing_stats.processed_sets / processing_stats.total_sets * 100
                )
            
            logger.info(f"Completed variant upload. Created {inserted_total} unique variants")
            
            return {
                "statistics": processing_stats.dict(),
                "total_variants_created": inserted_total,
                "previous_variants_cleared": delete_result.deleted_count
            }
            
        except Exception as e:
            logger.error(f"Error uploading card variants: {e}")
            raise
    
    @monitor_memory
    def get_cached_card_variants(self) -> List[Dict[str, Any]]:
        """
        Get card variants from MongoDB cache.
        
        Returns:
            List[Dict]: Cached card variants
        """
        try:
            collection = get_card_variants_collection()
            
            # Use projection to limit data returned
            cursor = collection.find({}, {"_id": 0})
            
            # Convert cursor to list with memory monitoring
            variants = []
            for doc in cursor:
                variants.append(doc)
                
                # Check memory periodically
                if len(variants) % 1000 == 0:
                    self.memory_manager.check_memory_and_cleanup()
            
            logger.info(f"Retrieved {len(variants)} card variants from cache")
            return variants
            
        except Exception as e:
            logger.error(f"Error getting cached card variants: {e}")
            raise

class CardLookupService:
    """Service for card lookup operations."""
    
    def __init__(self):
        self.memory_manager = get_memory_manager()
    
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
            collection = get_card_variants_collection()
            
            # Try to find by set code matching
            query = {"set_code": {"$regex": card_number, "$options": "i"}}
            result = collection.find_one(query, {"_id": 0})
            
            if result:
                return result
            
            # Try broader search
            query = {"card_name": {"$regex": card_number, "$options": "i"}}
            result = collection.find_one(query, {"_id": 0})
            
            return result
            
        except Exception as e:
            logger.error(f"Error looking up card info: {e}")
            return None
    
    @monitor_memory
    def lookup_card_name_from_ygo_api(self, card_number: str) -> Optional[str]:
        """
        Look up card name from YGO API.
        
        Args:
            card_number: Card number to look up
            
        Returns:
            Optional[str]: Card name if found
        """
        try:
            # Try different API endpoints
            endpoints = [
                f"{YGO_API_BASE_URL}/cardinfo.php?num={card_number}",
                f"{YGO_API_BASE_URL}/cardinfo.php?name={card_number}"
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

# Service instances
card_set_service = CardSetService()
card_variant_service = CardVariantService()
card_lookup_service = CardLookupService()