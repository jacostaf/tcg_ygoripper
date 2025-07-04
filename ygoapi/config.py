"""
Configuration management for YGO API

Centralized configuration handling with environment variable support.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# YGO API Configuration
YGO_API_BASE_URL = "https://db.ygoprodeck.com/api/v7"

# MongoDB Configuration
MONGODB_CONNECTION_STRING = os.getenv('MONGODB_CONNECTION_STRING')
MONGODB_COLLECTION_NAME = "YGO_SETS_CACHE_V1"
MONGODB_CARD_VARIANTS_COLLECTION = "YGO_CARD_VARIANT_CACHE_V1"
PRICE_CACHE_COLLECTION = "YGO_PRICE_CACHE_V1"

# Cache Configuration
CACHE_EXPIRY_DAYS = int(os.getenv('CACHE_EXPIRY_DAYS', '7'))

# TCGPlayer Configuration
TCGPLAYER_MAX_PREFERRED_RESULTS = int(os.getenv('TCGPLAYER_MAX_PREFERRED_RESULTS', '50'))
TCGPLAYER_MAX_ACCEPTABLE_RESULTS = int(os.getenv('TCGPLAYER_MAX_ACCEPTABLE_RESULTS', '200'))
TCGPLAYER_DEFAULT_VARIANT_LIMIT = int(os.getenv('TCGPLAYER_DEFAULT_VARIANT_LIMIT', '100'))
TCGPLAYER_EARLY_TERMINATION_SCORE = int(os.getenv('TCGPLAYER_EARLY_TERMINATION_SCORE', '800'))
TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION = int(os.getenv('TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION', '10'))

# Memory Management Configuration
MEM_LIMIT = int(os.getenv('MEM_LIMIT', '512'))  # Memory limit in MB
MEM_CHECK_INTERVAL = int(os.getenv('MEM_CHECK_INTERVAL', '30'))  # Check interval in seconds
MEM_WARNING_THRESHOLD = float(os.getenv('MEM_WARNING_THRESHOLD', '0.8'))  # Warning at 80% of limit
MEM_CRITICAL_THRESHOLD = float(os.getenv('MEM_CRITICAL_THRESHOLD', '0.95'))  # Critical at 95% of limit

# Application Configuration
DEBUG_MODE = os.getenv('DEBUG_MODE', 'false').lower() == 'true'
PORT = int(os.getenv("PORT", 8081))