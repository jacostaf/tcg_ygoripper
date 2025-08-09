"""
TCGcsv Implementation Configuration
Simplified configuration for TCGcsv-only data source without MongoDB
"""

import os
import json
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.development')

# =============================================================================
# CORE APPLICATION SETTINGS
# =============================================================================

# Server Configuration
PORT = int(os.getenv("PORT", 8081))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# =============================================================================
# TCGCSV CONFIGURATION
# =============================================================================

# TCGcsv Base Configuration
TCGCSV_BASE_URL = os.getenv("TCGCSV_BASE_URL", "https://tcgcsv.com")
YUGIOH_CATEGORY_ID = int(os.getenv("YUGIOH_CATEGORY_ID", 2))

# Data URLs (constructed from base URL)
TCGCSV_GROUPS_URL = f"{TCGCSV_BASE_URL}/tcgplayer/{YUGIOH_CATEGORY_ID}/Groups.csv"
TCGCSV_PRODUCTS_URL_TEMPLATE = f"{TCGCSV_BASE_URL}/tcgplayer/{YUGIOH_CATEGORY_ID}/{{group_id}}/ProductsAndPrices.csv"

# =============================================================================
# CACHING CONFIGURATION (In-Memory Only)
# =============================================================================

# Cache Settings
CACHE_EXPIRY_HOURS = int(os.getenv("CACHE_EXPIRY_HOURS", 24))
CACHE_MAX_SIZE_MB = int(os.getenv("CACHE_MAX_SIZE_MB", 100))
AUTO_REFRESH_ENABLED = os.getenv("AUTO_REFRESH_ENABLED", "true").lower() == "true"
REFRESH_CHECK_INTERVAL_HOURS = int(os.getenv("REFRESH_CHECK_INTERVAL_HOURS", 6))

# =============================================================================
# CARD IMAGE CONFIGURATION
# =============================================================================

# Image Sources
USE_TCGCSV_IMAGES = os.getenv("USE_TCGCSV_IMAGES", "true").lower() == "true"
ENABLE_YGOPRODECK_IMAGE_FALLBACK = os.getenv("ENABLE_YGOPRODECK_IMAGE_FALLBACK", "true").lower() == "true"
YGOPRODECK_IMAGE_BASE_URL = os.getenv("YGOPRODECK_IMAGE_BASE_URL", "https://images.ygoprodeck.com/images/cards")

# Image Processing
IMAGE_CACHE_ENABLED = os.getenv("IMAGE_CACHE_ENABLED", "true").lower() == "true"
IMAGE_CACHE_DURATION_HOURS = int(os.getenv("IMAGE_CACHE_DURATION_HOURS", 168))  # 1 week

# =============================================================================
# PERFORMANCE & RATE LIMITING
# =============================================================================

# API Rate Limiting
API_RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", 60))
API_RATE_LIMIT_BURST = int(os.getenv("API_RATE_LIMIT_BURST", 10))

# Download Settings
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", 300))
DOWNLOAD_RETRY_ATTEMPTS = int(os.getenv("DOWNLOAD_RETRY_ATTEMPTS", 3))
DOWNLOAD_RETRY_DELAY_SECONDS = int(os.getenv("DOWNLOAD_RETRY_DELAY_SECONDS", 5))

# Processing Limits
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 5))
BATCH_PROCESSING_SIZE = int(os.getenv("BATCH_PROCESSING_SIZE", 1000))

# =============================================================================
# CORS & SECURITY
# =============================================================================

# CORS Configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:7001,http://127.0.0.1:7001,http://localhost:3000,http://127.0.0.1:3000,https://ygopwa.onrender.com").split(",")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"

# Security
ENABLE_SECURITY_HEADERS = os.getenv("ENABLE_SECURITY_HEADERS", "true").lower() == "true"

# =============================================================================
# DATA PROCESSING CONFIGURATION
# =============================================================================

# Card Filtering
EXCLUDE_SEALED_PRODUCTS = os.getenv("EXCLUDE_SEALED_PRODUCTS", "true").lower() == "true"
EXCLUDE_ACCESSORIES = os.getenv("EXCLUDE_ACCESSORIES", "true").lower() == "true"
INCLUDE_VARIANT_ARTS = os.getenv("INCLUDE_VARIANT_ARTS", "true").lower() == "true"

# Set Filtering
EXCLUDE_PROMOTIONAL_SETS = os.getenv("EXCLUDE_PROMOTIONAL_SETS", "false").lower() == "true"
EXCLUDE_TOURNAMENT_PACKS = os.getenv("EXCLUDE_TOURNAMENT_PACKS", "false").lower() == "true"
MIN_CARDS_PER_SET = int(os.getenv("MIN_CARDS_PER_SET", 1))

# Rarity Processing
NORMALIZE_RARITY_NAMES = os.getenv("NORMALIZE_RARITY_NAMES", "true").lower() == "true"
CUSTOM_RARITY_MAPPINGS_STR = os.getenv("CUSTOM_RARITY_MAPPINGS", '{}')
try:
    CUSTOM_RARITY_MAPPINGS = json.loads(CUSTOM_RARITY_MAPPINGS_STR)
except json.JSONDecodeError:
    CUSTOM_RARITY_MAPPINGS = {}

# =============================================================================
# PRICE DATA CONFIGURATION
# =============================================================================

# Price Settings
INCLUDE_PRICE_DATA = os.getenv("INCLUDE_PRICE_DATA", "true").lower() == "true"
PRICE_CACHE_DURATION_HOURS = int(os.getenv("PRICE_CACHE_DURATION_HOURS", 24))

# Price Filtering
MIN_PRICE_THRESHOLD = float(os.getenv("MIN_PRICE_THRESHOLD", 0.01))
MAX_PRICE_THRESHOLD = float(os.getenv("MAX_PRICE_THRESHOLD", 10000.00))
EXCLUDE_NO_PRICE_CARDS = os.getenv("EXCLUDE_NO_PRICE_CARDS", "false").lower() == "true"

# Price Calculation
USE_MARKET_PRICE_AS_PRIMARY = os.getenv("USE_MARKET_PRICE_AS_PRIMARY", "true").lower() == "true"
FALLBACK_TO_MIDPRICE = os.getenv("FALLBACK_TO_MIDPRICE", "true").lower() == "true"

# =============================================================================
# STORAGE CONFIGURATION (No MongoDB)
# =============================================================================

# Disk Persistence (Optional)
ENABLE_DISK_PERSISTENCE = os.getenv("ENABLE_DISK_PERSISTENCE", "true").lower() == "true"
DATA_STORAGE_PATH = os.getenv("DATA_STORAGE_PATH", "./data/")
BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", 24))
MAX_BACKUP_FILES = int(os.getenv("MAX_BACKUP_FILES", 7))

# =============================================================================
# FEATURE FLAGS
# =============================================================================

# Debug Features
ENABLE_DEBUG_ENDPOINTS = os.getenv("ENABLE_DEBUG_ENDPOINTS", "false").lower() == "true"
MOCK_TCGCSV_DATA = os.getenv("MOCK_TCGCSV_DATA", "false").lower() == "true"

# Enhanced Features
ENABLE_ADVANCED_SEARCH = os.getenv("ENABLE_ADVANCED_SEARCH", "true").lower() == "true"
ENABLE_SET_STATISTICS = os.getenv("ENABLE_SET_STATISTICS", "true").lower() == "true"
ENABLE_BULK_OPERATIONS = os.getenv("ENABLE_BULK_OPERATIONS", "true").lower() == "true"

# Fallback Options
ENABLE_YGOPRODECK_FALLBACK = os.getenv("ENABLE_YGOPRODECK_FALLBACK", "false").lower() == "true"
YGOPRODECK_API_BASE_URL = os.getenv("YGOPRODECK_API_BASE_URL", "https://db.ygoprodeck.com/api/v7")

# =============================================================================
# MEMORY MANAGEMENT
# =============================================================================

MEMORY_LIMIT_MB = int(os.getenv("MEMORY_LIMIT_MB", 512))
MEMORY_WARNING_THRESHOLD = float(os.getenv("MEMORY_WARNING_THRESHOLD", 0.8))
MEMORY_CRITICAL_THRESHOLD = float(os.getenv("MEMORY_CRITICAL_THRESHOLD", 0.9))

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_tcgcsv_products_url(group_id: int) -> str:
    """Get the TCGcsv URL for a specific group's products."""
    return TCGCSV_PRODUCTS_URL_TEMPLATE.format(group_id=group_id)

def get_cors_origins() -> list:
    """Get CORS origins as a list."""
    return [origin.strip() for origin in CORS_ORIGINS if origin.strip()]

def get_data_storage_path() -> str:
    """Get the data storage path, creating directory if needed."""
    import os
    path = DATA_STORAGE_PATH
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path

def is_development() -> bool:
    """Check if running in development mode."""
    return ENVIRONMENT.lower() == "development"

def is_production() -> bool:
    """Check if running in production mode."""
    return ENVIRONMENT.lower() == "production"

# =============================================================================
# CONFIGURATION VALIDATION
# =============================================================================

def validate_config() -> Dict[str, Any]:
    """Validate configuration and return any issues."""
    issues = []
    warnings = []
    
    # Check required settings
    if not TCGCSV_BASE_URL:
        issues.append("TCGCSV_BASE_URL is required")
    
    if YUGIOH_CATEGORY_ID <= 0:
        issues.append("YUGIOH_CATEGORY_ID must be positive")
    
    # Check memory limits
    if MEMORY_LIMIT_MB < 64:
        warnings.append("MEMORY_LIMIT_MB is very low (< 64MB)")
    
    # Check cache settings
    if CACHE_EXPIRY_HOURS < 1:
        warnings.append("CACHE_EXPIRY_HOURS is very low")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings
    }

# Print configuration summary if run directly
if __name__ == "__main__":
    validation = validate_config()
    print("TCGcsv Configuration Summary:")
    print(f"  Environment: {ENVIRONMENT}")
    print(f"  Port: {PORT}")
    print(f"  TCGcsv URL: {TCGCSV_BASE_URL}")
    print(f"  Yu-Gi-Oh Category: {YUGIOH_CATEGORY_ID}")
    print(f"  Cache Expiry: {CACHE_EXPIRY_HOURS} hours")
    print(f"  Memory Limit: {MEMORY_LIMIT_MB} MB")
    print(f"  Data Storage: {DATA_STORAGE_PATH}")
    
    if validation["warnings"]:
        print("\nWarnings:")
        for warning in validation["warnings"]:
            print(f"  - {warning}")
    
    if not validation["valid"]:
        print("\nErrors:")
        for issue in validation["issues"]:
            print(f"  - {issue}")
        exit(1)
    else:
        print("\nConfiguration is valid!")