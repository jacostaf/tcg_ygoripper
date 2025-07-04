"""
Database operations for YGO API

MongoDB connection management and database operations.
"""

import logging
from typing import Optional, Dict, List, Any, Generator
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from contextlib import contextmanager
from datetime import datetime, UTC, timedelta

from ..config import (
    MONGODB_CONNECTION_STRING,
    MONGODB_COLLECTION_NAME,
    MONGODB_CARD_VARIANTS_COLLECTION,
    PRICE_CACHE_COLLECTION,
    CACHE_EXPIRY_DAYS
)
from ..memory import get_memory_manager

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Database manager for MongoDB operations with memory optimization."""
    
    def __init__(self):
        self.connection_string = MONGODB_CONNECTION_STRING
        self._client: Optional[MongoClient] = None
        self._database: Optional[Database] = None
        self.memory_manager = get_memory_manager()
        
        # Register cleanup callback
        self.memory_manager.add_cleanup_callback(self._cleanup_connections)
    
    def _get_client(self) -> MongoClient:
        """Get MongoDB client with proper SSL configuration."""
        if self._client is None:
            try:
                # Connect with simplified SSL settings
                self._client = MongoClient(
                    self.connection_string,
                    ssl=True,
                    tlsAllowInvalidCertificates=True,
                    connectTimeoutMS=60000,
                    serverSelectionTimeoutMS=60000,
                    retryWrites=True,
                    w='majority'
                )
                
                # Test the connection
                self._client.admin.command('ping')
                logger.info("Successfully connected to MongoDB with SSL configuration")
                
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB: {str(e)}")
                # Try a fallback connection approach
                try:
                    logger.info("Attempting fallback connection approach...")
                    self._client = MongoClient(
                        self.connection_string,
                        tls=True,
                        tlsAllowInvalidCertificates=True,
                        serverSelectionTimeoutMS=60000,
                        retryWrites=True
                    )
                    self._client.admin.command('ping')
                    logger.info("Successfully connected to MongoDB with fallback settings")
                    
                except Exception as fallback_e:
                    logger.error(f"Fallback connection also failed: {str(fallback_e)}")
                    raise
        
        return self._client
    
    def _get_database(self) -> Database:
        """Get database instance."""
        if self._database is None:
            client = self._get_client()
            # Extract database name from connection string
            if 'mongodb+srv://' in self.connection_string:
                db_name = self.connection_string.split('/')[-1].split('?')[0]
            else:
                db_name = 'ygo_database'  # Default database name
            
            self._database = client[db_name]
        
        return self._database
    
    def _cleanup_connections(self):
        """Clean up database connections to free memory."""
        logger.info("🧹 Cleaning up database connections...")
        if self._client:
            self._client.close()
            self._client = None
            self._database = None
    
    @contextmanager
    def get_collection(self, collection_name: str):
        """Context manager for getting a collection with automatic cleanup."""
        collection = None
        try:
            with self.memory_manager.memory_context(f"db_collection_{collection_name}"):
                database = self._get_database()
                collection = database[collection_name]
                yield collection
        finally:
            # Force garbage collection after database operations
            if self.memory_manager.get_memory_level() != "normal":
                self.memory_manager.force_garbage_collection()
    
    def get_card_sets_collection(self) -> Collection:
        """Get the card sets collection."""
        return self._get_database()[MONGODB_COLLECTION_NAME]
    
    def get_card_variants_collection(self) -> Collection:
        """Get the card variants collection."""
        return self._get_database()[MONGODB_CARD_VARIANTS_COLLECTION]
    
    def get_price_cache_collection(self) -> Collection:
        """Get the price cache collection."""
        return self._get_database()[PRICE_CACHE_COLLECTION]
    
    def find_cached_price_data(
        self,
        card_number: Optional[str] = None,
        card_name: Optional[str] = None,
        card_rarity: Optional[str] = None,
        art_variant: Optional[str] = None
    ) -> tuple[bool, Optional[Dict]]:
        """Find cached price data with memory optimization."""
        
        with self.memory_manager.memory_context("find_cached_price"):
            try:
                with self.get_collection(PRICE_CACHE_COLLECTION) as collection:
                    # Build query
                    query = {}
                    
                    if card_number and card_number != "Unknown":
                        query["card_number"] = card_number
                    elif card_name:
                        query["card_name"] = {"$regex": card_name, "$options": "i"}
                    else:
                        return False, None
                    
                    if card_rarity:
                        query["card_rarity"] = card_rarity
                    
                    if art_variant:
                        query["card_art_variant"] = art_variant
                    
                    # Use projection to limit memory usage
                    projection = {
                        "card_number": 1,
                        "card_name": 1,
                        "card_art_variant": 1,
                        "card_rarity": 1,
                        "tcg_price": 1,
                        "tcg_market_price": 1,
                        "pc_ungraded_price": 1,
                        "last_price_updt": 1,
                        "scrape_success": 1,
                        "error_message": 1
                    }
                    
                    document = collection.find_one(query, projection)
                    
                    if document:
                        return self._check_freshness_and_return(document)
                    else:
                        return False, None
                        
            except Exception as e:
                logger.error(f"Error finding cached price data: {e}")
                return False, None
    
    def _check_freshness_and_return(self, document: Dict) -> tuple[bool, Optional[Dict]]:
        """Check if cached data is fresh and return it."""
        try:
            last_update = document.get('last_price_updt')
            if last_update:
                # Check if data is fresh (within cache expiry period)
                expiry_date = datetime.now(UTC) - timedelta(days=CACHE_EXPIRY_DAYS)
                
                if isinstance(last_update, datetime):
                    # Handle timezone-aware datetime
                    if last_update.tzinfo is None:
                        last_update = last_update.replace(tzinfo=UTC)
                    
                    if last_update > expiry_date:
                        logger.info(f"✅ Found fresh cached data for {document.get('card_name', 'Unknown')}")
                        return True, document
                    else:
                        logger.info(f"⏰ Cached data is stale for {document.get('card_name', 'Unknown')}")
                        return False, None
                else:
                    logger.warning(f"⚠️ Invalid timestamp in cached data: {last_update}")
                    return False, None
            else:
                logger.info("❌ No timestamp found in cached data")
                return False, None
                
        except Exception as e:
            logger.error(f"Error checking data freshness: {e}")
            return False, None
    
    def save_price_data(self, price_data: Dict, requested_art_variant: Optional[str] = None) -> bool:
        """Save price data to MongoDB with memory optimization."""
        
        with self.memory_manager.memory_context("save_price_data"):
            try:
                with self.get_collection(PRICE_CACHE_COLLECTION) as collection:
                    # Update timestamp
                    price_data['last_price_updt'] = datetime.now(UTC)
                    
                    # Build deletion query to avoid duplicates
                    deletion_query = {}
                    
                    if price_data.get("card_number") and price_data["card_number"] != "Unknown":
                        deletion_query["card_number"] = price_data["card_number"]
                    elif price_data.get("card_name"):
                        deletion_query["card_name"] = {"$regex": price_data["card_name"], "$options": "i"}
                    
                    if price_data.get("card_rarity"):
                        deletion_query["card_rarity"] = price_data["card_rarity"]
                    
                    if requested_art_variant:
                        deletion_query["card_art_variant"] = requested_art_variant
                    
                    # Delete existing records
                    if deletion_query:
                        delete_result = collection.delete_many(deletion_query)
                        logger.info(f"🗑️ Deleted {delete_result.deleted_count} existing records")
                    
                    # Insert new record
                    collection.insert_one(price_data)
                    logger.info(f"💾 Saved price data for {price_data.get('card_name', 'Unknown')}")
                    
                    return True
                    
            except Exception as e:
                logger.error(f"Error saving price data: {e}")
                return False
    
    def get_card_sets_from_cache(self) -> List[Dict]:
        """Get all card sets from cache with memory optimization."""
        
        with self.memory_manager.memory_context("get_card_sets_cache"):
            try:
                with self.get_collection(MONGODB_COLLECTION_NAME) as collection:
                    # Use cursor to avoid loading all data into memory at once
                    cursor = collection.find({})
                    return list(cursor)
                    
            except Exception as e:
                logger.error(f"Error getting card sets from cache: {e}")
                return []
    
    def get_card_sets_count(self) -> int:
        """Get count of card sets in cache."""
        try:
            with self.get_collection(MONGODB_COLLECTION_NAME) as collection:
                return collection.count_documents({})
        except Exception as e:
            logger.error(f"Error getting card sets count: {e}")
            return 0
    
    def upload_card_sets(self, card_sets: List[Dict]) -> Dict[str, Any]:
        """Upload card sets to MongoDB with memory optimization."""
        
        with self.memory_manager.memory_context("upload_card_sets"):
            try:
                with self.get_collection(MONGODB_COLLECTION_NAME) as collection:
                    # Clear existing data
                    delete_result = collection.delete_many({})
                    
                    # Insert new data in batches to manage memory
                    batch_size = 100
                    inserted_count = 0
                    
                    for i in range(0, len(card_sets), batch_size):
                        batch = card_sets[i:i + batch_size]
                        collection.insert_many(batch)
                        inserted_count += len(batch)
                        
                        # Check memory usage between batches
                        if self.memory_manager.get_memory_level() != "normal":
                            self.memory_manager.force_garbage_collection()
                    
                    return {
                        "inserted_count": inserted_count,
                        "deleted_count": delete_result.deleted_count
                    }
                    
            except Exception as e:
                logger.error(f"Error uploading card sets: {e}")
                raise
    
    def get_price_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the price cache."""
        try:
            with self.get_collection(PRICE_CACHE_COLLECTION) as collection:
                total_records = collection.count_documents({})
                
                # Count fresh records
                expiry_date = datetime.now(UTC) - timedelta(days=CACHE_EXPIRY_DAYS)
                fresh_records = collection.count_documents({
                    "last_price_updt": {"$gt": expiry_date}
                })
                
                # Count successful scrapes
                successful_records = collection.count_documents({
                    "scrape_success": True
                })
                
                return {
                    "total_records": total_records,
                    "fresh_records": fresh_records,
                    "stale_records": total_records - fresh_records,
                    "successful_records": successful_records,
                    "failed_records": total_records - successful_records,
                    "cache_expiry_days": CACHE_EXPIRY_DAYS
                }
                
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}
    
    def close(self):
        """Close database connections."""
        self._cleanup_connections()

# Global database manager instance
_db_manager: Optional[DatabaseManager] = None

def get_database_manager() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager