"""
Database Module

Manages MongoDB connections and provides database operations with proper
resource management and connection pooling.
"""

import ssl
import logging
import os
from typing import Optional, Dict, Any, List
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from contextlib import contextmanager
from .config import (
    MONGODB_CONNECTION_STRING,
    MONGODB_COLLECTION_NAME,
    MONGODB_CARD_VARIANTS_COLLECTION,
    PRICE_CACHE_COLLECTION,
    MONGODB_CONNECT_TIMEOUT_MS,
    MONGODB_SERVER_SELECTION_TIMEOUT_MS
)
from .memory_manager import monitor_memory, get_memory_manager

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Database manager for MongoDB operations with connection pooling and
    resource management.
    """
    
    def __init__(self):
        self._client: Optional[MongoClient] = None
        self._db: Optional[Database] = None
        self.connection_string = MONGODB_CONNECTION_STRING
        
        # Register cleanup callback with memory manager
        memory_manager = get_memory_manager()
        memory_manager.register_cleanup_callback("database_cleanup", self._cleanup_connections)
    
    def _cleanup_connections(self):
        """Clean up database connections to free memory."""
        if self._client:
            try:
                self._client.close()
                logger.info("Database connections cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up database connections: {e}")
            finally:
                self._client = None
                self._db = None
    
    def get_client(self) -> MongoClient:
        """
        Get MongoDB client connection with proper SSL configuration.
        
        Returns:
            MongoClient: MongoDB client instance
        """
        # Check if database connections are disabled
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            logger.info("Database connections disabled by DISABLE_DB_CONNECTION environment variable")
            return None
        
        if self._client is None:
            try:
                # Connect with simplified SSL settings
                self._client = MongoClient(
                    self.connection_string,
                    ssl=True,
                    tlsAllowInvalidCertificates=True,
                    connectTimeoutMS=MONGODB_CONNECT_TIMEOUT_MS,
                    serverSelectionTimeoutMS=MONGODB_SERVER_SELECTION_TIMEOUT_MS
                )
                
                # Test connection
                self._client.admin.command('ping')
                logger.info("MongoDB connection established successfully")
                
            except Exception as e:
                logger.error(f"Primary MongoDB connection failed: {e}")
                
                # Fallback connection method
                try:
                    self._client = MongoClient(
                        self.connection_string,
                        tlsAllowInvalidCertificates=True,
                        connectTimeoutMS=MONGODB_CONNECT_TIMEOUT_MS,
                        serverSelectionTimeoutMS=MONGODB_SERVER_SELECTION_TIMEOUT_MS
                    )
                    
                    # Test fallback connection
                    self._client.admin.command('ping')
                    logger.info("MongoDB fallback connection established successfully")
                    
                except Exception as fallback_e:
                    logger.error(f"Fallback connection also failed: {fallback_e}")
                    self._client = None
                    raise ConnectionError(f"Failed to connect to MongoDB: {fallback_e}")
        
        return self._client
    
    def get_database(self) -> Database:
        """
        Get database instance.
        
        Returns:
            Database: MongoDB database instance
        """
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            logger.info("Database connections disabled by DISABLE_DB_CONNECTION environment variable")
            return None
            
        if self._db is None:
            client = self.get_client()
            if client is None:
                return None
            self._db = client.get_default_database()
        
        return self._db
    
    def get_collection(self, collection_name: str) -> Collection:
        """
        Get collection instance.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Collection: MongoDB collection instance
        """
        db = self.get_database()
        if db is None:
            return None
        return db[collection_name]
    
    def get_card_sets_collection(self) -> Collection:
        """Get card sets collection."""
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            return None
        return self.get_collection(MONGODB_COLLECTION_NAME)
    
    def get_card_variants_collection(self) -> Collection:
        """Get card variants collection."""
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            return None
        return self.get_collection(MONGODB_CARD_VARIANTS_COLLECTION)
    
    def get_price_cache_collection(self) -> Collection:
        """Get price cache collection."""
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            return None
        return self.get_collection(PRICE_CACHE_COLLECTION)
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.
        Ensures proper cleanup of resources.
        
        Yields:
            MongoClient: Database client
        """
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            logger.info("Database connections disabled by DISABLE_DB_CONNECTION environment variable")
            yield None
            return
            
        client = None
        try:
            client = self.get_client()
            yield client
        finally:
            # Connection cleanup is handled by connection pooling
            # We only close on explicit cleanup
            pass
    
    @contextmanager
    def get_database_context(self):
        """
        Context manager for database operations.
        
        Yields:
            Database: Database instance
        """
        with self.get_connection() as client:
            if client is None:
                yield None
            else:
                yield client.get_default_database()
    
    @contextmanager
    def get_collection_context(self, collection_name: str):
        """
        Context manager for collection operations.
        
        Args:
            collection_name: Name of the collection
            
        Yields:
            Collection: Collection instance
        """
        with self.get_database_context() as db:
            if db is None:
                yield None
            else:
                yield db[collection_name]
    
    def close(self):
        """Close database connections."""
        self._cleanup_connections()
    
    def test_connection(self) -> bool:
        """
        Test database connection.
        
        Returns:
            bool: True if connection is successful
        """
        # Check if database connections are disabled
        if os.environ.get('DISABLE_DB_CONNECTION') == '1':
            logger.info("Database connections disabled by DISABLE_DB_CONNECTION environment variable")
            return True
            
        try:
            with self.get_connection() as client:
                if client is None:
                    return False
                client.admin.command('ping')
                return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False

# Global database manager instance
_db_manager: Optional[DatabaseManager] = None

def get_database_manager() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager

@monitor_memory
def get_mongo_client() -> MongoClient:
    """
    Get MongoDB client connection.
    
    Returns:
        MongoClient: MongoDB client instance
    """
    db_manager = get_database_manager()
    return db_manager.get_client()

@monitor_memory
def get_database() -> Database:
    """
    Get database instance.
    
    Returns:
        Database: MongoDB database instance
    """
    db_manager = get_database_manager()
    return db_manager.get_database()

@monitor_memory
def get_collection(collection_name: str) -> Collection:
    """
    Get collection instance.
    
    Args:
        collection_name: Name of the collection
        
    Returns:
        Collection: MongoDB collection instance
    """
    db_manager = get_database_manager()
    return db_manager.get_collection(collection_name)

def get_card_sets_collection() -> Collection:
    """Get card sets collection."""
    db_manager = get_database_manager()
    return db_manager.get_card_sets_collection()

def get_card_variants_collection() -> Collection:
    """Get card variants collection."""
    db_manager = get_database_manager()
    return db_manager.get_card_variants_collection()

def get_price_cache_collection() -> Collection:
    """Get price cache collection."""
    db_manager = get_database_manager()
    return db_manager.get_price_cache_collection()

def close_database_connections():
    """Close all database connections."""
    global _db_manager
    if _db_manager:
        _db_manager.close()
        _db_manager = None

def test_database_connection() -> bool:
    """
    Test database connection.
    
    Returns:
        bool: True if connection is successful
    """
    # Check if database connections are disabled
    if os.environ.get('DISABLE_DB_CONNECTION') == '1':
        logger.info("Database connections disabled by DISABLE_DB_CONNECTION environment variable")
        return True
    
    db_manager = get_database_manager()
    return db_manager.test_connection()