"""
Application configuration settings.

This module handles all configuration settings for the YGOAPI application,
including environment variables and default values.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Config:
    """Base configuration with default settings."""
    # Flask settings
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-please-change-in-production'
    
    # MongoDB settings
    MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/ygopydb')
    MONGODB_DB = os.environ.get('MONGODB_DB', 'ygopydb')
    
    # API settings
    API_PREFIX = '/api/v1'
    
    # CORS settings
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*').split(',')
    
    # Rate limiting
    RATELIMIT_DEFAULT = '200 per day;50 per hour'
    
    # Cache settings
    CACHE_TYPE = 'simple'  # Can be 'redis', 'memcached', etc.
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes
    
    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    
    # YGO API settings
    YGO_API_BASE_URL = 'https://db.ygoprodeck.com/api/v7'
    
    # TCGPlayer API settings
    TCGPLAYER_API_BASE_URL = 'https://api.tcgplayer.com'
    TCGPLAYER_PUBLIC_KEY = os.environ.get('TCGPLAYER_PUBLIC_KEY', '')
    TCGPLAYER_PRIVATE_KEY = os.environ.get('TCGPLAYER_PRIVATE_KEY', '')
    
    # PriceCharting settings
    PRICECHARTING_API_KEY = os.environ.get('PRICECHARTING_API_KEY', '')
    
    # Image storage
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    
    # Enable/disable features
    ENABLE_TCGPLAYER = os.environ.get('ENABLE_TCGPLAYER', 'true').lower() == 'true'
    ENABLE_PRICECHARTING = os.environ.get('ENABLE_PRICECHARTING', 'true').lower() == 'true'
    
    @classmethod
    def init_app(cls, app):
        """Initialize configuration for the Flask app."""
        # Create upload folder if it doesn't exist
        if not os.path.exists(cls.UPLOAD_FOLDER):
            os.makedirs(cls.UPLOAD_FOLDER)


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'
    MONGODB_URI = os.environ.get('DEV_MONGODB_URI', 'mongodb://localhost:27017/ygopydb_dev')


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    MONGODB_URI = os.environ.get('TEST_MONGODB_URI', 'mongodb://localhost:27017/ygopydb_test')
    WTF_CSRF_ENABLED = False
    ENABLE_TCGPLAYER = False
    ENABLE_PRICECHARTING = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    @classmethod
    def init_app(cls, app):
        """Initialize production configuration."""
        Config.init_app(app)
        
        # Log to stderr in production
        import logging
        from logging import StreamHandler
        file_handler = StreamHandler()
        file_handler.setLevel(logging.WARNING)
        app.logger.addHandler(file_handler)


class DockerConfig(ProductionConfig):
    """Docker configuration."""
    MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://mongo:27017/ygopydb')
    
    @classmethod
    def init_app(cls, app):
        """Initialize Docker configuration."""
        ProductionConfig.init_app(app)
        
        # Log to stderr
        import logging
        from logging import StreamHandler
        stream_handler = StreamHandler()
        stream_handler.setLevel(logging.INFO)
        app.logger.addHandler(stream_handler)


# Dictionary to map config names to classes
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'docker': DockerConfig,
    'default': DevelopmentConfig
}
