"""
Flask extensions module.

This module initializes and configures Flask extensions used throughout the application.
"""
from flask_pymongo import PyMongo
from flask_cors import CORS
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_httpauth import HTTPTokenAuth
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_assets import Environment, Bundle
from pymongo import MongoClient
from typing import Optional
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize extensions
mongo = PyMongo()
cors = CORS()
cache = Cache()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
auth = HTTPTokenAuth(scheme='Bearer')
mail = Mail()
csrf = CSRFProtect()
assets = Environment()

class MongoDBManager:
    """Manages MongoDB connections and provides database access."""
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db = None
        
    def init_app(self, app):
        """Initialize MongoDB connection using application config.
        
        Args:
            app: Flask application instance
        """
        try:
            self.client = MongoClient(
                app.config['MONGODB_CONNECTION_STRING'],
                ssl=True,
                tlsAllowInvalidCertificates=True,
                connectTimeoutMS=60000,
                serverSelectionTimeoutMS=60000,
                retryWrites=True,
                w='majority'
            )
            # Test the connection
            self.client.admin.command('ping')
            self.db = self.client.get_default_database()
            logger.info("Successfully connected to MongoDB")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            # Fallback connection approach
            try:
                logger.info("Attempting fallback connection approach...")
                self.client = MongoClient(
                    app.config['MONGODB_CONNECTION_STRING'],
                    tls=True,
                    tlsAllowInvalidCertificates=True,
                    serverSelectionTimeoutMS=60000,
                    retryWrites=True
                )
                self.client.admin.command('ping')
                self.db = self.client.get_default_database()
                logger.info("Successfully connected to MongoDB with fallback settings")
            except Exception as fallback_e:
                logger.error(f"Fallback connection also failed: {str(fallback_e)}")
                raise
    
    def get_collection(self, collection_name: str):
        """Get a collection from the database.
        
        Args:
            collection_name: Name of the collection to retrieve
            
        Returns:
            MongoDB collection instance
        """
        if not self.db:
            raise RuntimeError("Database not initialized. Call init_app first.")
        return self.db[collection_name]
    
    def close(self):
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Initialize MongoDB manager
mongo = MongoDBManager()

def init_extensions(app):
    """Initialize all Flask extensions.
    
    Args:
        app: Flask application instance
    """
    # Initialize CORS
    cors.init_app(
        app,
        resources={r"/*": {"origins": app.config['CORS_ORIGINS']}},
        supports_credentials=True
    )
    
    # Initialize MongoDB
    mongo.init_app(app)
