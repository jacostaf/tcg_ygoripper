"""
Configuration Module

Centralizes all configuration settings, environment variables, and constants
used throughout the YGO API application.
"""

import os
from typing import Optional

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# YGO API Configuration
YGO_API_BASE_URL = "https://db.ygoprodeck.com/api/v7"

# MongoDB Configuration
MONGODB_CONNECTION_STRING = os.getenv('MONGODB_CONNECTION_STRING')
MONGODB_COLLECTION_NAME = "YGO_SETS_CACHE_V1"
MONGODB_CARD_VARIANTS_COLLECTION = "YGO_CARD_VARIANT_CACHE_V1"

# MongoDB connection settings
MONGODB_CONNECT_TIMEOUT_MS = 60000
MONGODB_SERVER_SELECTION_TIMEOUT_MS = 30000

# TCGPlayer Search Optimization Configuration
# Can be overridden via environment variables for fine-tuning
TCGPLAYER_MAX_PREFERRED_RESULTS = int(os.getenv('TCGPLAYER_MAX_PREFERRED_RESULTS', '50'))
TCGPLAYER_MAX_ACCEPTABLE_RESULTS = int(os.getenv('TCGPLAYER_MAX_ACCEPTABLE_RESULTS', '200'))
TCGPLAYER_DEFAULT_VARIANT_LIMIT = int(os.getenv('TCGPLAYER_DEFAULT_VARIANT_LIMIT', '100'))
TCGPLAYER_EARLY_TERMINATION_SCORE = int(os.getenv('TCGPLAYER_EARLY_TERMINATION_SCORE', '800'))
TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION = int(os.getenv('TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION', '10'))

# Price Scraping Configuration
PRICE_CACHE_EXPIRY_DAYS = 7
PRICE_SCRAPING_TIMEOUT_SECONDS = 30
PRICE_SCRAPING_MAX_RETRIES = 3
PRICE_SCRAPING_RETRY_DELAY = 5

# Price Cache Collection
PRICE_CACHE_COLLECTION = "YGO_PRICE_CACHE_V1"

# Rate Limiting Configuration
API_RATE_LIMIT_DELAY = 0.1  # 100ms delay between requests (20 req/sec max)
BATCH_SIZE = 100  # Default batch size for bulk operations

# Memory Management Configuration
MEM_LIMIT_MB = int(os.getenv('MEM_LIMIT', '512'))
MEMORY_WARNING_THRESHOLD = 0.8

# Application Configuration
ALLOW_START_WITHOUT_DATABASE = os.getenv('ALLOW_START_WITHOUT_DATABASE', '0') == '1'
MEMORY_CRITICAL_THRESHOLD = 0.9

# Application Configuration
DEFAULT_PORT = int(os.getenv("PORT", 8081))
DEBUG_MODE = os.getenv("DEBUG", "true").lower() == "true"

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Selenium/Playwright Configuration for price scraping
SELENIUM_HEADLESS = os.getenv("SELENIUM_HEADLESS", "true").lower() == "true"
SELENIUM_TIMEOUT = int(os.getenv("SELENIUM_TIMEOUT", "30"))
SELENIUM_IMPLICIT_WAIT = int(os.getenv("SELENIUM_IMPLICIT_WAIT", "10"))

# TCGPlayer specific configuration
TCGPLAYER_BASE_URL = "https://www.tcgplayer.com"
TCGPLAYER_SEARCH_PATH = "/search/yugioh/product"

# Card processing configuration
CARD_PROCESSING_BATCH_SIZE = int(os.getenv("CARD_PROCESSING_BATCH_SIZE", "100"))
CARD_PROCESSING_DELAY = float(os.getenv("CARD_PROCESSING_DELAY", "0.1"))

def get_mongodb_connection_string() -> Optional[str]:
    """Get MongoDB connection string from environment."""
    return MONGODB_CONNECTION_STRING

def get_port() -> int:
    """Get application port from environment."""
    return DEFAULT_PORT

def get_debug_mode() -> bool:
    """Get debug mode setting."""
    return DEBUG_MODE

def get_memory_limit_mb() -> int:
    """Get memory limit in MB."""
    return MEM_LIMIT_MB

def is_production() -> bool:
    """Check if running in production environment."""
    return os.getenv("ENVIRONMENT", "development").lower() == "production"

def get_log_level() -> str:
    """Get logging level."""
    return LOG_LEVEL

# Validation
def validate_config() -> bool:
    """
    Validate essential configuration settings.
    
    Returns:
        bool: True if configuration is valid, False otherwise
    """
    if not MONGODB_CONNECTION_STRING:
        print("ERROR: MONGODB_CONNECTION_STRING environment variable is required")
        return False
    
    if MEM_LIMIT_MB <= 0:
        print("ERROR: MEM_LIMIT must be a positive number")
        return False
    
    return True