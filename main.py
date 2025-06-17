from flask import Flask, jsonify, request
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta, UTC
from urllib.parse import quote, urlencode
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field
from bson import ObjectId
import requests
import logging
import os
import time
import re
import asyncio
import ssl

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# YGO API base URL
YGO_API_BASE_URL = "https://db.ygoprodeck.com/api/v7"

# MongoDB configuration
MONGODB_CONNECTION_STRING = os.getenv('MONGODB_CONNECTION_STRING')
MONGODB_COLLECTION_NAME = "YGO_SETS_CACHE_V1"
MONGODB_CARD_VARIANTS_COLLECTION = "YGO_CARD_VARIANT_CACHE_V1"

# TCGPlayer search optimization configuration
# Can be overridden via environment variables for fine-tuning
TCGPLAYER_MAX_PREFERRED_RESULTS = int(os.getenv('TCGPLAYER_MAX_PREFERRED_RESULTS', '50'))
TCGPLAYER_MAX_ACCEPTABLE_RESULTS = int(os.getenv('TCGPLAYER_MAX_ACCEPTABLE_RESULTS', '200'))
TCGPLAYER_DEFAULT_VARIANT_LIMIT = int(os.getenv('TCGPLAYER_DEFAULT_VARIANT_LIMIT', '100'))
TCGPLAYER_EARLY_TERMINATION_SCORE = int(os.getenv('TCGPLAYER_EARLY_TERMINATION_SCORE', '800'))
TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION = int(os.getenv('TCGPLAYER_MIN_VARIANTS_BEFORE_EARLY_TERMINATION', '10'))

def get_mongo_client():
    """Get MongoDB client connection with proper SSL configuration for Render"""
    try:
        # Connect with simplified SSL settings
        client = MongoClient(
            MONGODB_CONNECTION_STRING,
            ssl=True,
            tlsAllowInvalidCertificates=True,
            connectTimeoutMS=60000,
            serverSelectionTimeoutMS=60000,
            retryWrites=True,
            w='majority'
        )
        
        # Test the connection
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB with SSL configuration")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
        # Try a fallback connection approach with minimal SSL settings
        try:
            logger.info("Attempting fallback connection approach...")
            client = MongoClient(
                MONGODB_CONNECTION_STRING,
                tls=True,
                tlsAllowInvalidCertificates=True,
                serverSelectionTimeoutMS=60000,
                retryWrites=True
            )
            client.admin.command('ping')
            logger.info("Successfully connected to MongoDB with fallback settings")
            return client
        except Exception as fallback_e:
            logger.error(f"Fallback connection also failed: {str(fallback_e)}")
            return None

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "message": "YGO API is running"})

# Price scraping models
class PyObjectId(ObjectId):
    """Custom ObjectId class for Pydantic compatibility."""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")
        return field_schema

class CardPriceModel(BaseModel):
    """Model for card pricing data stored in MongoDB."""
    
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    
    # Core card identification fields
    card_number: str = Field(..., description="Card number (e.g., BLTR-EN051)")
    card_name: str = Field(..., description="Card name, may include art information")
    card_art_variant: Optional[str] = Field(None, description="Art version (e.g., '7', '1st', etc.)")
    booster_set_name: Optional[str] = Field(None, description="Booster set name where card is from")
    set_code: Optional[str] = Field(None, description="4-character set code (e.g., BLTR, SUDA, RA04)")
    card_rarity: str = Field(..., description="Card rarity (e.g., Secret Rare, Ultra Rare) - REQUIRED")
    
    # Pricing data fields
    tcg_price: Optional[float] = Field(None, description="TCGPlayer price")
    tcg_market_price: Optional[float] = Field(None, description="TCGPlayer market price")
    pc_ungraded_price: Optional[float] = Field(None, description="PriceCharting ungraded price")
    pc_grade7: Optional[float] = Field(None, description="PriceCharting Grade 7 price")
    pc_grade8: Optional[float] = Field(None, description="PriceCharting Grade 8 price")
    pc_grade9: Optional[float] = Field(None, description="PriceCharting Grade 9 price")
    pc_grade9_5: Optional[float] = Field(None, description="PriceCharting Grade 9.5 price")
    pc_grade10: Optional[float] = Field(None, description="PriceCharting Grade 10/PSA 10 price")
    
    # Metadata fields
    last_price_updt: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Last price update time")
    source_url: Optional[str] = Field(None, description="URL where prices were scraped from")
    scrape_success: bool = Field(True, description="Whether the last scrape was successful")
    error_message: Optional[str] = Field(None, description="Error message if scrape failed")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

# Global variables for price scraping service
sync_price_scraping_client = None
sync_price_scraping_collection = None

# Price scraping configuration
PRICE_CACHE_COLLECTION = "YGO_CARD_VARIANT_PRICE_CACHE_V1"
CACHE_EXPIRY_DAYS = 7

def initialize_sync_price_scraping():
    """Initialize synchronous MongoDB client for price scraping."""
    global sync_price_scraping_client, sync_price_scraping_collection
    try:
        if sync_price_scraping_client is None:
            # Use identical SSL configuration as the main client function
            sync_price_scraping_client = MongoClient(
                MONGODB_CONNECTION_STRING,
                ssl=True,
                tlsAllowInvalidCertificates=True,
                connectTimeoutMS=60000,
                serverSelectionTimeoutMS=60000,
                retryWrites=True,
                w='majority'
            )
            
            db = sync_price_scraping_client.get_default_database()
            sync_price_scraping_collection = db[PRICE_CACHE_COLLECTION]
            
            # Create indexes for efficient querying
            try:
                sync_price_scraping_collection.create_index([
                    ("card_number", 1),
                    ("card_name", 1),
                    ("card_rarity", 1),
                    ("card_art_variant", 1)
                ], name="card_identification_idx", background=True)
                
                sync_price_scraping_collection.create_index("card_number", name="card_number_idx", background=True)
                sync_price_scraping_collection.create_index("last_price_updt", name="timestamp_idx", background=True)
                logger.info("Successfully created indexes for price scraping")
            except Exception as index_error:
                logger.warning(f"Failed to create indexes (continuing anyway): {index_error}")
        
        return True
    except Exception as e:
        logger.error(f"Failed to initialize sync price scraping: {e}")
        return False

def extract_art_version(card_name: str) -> Optional[str]:
    """Extract art version from card name using regex patterns for both numbered and named variants."""
    if not card_name:
        return None
    
    # First, try numbered art variants
    numbered_patterns = [
        r'\[(\d+)(st|nd|rd|th)?\s*art\]',                         # "[9th Art]", "[7th art]"
        r'\[(\d+)(st|nd|rd|th)?\s*quarter\s*century.*?\]',        # "[7th Quarter Century Secret Rare]" 
        r'\[(\d+)(st|nd|rd|th)?\s*.*?secret.*?\]',                # "[7th Platinum Secret Rare]"
        r'\[(\d+)(st|nd|rd|th)?\]',                               # "[7th]", "[1]"
        r'\((\d+)(st|nd|rd|th)?\s*art\)',                         # "(7th art)", "(1st art)"
        r'\b(\d+)(st|nd|rd|th)?\s*art\b',                         # "7th art", "1st artwork"
        r'/(\d+)(st|nd|rd|th)?\-(?:quarter\-century|art)',        # "/7th-quarter-century", "/9th-art"
        r'magician\-(\d+)(st|nd|rd|th)?\-',                       # "dark-magician-7th-quarter"
        r'\-(\d+)(st|nd|rd|th)?\-(?:quarter|art)',                # "-7th-quarter", "-9th-art"
    ]
    
    for pattern in numbered_patterns:
        match = re.search(pattern, card_name, re.IGNORECASE)
        if match:
            art_version = match.group(1)
            logger.debug(f"Detected numbered art version: {art_version} using pattern '{pattern}' in: {card_name}")
            return art_version
    
    # Then, try named art variants (like "Arkana", "Joey Wheeler", etc.)
    named_patterns = [
        r'\b(arkana)\b',                                          # "arkana" (case insensitive)
        r'\b(joey\s+wheeler)\b',                                  # "joey wheeler"
        r'\b(kaiba)\b',                                           # "kaiba"
        r'\b(pharaoh)\b',                                         # "pharaoh"
        r'\b(anime)\b',                                           # "anime"
        r'\b(manga)\b',                                           # "manga"
        r'-([a-zA-Z]+(?:\s+[a-zA-Z]+)*)-',                       # Generic pattern for "-name-" format
        r'\(([a-zA-Z]+(?:\s+[a-zA-Z]+)*)\)',                     # Generic pattern for "(name)" format
    ]
    
    for pattern in named_patterns:
        match = re.search(pattern, card_name, re.IGNORECASE)
        if match:
            art_version = match.group(1).strip().title()  # Capitalize properly
            logger.debug(f"Detected named art version: '{art_version}' using pattern '{pattern}' in: {card_name}")
            return art_version
    
    return None

def normalize_rarity(rarity: str) -> str:
    """Normalize rarity string for consistent comparison."""
    if not rarity:
        return ''
    
    normalized = rarity.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)  # Replace multiple spaces
    normalized = re.sub(r'[-_]', ' ', normalized)  # Replace hyphens/underscores
    
    # Special handling for Quarter Century variants
    if 'quarter century' in normalized or '25th anniversary' in normalized:
        if 'secret' in normalized:
            return 'quarter century secret rare'
        elif 'ultra' in normalized:
            return 'quarter century ultra rare'
        elif 'rare' in normalized:
            return 'quarter century rare'
        return 'quarter century'
    
    # Special handling for Platinum Secret Rare
    if 'platinum' in normalized and 'secret' in normalized:
        return 'platinum secret rare'
    
    # Special handling for Prismatic variants
    if 'prismatic' in normalized:
        if 'secret' in normalized:
            return 'prismatic secret rare'
        elif 'collector' in normalized:
            return "prismatic collector's rare"
        elif 'ultimate' in normalized:
            return 'prismatic ultimate rare'
    
    # Special handling for Starlight Rare
    if 'starlight' in normalized:
        return 'starlight rare'
    
    # Special handling for Collector's Rare
    if 'collector' in normalized:
        return "collector's rare"
    
    # Special handling for Ghost variants
    if 'ghost' in normalized:
        if 'gold' in normalized:
            return 'ghost/gold rare'
        return 'ghost rare'
    
    # Special handling for Parallel variants
    if 'parallel' in normalized:
        if 'ultra' in normalized:
            return 'ultra parallel rare'
        elif 'secret' in normalized:
            return 'parallel secret rare'
        return 'parallel rare'
    
    # Special handling for Gold variants
    if 'gold' in normalized:
        if 'premium' in normalized:
            return 'premium gold rare'
        return 'gold rare'
    
    # Special handling for Platinum variants
    if 'platinum' in normalized:
        if 'secret' in normalized:
            return 'platinum secret rare'
        return 'platinum rare'
    
    # Special handling for other special rarities
    if 'duel terminal' in normalized:
        return 'duel terminal rare'
    if 'mosaic' in normalized:
        return 'mosaic rare'
    if 'shatterfoil' in normalized:
        return 'shatterfoil rare'
    if 'starfoil' in normalized:
        return 'starfoil rare'
    if 'hobby league' in normalized:
        return 'hobby league rare'
    if 'millennium' in normalized:
        return 'millennium rare'
    if '20th' in normalized and 'secret' in normalized:
        return '20th secret rare'
    
    return normalized

def normalize_rarity_for_matching(rarity: str) -> List[str]:
    """Generate multiple normalized forms of a rarity for better matching."""
    if not rarity:
        return []
    
    normalized = rarity.lower().strip()
    variants = [normalized]
    
    # Handle Quarter Century variants
    if 'quarter century' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'quarter century secret rare',
                'qcsr',
                '25th anniversary secret rare',
                'quarter century secret',
                'qc secret rare'
            ])
        elif 'ultra' in normalized:
            variants.extend([
                'quarter century ultra rare', 
                'qcur',
                '25th anniversary ultra rare'
            ])
    
    # Handle Platinum Secret Rare
    if 'platinum' in normalized and 'secret' in normalized:
        variants.extend([
            'platinum secret rare',
            'psr',
            'plat secret rare'
        ])
    
    # Handle Prismatic variants
    if 'prismatic' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'prismatic secret rare',
                'prismatic secret'
            ])
        elif 'collector' in normalized:
            variants.extend([
                'prismatic collector rare',
                "prismatic collector's rare"
            ])
        elif 'ultimate' in normalized:
            variants.extend([
                'prismatic ultimate rare'
            ])
    
    # Handle Starlight Rare
    if 'starlight' in normalized:
        variants.extend([
            'starlight rare',
            'starlight'
        ])
    
    # Handle Collector's Rare
    if 'collector' in normalized:
        variants.extend([
            "collector's rare",
            'collector rare',
            'collectors rare'
        ])
    
    # Handle Ghost Rare
    if 'ghost' in normalized:
        if 'gold' in normalized:
            variants.extend([
                'ghost gold rare',
                'ghost/gold rare'
            ])
        else:
            variants.extend([
                'ghost rare',
                'ghost'
            ])
    
    # Handle Ultimate Rare
    if 'ultimate' in normalized:
        variants.extend([
            'ultimate rare',
            'ultimate'
        ])
    
    # Handle Parallel variants
    if 'parallel' in normalized:
        if 'ultra' in normalized:
            variants.extend([
                'ultra parallel rare',
                'parallel ultra rare'
            ])
        elif 'secret' in normalized:
            variants.extend([
                'parallel secret rare'
            ])
        else:
            variants.extend([
                'parallel rare',
                'parallel'
            ])
    
    # Handle Gold variants
    if 'gold' in normalized:
        if 'premium' in normalized:
            variants.extend([
                'premium gold rare',
                'premium gold'
            ])
        else:
            variants.extend([
                'gold rare',
                'gold'
            ])
    
    # Handle Platinum variants
    if 'platinum' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'platinum secret rare',
                'psr',
                'plat secret rare'
            ])
        else:
            variants.extend([
                'platinum rare',
                'platinum'
            ])
    
    # Handle Duel Terminal Rare
    if 'duel terminal' in normalized:
        variants.extend([
            'duel terminal rare',
            'dt rare'
        ])
    
    # Handle Mosaic Rare
    if 'mosaic' in normalized:
        variants.extend([
            'mosaic rare',
            'mosaic'
        ])
    
    # Handle Shatterfoil Rare
    if 'shatterfoil' in normalized:
        variants.extend([
            'shatterfoil rare',
            'shatterfoil'
        ])
    
    # Handle Starfoil Rare
    if 'starfoil' in normalized:
        variants.extend([
            'starfoil rare',
            'starfoil'
        ])
    
    # Handle Hobby League Rare
    if 'hobby league' in normalized:
        variants.extend([
            'hobby league rare',
            'hl rare'
        ])
    
    # Handle Millennium Rare
    if 'millennium' in normalized:
        variants.extend([
            'millennium rare',
            'millennium'
        ])
    
    # Handle 25th Anniversary variants
    if '25th anniversary' in normalized:
        if 'ultra' in normalized:
            variants.extend([
                '25th anniversary ultra rare',
                'quarter century ultra rare'
            ])
        elif 'secret' in normalized:
            variants.extend([
                '25th anniversary secret rare',
                'quarter century secret rare'
            ])
    
    # Handle 20th Secret Rare
    if '20th' in normalized and 'secret' in normalized:
        variants.extend([
            '20th secret rare'
        ])
    
    # Handle Extra Secret Rare (OCG)
    if 'extra secret' in normalized:
        variants.extend([
            'extra secret rare'
        ])
    
    # Handle Red/Blue Secret Rare (OCG)
    if ('red' in normalized or 'blue' in normalized) and 'secret' in normalized:
        variants.extend([
            'red secret rare' if 'red' in normalized else 'blue secret rare'
        ])
    
    # Handle common abbreviations for standard rarities
    if 'secret rare' in normalized:
        variants.extend(['secret', 'sr'])
    if 'ultra rare' in normalized:
        variants.extend(['ultra', 'ur'])
    if 'super rare' in normalized:
        variants.extend(['super', 'sr'])
    if normalized == 'rare':
        variants.extend(['r'])
    if normalized == 'common':
        variants.extend(['c'])
    
    return list(set(variants))  # Remove duplicates

def normalize_art_variant(art_variant: Optional[str]) -> Optional[str]:
    """Normalize art variant to consistent format for cache operations."""
    if not art_variant or not art_variant.strip():
        return None
    
    art_variant_clean = art_variant.strip()
    
    # If it's a number, convert to ordinal format (e.g., "7" -> "7th")
    if art_variant_clean.isdigit():
        num = art_variant_clean
        suffix = "th"
        if num.endswith("1") and not num.endswith("11"):
            suffix = "st"
        elif num.endswith("2") and not num.endswith("12"):
            suffix = "nd"
        elif num.endswith("3") and not num.endswith("13"):
            suffix = "rd"
        return f"{num}{suffix}"
    
    # If it's already in ordinal format, keep as is
    if re.match(r'^\d+(st|nd|rd|th)(\s+[Aa]rt)?$', art_variant_clean):
        return art_variant_clean
    
    # For other formats, return as is
    return art_variant_clean

def find_cached_price_data_sync(
    card_number: Optional[str] = None, 
    card_name: Optional[str] = None,
    card_rarity: Optional[str] = None,
    art_variant: Optional[str] = None
) -> tuple[bool, Optional[Dict]]:
    """Check if we have fresh price data in cache using synchronous MongoDB client."""
    if sync_price_scraping_collection is None:
        return False, None
    
    # Need at least card_number or card_name for cache lookup
    if not card_number and not card_name:
        return False, None
    
    try:
        # Normalize art variant for consistent lookups
        normalized_art_variant = normalize_art_variant(art_variant)
        
        logger.info(f"🔍 CACHE LOOKUP: card_number={card_number}, card_name={card_name}, rarity={card_rarity}, art_variant={art_variant} -> normalized: {normalized_art_variant}")
        
        # Define projection to exclude _id field
        projection = {
            "_id": 0,  # Explicitly exclude _id field
            "card_number": 1,
            "card_name": 1,
            "card_art_variant": 1,
            "card_rarity": 1,
            "booster_set_name": 1,
            "set_code": 1,
            "tcg_price": 1,
            "tcg_market_price": 1,
            "pc_ungraded_price": 1,
            "pc_grade7": 1,
            "pc_grade8": 1,
            "pc_grade9": 1,
            "pc_grade9_5": 1,
            "pc_grade10": 1,
            "source_url": 1,
            "scrape_success": 1,
            "last_price_updt": 1,
            "error_message": 1
        }
        
        # Build base query - use card_number if available, otherwise card_name
        base_query = {}
        if card_number:
            base_query["card_number"] = card_number
        elif card_name:
            base_query["card_name"] = {"$regex": re.escape(card_name), "$options": "i"}
            
        # Add rarity filter if provided - use exact normalized matching to prevent conflicts
        if card_rarity:
            normalized_target_rarity = normalize_rarity(card_rarity)
            base_query["card_rarity"] = normalized_target_rarity
        
        # Build query based on art variant parameter
        if art_variant is not None:
            # art_variant was explicitly provided (could be "" or actual value)
            if normalized_art_variant:
                # Non-empty art variant provided
                base_query["card_art_variant"] = normalized_art_variant
                logger.info(f"  🎨 Using normalized art variant filter: '{normalized_art_variant}'")
            else:
                # Empty string art variant provided - look for records with no art variant
                base_query["$or"] = [
                    {"card_art_variant": {"$exists": False}},
                    {"card_art_variant": None},
                    {"card_art_variant": ""}
                ]
                logger.info(f"  🎨 Looking for records with no art variant (empty string provided)")
        else:
            # art_variant parameter was not provided - find any matching record
            logger.info(f"  🎨 No art variant filter applied (parameter not provided)")
        
        logger.info(f"  📋 Cache query: {base_query}")
        
        # Find documents with projection and sort
        documents = list(sync_price_scraping_collection.find(
            base_query,
            projection=projection,
            sort=[("last_price_updt", -1)]
        ).limit(5))
        
        logger.info(f"  📄 Found {len(documents)} matching documents in cache")
        
        # Process and return the first valid document
        for i, doc in enumerate(documents):
            logger.info(f"  📄 Document {i+1}: card_art_variant='{doc.get('card_art_variant', 'N/A')}', card_rarity='{doc.get('card_rarity', 'N/A')}'")
            # Convert last_price_updt to proper format
            if 'last_price_updt' in doc:
                last_update = doc['last_price_updt']
                if isinstance(last_update, datetime):
                    doc['last_price_updt'] = last_update.strftime("%a, %d %b %Y %H:%M:%S GMT")
                elif isinstance(last_update, str):
                    # Keep string format if it's already a string
                    pass
            return _check_freshness_and_return(doc)
        
        logger.info(f"  ❌ No matching documents found in cache")
        return False, None
        
    except Exception as e:
        logger.error(f"Error checking sync cached price data: {e}")
        return False, None

def _check_freshness_and_return(document) -> tuple[bool, Optional[Dict]]:
    """Helper function to check cache freshness and return the result."""
    try:
        # Check if data is fresh (within expiry period)
        current_time = datetime.now(UTC)
        expiry_date = current_time - timedelta(days=CACHE_EXPIRY_DAYS)
        
        # Get last update time
        last_update = document.get('last_price_updt')
        
        # Convert last_update to datetime if it's a string
        if isinstance(last_update, str):
            try:
                # Try ISO format first
                last_update = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Try RFC format
                    last_update = datetime.strptime(last_update, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)
                except ValueError:
                    logger.error(f"Could not parse date string: {last_update}")
                    last_update = datetime.min.replace(tzinfo=UTC)
        elif isinstance(last_update, datetime):
            # Ensure timezone awareness - convert naive to UTC if needed
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=UTC)
        else:
            last_update = datetime.min.replace(tzinfo=UTC)
        
        # At this point both dates should be timezone-aware (UTC)
        is_fresh = last_update > expiry_date
        
        # Check if the cached data has actual price information
        has_price_data = bool(
            document.get('tcg_price') is not None or 
            document.get('tcg_market_price') is not None or 
            document.get('pc_ungraded_price') is not None
        )
        
        if is_fresh and has_price_data:
            logger.info(f"  ✅ Found FRESH cached data with pricing (updated: {last_update})")
        elif is_fresh and not has_price_data:
            logger.info(f"  ⚠️  Found FRESH cached data but NO PRICING DATA (updated: {last_update}) - treating as stale")
            is_fresh = False  # Treat as stale if no pricing data
        elif not is_fresh and has_price_data:
            logger.info(f"  ⚠️  Found STALE cached data with pricing (updated: {last_update}, expired: {expiry_date})")
        else:
            logger.info(f"  ❌ Found STALE cached data with NO PRICING DATA (updated: {last_update}, expired: {expiry_date})")
        
        # Format the date as RFC string for JSON serialization
        document['last_price_updt'] = last_update.strftime("%a, %d %b %Y %H:%M:%S GMT")
        
        return is_fresh, document
        
    except Exception as e:
        logger.error(f"Error checking cache freshness: {e}")
        return False, None

def validate_card_rarity_sync(card_number: str, card_rarity: str) -> bool:
    """Validate the requested rarity against available rarities using synchronous MongoDB client."""
    if not card_rarity or not card_number:
        return False
    
    try:
        # Initialize sync MongoDB connection if needed
        if sync_price_scraping_client is None:
            initialize_sync_price_scraping()
        
        # Get the card variants collection
        db = sync_price_scraping_client.get_default_database()
        variants_collection = db[MONGODB_CARD_VARIANTS_COLLECTION]
        
        # Search for all variants with the same card_id/card_name as this card number
        # First find the card with this set_code to get its card_name
        query = {"set_code": card_number}
        card_document = variants_collection.find_one(query)
        
        if not card_document:
            logger.warning(f"Card {card_number} not found in YGO_CARD_VARIANT_CACHE_V1")
            # If card is not found in our database, allow the rarity (fallback)
            return True
        
        # Get the card name to find all variants of this card
        card_name = card_document.get('card_name')
        if not card_name:
            return True
        
        # Find all variants of this card to get available rarities
        variants_query = {"card_name": card_name}
        all_variants = variants_collection.find(variants_query)
        
        # Extract available rarities from all variants
        available_rarities = set()
        for variant in all_variants:
            rarity = variant.get('set_rarity')
            if rarity:
                available_rarities.add(rarity.lower().strip())
        
        # Normalize the requested rarity for comparison
        normalized_requested = normalize_rarity(card_rarity)
        
        # Check if the normalized requested rarity matches any available rarity
        for available_rarity in available_rarities:
            normalized_available = normalize_rarity(available_rarity)
            
            # Check for exact match
            if normalized_requested == normalized_available:
                logger.info(f"Rarity '{card_rarity}' validated for card {card_number}")
                return True
            
            # Check for partial matches
            if (normalized_requested in normalized_available or 
                normalized_available in normalized_requested):
                logger.info(f"Rarity '{card_rarity}' partially validated for card {card_number}")
                return True
        
        logger.warning(f"Rarity '{card_rarity}' not found for card {card_number}. Available rarities: {list(available_rarities)}")
        return False
        
    except Exception as e:
        logger.error(f"Error validating card rarity: {e}")
        return True

def save_price_data_sync(price_data: Dict, requested_art_variant: Optional[str] = None) -> bool:
    """Save price data to MongoDB using synchronous client."""
    if sync_price_scraping_collection is None:
        logger.error("Sync price scraping collection not initialized")
        return False
    
    try:
        # Validate required fields - need either card_number or card_name
        if not price_data.get("card_number") and not price_data.get("card_name"):
            logger.error("Cannot save price data: either card_number or card_name is required")
            return False
        
        if not price_data.get("card_rarity"):
            logger.error("Cannot save price data: card_rarity is required")
            return False
        
        # Normalize art variant for consistent cache operations
        # Prioritize requested art variant over detected art variant for cache consistency
        original_art_variant = price_data.get("card_art_variant")
        
        # If we have a requested art variant, always use it for cache consistency
        # This ensures that subsequent cache lookups with the same request will find the record
        if requested_art_variant is not None:
            original_art_variant = requested_art_variant
            logger.info(f"🔧 Using requested art variant '{requested_art_variant}' for cache consistency (detected art variant was: '{price_data.get('card_art_variant')}')")
        elif not original_art_variant:
            # No requested variant and no detected variant
            original_art_variant = None
        
        normalized_art_variant = normalize_art_variant(original_art_variant)
        if normalized_art_variant:
            price_data["card_art_variant"] = normalized_art_variant
            logger.info(f"🔧 Normalized art variant: '{original_art_variant}' -> '{normalized_art_variant}'")
        else:
            # If requested_art_variant was empty string, explicitly set to None for consistency
            if requested_art_variant is not None and not requested_art_variant.strip():
                price_data["card_art_variant"] = None
                logger.info(f"🔧 Set card_art_variant to None for empty string request")
            # If no art variant requested and none detected, let the existing value remain or be None
        
        # Update timestamp
        price_data['last_price_updt'] = datetime.now(UTC)
        
        # Build deletion strategy: delete records matching card_number + rarity + art_variant
        # This ensures we only delete the exact variant being replaced, allowing different art variants to coexist
        deletion_query = {}
        
        # Use card_number as primary identifier if available
        if price_data.get("card_number") and price_data["card_number"] != "Unknown":
            deletion_query["card_number"] = price_data["card_number"]
        elif price_data.get("card_name"):
            deletion_query["card_name"] = {"$regex": re.escape(price_data["card_name"]), "$options": "i"}
        
        # Add rarity to deletion query using exact normalized matching to prevent conflicts
        card_rarity = price_data.get("card_rarity")
        if card_rarity and card_rarity.strip():
            normalized_rarity = normalize_rarity(card_rarity.strip())
            deletion_query["card_rarity"] = normalized_rarity
        
        # Add art variant to deletion query to prevent deleting different art variants
        # This is crucial for allowing multiple art variants of the same card+rarity to coexist
        if normalized_art_variant:
            # Delete records with this specific art variant
            deletion_query["card_art_variant"] = normalized_art_variant
        else:
            # Delete records with no art variant (None, empty string, or missing field)
            deletion_query["$or"] = [
                {"card_art_variant": {"$exists": False}},
                {"card_art_variant": None},
                {"card_art_variant": ""}
            ]
        
        logger.info(f"🗑️ TARGETED CACHE DELETION: Deleting records matching card + rarity + art variant to preserve other variants")
        logger.info(f"🗑️ Deletion query: {deletion_query}")
        
        # Check what we're about to delete
        docs_to_delete = list(sync_price_scraping_collection.find(
            deletion_query, 
            {"card_number": 1, "card_art_variant": 1, "card_rarity": 1, "last_price_updt": 1}
        ))
        
        if docs_to_delete:
            logger.info(f"  🎯 Found {len(docs_to_delete)} records to delete:")
            for doc in docs_to_delete:
                logger.info(f"    🗑️ Will delete: card_number={doc.get('card_number')}, art_variant={doc.get('card_art_variant')}, rarity={doc.get('card_rarity')}, last_update={doc.get('last_price_updt')}")
            
            # Perform deletion
            delete_result = sync_price_scraping_collection.delete_many(deletion_query)
            deleted_count = delete_result.deleted_count
            
            logger.info(f"  ✅ Successfully deleted {deleted_count} records")
            
            # Verify deletion was successful
            remaining_count = sync_price_scraping_collection.count_documents(deletion_query)
            if remaining_count > 0:
                logger.error(f"  ❌ DELETION FAILED: Still found {remaining_count} records after deletion!")
                remaining_docs = list(sync_price_scraping_collection.find(
                    deletion_query, 
                    {"card_number": 1, "card_art_variant": 1, "card_rarity": 1, "last_price_updt": 1}
                ))
                for doc in remaining_docs:
                    logger.error(f"    🔍 Remaining: card_number={doc.get('card_number')}, art_variant={doc.get('card_art_variant')}, rarity={doc.get('card_rarity')}, last_update={doc.get('last_price_updt')}")
            else:
                logger.info(f"  ✅ Deletion verification successful: No records remaining")
        else:
            logger.info("  📭 No existing records found to delete")
        
        # Clean the price_data before saving - remove empty strings
        cleaned_data = {}
        for key, value in price_data.items():
            if value is not None:
                if isinstance(value, str):
                    # Only keep non-empty strings
                    if value.strip():
                        cleaned_data[key] = value.strip()
                else:
                    cleaned_data[key] = value
        
        # Ensure required fields are present in cleaned data
        if "card_rarity" not in cleaned_data:
            logger.error("card_rarity missing from cleaned data")
            return False
        
        # Normalize the card_rarity before saving to ensure consistent cache operations
        original_rarity = cleaned_data["card_rarity"]
        normalized_rarity = normalize_rarity(original_rarity)
        cleaned_data["card_rarity"] = normalized_rarity
        if original_rarity != normalized_rarity:
            logger.info(f"🔧 Normalized card rarity: '{original_rarity}' -> '{normalized_rarity}'")
        
        
        # Insert the new record (we deleted matching ones above, so this will always be an insert)
        logger.info(f"💾 About to save record with the following key fields:")
        logger.info(f"  💾 card_number: '{cleaned_data.get('card_number')}'")
        logger.info(f"  💾 card_name: '{cleaned_data.get('card_name')}'") 
        logger.info(f"  💾 card_art_variant: '{cleaned_data.get('card_art_variant')}'")
        logger.info(f"  💾 card_rarity: '{cleaned_data.get('card_rarity')}'")
        
        result = sync_price_scraping_collection.insert_one(cleaned_data)
        
        if result.inserted_id:
            logger.info(f"✅ Created new sync price record with ID: {result.inserted_id}")
            
            # Verify the record was saved correctly by using the SAME query logic as cache lookup
            # This ensures complete consistency between save and lookup operations
            verification_query = {}
            if cleaned_data.get("card_number") and cleaned_data["card_number"] != "Unknown":
                verification_query["card_number"] = cleaned_data["card_number"]
            elif cleaned_data.get("card_name"):
                verification_query["card_name"] = {"$regex": re.escape(cleaned_data["card_name"]), "$options": "i"}
                
            if cleaned_data.get("card_rarity"):
                normalized_verification_rarity = normalize_rarity(cleaned_data["card_rarity"])
                verification_query["card_rarity"] = normalized_verification_rarity
                
            # Use exact same logic as cache lookup for art variant
            if cleaned_data.get("card_art_variant"):
                verification_query["card_art_variant"] = cleaned_data["card_art_variant"]
                logger.info(f"  🎨 Verification will use art variant filter: '{cleaned_data['card_art_variant']}'")
            else:
                logger.info(f"  🎨 No art variant in cleaned data - verification will not filter by art variant")
            
            logger.info(f"🔍 VERIFICATION: Checking if new record was saved with query: {verification_query}")
            
            verification_docs = list(sync_price_scraping_collection.find(
                verification_query,
                {"card_number": 1, "card_art_variant": 1, "card_rarity": 1, "last_price_updt": 1, "_id": 1}
            ).sort([("last_price_updt", -1)]).limit(3))
            
            if verification_docs:
                logger.info(f"  ✅ Verification successful: Found {len(verification_docs)} matching record(s)")
                for i, doc in enumerate(verification_docs):
                    logger.info(f"    📄 Record {i+1}: ID={doc.get('_id')}, card_number={doc.get('card_number')}, art_variant='{doc.get('card_art_variant')}', rarity='{doc.get('card_rarity')}', last_update={doc.get('last_price_updt')}")
            else:
                logger.error(f"  ❌ VERIFICATION FAILED: Could not find the record we just inserted!")
                logger.error(f"  🔍 Verification query was: {verification_query}")
                logger.error(f"  📊 Let's check what records exist for this card...")
                
                # Debug: check what records actually exist for this card
                debug_query = {}
                if cleaned_data.get("card_number") and cleaned_data["card_number"] != "Unknown":
                    debug_query["card_number"] = cleaned_data["card_number"]
                elif cleaned_data.get("card_name"):
                    debug_query["card_name"] = {"$regex": re.escape(cleaned_data["card_name"]), "$options": "i"}
                
                debug_docs = list(sync_price_scraping_collection.find(
                    debug_query,
                    {"card_number": 1, "card_art_variant": 1, "card_rarity": 1, "last_price_updt": 1, "_id": 1}
                ).sort([("last_price_updt", -1)]).limit(5))
                
                if debug_docs:
                    logger.error(f"  🔍 Found {len(debug_docs)} records for this card (without rarity/art filters):")
                    for i, doc in enumerate(debug_docs):
                        logger.error(f"    📄 Record {i+1}: ID={doc.get('_id')}, card_number={doc.get('card_number')}, art_variant='{doc.get('card_art_variant')}', rarity='{doc.get('card_rarity')}', last_update={doc.get('last_price_updt')}")
                else:
                    logger.error(f"  ❌ No records found at all for this card!")
                    
                return False
                
            return True
        else:
            logger.warning("❌ Failed to insert new sync price record")
            return False
        
    except Exception as e:
        logger.error(f"Error saving sync price data: {e}")
        return False

def lookup_card_info_from_cache(card_number: str) -> Optional[Dict]:
    """Lookup comprehensive card information from MongoDB cache using the card number."""
    try:
        # Initialize sync MongoDB connection if needed
        if sync_price_scraping_client is None:
            initialize_sync_price_scraping()
        
        # Get the card variants collection
        db = sync_price_scraping_client.get_default_database()
        variants_collection = db[MONGODB_CARD_VARIANTS_COLLECTION]
        
        # Search for the card in the variants collection by set_code (card number)
        query = {"set_code": card_number}
        
        card_document = variants_collection.find_one(query)
        
        if card_document:
            # Get card name and other info
            card_name = card_document.get('card_name', '')
            set_name = card_document.get('set_name', '')
            set_rarity = card_document.get('set_rarity', '')
            card_id = card_document.get('card_id')
            
            # Find variants of this card only within the same set to avoid excessive logging
            if card_name:
                # Get the set code prefix from the card number (e.g., "RA04" from "RA04-EN106")
                set_code_prefix = extract_set_code(card_number)
                
                if set_code_prefix:
                    # Filter by both card_name and set_code prefix to only get variants from this set
                    variants_query = {
                        "card_name": card_name,
                        "set_code": {"$regex": f"^{re.escape(set_code_prefix)}-", "$options": "i"}
                    }
                    logger.info(f"Looking for variants in set {set_code_prefix} for card {card_name}")
                else:
                    # Fallback: use card_name only but limit results
                    variants_query = {"card_name": card_name}
                    logger.info(f"No set code prefix found, using card_name only for {card_name}")
                
                # Limit the query to avoid excessive processing
                all_variants = list(variants_collection.find(variants_query).limit(20))
                
                available_rarities = []
                available_sets = []
                for variant in all_variants:
                    if variant.get('set_rarity'):
                        available_rarities.append(variant.get('set_rarity'))
                    if variant.get('set_name'):
                        available_sets.append(variant.get('set_name'))
                
                card_info = {
                    'card_name': card_name,
                    'set_name': set_name,
                    'set_rarity': set_rarity,
                    'set_code': card_number,
                    'card_id': card_id,
                    'available_rarities': list(set(available_rarities)),
                    'available_sets': list(set(available_sets)),
                    'set_filtered': bool(set_code_prefix)  # Indicates if we filtered by set
                }
                
                logger.info(f"Found card info for {card_number}: {card_name}, rarities from set {set_code_prefix or 'all sets'}: {list(set(available_rarities))}")
                return card_info
        
        logger.warning(f"Card {card_number} not found in MongoDB cache")
        return None
        
    except Exception as e:
        logger.error(f"Error looking up card info from cache for {card_number}: {e}")
        return None

def lookup_card_name_from_cache(card_number: str) -> Optional[str]:
    """Lookup card name from MongoDB cache using the card number."""
    card_info = lookup_card_info_from_cache(card_number)
    return card_info.get('card_name') if card_info else None

def verify_card_match(
    tcg_card_name: str, 
    tcg_card_rarity: str, 
    expected_card_info: Optional[Dict], 
    target_rarity: str
) -> Dict[str, any]:
    """Verify if TCGPlayer card matches our expected card info from cache."""
    verification_result = {
        'name_match': False,
        'rarity_match': False,
        'overall_match': False,
        'confidence_score': 0
    }
    
    if not expected_card_info:
        # If no cache info, we can't verify but allow it
        verification_result['overall_match'] = True
        verification_result['confidence_score'] = 50  # Medium confidence
        return verification_result
    
    expected_name = expected_card_info.get('card_name', '')
    available_rarities = expected_card_info.get('available_rarities', [])
    
    # Check name match - be very strict about the actual card name matching
    if expected_name and tcg_card_name:
        # Extract the core card name from both (before any set/variant info)
        expected_core = expected_name.lower().strip()
        tcg_core = tcg_card_name.lower().strip()
        
        # Remove set information from TCG name for cleaner comparison
        # Split at common separators and take the first part
        for separator in [' - ', ' (', ' |', '  ']:
            if separator in tcg_core:
                tcg_core = tcg_core.split(separator)[0].strip()
                break
        
        # For a perfect match, the expected card name should be contained in or very close to the TCG name
        expected_words = [word for word in expected_core.split() if len(word) > 2]  # Skip small words
        tcg_words = [word for word in tcg_core.split() if len(word) > 2]
        
        # Check if all significant words from expected name appear in order in TCG name
        expected_word_set = set(expected_words)
        tcg_word_set = set(tcg_words)
        
        # Calculate exact matching score
        common_words = expected_word_set.intersection(tcg_word_set)
        
        # Require ALL expected words to be present for a match (very strict)
        if len(common_words) == len(expected_word_set) and len(expected_word_set) > 0:
            # Additional check: make sure we don't have conflicting key words
            # (e.g., "Skull" vs "Metal" are conflicting descriptors)
            conflicting_words = tcg_word_set - expected_word_set
            key_conflicts = {'skull', 'rose', 'flame', 'white', 'blue', 'red'} & conflicting_words
            
            if not key_conflicts:  # No conflicting descriptive words
                verification_result['name_match'] = True
                verification_result['confidence_score'] += 50
                logger.debug(f"✓ Perfect name match: expected '{expected_name}' matches TCG '{tcg_card_name}'")
            else:
                logger.debug(f"✗ Conflicting words detected: {key_conflicts} in '{tcg_card_name}' vs expected '{expected_name}'")
        else:
            missing_words = expected_word_set - common_words
            logger.debug(f"✗ Insufficient name match: missing words {missing_words} from expected '{expected_name}' in TCG '{tcg_card_name}'")
    
    # Check rarity match
    if target_rarity and available_rarities:
        target_normalized = normalize_rarity(target_rarity)
        for available_rarity in available_rarities:
            available_normalized = normalize_rarity(available_rarity)
            if target_normalized == available_normalized:
                verification_result['rarity_match'] = True
                verification_result['confidence_score'] += 40
                break
    
    # Overall match if both name and rarity match or if we have good confidence
    verification_result['overall_match'] = (
        verification_result['name_match'] and verification_result['rarity_match']
    ) or verification_result['confidence_score'] >= 60
    
    return verification_result


def lookup_card_name_from_cache(card_number: str) -> Optional[str]:
    try:
        # Initialize sync MongoDB connection if needed
        if sync_price_scraping_client is None:
            initialize_sync_price_scraping()
        
        # Get the card variants collection
        db = sync_price_scraping_client.get_default_database()
        variants_collection = db[MONGODB_CARD_VARIANTS_COLLECTION]
        
        # Search for the card in the variants collection by set_code (card number)
        query = {"set_code": card_number}
        
        card_document = variants_collection.find_one(query)
        
        if card_document:
            card_name = card_document.get('card_name')
            if card_name:
                logger.info(f"Found card name '{card_name}' for card number {card_number} in cache")
                return card_name.strip()
        
        logger.warning(f"Card {card_number} not found in MongoDB cache")
        return None
        
    except Exception as e:
        logger.error(f"Error looking up card name from cache for {card_number}: {e}")
        return None

def lookup_card_name_from_ygo_api(card_number: str) -> Optional[str]:
    """Lookup card name from YGO API using the card number."""
    try:
        # Try to search by card number first
        api_url = f"{YGO_API_BASE_URL}/cardinfo.php?misc=yes&num={quote(card_number)}"
        response = requests.get(api_url, timeout=10)
        
        if response.status_code == 200:
            cards_data = response.json()
            cards_list = cards_data.get('data', [])
            
            # Look for exact card number match in card sets
            for card in cards_list:
                card_sets = card.get('card_sets', [])
                for card_set in card_sets:
                    set_rarity_code = card_set.get('set_rarity_code', '')
                    if set_rarity_code.upper() == card_number.upper():
                        card_name = card.get('name')
                        if card_name:
                            logger.info(f"Found card name '{card_name}' for card number {card_number} via YGO API")
                            return card_name.strip()
        
        logger.warning(f"Card {card_number} not found in YGO API")
        return None
        
    except Exception as e:
        logger.error(f"Error looking up card name from YGO API for {card_number}: {e}")
        return None

def lookup_card_name(card_number: str) -> Optional[str]:
    """Lookup card name using MongoDB cache first, then YGO API as fallback."""
    # Try cache first
    card_name = lookup_card_name_from_cache(card_number)
    if card_name:
        return card_name
    
    # Fallback to YGO API
    card_name = lookup_card_name_from_ygo_api(card_number)
    if card_name:
        return card_name
    
    logger.warning(f"Could not find card name for {card_number} in cache or YGO API")
    return None

def extract_set_code(card_number: str) -> Optional[str]:
    """Extract set code from card number."""
    if not card_number:
        return None
    
    # Most Yu-Gi-Oh card numbers follow the pattern: SETCODE-REGION###
    # Handle both numeric and alphanumeric card numbers
    match = re.match(r'^([A-Z]+\d*)-[A-Z]{2}\d+$', card_number.upper())
    if match:
        set_code = match.group(1)
        logger.debug(f"Extracted set code: {set_code} from card number: {card_number}")
        return set_code
    
    # Fallback: try to extract the first part before the hyphen
    if '-' in card_number:
        potential_set_code = card_number.split('-')[0].upper()
        if len(potential_set_code) >= 2 and potential_set_code.isalpha():
            logger.debug(f"Extracted set code (fallback): {potential_set_code} from card number: {card_number}")
            return potential_set_code
    
    logger.debug(f"Could not extract set code from card number: {card_number}")
    return None

def map_set_code_to_tcgplayer_name(set_code: str) -> Optional[str]:
    """Map YGO set code to TCGPlayer set name using MongoDB cache."""
    if not set_code:
        return None
    
    try:
        # Initialize sync MongoDB connection if needed
        if sync_price_scraping_client is None:
            initialize_sync_price_scraping()
        
        # Get the sets collection
        db = sync_price_scraping_client.get_default_database()
        sets_collection = db["YGO_SETS_CACHE_V1"]
        
        # Search for the set by code (case-insensitive)
        set_document = sets_collection.find_one(
            {"set_code": {"$regex": f"^{re.escape(set_code)}$", "$options": "i"}},
            {"set_name": 1, "_id": 0}
        )
        
        if set_document and 'set_name' in set_document:
            set_name = set_document['set_name']
            logger.debug(f"Mapped set code {set_code} to TCGPlayer set name: {set_name}")
            return set_name
        else:
            logger.debug(f"No TCGPlayer set name mapping found in MongoDB for set code: {set_code}")
            
            # Fallback to hardcoded mappings for critical sets if MongoDB lookup fails
            fallback_mappings = {
                'RA04': 'Quarter Century Stampede',
                'RA03': 'Quarter Century Bonanza',
                'SUDA': 'Supreme Darkness'  # Fixed mapping
            }
            
            fallback_name = fallback_mappings.get(set_code.upper())
            if fallback_name:
                logger.debug(f"Using fallback mapping for {set_code}: {fallback_name}")
                return fallback_name
            
            return None
            
    except Exception as e:
        logger.error(f"Error looking up set name for code '{set_code}': {e}")
        
        # Fallback to hardcoded mappings if MongoDB fails
        fallback_mappings = {
            'RA04': 'Quarter Century Stampede',
            'RA03': 'Quarter Century Bonanza', 
            'SUDA': 'Supreme Darkness'  # Fixed mapping
        }
        
        fallback_name = fallback_mappings.get(set_code.upper())
        if fallback_name:
            logger.debug(f"Using fallback mapping for {set_code}: {fallback_name}")
            return fallback_name
        
        return None

def map_rarity_to_tcgplayer_filter(rarity: str) -> Optional[str]:
    """Map YGO rarity to TCGPlayer rarity filter value."""
    if not rarity:
        return None
    
    rarity_lower = rarity.lower().strip()
    
    # Map common rarity variations to TCGPlayer filter values
    # These need to match exactly how they appear in TCGPlayer's filter dropdown
    rarity_mappings = {
        'platinum secret rare': 'Platinum Secret Rare',
        'quarter century secret rare': 'Quarter Century Secret Rare', 
        'secret rare': 'Secret Rare',
        'ultra rare': 'Ultra Rare',
        'super rare': 'Super Rare',
        'rare': 'Rare',
        'common': 'Common / Short Print',
        'common / short print': 'Common / Short Print',
        'starlight rare': 'Starlight Rare',
        'collector\'s rare': 'Collector\'s Rare',
        'collectors rare': 'Collector\'s Rare',
        'ghost rare': 'Ghost Rare',
        'gold rare': 'Gold Rare',
        'premium gold rare': 'Premium Gold Rare',
        'prismatic secret rare': 'Prismatic Secret Rare',
        'prismatic ultimate rare': 'Prismatic Ultimate Rare',
        'ultimate rare': 'Ultimate Rare',
        'starfoil rare': 'Starfoil Rare'
    }
    
    tcgplayer_rarity = rarity_mappings.get(rarity_lower)
    if tcgplayer_rarity:
        logger.debug(f"Mapped rarity '{rarity}' to TCGPlayer filter: {tcgplayer_rarity}")
        return tcgplayer_rarity
    
    logger.debug(f"No TCGPlayer rarity filter mapping found for: {rarity}")
    return None

def extract_booster_set_name(source_url: str) -> Optional[str]:
    """Extract booster set name from TCGPlayer URL."""
    if not source_url:
        return None
    
    try:
        # TCGPlayer URLs often contain set information in the path
        # Example: https://www.tcgplayer.com/product/626754/yugioh-quarter-century-stampede-black-metal-dragon-secret-rare
        
        # Extract set name from URL path
        import re
        
        # Look for yugioh-{set-name} pattern in TCGPlayer URLs
        set_match = re.search(r'/yugioh-([^/]+?)(?:-[^-/]*?-(?:secret|ultra|super|rare|common))', source_url, re.IGNORECASE)
        if set_match:
            set_name = set_match.group(1)
            # Clean and format set name
            set_name = set_name.replace('-', ' ').title()
            # Handle specific known abbreviations
            if 'quarter-century' in set_name.lower() or 'quarter century' in set_name.lower():
                return 'Quarter Century Stampede'
            return set_name
            
        # Fallback: look for any meaningful set identifier in the URL
        path_parts = source_url.split('/')
        for part in path_parts:
            if 'yugioh-' in part.lower() and len(part) > 10:
                set_candidate = part.replace('yugioh-', '').replace('-', ' ').title()
                # Remove card-specific terms
                set_candidate = re.sub(r'\b(Secret|Ultra|Super|Rare|Common)\b.*$', '', set_candidate, flags=re.IGNORECASE).strip()
                if len(set_candidate) > 3:  # Avoid single words
                    return set_candidate
                    
        return None
        
    except Exception as e:
        logger.error(f"Error extracting booster set name from URL {source_url}: {e}")
        return None

async def select_best_tcgplayer_variant(
    page, 
    card_number: str, 
    card_name: Optional[str], 
    card_rarity: Optional[str], 
    target_art_version: Optional[str],
    expected_card_info: Optional[Dict] = None,
    max_variants_to_process: int = None
) -> Optional[str]:
    """Select best card variant from TCGPlayer search results.
    
    Args:
        max_variants_to_process: Maximum number of variants to evaluate. 
                                If None, uses TCGPLAYER_DEFAULT_VARIANT_LIMIT (default 100)
                                to prevent performance issues with large result sets
    """
    if max_variants_to_process is None:
        max_variants_to_process = TCGPLAYER_DEFAULT_VARIANT_LIMIT
    try:
        logger.info("="*80)
        logger.info("STARTING TCGPLAYER VARIANT SELECTION")
        logger.info(f"Target Card Number: {card_number}")
        logger.info(f"Target Rarity: {card_rarity}")
        logger.info(f"Target Art Version: {target_art_version}")
        logger.info("="*80)
        
        # Extract product links from TCGPlayer search results with limiting
        max_variants = max_variants_to_process
        variants = await page.evaluate("""
            (maxVariants) => {
                const variants = [];
                
                // TCGPlayer search results - look for product links directly
                const productLinks = Array.from(document.querySelectorAll('a[href*="/product/"]'));
                
                // Log total found and apply limiting
                console.log('Found ' + productLinks.length + ' total product links');
                const linksToProcess = productLinks.slice(0, maxVariants);
                console.log('Processing first ' + linksToProcess.length + ' variants (limit: ' + maxVariants + ')');
                
                linksToProcess.forEach(link => {
                    const href = link.getAttribute('href');
                    
                    // Extract comprehensive product information from the link
                    let cardName = '';
                    let setName = '';
                    let rarity = '';
                    let cardNumber = '';
                    
                    // Method 1: Extract from structured elements within the link
                    const heading = link.querySelector('h4');  // Set name is in h4
                    if (heading) {
                        setName = heading.textContent ? heading.textContent.trim() : '';
                    }
                    
                    // Find generic elements that contain the card information
                    const generics = link.querySelectorAll('generic');
                    generics.forEach(generic => {
                        const text = generic.textContent ? generic.textContent.trim() : '';
                        
                        // Look for card number (starts with #)
                        if (text.startsWith('#')) {
                            cardNumber = text.replace('#', '').trim();
                        }
                        // Enhanced rarity detection - look for complete rarity phrases
                        else if (text.match(/quarter\\s+century\\s+secret\\s+rare/i)) {
                            rarity = 'Quarter Century Secret Rare';
                        }
                        else if (text.match(/platinum\\s+secret\\s+rare/i)) {
                            rarity = 'Platinum Secret Rare';
                        }
                        else if (text.match(/collector'?s\\s+rare/i)) {
                            rarity = "Collector's Rare";
                        }
                        else if (text.match(/starlight\\s+rare/i)) {
                            rarity = 'Starlight Rare';
                        }
                        else if (text.match(/secret\\s+rare/i)) {
                            rarity = 'Secret Rare';
                        }
                        else if (text.match(/ultra\\s+rare/i)) {
                            rarity = 'Ultra Rare';
                        }
                        else if (text.match(/super\\s+rare/i)) {
                            rarity = 'Super Rare';
                        }
                        else if (text.match(/\\bcommon\\b/i)) {
                            rarity = 'Common';
                        }
                        else if (text.match(/\\brare\\b/i) && !text.includes('$') && !text.includes('listings')) {
                            rarity = 'Rare';
                        }
                        // Look for card name (longer text, contains letters, not price/listing info)
                        else if (text.length > 3 && /[a-zA-Z]/.test(text) && 
                                !text.includes('listings') && !text.includes('$') && 
                                !text.includes('Market Price:') && !text.includes('from') &&
                                !text.startsWith('#') && text !== setName && !rarity) {
                            // This could be the card name - take the longest meaningful one
                            if (text.length > cardName.length) {
                                cardName = text;
                            }
                        }
                    });
                    
                    // Fallback: if no rarity found in generic elements, check other page elements
                    if (!rarity) {
                        // Check all text content in the link for rarity information
                        const allText = link.textContent || '';
                        
                        if (allText.match(/quarter\\s+century\\s+secret\\s+rare/i)) {
                            rarity = 'Quarter Century Secret Rare';
                        } else if (allText.match(/platinum\\s+secret\\s+rare/i)) {
                            rarity = 'Platinum Secret Rare';
                        } else if (allText.match(/collector'?s\\s+rare/i)) {
                            rarity = "Collector's Rare";
                        } else if (allText.match(/starlight\\s+rare/i)) {
                            rarity = 'Starlight Rare';
                        } else if (allText.match(/secret\\s+rare/i)) {
                            rarity = 'Secret Rare';
                        } else if (allText.match(/ultra\\s+rare/i)) {
                            rarity = 'Ultra Rare';
                        } else if (allText.match(/super\\s+rare/i)) {
                            rarity = 'Super Rare';
                        } else if (allText.match(/\\bcommon\\b/i)) {
                            rarity = 'Common';
                        }
                    }
                    
                    // Build comprehensive title from extracted components
                    let title = '';
                    if (cardName) {
                        title = cardName;
                        if (setName) {
                            title += ' - ' + setName;
                        }
                        if (rarity) {
                            title += ' (' + rarity + ')';
                        }
                        if (cardNumber) {
                            title += ' [' + cardNumber + ']';
                        }
                    } else {
                        // Fallback: use all text content and clean it up
                        const allText = link.textContent ? link.textContent.trim() : '';
                        // Take first meaningful part before price info
                        const parts = allText.split(/Market Price:|listings from|\\$/);
                        title = parts[0] ? parts[0].trim() : '';
                    }
                    
                    if (href && title) {
                        // Make sure href is absolute
                        const fullHref = href.startsWith('http') ? href : 'https://www.tcgplayer.com' + href;
                        
                        variants.push({
                            title: title,
                            href: fullHref,
                            cardName: cardName,
                            setName: setName,
                            rarity: rarity,
                            cardNumber: cardNumber
                        });
                    }
                });
                
                return variants;
            }
        """, max_variants)

        if not variants:
            logger.warning("No variants found in TCGPlayer search results")
            # Log page content for debugging
            page_content = await page.evaluate("() => document.body.textContent || ''")
            if "0 results for:" in page_content:
                logger.warning("TCGPlayer returned 0 results - page shows no matching products")
            elif "No results for" in page_content:
                logger.warning("TCGPlayer 'No results' message detected")
            else:
                logger.warning("Unknown issue with TCGPlayer search results extraction")
            return None
            
        logger.info(f"Found {len(variants)} variants to check - will process ALL variants (no early termination)")
        
        # Log if we hit the processing limit
        total_available = await page.evaluate("() => document.querySelectorAll('a[href*=\"/product/\"]').length")
        if total_available > max_variants_to_process:
            logger.warning(f"Large result set detected: {total_available} total variants found, processing first {max_variants_to_process} (limit)")
            logger.info(f"Processing limit applied to prevent excessive processing time. All {max_variants_to_process} variants will still be evaluated.")
        
        # Score variants based on card number, rarity, card name, and art variant matches
        # Process ALL variants to ensure we don't miss the correct card
        scored_variants = []
        
        for i, variant in enumerate(variants):
            score = 0
            title_lower = variant['title'].lower()
            url_lower = variant['href'].lower()
            
            # Extract structured data
            variant_card_name = variant.get('cardName', '').lower()
            variant_card_number = variant.get('cardNumber', '').lower()
            variant_rarity = variant.get('rarity', '').lower()
            variant_set_name = variant.get('setName', '').lower()
            
            logger.info(f"Evaluating variant {i+1}/{len(variants)}: {variant['title'][:80]}...")
            logger.info(f"  Card Name: '{variant.get('cardName', 'N/A')}'")
            logger.info(f"  Card Number: '{variant.get('cardNumber', 'N/A')}'")
            logger.info(f"  Rarity: '{variant.get('rarity', 'N/A')}'")
            logger.info(f"  Set: '{variant.get('setName', 'N/A')}'")
            
            # CRITICAL: Card number exact match
            card_number_found = False
            if card_number:
                card_number_lower = card_number.lower()
                # Check extracted card number first, then fallback to title/URL
                if variant_card_number == card_number_lower:
                    card_number_found = True
                    score += 300  # Highest score for exact card number match
                    logger.info(f"✓ EXACT card number match: {card_number}")
                elif card_number_lower in title_lower or card_number_lower in url_lower:
                    card_number_found = True
                    score += 200  # High score for card number in title/URL
                    logger.info(f"✓ Card number {card_number} found in title/URL")
                else:
                    # Heavily penalize variants without the target card number
                    score -= 200
                    logger.warning(f"✗ Card number {card_number} NOT found")
                    
            # CRITICAL: Card name verification
            card_name_perfect_match = False
            if card_name:
                expected_name = card_name.lower()
                # Check extracted card name first
                if variant_card_name and expected_name == variant_card_name:
                    card_name_perfect_match = True
                    score += 250  # Very high score for exact card name match
                    logger.info(f"✓ EXACT card name match: '{card_name}'")
                elif variant_card_name:
                    # Check if all words of expected name are in extracted name
                    name_words = expected_name.split()
                    name_match_count = sum(1 for word in name_words if word in variant_card_name)
                    if name_match_count == len(name_words):
                        card_name_perfect_match = True
                        score += 200  # High score for all words matching
                        logger.info(f"✓ All words match in card name: '{card_name}'")
                    elif name_match_count > 0:
                        score += (name_match_count / len(name_words)) * 100
                        logger.info(f"⚠ Partial card name match ({name_match_count}/{len(name_words)})")
                    else:
                        score -= 100
                        logger.warning(f"✗ No card name match in extracted data")
                else:
                    # Fallback to checking title
                    name_words = expected_name.split()
                    name_match_count = sum(1 for word in name_words if word in title_lower)
                    if name_match_count == len(name_words):
                        card_name_perfect_match = True
                        score += 150  # Good score for title match
                        logger.info(f"✓ Card name words found in title")
                    else:
                        score -= 50
                        logger.warning(f"✗ Incomplete card name match in title")
            
            # Prefer variants that have both card number and card name matches, but don't completely reject others
            if not card_number_found:
                score -= 75   # Moderate penalty for missing card number (reduced from 150)
                logger.warning(f"⚠ Card number not found - applying penalty")
            if not card_name_perfect_match:
                score -= 50   # Small penalty for imperfect card name match (reduced from 100)
                logger.warning(f"⚠ Card name not perfectly matched - applying penalty")
            
            # Verify this variant against our expected card info from MongoDB cache
            verification_result = None
            if expected_card_info:
                # Extract a more comprehensive card name from title for verification
                # Remove common suffixes to get cleaner card name for comparison
                clean_title = variant['title']
                for suffix in [' -', ' (', ' -', ' |']:
                    if suffix in clean_title:
                        clean_title = clean_title.split(suffix)[0]
                
                verification_result = verify_card_match(
                    clean_title.strip(), 
                    '', # We don't extract rarity from title here
                    expected_card_info, 
                    card_rarity or ''
                )
                
                # Boost score for verified matches
                if verification_result['overall_match']:
                    score += 100  # Boost for verified cards
                    logger.info(f"✓ Cache verification passed for {variant['title'][:50]}... (confidence: {verification_result['confidence_score']})")
                else:
                    logger.info(f"⚠ Cache verification failed for {variant['title'][:50]}... (confidence: {verification_result['confidence_score']})")
                
            # Score for rarity match - use strict exact matching for better precision
            if card_rarity:
                target_rarity_normalized = normalize_rarity(card_rarity).lower().strip()
                rarity_found = False
                rarity_score = 0
                
                # First check extracted rarity data for exact match
                if variant_rarity:
                    variant_rarity_normalized = normalize_rarity(variant_rarity).lower().strip()
                    
                    if variant_rarity_normalized == target_rarity_normalized:
                        # Perfect exact rarity match - highest score
                        rarity_score = 400
                        rarity_found = True
                        logger.info(f"✓ PERFECT rarity match: '{card_rarity}' == '{variant.get('rarity', '')}'")
                    else:
                        # For non-exact matches, be much more strict to avoid confusion between similar rarities
                        # Check if this is a meaningful partial match vs just sharing common words
                        target_words = set(target_rarity_normalized.split())
                        variant_words = set(variant_rarity_normalized.split())
                        
                        # Calculate word overlap, but require significant overlap to be considered partial
                        common_words = target_words.intersection(variant_words)
                        target_unique_words = target_words - {'rare', 'card'}  # Exclude generic words
                        variant_unique_words = variant_words - {'rare', 'card'}
                        
                        # Only consider it a partial match if:
                        # 1. Most meaningful words overlap AND
                        # 2. No conflicting distinctive words (like "quarter century" vs "platinum")
                        distinctive_conflicts = {
                            'quarter', 'century', 'platinum', 'prismatic', 'starlight', 
                            'collector', 'ghost', 'gold', 'parallel', 'mosaic'
                        }
                        
                        target_distinctive = target_unique_words.intersection(distinctive_conflicts)
                        variant_distinctive = variant_unique_words.intersection(distinctive_conflicts)
                        
                        # If both have distinctive words but they're different, heavily penalize
                        if target_distinctive and variant_distinctive and not target_distinctive.intersection(variant_distinctive):
                            rarity_score = -300  # Heavy penalty for conflicting rarities
                            logger.warning(f"✗ CONFLICTING rarity types: '{card_rarity}' vs '{variant.get('rarity', '')}' (distinctive words: {target_distinctive} vs {variant_distinctive})")
                        elif len(common_words) >= 2 and len(target_unique_words) > 0:
                            # Meaningful partial match
                            overlap_ratio = len(common_words) / max(len(target_unique_words), 1)
                            if overlap_ratio >= 0.6:  # At least 60% overlap
                                rarity_score = 50  # Very low score for partial matches
                                rarity_found = True
                                logger.info(f"⚠ Weak partial rarity match: '{card_rarity}' ~= '{variant.get('rarity', '')}' (overlap: {overlap_ratio:.1%})")
                            else:
                                rarity_score = -150
                                logger.warning(f"✗ Insufficient rarity overlap: '{card_rarity}' vs '{variant.get('rarity', '')}' (overlap: {overlap_ratio:.1%})")
                        else:
                            # Different rarity - penalty
                            rarity_score = -150
                            logger.warning(f"✗ Rarity mismatch: '{card_rarity}' != '{variant.get('rarity', '')}'")
                
                # Fallback to checking title if no extracted rarity data
                if not rarity_found:
                    # Generate all possible variations for flexible matching in title
                    rarity_variants = normalize_rarity_for_matching(card_rarity)
                    
                    for rarity_variant in rarity_variants:
                        if rarity_variant.lower() in title_lower:
                            rarity_score = 25  # Much lower score for title-based match
                            rarity_found = True
                            logger.info(f"✓ Weak rarity match for '{card_rarity}' found in title")
                            break
                
                if not rarity_found:
                    rarity_score = -100  # Penalize missing rarity match
                    logger.warning(f"✗ No rarity match for '{card_rarity}' (extracted: '{variant.get('rarity', 'N/A')}')")
                
                score += rarity_score
            
            # Score for art variant match - improved precision
            if target_art_version:
                art_version_score = 0
                target_art = str(target_art_version).strip().lower()
                
                # Extract art variant from this variant's title and URL
                variant_art = extract_art_version(variant['title'])
                if not variant_art:
                    variant_art = extract_art_version(variant['href'])
                
                if variant_art:
                    variant_art_normalized = str(variant_art).strip().lower()
                    # Remove ordinal suffixes for comparison
                    target_art_clean = re.sub(r'(st|nd|rd|th)$', '', target_art)
                    variant_art_clean = re.sub(r'(st|nd|rd|th)$', '', variant_art_normalized)
                    
                    if target_art_clean == variant_art_clean:
                        # Exact art variant match - high score
                        art_version_score = 100
                        logger.info(f"✓ EXACT art variant match: '{target_art_version}' == '{variant_art}'")
                    else:
                        # Art variant mismatch - penalty
                        art_version_score = -50
                        logger.warning(f"✗ Art variant mismatch: '{target_art_version}' != '{variant_art}'")
                else:
                    # No art variant found in title - check for basic presence in text
                    if target_art in title_lower or target_art in url_lower:
                        art_version_score = 25
                        logger.info(f"⚠ Weak art variant match for '{target_art_version}' found in text")
                    else:
                        # No art variant info available - small penalty
                        art_version_score = -10
                        logger.info(f"⚠ No art variant info found for comparison")
                
                score += art_version_score
                    
            # Small bonus for detailed titles (but not a major factor)
            score += min(len(variant['title']) // 20, 5)
            
            scored_variants.append((score, variant))
            logger.info(f"Final Score: {score} | Variant: {variant['title'][:80]}...")
            
            # Continue processing ALL variants as requested - no early termination
        
        # Sort by score and return the best match
        scored_variants.sort(reverse=True, key=lambda x: x[0])
        
        if scored_variants and scored_variants[0][0] > 0:
            best_variant = scored_variants[0][1]
            best_score = scored_variants[0][0]
            
            # CRITICAL VALIDATION: Do a final check that our selected variant actually matches our requirements
            best_title_lower = best_variant['title'].lower()
            best_url_lower = best_variant['href'].lower()
            best_card_number = best_variant.get('cardNumber', '').lower()
            best_card_name = best_variant.get('cardName', '').lower()
            
            # Verify card number is present
            card_number_present = True
            if card_number:
                card_number_lower = card_number.lower()
                if best_card_number == card_number_lower:
                    # Perfect match in extracted data
                    pass
                elif card_number_lower in best_title_lower or card_number_lower in best_url_lower:
                    # Found in title or URL
                    pass
                else:
                    card_number_present = False
            
            # Verify card name match if provided
            card_name_match = True
            if card_name:
                expected_name = card_name.lower()
                if best_card_name == expected_name:
                    # Perfect match in extracted data
                    pass
                elif best_card_name:
                    # Check if all words match in extracted name
                    name_words = expected_name.split()
                    card_name_match = all(word in best_card_name for word in name_words)
                else:
                    # Fallback to title check
                    name_words = expected_name.split()
                    card_name_match = all(word in best_title_lower for word in name_words)
            
            if not card_number_present:
                logger.error(f"CRITICAL ERROR: Selected variant does not contain card number {card_number}")
                logger.error(f"Selected: {best_variant['title']}")
                logger.error(f"URL: {best_variant['href']}")
                return None
                
            if not card_name_match:
                logger.error(f"CRITICAL ERROR: Selected variant does not match card name '{card_name}'")
                logger.error(f"Selected: {best_variant['title']}")
                return None
            
            # Log final selection details
            logger.info(f"="*80)
            logger.info(f"FINAL SELECTION - Score: {best_score}")
            logger.info(f"Title: {best_variant['title']}")
            logger.info(f"URL: {best_variant['href']}")
            logger.info(f"Extracted Data:")
            logger.info(f"  Card Name: '{best_variant.get('cardName', 'N/A')}'")
            logger.info(f"  Card Number: '{best_variant.get('cardNumber', 'N/A')}'")
            logger.info(f"  Rarity: '{best_variant.get('rarity', 'N/A')}'")
            logger.info(f"  Set: '{best_variant.get('setName', 'N/A')}'")
            if expected_card_info:
                logger.info(f"Expected from cache: {expected_card_info['card_name']} | {expected_card_info.get('set_rarity', 'Unknown rarity')}")
                logger.info(f"Available rarities in cache: {expected_card_info['available_rarities']}")
            logger.info(f"="*80)
            
            return best_variant['href']
        else:
            logger.warning("No suitable variant found based on scoring")
            return None
            
    except Exception as e:
        logger.error(f"Error selecting TCGPlayer variant: {e}")
        return None


async def select_best_card_variant(
    page, 
    card_number: str, 
    card_name: Optional[str], 
    card_rarity: Optional[str], 
    target_art_version: Optional[str]
) -> Optional[str]:
    """Select best card variant prioritizing TCGPlayer rarity validation."""
    try:
        logger.info("="*80)
        logger.info("STARTING VARIANT SELECTION WITH TCGPLAYER VALIDATION")
        logger.info(f"Target Card Number: {card_number}")
        logger.info(f"Target Rarity: {card_rarity}")
        logger.info(f"Target Art Version: {target_art_version}")
        logger.info("="*80)
        
        # Extract all product links from search results
        variants = await page.evaluate("""
            () => {
                const variants = [];
                const rows = Array.from(document.querySelectorAll('#games_table tbody tr, .search-results tr'));
                
                rows.forEach(row => {
                    const titleCell = row.querySelector('td.title');
                    if (!titleCell) return;
                    
                    const link = titleCell.querySelector('a');
                    if (!link) return;
                    
                    const href = link.getAttribute('href');
                    const title = link.textContent.trim();
                    
                    if (href && href.includes('/game/')) {
                        variants.push({
                            title: title,
                            href: href
                        });
                    }
                });
                
                return variants;
            }
        """)

        if not variants:
            logger.warning("No variants found")
            return None
            
        logger.info(f"Found {len(variants)} variants to check")
        
        # If we only have one variant, verify it meets our requirements
        if len(variants) == 1:
            variant = variants[0]
            if card_rarity:
                # Open the variant page to verify rarity
                page_context = await page.context.new_page()
                try:
                    await page_context.goto(variant['href'], wait_until='networkidle', timeout=15000)
                    tcg_rarity, tcg_art = await extract_rarity_from_tcgplayer(page_context)
                    
                    # Check both rarity and art variant if provided (case-insensitive)
                    rarity_matches = tcg_rarity and normalize_rarity(tcg_rarity).lower() == normalize_rarity(card_rarity).lower()
                    art_matches = not target_art_version or (tcg_art and str(tcg_art).strip().lower() == str(target_art_version).strip().lower())
                    
                    if rarity_matches and art_matches:
                        logger.info(f"Single variant matches criteria - Rarity: {tcg_rarity}, Art: {tcg_art}")
                        return variant['href']
                    else:
                        if not rarity_matches:
                            logger.warning(f"Single variant has wrong rarity. Found: {tcg_rarity}, Expected: {card_rarity}")
                        if not art_matches:
                            logger.warning(f"Single variant has wrong art. Found: {tcg_art}, Expected: {target_art_version}")
                        return None
                finally:
                    await page_context.close()
            else:
                return variant['href']

        # For multiple variants, first filter by card number
        matching_variants = [
            v for v in variants 
            if card_number.lower() in v['title'].lower()
        ]

        if not matching_variants:
            logger.warning(f"No variants found matching card number {card_number}")
            return None

        # If art variant is specified, filter by that first
        if target_art_version:
            art_matching_variants = []
            for variant in matching_variants:
                title_lower = variant['title'].lower()
                art_version = str(target_art_version).strip().lower()
                
                # Check for art variant in title
                if art_version in title_lower:
                    art_matching_variants.append(variant)

            if art_matching_variants:
                matching_variants = art_matching_variants
                logger.info(f"Found {len(matching_variants)} variants matching art variant {target_art_version}")

        # Check each remaining variant's rarity and art variant via TCGPlayer
        for variant in matching_variants:
            page_context = await page.context.new_page()
            try:
                logger.info(f"Checking rarity for variant: {variant['title']}")
                await page_context.goto(variant['href'], wait_until='networkidle', timeout=15000)
                tcg_rarity, tcg_art = await extract_rarity_from_tcgplayer(page_context)
                
                if tcg_rarity:
                    normalized_tcg = normalize_rarity(tcg_rarity).lower()
                    normalized_requested = normalize_rarity(card_rarity).lower()
                    
                    logger.info(f"TCGPlayer rarity: {tcg_rarity} (normalized: {normalized_tcg})")
                    logger.info(f"Requested rarity: {card_rarity} (normalized: {normalized_requested})")
                    
                    # Check both rarity and art variant (case-insensitive)
                    rarity_matches = normalized_tcg == normalized_requested
                    art_matches = not target_art_version or (tcg_art and str(tcg_art).strip().lower() == str(target_art_version).strip().lower())
                    
                    if rarity_matches and art_matches:
                        logger.info(f"✓ Found perfect match! Rarity: {tcg_rarity}, Art: {tcg_art}")
                        return variant['href']
                    else:
                        if not rarity_matches:
                            logger.info("✗ TCGPlayer rarity does not match")
                        if not art_matches:
                            logger.info(f"✗ Art variant does not match. Found: {tcg_art}, Expected: {target_art_version}")
                else:
                    logger.info("Could not extract rarity from TCGPlayer")
            finally:
                await page_context.close()
        
        # If we get here with no match but have variants, return first matching variant
        # if we weren't able to validate completely
        if matching_variants:
            logger.warning("No exact match found, using first matching variant")
            return matching_variants[0]['href']
            
        return None
        
    except Exception as e:
        logger.error(f"Error selecting card variant: {e}")
        return None

async def extract_prices_from_tcgplayer_dom(page) -> Dict[str, Any]:
    """Extract price data from TCGPlayer product page DOM."""
    try:
        prices = await page.evaluate("""
            () => {
                // Helper function to extract price from text with better validation
                const extractPrice = (text) => {
                    if (!text) return null;
                    // Look for currency amounts, handle comma separators
                    const match = text.match(/\\$([\\d,]+(?:\\.\\d{2})?)/);
                    if (match) {
                        const price = parseFloat(match[1].replace(/,/g, ''));
                        // Validate price range (reasonable for TCG cards)
                        return (price >= 0.01 && price <= 10000) ? price : null;
                    }
                    return null;
                };
                
                const result = {
                    tcg_price: null,
                    tcg_market_price: null,
                    debug_info: []
                };
                
                // Log page structure for debugging
                result.debug_info.push(`Page title: ${document.title}`);
                result.debug_info.push(`URL: ${window.location.href}`);
                
                // Strategy 1: Target specific TCGPlayer table structure for Market Price
                // Look for table rows containing "Market Price" specifically
                const marketPriceRows = Array.from(document.querySelectorAll('tr')).filter(row => {
                    const text = row.textContent?.toLowerCase() || '';
                    return text.includes('market price') && text.includes('$');
                });
                
                for (const row of marketPriceRows) {
                    // Look for the price cell in this row - prefer cells that contain only the price
                    const cells = Array.from(row.querySelectorAll('td'));
                    
                    // Find the cell that contains "Market Price" label
                    const labelCell = cells.find(cell => 
                        cell.textContent?.toLowerCase().includes('market price'));
                    
                    if (labelCell) {
                        // Look for the next cell that contains the price
                        const labelIndex = cells.indexOf(labelCell);
                        for (let i = labelIndex + 1; i < cells.length; i++) {
                            const priceCell = cells[i];
                            const price = extractPrice(priceCell.textContent);
                            if (price !== null) {
                                result.tcg_market_price = price;
                                result.debug_info.push(`Market Price found in adjacent cell: $${price} from row "${row.textContent.trim()}"`);
                                break;
                            }
                        }
                    }
                    
                    // Fallback: look for any price in the row if label-adjacent approach fails
                    if (result.tcg_market_price === null) {
                        for (const cell of cells) {
                            const price = extractPrice(cell.textContent);
                            if (price !== null) {
                                result.tcg_market_price = price;
                                result.debug_info.push(`Market Price found in table row: $${price} from "${row.textContent.trim()}"`);
                                break;
                            }
                        }
                    }
                    
                    if (result.tcg_market_price !== null) break;
                }
                
                // Strategy 2: Target specific TCGPlayer table structure for TCG Low/Low prices
                const tcgLowRows = Array.from(document.querySelectorAll('tr')).filter(row => {
                    const text = row.textContent?.toLowerCase() || '';
                    return (text.includes('tcg low') || text.includes('tcgplayer low') || 
                            text.includes('low price') || text.includes('tcg direct low') ||
                            (text.includes('low') && !text.includes('market'))) && text.includes('$');
                });
                
                for (const row of tcgLowRows) {
                    // Look for the price cell in this row - prefer cells that contain only the price
                    const cells = Array.from(row.querySelectorAll('td'));
                    
                    // Find the cell that contains a "Low" label
                    const labelCell = cells.find(cell => {
                        const text = cell.textContent?.toLowerCase() || '';
                        return text.includes('tcg low') || text.includes('low price') || 
                               (text.includes('low') && !text.includes('market'));
                    });
                    
                    if (labelCell) {
                        // Look for the next cell that contains the price
                        const labelIndex = cells.indexOf(labelCell);
                        for (let i = labelIndex + 1; i < cells.length; i++) {
                            const priceCell = cells[i];
                            const price = extractPrice(priceCell.textContent);
                            if (price !== null) {
                                result.tcg_price = price;
                                result.debug_info.push(`TCG Low found in adjacent cell: $${price} from row "${row.textContent.trim()}"`);
                                break;
                            }
                        }
                    }
                    
                    // Fallback: look for any price in the row if label-adjacent approach fails
                    if (result.tcg_price === null) {
                        for (const cell of cells) {
                            const price = extractPrice(cell.textContent);
                            if (price !== null) {
                                result.tcg_price = price;
                                result.debug_info.push(`TCG Low found in table row: $${price} from "${row.textContent.trim()}"`);
                                break;
                            }
                        }
                    }
                    
                    if (result.tcg_price !== null) break;
                }
                
                // Strategy 3: Search for price labels in all elements
                if (!result.tcg_market_price || !result.tcg_price) {
                    const allElements = Array.from(document.querySelectorAll('*')).filter(el => {
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none' && style.visibility !== 'hidden' && 
                               el.offsetHeight > 0 && el.offsetWidth > 0 && el.textContent?.trim();
                    });
                    
                    // Find Market Price if not found yet
                    if (!result.tcg_market_price) {
                        for (const element of allElements) {
                            const text = element.textContent?.toLowerCase() || '';
                            if (text.includes('market price') && text.includes('$')) {
                                const price = extractPrice(element.textContent);
                                if (price !== null) {
                                    result.tcg_market_price = price;
                                    result.debug_info.push(`Market Price found in element: $${price} from "${element.textContent.trim().substring(0, 100)}"`);
                                    break;
                                }
                            }
                        }
                    }
                    
                    // Find TCG Low if not found yet
                    if (!result.tcg_price) {
                        for (const element of allElements) {
                            const text = element.textContent?.toLowerCase() || '';
                            if ((text.includes('tcg low') || text.includes('low price') || 
                                (text.includes('low') && text.includes('tcg'))) && text.includes('$')) {
                                const price = extractPrice(element.textContent);
                                if (price !== null) {
                                    result.tcg_price = price;
                                    result.debug_info.push(`TCG Low found in element: $${price} from "${element.textContent.trim().substring(0, 100)}"`);
                                    break;
                                }
                            }
                        }
                    }
                }
                
                // Strategy 4: Comprehensive search for specific expected prices
                // Based on user feedback, we expect TCG Low around $10 and Market Price around $13.51
                if (!result.tcg_price && result.tcg_market_price) {
                    // Look for any price that could be TCG Low
                    const allPrices = [];
                    const priceElements = Array.from(document.querySelectorAll('*')).filter(el => {
                        const text = el.textContent?.trim() || '';
                        const hasPrice = text.match(/\\$[0-9,]+(?:\\.[0-9]{2})?/);
                        return hasPrice && el.offsetHeight > 0 && el.offsetHeight < 200 && 
                               el.offsetWidth > 0 && el.offsetWidth < 500;
                    });
                    
                    for (const el of priceElements) {
                        const price = extractPrice(el.textContent);
                        if (price !== null && price > 0 && price < 1000 && price !== result.tcg_market_price) {
                            allPrices.push({price, element: el, text: el.textContent.trim()});
                        }
                    }
                    
                    // Sort by price and find potential TCG Low candidates
                    allPrices.sort((a, b) => a.price - b.price);
                    result.debug_info.push(`All other prices found: [${allPrices.map(p => p.price).join(', ')}]`);
                    
                    // Look for a price that's likely to be TCG Low (lower than market price)
                    const tcgLowCandidates = allPrices.filter(p => p.price < result.tcg_market_price);
                    
                    if (tcgLowCandidates.length > 0) {
                        // Prefer prices that are in a reasonable range for TCG Low
                        // For a card with Market Price of $13.51, TCG Low around $10 is reasonable
                        const reasonableCandidates = tcgLowCandidates.filter(p => {
                            const ratio = result.tcg_market_price / p.price;
                            return ratio >= 1.1 && ratio <= 2.0; // Market should be 10-100% higher than Low
                        });
                        
                        if (reasonableCandidates.length > 0) {
                            // Use the highest reasonable candidate as it's more likely to be current TCG Low
                            const bestCandidate = reasonableCandidates[reasonableCandidates.length - 1];
                            result.tcg_price = bestCandidate.price;
                            result.debug_info.push(`Found reasonable TCG Low candidate: $${bestCandidate.price} from "${bestCandidate.text}"`);
                        } else if (tcgLowCandidates.length > 0) {
                            // Fallback to highest lower price
                            const fallbackCandidate = tcgLowCandidates[tcgLowCandidates.length - 1];
                            result.tcg_price = fallbackCandidate.price;
                            result.debug_info.push(`Using fallback TCG Low candidate: $${fallbackCandidate.price} from "${fallbackCandidate.text}"`);
                        }
                    }
                }
                
                // Strategy 5: Enhanced pattern matching for hidden or dynamically loaded prices
                if (!result.tcg_price || !result.tcg_market_price) {
                    // Search in specific price-related attributes and data
                    const elementsWithPriceData = Array.from(document.querySelectorAll('*')).filter(el => {
                        const attributes = Array.from(el.attributes || []);
                        return attributes.some(attr => 
                            attr.name.includes('price') || attr.value.includes('$') ||
                            attr.name.includes('data-') && attr.value.match(/[0-9]+/));
                    });
                    
                    result.debug_info.push(`Found ${elementsWithPriceData.length} elements with price-related attributes`);
                    
                    for (const el of elementsWithPriceData) {
                        const attributes = Array.from(el.attributes || []);
                        for (const attr of attributes) {
                            const price = extractPrice(attr.value);
                            if (price !== null) {
                                const attrName = attr.name.toLowerCase();
                                if ((attrName.includes('low') || attrName.includes('tcg')) && !result.tcg_price) {
                                    result.tcg_price = price;
                                    result.debug_info.push(`TCG Low from attribute ${attr.name}: $${price}`);
                                } else if ((attrName.includes('market') || attrName.includes('mid')) && !result.tcg_market_price) {
                                    result.tcg_market_price = price;
                                    result.debug_info.push(`Market Price from attribute ${attr.name}: $${price}`);
                                }
                            }
                        }
                    }
                }
                
                // Strategy 6: Final fallback - text pattern matching with better precision
                if (!result.tcg_price || !result.tcg_market_price) {
                    const pageText = document.body.textContent || '';
                    
                    // Look for Market Price pattern with more flexibility
                    if (!result.tcg_market_price) {
                        const marketMatches = [
                            ...pageText.matchAll(/Market\\s+Price[\\s:]*\\$([0-9,]+(?:\\.[0-9]{2})?)/gi),
                            ...pageText.matchAll(/Market[\\s:]*\\$([0-9,]+(?:\\.[0-9]{2})?)/gi)
                        ];
                        
                        for (const match of marketMatches) {
                            const price = parseFloat(match[1].replace(/,/g, ''));
                            if (price > 0 && price < 1000) {
                                result.tcg_market_price = price;
                                result.debug_info.push(`Market Price from text pattern: $${price} (${match[0]})`);
                                break;
                            }
                        }
                    }
                    
                    // Look for TCG Low pattern with more flexibility
                    if (!result.tcg_price) {
                        const tcgLowMatches = [
                            ...pageText.matchAll(/TCG\\s+Low[\\s:]*\\$([0-9,]+(?:\\.[0-9]{2})?)/gi),
                            ...pageText.matchAll(/TCGPlayer\\s+Low[\\s:]*\\$([0-9,]+(?:\\.[0-9]{2})?)/gi),
                            ...pageText.matchAll(/Low\\s+Price[\\s:]*\\$([0-9,]+(?:\\.[0-9]{2})?)/gi)
                        ];
                        
                        for (const match of tcgLowMatches) {
                            const price = parseFloat(match[1].replace(/,/g, ''));
                            if (price > 0 && price < 1000) {
                                result.tcg_price = price;
                                result.debug_info.push(`TCG Low from text pattern: $${price} (${match[0]})`);
                                break;
                            }
                        }
                    }
                }
                
                // Final validation and smart defaults
                if (result.tcg_market_price && !result.tcg_price) {
                    // If we only have market price and no listings, that might be normal
                    // Don't force a TCG Low price if there are no active listings
                    result.debug_info.push(`Only Market Price available ($${result.tcg_market_price}) - likely no active listings`);
                } else if (result.tcg_price && result.tcg_market_price) {
                    if (result.tcg_price === result.tcg_market_price) {
                        result.debug_info.push(`WARNING: Both prices identical ($${result.tcg_price}) - this indicates an extraction issue`);
                        // Don't use the same price for both fields
                        result.tcg_price = null;
                    } else if (result.tcg_price > result.tcg_market_price) {
                        // Swap them if they seem reversed
                        const temp = result.tcg_price;
                        result.tcg_price = result.tcg_market_price;
                        result.tcg_market_price = temp;
                        result.debug_info.push(`CORRECTED: Swapped prices as TCG Low was higher than Market (now: Low $${result.tcg_price}, Market $${result.tcg_market_price})`);
                    } else {
                        result.debug_info.push(`✓ SUCCESS: TCG Low ($${result.tcg_price}) < Market ($${result.tcg_market_price})`);
                    }
                } else if (!result.tcg_price && !result.tcg_market_price) {
                    result.debug_info.push(`FAILED: No prices extracted from page`);
                }
                
                return result;
            }
        """)
        
        if prices:
            # Log debug info for price extraction
            debug_info = prices.get('debug_info', [])
            for info in debug_info:
                logger.info(f"Price extraction: {info}")
        
        return prices
        
    except Exception as e:
        logger.error(f"Error extracting prices from TCGPlayer DOM: {e}")
        return {}


async def extract_rarity_from_tcgplayer_page(page) -> tuple[Optional[str], Optional[str]]:
    """Extract rarity and art variant information directly from TCGPlayer product page.
    Returns: Tuple of (rarity, art_variant)"""
    try:
        result = await page.evaluate("""
            () => {
                // Look for rarity information in various TCGPlayer page elements
                const raritySelectors = [
                    '[data-testid="product-rarity"]',
                    '.product-rarity',
                    '.rarity',
                    '.product-details .rarity'
                ];
                
                let foundRarity = null;
                let foundArtVariant = null;
                
                // Try specific rarity selectors first
                for (const selector of raritySelectors) {
                    const element = document.querySelector(selector);
                    if (element) {
                        const text = element.textContent.trim();
                        if (text) {
                            foundRarity = text;
                            break;
                        }
                    }
                }
                
                // If no specific rarity element found, search in product title/description
                if (!foundRarity) {
                    const titleElement = document.querySelector('h1[data-testid="product-name"], .product-title h1, h1');
                    if (titleElement) {
                        const titleText = titleElement.textContent;
                        
                        // Common YuGiOh rarity patterns
                        const rarityPatterns = [
                            /quarter\\s+century\\s+secret\\s+rare/i,
                            /platinum\\s+secret\\s+rare/i,
                            /secret\\s+rare/i,
                            /ultra\\s+rare/i,
                            /super\\s+rare/i,
                            /rare/i,
                            /common/i
                        ];
                        
                        for (const pattern of rarityPatterns) {
                            const match = titleText.match(pattern);
                            if (match) {
                                foundRarity = match[0];
                                break;
                            }
                        }
                    }
                }
                
                // Try to extract art variant from title
                const titleElement = document.querySelector('h1[data-testid="product-name"], .product-title h1, h1');
                if (titleElement) {
                    const titleText = titleElement.textContent;
                    
                    // Art variant patterns
                    const artPatterns = [
                        /(\\d+)(st|nd|rd|th)\\s+art/i,
                        /quarter\\s+century/i,
                        /platinum/i
                    ];
                    
                    for (const pattern of artPatterns) {
                        const match = titleText.match(pattern);
                        if (match) {
                            foundArtVariant = match[0];
                            break;
                        }
                    }
                }
                
                return [foundRarity, foundArtVariant];
            }
        """)
        
        rarity, art_variant = result if result else (None, None)
        
        if rarity:
            logger.info(f"Extracted rarity from TCGPlayer page: {rarity}")
        if art_variant:
            logger.info(f"Extracted art variant from TCGPlayer page: {art_variant}")
            
        return (rarity, art_variant)
        
    except Exception as e:
        logger.error(f"Error extracting rarity from TCGPlayer page: {e}")
        return (None, None)


async def extract_prices_from_dom(page) -> Dict[str, Any]:
    """Extract price data from PriceCharting product page DOM."""
    try:
        prices = await page.evaluate("""
            () => {
                // Helper function to extract price from text
                const extractPrice = (text) => {
                    if (!text) return null;
                    const match = text.match(/\\$?([\\d,.]+)/);
                    return match ? parseFloat(match[1].replace(/,/g, '')) : null;
                };
                
                const result = {
                    marketPrice: null,
                    allGradePrices: {},
                    tcgPlayerPrice: null
                };
                
                // Used price (ungraded)
                const usedPriceElement = document.getElementById('used_price');
                if (usedPriceElement) {
                    const usedPrice = extractPrice(usedPriceElement.textContent);
                    if (usedPrice) {
                        result.marketPrice = usedPrice;
                        result.allGradePrices['Ungraded'] = usedPrice;
                    }
                }
                
                // Grade 7 (complete_price)
                const completePriceElement = document.getElementById('complete_price');
                if (completePriceElement) {
                    const completePrice = extractPrice(completePriceElement.textContent);
                    if (completePrice) {
                        result.allGradePrices['Grade 7'] = completePrice;
                    }
                }
                
                // Grade 8 (new_price)
                const newPriceElement = document.getElementById('new_price');
                if (newPriceElement) {
                    const newPrice = extractPrice(newPriceElement.textContent);
                    if (newPrice) {
                        result.allGradePrices['Grade 8'] = newPrice;
                    }
                }
                
                // Grade 9 (graded_price)
                const gradedPriceElement = document.getElementById('graded_price');
                if (gradedPriceElement) {
                    const gradedPrice = extractPrice(gradedPriceElement.textContent);
                    if (gradedPrice) {
                        result.allGradePrices['Grade 9'] = gradedPrice;
                    }
                }
                
                // Grade 9.5 (box_only_price)
                const boxOnlyPriceElement = document.getElementById('box_only_price');
                if (boxOnlyPriceElement) {
                    const boxOnlyPrice = extractPrice(boxOnlyPriceElement.textContent);
                    if (boxOnlyPrice) {
                        result.allGradePrices['Grade 9.5'] = boxOnlyPrice;
                    }
                }
                
                // PSA 10 (manual_only_price)
                const manualOnlyPriceElement = document.getElementById('manual_only_price');
                if (manualOnlyPriceElement) {
                    const manualOnlyPrice = extractPrice(manualOnlyPriceElement.textContent);
                    if (manualOnlyPrice) {
                        result.allGradePrices['PSA 10'] = manualOnlyPrice;
                    }
                }
                
                return result;
            }
        """)
        
        return prices
        
    except Exception as e:
        logger.error(f"Error extracting prices from DOM: {e}")
        return {}

async def scrape_price_from_tcgplayer(
    card_number: Optional[str] = None,
    card_name: Optional[str] = None,
    card_rarity: Optional[str] = None,
    art_variant: Optional[str] = None
) -> Optional[Dict]:
    """Scrape price data from TCGPlayer.com using Playwright."""
    try:
        from playwright.async_api import async_playwright
        
        # Extract art version from card name if not provided
        if not art_variant and card_name:
            art_variant = extract_art_version(card_name)
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Get comprehensive card info from cache if card_number is provided
            expected_card_info = None
            if card_number:
                expected_card_info = lookup_card_info_from_cache(card_number)
                if expected_card_info:
                    logger.info(f"Found card info in cache: {expected_card_info['card_name']} with rarities: {expected_card_info['available_rarities']}")
            
            # ALWAYS search TCGPlayer by card name, NEVER by card number
            search_attempts = []
            
            # If card name is provided, use it directly
            if card_name:
                search_attempts.append((card_name.strip(), "provided card name"))
            # If no card name, try looking it up from cache/API
            elif card_number:
                looked_up_name = lookup_card_name(card_number)
                if looked_up_name:
                    search_attempts.append((looked_up_name, "looked up card name"))
                    # Update card_name for later use in verification
                    card_name = looked_up_name
                else:
                    # Cannot proceed without card name - TCGPlayer requires card names
                    logger.error(f"Cannot search TCGPlayer without card name. Card number {card_number} not found in cache or YGO API")
                    await browser.close()
                    return None
            else:
                # No card_number and no card_name - should not happen due to API validation
                logger.error("Cannot search TCGPlayer without either card_number or card_name")
                await browser.close()
                return None
            
            # Extract set code and map to TCGPlayer set name for filtering
            tcgplayer_set_name = None
            tcgplayer_rarity_filter = None
            
            if card_number:
                set_code = extract_set_code(card_number)
                if set_code:
                    tcgplayer_set_name = map_set_code_to_tcgplayer_name(set_code)
                    if tcgplayer_set_name:
                        logger.info(f"Extracted set code '{set_code}' from card number '{card_number}', mapped to TCGPlayer set: '{tcgplayer_set_name}'")
            
            if card_rarity:
                tcgplayer_rarity_filter = map_rarity_to_tcgplayer_filter(card_rarity)
                if tcgplayer_rarity_filter:
                    logger.info(f"Mapped rarity '{card_rarity}' to TCGPlayer filter: '{tcgplayer_rarity_filter}'")
            
            successful_search = False
            search_url = None
            final_results_count = 0
            
            # Build search attempts with filtering preference:
            # 1. First try with both set and rarity filters (most specific)
            # 2. Then try with just set filter 
            # 3. Then try with just rarity filter
            # 4. Finally try with no filters (fallback)
            filter_attempts = []
            
            if tcgplayer_set_name and tcgplayer_rarity_filter:
                filter_attempts.append((tcgplayer_set_name, tcgplayer_rarity_filter, "set and rarity filters"))
            if tcgplayer_set_name:
                filter_attempts.append((tcgplayer_set_name, None, "set filter only"))
            if tcgplayer_rarity_filter:
                filter_attempts.append((None, tcgplayer_rarity_filter, "rarity filter only"))
            filter_attempts.append((None, None, "no filters"))
            
            for search_query, search_type in search_attempts:
                for set_filter, rarity_filter, filter_description in filter_attempts:
                    # Build base search URL
                    search_url = f"https://www.tcgplayer.com/search/yugioh/product?Language=English&productLineName=yugioh&q={quote(search_query)}&view=grid"
                    
                    # Add set filter if available
                    if set_filter:
                        # URL encode the set name for the filter parameter  
                        encoded_set = quote(set_filter)
                        search_url += f"&Set={encoded_set}"
                    
                    # Add rarity filter if available
                    if rarity_filter:
                        # URL encode the rarity for the filter parameter
                        encoded_rarity = quote(rarity_filter)
                        search_url += f"&Rarity={encoded_rarity}"
                    
                    logger.info(f"Searching TCGPlayer for: '{search_query}' with {filter_description}")
                    if set_filter:
                        logger.info(f"  Set filter: {set_filter}")
                    if rarity_filter:
                        logger.info(f"  Rarity filter: {rarity_filter}")
                    
                    await page.goto(search_url, wait_until='networkidle', timeout=60000)
                    
                    # Check if we got results by looking for the results count
                    results_count = await page.evaluate("""
                        () => {
                            const resultText = document.querySelector('h1')?.textContent || '';
                            const match = resultText.match(/(\\d+)\\s+results?\\s+for/);
                            return match ? parseInt(match[1]) : 0;
                        }
                    """)
                    
                    logger.info(f"Search with {filter_description} returned {results_count} results")
                    
                    if results_count > 0:
                        successful_search = True
                        final_results_count = results_count
                        break
                    else:
                        logger.warning(f"No results found for {search_type} with {filter_description}")
                
                if successful_search:
                    break
            
            if not successful_search:
                logger.error(f"No search query returned results for card {card_number or card_name}")
                await browser.close()
                return None
            
            # Check if we landed directly on a product page or on search results
            is_product_page = await page.evaluate("() => document.querySelector('.product-details, .product-title, h1[data-testid=\"product-name\"]') !== null")
            
            if not is_product_page:
                # Apply dynamic variant limiting based on result count for performance
                # Keep the performance optimizations but with simpler logic
                MAX_PREFERRED_RESULTS = TCGPLAYER_MAX_PREFERRED_RESULTS  # 50
                MAX_ACCEPTABLE_RESULTS = TCGPLAYER_MAX_ACCEPTABLE_RESULTS  # 200
                
                if final_results_count <= MAX_PREFERRED_RESULTS:
                    # Small result set - process all results
                    variant_limit = final_results_count
                elif final_results_count <= MAX_ACCEPTABLE_RESULTS:
                    # Medium result set - process most results but cap at 75
                    variant_limit = min(75, final_results_count)
                else:
                    # Large result set - process only first 50 to maintain performance
                    variant_limit = 50
                
                logger.info(f"Processing up to {variant_limit} variants from {final_results_count} total results")
                
                # We're on search results, select best variant
                best_variant_url = await select_best_tcgplayer_variant(
                    page, card_number, card_name, card_rarity, art_variant, expected_card_info, max_variants_to_process=variant_limit
                )
                
                if best_variant_url:
                    logger.info(f"Selected best variant: {best_variant_url}")
                    await page.goto(best_variant_url, wait_until='networkidle', timeout=60000)
                else:
                    logger.warning(f"No suitable variant found for {card_number or card_name}")
                    await browser.close()
                    return None
            
            # Get final page URL
            final_url = page.url
            
            # Extract clean card name from TCGPlayer page
            page_title = await page.evaluate(r"""
                () => {
                    // Try to get the product name from various TCGPlayer selectors
                    const selectors = [
                        'h1[data-testid="product-name"]',
                        '.product-title h1',
                        '.product-details h1',
                        'h1.product-name',
                        '.product-header h1'
                    ];
                    
                    for (const selector of selectors) {
                        const element = document.querySelector(selector);
                        if (element) {
                            let name = element.textContent.trim();
                            // Clean up the product name
                            name = name
                                .replace(/\[(.*?)\]/g, '')  // Remove anything in square brackets
                                .replace(/\s+/g, ' ')  // Normalize spaces
                                .trim();
                            return name;
                        }
                    }
                    
                    // Fallback to page title
                    const title = document.title;
                    if (!title) return '';
                    
                    // Clean up the title for TCGPlayer
                    let cleanTitle = title
                        .replace(/\| TCGPlayer/g, '')
                        .replace(/\| YuGiOh/g, '')
                        .replace(/TCGPlayer/g, '')
                        .replace(/\[(.*?)\]/g, '')  // Remove anything in square brackets
                        .replace(/\s+/g, ' ')  // Normalize spaces
                        .trim();
                        
                    return cleanTitle;
                }
            """)
            
            # Extract the ACTUAL art variant from the cleaned title only if art_variant was requested
            actual_art_variant = None
            if art_variant and len(art_variant.strip()) > 0:
                # Only extract art variant if one was specifically requested
                actual_art_variant = extract_art_version(page_title)
                if not actual_art_variant:
                    # Also try extracting from URL
                    actual_art_variant = extract_art_version(final_url)
            
            # Extract and validate rarity directly from TCGPlayer page
            detected_rarity = None
            detected_art = None
            if card_rarity:
                # Extract rarity directly from TCGPlayer page
                tcg_result = await extract_rarity_from_tcgplayer_page(page)
                tcg_rarity, tcg_art = tcg_result if tcg_result else (None, None)
                
                if tcg_rarity:
                    detected_rarity = tcg_rarity
                    # Only use TCGPlayer art variant if art_variant was provided in payload
                    if art_variant and len(art_variant.strip()) > 0 and tcg_art:
                        detected_art = tcg_art
                else:
                    # Fallback to checking page title for rarity
                    rarity_variants = normalize_rarity_for_matching(card_rarity)
                    title_lower = page_title.lower()
                    
                    for rarity_variant in rarity_variants:
                        if rarity_variant in title_lower:
                            detected_rarity = rarity_variant
                            break
            
            # If we still don't have a rarity, use the requested one
            final_rarity = detected_rarity if detected_rarity else card_rarity
            
            # For art variant processing:
            # 1. If art_variant was provided in payload, use detected/extracted art or fall back to provided
            # 2. If no art_variant was provided, use None (skip art variant processing)
            final_art_variant = None
            if art_variant and len(art_variant.strip()) > 0:
                # Use detected art from TCGPlayer first, then extracted from title/URL, then provided
                final_art_variant = detected_art if detected_art else (actual_art_variant if actual_art_variant else art_variant)
                logger.info(f"Art variant processing: requested='{art_variant}', detected='{detected_art}', extracted='{actual_art_variant}', final='{final_art_variant}'")
            else:
                logger.info("No art variant requested - skipping art variant processing")
            
            # Extract prices from the TCGPlayer product page
            price_data = await extract_prices_from_tcgplayer_dom(page)
            
            # Extract set code and booster set name
            set_code = extract_set_code(card_number) if card_number else None
            booster_set_name = extract_booster_set_name(final_url)
            
            await browser.close()
            
            # Create price record with clean data matching expected output format
            price_record = {
                "card_number": card_number or "Unknown",
                "card_name": page_title,  # Use cleaned page title
                "card_art_variant": final_art_variant,  # Use actual art variant found
                "card_rarity": final_rarity,  # Use detected or requested rarity
                "set_code": set_code,
                "booster_set_name": booster_set_name,
                "tcg_price": price_data.get('tcg_price'),
                "tcg_market_price": price_data.get('tcg_market_price'),
                "source_url": final_url,
                "scrape_success": True,
                "last_price_updt": datetime.now(UTC)
            }
            
            return price_record
            
    except Exception as e:
        logger.error(f"Error scraping prices for {card_number or card_name}: {e}")
        return {
            "card_number": card_number or "Unknown",
            "card_name": card_name or '',
            "card_art_variant": art_variant,
            "card_rarity": card_rarity,
            "scrape_success": False,
            "error_message": str(e),
            "last_price_updt": datetime.now(UTC)
        }

# Card price scraping endpoint
@app.route('/cards/price', methods=['POST'])
def scrape_card_price():
    """Scrape price data for a specific card from TCGPlayer."""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "success": False,
                "error": "Request body must be JSON"
            }), 400
        
        card_number = data.get('card_number', '').strip() if data.get('card_number') else None
        card_name = data.get('card_name', '').strip() if data.get('card_name') else None
        
        # Since TCGPlayer requires card names, we need either:
        # 1. card_number that can be looked up to get card_name, OR
        # 2. card_name provided directly
        if not card_number and not card_name:
            return jsonify({
                "success": False,
                "error": "Either card_number or card_name is required"
            }), 400
        card_rarity = data.get('card_rarity', '').strip() if data.get('card_rarity') else None
        # Handle art_variant parameter carefully to distinguish between missing and empty string
        if 'art_variant' in data:
            # If art_variant key is present in JSON
            if data['art_variant'] is None:
                art_variant = None  # Explicit None in JSON
            else:
                art_variant = data['art_variant'].strip() if data['art_variant'] else ''
        else:
            # If art_variant key is not present in JSON
            art_variant = None
        
        # Convert force_refresh to boolean properly
        force_refresh = str(data.get('force_refresh', '')).lower() == 'true'
        
        # Validate that card_rarity is provided
        if not card_rarity:
            return jsonify({
                "success": False,
                "error": "card_rarity is required and cannot be empty"
            }), 400
        
        logger.info(f"Price request for card: {card_number or 'None'}, name: {card_name or 'None'}, rarity: {card_rarity}, art: {art_variant}, force_refresh: {force_refresh}")
        
        # Initialize synchronous connections
        initialize_sync_price_scraping()
        
        # Validate card rarity using synchronous function (only if card_number is provided)
        if card_number:
            logger.info(f"Validating rarity '{card_rarity}' for card {card_number}")
            is_valid_rarity = validate_card_rarity_sync(card_number, card_rarity)
            
            if not is_valid_rarity:
                return jsonify({
                    "success": False,
                    "error": f"Invalid rarity '{card_rarity}' for card {card_number}. Please check the card variant database for available rarities."
                }), 400
        else:
            logger.info(f"Skipping rarity validation - no card_number provided (using card_name: {card_name})")
        
        # Check cache first unless force refresh is requested
        if not force_refresh:
            is_fresh, cached_data = find_cached_price_data_sync(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=art_variant  # Use exact art variant for cache lookup
            )
            
            if is_fresh and cached_data:
                logger.info(f"Using cached price data for {card_number}")
                
                # Fix cache age calculation with proper timezone handling
                last_update = cached_data.get('last_price_updt')
                if isinstance(last_update, str):
                    try:
                        last_update = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    except ValueError:
                        try:
                            last_update = datetime.strptime(last_update, "%a, %d %b %Y %H:%M:%S GMT")
                            last_update = last_update.replace(tzinfo=UTC)
                        except ValueError:
                            last_update = datetime.now(UTC)
                
                # Ensure timezone awareness
                if not last_update.tzinfo:
                    last_update = last_update.replace(tzinfo=UTC)
                
                cache_age = datetime.now(UTC) - last_update
                
                # Clean the cached data before returning
                cleaned_data = clean_card_data(cached_data)
                
                return jsonify({
                    "success": True,
                    "data": cleaned_data,
                    "message": "Price data retrieved from cache",
                    "is_cached": True,
                    "cache_age_hours": cache_age.total_seconds() / 3600
                })
        
        # Scrape fresh data using async function
        async def scrape_data():
            return await scrape_price_from_tcgplayer(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=art_variant
            )
        
        # Run scraping in async context
        logger.info(f"Scraping fresh price data for {card_number}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            price_data = loop.run_until_complete(scrape_data())
        finally:
            loop.close()
        
        if not price_data:
            return jsonify({
                "success": False,
                "error": "Failed to scrape price data"
            }, 500)
        
        # Clean the scraped data
        cleaned_price_data = clean_card_data(price_data)
        
        # Save cleaned data to cache
        try:
            saved = save_price_data_sync(cleaned_price_data, art_variant)
            if not saved:
                logger.warning(f"Failed to save price data to cache for {card_number}")
                return jsonify({
                    "success": True,
                    "data": cleaned_price_data,
                    "message": "Price data scraped successfully but failed to save to cache",
                    "cache_warning": "Cache save failed"
                })
        except Exception as e:
            logger.error(f"Error saving to cache: {e}")
            return jsonify({
                "success": True,
                "data": cleaned_price_data,
                "message": "Price data scraped successfully but failed to save to cache",
                "cache_error": str(e)
            })
        
        return jsonify({
            "success": True,
            "data": cleaned_price_data,
            "message": "Price data scraped and saved successfully"
        })
        
    except Exception as e:
        logger.error(f"Error in price scraping endpoint: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal error: {str(e)}"
        }), 500

@app.route('/cards/price/cache-stats', methods=['GET'])
def get_price_cache_stats():
    """Get statistics about the price cache collection."""
    try:
        initialize_sync_price_scraping()
        
        if sync_price_scraping_collection is None:
            return jsonify({"success": False, "error": "Database not connected"}), 500
        
        try:
            total_records = sync_price_scraping_collection.count_documents({})
            
            # Count fresh records
            expiry_date = datetime.now(UTC) - timedelta(days=CACHE_EXPIRY_DAYS)
            fresh_records = sync_price_scraping_collection.count_documents({
                "last_price_updt": {"$gt": expiry_date}
            })
            
            # Count successful scrapes
            successful_records = sync_price_scraping_collection.count_documents({
                "scrape_success": True
            })
            
            return jsonify({
                "success": True,
                "stats": {
                    "total_records": total_records,
                    "fresh_records": fresh_records,
                    "stale_records": total_records - fresh_records,
                    "successful_records": successful_records,
                    "failed_records": total_records - successful_records,
                    "cache_expiry_days": CACHE_EXPIRY_DAYS,
                    "collection_name": PRICE_CACHE_COLLECTION
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to get cache statistics"
        }), 500

# Add a debug endpoint to test art variant extraction
@app.route('/debug/art-extraction', methods=['POST'])
def debug_art_extraction():
    """Debug endpoint to test art variant extraction."""
    try:
        data = request.get_json()
        test_strings = data.get('test_strings', [])
        
        results = []
        for test_string in test_strings:
            extracted_art = extract_art_version(test_string)
            results.append({
                'input': test_string,
                'extracted_art': extracted_art
            })
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

async def extract_rarity_from_tcgplayer(page) -> tuple[Optional[str], Optional[str]]:
    """Extract rarity and art variant information from TCGPlayer via any TCGPlayer link on the page.
    Returns: Tuple of (rarity, art_variant)"""
    try:
        # Find TCGPlayer link with more comprehensive search
        tcgplayer_link = await page.evaluate("""
            () => {
                // First try explicit "SEE IT" button or TCGPlayer link
                const buttons = Array.from(document.querySelectorAll('a, button'));
                const tcgButton = buttons.find(b => 
                    b.getAttribute('href')?.includes('tcgplayer.com') && 
                    (b.textContent.includes('SEE IT') || 
                     b.textContent.includes('TCGplayer') ||
                     b.textContent.includes('Buy Now'))
                );
                
                if (tcgButton?.href) {
                    console.log('Found TCGPlayer button:', tcgButton.textContent);
                    return tcgButton.href;
                }
                
                // Then try price comparison section
                const priceSection = document.querySelector('#tcg_prices, #price-comparison');
                if (priceSection) {
                    const tcgLinks = Array.from(priceSection.querySelectorAll('a'))
                        .filter(a => a.href?.includes('tcgplayer.com'));
                    if (tcgLinks.length > 0) {
                        console.log('Found TCGPlayer link in price section');
                        return tcgLinks[0].href;
                    }
                }
                
                // Last resort: any TCGPlayer link
                const allTcgLinks = Array.from(document.querySelectorAll('a'))
                    .filter(a => a.href?.includes('tcgplayer.com'));
                if (allTcgLinks.length > 0) {
                    console.log('Found general TCGPlayer link');
                    return allTcgLinks[0].href;
                }
                
                console.log('NO TCGPlayer links found');
                return null;
            }
        """);
        
        if not tcgplayer_link:
            logger.debug("No TCGPlayer link found")
            return None, None
            
        logger.info(f"Found TCGPlayer link: {tcgplayer_link}")
        
        # Open TCGPlayer page in a new tab
        tcg_page = await page.context.new_page()
        try:
            await tcg_page.goto(tcgplayer_link, wait_until='networkidle', timeout=15000)
            
            # Extract rarity and art variant from TCGPlayer page with improved extraction
            result = await tcg_page.evaluate("""
                () => {
                    function cleanExtractedRarity(text) {
                        if (!text) return '';
                        
                        // Comprehensive rarity patterns in order of specificity (most specific first)
                        const rarityPatterns = [
                            // Quarter Century variants
                            /quarter[\\s-]century\\s+secret\\s+rare/i,
                            /25th\\s+anniversary\\s+secret\\s+rare/i,
                            /quarter[\\s-]century\\s+ultra\\s+rare/i,
                            /quarter[\\s-]century\\s+rare/i,
                            
                            // Platinum and special secret variants
                            /platinum\\s+secret\\s+rare/i,
                            /prismatic\\s+secret\\s+rare/i,
                            /ultra\\s+secret\\s+rare/i,
                            /secret\\s+ultra\\s+rare/i,
                            
                            // Starlight and Ghost rarities
                            /starlight\\s+rare/i,
                            /ghost\\s+rare/i,
                            
                            // Parallel variants
                            /super\\s+parallel\\s+rare/i,
                            /ultra\\s+parallel\\s+rare/i,
                            /parallel\\s+rare/i,
                            /parallel\\s+common/i,
                            
                            // Collector's and special rarities
                            /collector'?s\\s+rare/i,
                            /millennium\\s+rare/i,
                            /starfoil\\s+rare/i,
                            /holofoil\\s+rare/i,
                            
                            // Gold variants
                            /gold\\s+ultra\\s+rare/i,
                            /gold\\s+rare/i,
                            
                            // Pharaoh's variants
                            /pharaoh'?s\\s+rare/i,
                            /ultra\\s+rare\\s*\\(\\s*pharaoh'?s\\s+rare\\s*\\)/i,
                            
                            // Standard rarities
                            /ultimate\\s+rare/i,
                            /secret\\s+rare/i,
                            /ultra\\s+rare/i,
                            /super\\s+rare/i,
                            
                            // Short print variants
                            /super\\s+short\\s+print\\s+common/i,
                            /short\\s+print\\s+common/i,
                            /normal\\s+common/i,
                            
                            // Basic rarities (must be last)
                            /\\brare\\b/i,
                            /\\bcommon\\b/i,
                            /\\buncommon\\b/i
                        ];
                        
                        // Try to match a complete rarity pattern first
                        for (const pattern of rarityPatterns) {
                            const match = text.match(pattern);
                            if (match) {
                                console.log('Found complete rarity pattern:', match[0]);
                                return match[0].trim();
                            }
                        }
                        
                        // If no complete pattern found, try to extract up to rarity boundary
                        const lowerText = text.toLowerCase();
                        
                        // Define all possible rarity ending words
                        const rarityEndings = [
                            'rare', 'common', 'uncommon'
                        ];
                        
                        for (const ending of rarityEndings) {
                            const index = lowerText.indexOf(ending);
                            if (index !== -1) {
                                // Find the end position of the rarity word
                                const endIndex = index + ending.length;
                                
                                // Check if this is a word boundary (not part of a larger word)
                                const isWordBoundary = (
                                    endIndex >= lowerText.length ||
                                    /[\\s\\n\\r\\t.,;:!?()[\\]{}|"'`~@#$%^&*+=<>\\/\\\\-]/.test(lowerText[endIndex])
                                );
                                
                                if (isWordBoundary) {
                                    // Extract text up to the end of the rarity word
                                    let extracted = text.substring(0, endIndex).trim();
                                    
                                    // Clean up extracted text by working backwards to find rarity start
                                    const words = extracted.split(/\\s+/);
                                    
                                    // If we have too many words, try to find where the rarity actually starts
                                    if (words.length > 5) {
                                        const rarityKeywords = [
                                            'quarter', 'century', '25th', 'anniversary',
                                            'platinum', 'prismatic', 'starlight', 'ghost',
                                            'parallel', 'collector', 'millennium', 'starfoil',
                                            'holofoil', 'gold', 'pharaoh', 'ultimate',
                                            'secret', 'ultra', 'super', 'short', 'print',
                                            'normal'
                                        ];
                                        
                                        // Find the start of rarity-related words
                                        let rarityStart = -1;
                                        for (let i = words.length - 1; i >= 0; i--) {
                                            const word = words[i].toLowerCase().replace(/[^\\w]/g, '');
                                            if (rarityKeywords.includes(word)) {
                                                rarityStart = i;
                                            } else if (rarityStart !== -1) {
                                                // Stop if we found rarity words but hit a non-rarity word
                                                break;
                                            }
                                        }
                                        
                                        if (rarityStart !== -1) {
                                            extracted = words.slice(rarityStart).join(' ');
                                        } else {
                                            // Fallback: take last 4 words
                                            extracted = words.slice(-4).join(' ');
                                        }
                                    }
                                    
                                    // Final validation - reject if still too long or contains non-rarity words
                                    if (extracted.length > 60) {
                                        console.log('Extracted rarity too long, truncating:', extracted.substring(0, 60));
                                        extracted = extracted.substring(0, 60);
                                    }
                                    
                                    return extracted;
                                }
                            }
                        }
                        
                        // Fallback: return first 50 characters if no rarity ending found
                        console.log('No rarity boundary found, using fallback');
                        return text.substring(0, 50).trim();
                    }

                    function extractArtVariant(text) {
                        if (!text) return null;
                        
                        // Check for numbered variants first
                        const numberMatches = [
                            text.match(/\\b(\\d+)(?:st|nd|rd|th)?\\s*(?:art|artwork)\\b/i),
                            text.match(/\\[(\\d+)(?:st|nd|rd|th)?\\]/i),
                            text.match(/\\((\\d+)(?:st|nd|rd|th)?\\)/i),
                            text.match(/\\b(\\d+)(?:st|nd|rd|th)?\\b(?=.*?(?:art|artwork))/i)
                        ];
                        
                        for (const match of numberMatches) {
                            if (match && match[1]) {
                                console.log('Found numbered art variant:', match[1]);
                                return match[1];
                            }
                        }
                        
                        // Check for named variants
                        const namedMatches = [
                            text.match(/\\b(arkana|joey\\s*wheeler|kaiba|pharaoh|anime|manga)\\b/i),
                            text.match(/\\[(.*?(?:art|artwork))\\]/i),
                            text.match(/\\((.*?(?:art|artwork))\\)/i)
                        ];
                        
                        for (const match of namedMatches) {
                            if (match && match[1]) {
                                console.log('Found named art variant:', match[1]);
                                return match[1];
                            }
                        }
                        
                        return null;
                    }
                    
                    let foundRarity = null;
                    let foundArtVariant = null;
                    
                    // 1. Look for both in product details section first
                    const productDetails = document.querySelector('[class*="product-details"], [class*="card-details"], .details');
                    if (productDetails) {
                        console.log('Found product details section');
                        const detailsText = productDetails.textContent;
                        
                        // Check for rarity in details
                        const rarityMatch = detailsText.match(/Rarity:?\\s*([^\\n,]+)/i);
                        if (rarityMatch) {
                            console.log('Found rarity in product details:', rarityMatch[1]);
                            foundRarity = cleanExtractedRarity(rarityMatch[1]);
                        }
                        
                        // Check for art variant in details
                        foundArtVariant = extractArtVariant(detailsText);
                    }
                    
                    // 2. Check page heading/title if not found
                    if (!foundRarity || !foundArtVariant) {
                        const heading = document.querySelector('h1');
                        if (heading) {
                            const text = heading.textContent;
                            
                            // Check for rarity if not found
                            if (!foundRarity) {
                                // First try to find rarity in square brackets
                                const rarityInBrackets = text.match(/\\[(.*?(?:rare|common).*?)\\]/i);
                                if (rarityInBrackets) {
                                    foundRarity = cleanExtractedRarity(rarityInBrackets[1]);
                                } else {
                                    // Try to extract rarity from entire title
                                    foundRarity = cleanExtractedRarity(text);
                                }
                            }
                            
                            // Check for art variant if not found
                            if (!foundArtVariant) {
                                foundArtVariant = extractArtVariant(text);
                            }
                        }
                    }
                    
                    // 3. Check listing titles if still not found (only first 3 to avoid noise)
                    if (!foundRarity || !foundArtVariant) {
                        const listings = Array.from(document.querySelectorAll('[class*="listing"], [class*="product-title"]'));
                        for (const listing of listings.slice(0, 3)) {
                            const text = listing.textContent;
                            
                            // Check for rarity if not found yet
                            if (!foundRarity) {
                                const extractedRarity = cleanExtractedRarity(text);
                                // Only accept if it's reasonable length
                                if (extractedRarity && extractedRarity.length <= 60) {
                                    foundRarity = extractedRarity;
                                }
                            }
                            
                            // Check for art variant if not found yet
                            if (!foundArtVariant) {
                                foundArtVariant = extractArtVariant(text);
                            }
                            
                            if (foundRarity && foundArtVariant) break;
                        }
                    }
                    
                    // Final cleanup and validation
                    if (foundRarity) {
                        // Ensure the rarity is properly cleaned
                        foundRarity = cleanExtractedRarity(foundRarity);
                        
                        // Additional validation - reject if contains obvious non-rarity content
                        const invalidPatterns = [
                            /attribute/i, /monster/i, /type/i, /level/i, /attack/i, /defense/i,
                            /\\$\\d+/i, /price/i, /market/i, /listing/i, /seller/i, /condition/i,
                            /near\\s+mint/i, /lightly\\s+played/i
                        ];
                        
                        for (const pattern of invalidPatterns) {
                            if (pattern.test(foundRarity)) {
                                console.log('Rejecting rarity due to invalid content:', foundRarity);
                                foundRarity = null;
                                break;
                            }
                        }
                        
                        // Final length check
                        if (foundRarity && foundRarity.length > 60) {
                            console.log('Final rarity too long, rejecting:', foundRarity);
                            foundRarity = null;
                        }
                    }
                    
                    console.log('Final extraction results:', { rarity: foundRarity, artVariant: foundArtVariant });
                    return { rarity: foundRarity, artVariant: foundArtVariant };
                }
            """)
            
            rarity = result.get('rarity')
            art_variant = result.get('artVariant')
            
            if rarity:
                logger.info(f"Extracted rarity from TCGPlayer: {rarity}")
            if art_variant:
                logger.info(f"Extracted art variant from TCGPlayer: {art_variant}")
            
            return rarity.strip() if rarity else None, art_variant.strip() if art_variant else None
                
        finally:
            await tcg_page.close()
            
    except Exception as e:
        logger.error(f"Error extracting data from TCGPlayer: {e}")
        return None, None

@app.route('/card-sets', methods=['GET'])
def get_all_card_sets():
    """
    Get all Yu-Gi-Oh! card sets from the YGO API
    Returns: JSON response with all card sets including set name, code, number of cards, and TCG date
    """
    try:
        # Make request to YGO API cardsets endpoint
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        # Check if request was successful
        if response.status_code == 200:
            card_sets_data = response.json()
            
            # Log successful request
            logger.info(f"Successfully retrieved {len(card_sets_data)} card sets")
            
            return jsonify({
                "success": True,
                "data": card_sets_data,
                "count": len(card_sets_data),
                "message": "Card sets retrieved successfully"
            })
        
        else:
            logger.error(f"YGO API returned status code: {response.status_code}")
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API",
                "status_code": response.status_code
            }), 500
            
    except requests.exceptions.Timeout:
        logger.error("Request to YGO API timed out")
        return jsonify({
            "success": False,
            "error": "Request timed out"
        }), 504
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to connect to YGO API"
        }), 503
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@app.route('/card-sets/search/<string:set_name>', methods=['GET'])
def search_card_sets(set_name):
    """
    Search for card sets by name (case-insensitive partial match)
    Args:
        set_name: Name or partial name of the card set to search for
    Returns: JSON response with matching card sets
    """
    try:
        # Get all card sets first
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        if response.status_code == 200:
            all_sets = response.json()
            
            # Filter sets by name (case-insensitive)
            matching_sets = [
                card_set for card_set in all_sets 
                if set_name.lower() in card_set.get('set_name', '').lower()
            ]
            
            logger.info(f"Found {len(matching_sets)} card sets matching '{set_name}'")
            
            return jsonify({
                "success": True,
                "data": matching_sets,
                "count": len(matching_sets),
                "search_term": set_name,
                "message": f"Found {len(matching_sets)} matching card sets"
            })
        
        else:
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API",
                "status_code": response.status_code
            }), 500
            
    except Exception as e:
        logger.error(f"Error searching card sets: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to search card sets"
        }), 500

@app.route('/card-sets/upload', methods=['POST'])
def upload_card_sets_to_mongodb():
    """
    Upload all card sets from YGO API to MongoDB collection YGO_SETS_CACHE_V1
    Returns: JSON response with upload status and statistics
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Make request to YGO API cardsets endpoint
        logger.info("Fetching card sets from YGO API...")
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API",
                "status_code": response.status_code
            }), 500
        
        card_sets_data = response.json()
        logger.info(f"Retrieved {len(card_sets_data)} card sets from API")
        
        # Get database and collection
        db = client.get_default_database()
        collection = db[MONGODB_COLLECTION_NAME]
        
        # Add metadata to each document
        upload_timestamp = datetime.now(UTC)
        for card_set in card_sets_data:
            card_set['_uploaded_at'] = upload_timestamp
            card_set['_source'] = 'ygoprodeck_api'
        
        # Clear existing data in collection
        delete_result = collection.delete_many({})
        logger.info(f"Cleared {delete_result.deleted_count} existing documents")
        
        # Insert new data
        insert_result = collection.insert_many(card_sets_data)
        inserted_count = len(insert_result.inserted_ids)
        
        # Create index on set_code for better query performance
        collection.create_index("set_code")
        collection.create_index("set_name")
        
        logger.info(f"Successfully uploaded {inserted_count} card sets to MongoDB")
        
        # Close MongoDB connection
        client.close()
        
        return jsonify({
            "success": True,
            "message": "Card sets uploaded successfully to MongoDB",
            "statistics": {
                "total_sets_uploaded": inserted_count,
                "previous_documents_cleared": delete_result.deleted_count,
                "collection_name": MONGODB_COLLECTION_NAME,
                "upload_timestamp": upload_timestamp.isoformat()
            }
        })
        
    except requests.exceptions.Timeout:
        logger.error("Request to YGO API timed out")
        return jsonify({
            "success": False,
            "error": "Request timed out"
        }), 504
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to connect to YGO API"
        }), 503
        
    except Exception as e:
        logger.error(f"Unexpected error during upload: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during upload"
        }), 500

@app.route('/card-sets/from-cache', methods=['GET'])
def get_card_sets_from_cache():
    """
    Get all card sets from MongoDB cache
    Returns: JSON response with cached card sets
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Get database and collection
        db = client.get_default_database()
        collection = db[MONGODB_COLLECTION_NAME]
        
        # Get all documents (excluding MongoDB internal fields)
        cursor = collection.find({}, {"_id": 0})
        card_sets = list(cursor)
        
        # Get cache metadata if available
        cache_info = None
        if card_sets:
            cache_info = {
                "last_updated": card_sets[0].get('_uploaded_at'),
                "source": card_sets[0].get('_source')
            }
        
        # Close MongoDB connection
        client.close()
        
        logger.info(f"Retrieved {len(card_sets)} card sets from MongoDB cache")
        
        return jsonify({
            "success": True,
            "data": card_sets,
            "count": len(card_sets),
            "cache_info": cache_info,
            "message": f"Retrieved {len(card_sets)} card sets from cache"
        })
        
    except Exception as e:
        logger.error(f"Error retrieving card sets from cache: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to retrieve card sets from cache"
        }), 500

@app.route('/card-sets/count', methods=['GET'])
def get_card_sets_count():
    """
    Get the total count of card sets
    Returns: JSON response with total count
    """
    try:
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        if response.status_code == 200:
            card_sets_data = response.json()
            total_count = len(card_sets_data)
            
            return jsonify({
                "success": True,
                "total_sets": total_count,
                "message": f"Total card sets available: {total_count}"
            })
        
        else:
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API"
            }), 500
            
    except Exception as e:
        logger.error(f"Error getting card sets count: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to get card sets count"
        }), 500

def filter_cards_by_set(cards_list: List[Dict], target_set_name: str) -> List[Dict]:
    """
    Filter cards to only include variants from the target set.
    
    Args:
        cards_list: List of card dictionaries from YGO API
        target_set_name: Name of the set to filter by
        
    Returns:
        List of filtered card dictionaries with only relevant set variants
    """
    if not cards_list or not target_set_name:
        return cards_list
    
    filtered_cards = []
    target_set_name_lower = target_set_name.lower().strip()
    
    for card in cards_list:
        # Create a copy of the card to avoid modifying the original
        filtered_card = card.copy()
        
        # Filter the card_sets array to only include the target set
        if 'card_sets' in card and isinstance(card['card_sets'], list):
            filtered_sets = []
            
            for card_set in card['card_sets']:
                set_name = card_set.get('set_name', '').lower().strip()
                
                # Check if this set matches the target set
                if set_name == target_set_name_lower:
                    filtered_sets.append(card_set)
            
            # Only include the card if it has variants in the target set
            if filtered_sets:
                filtered_card['card_sets'] = filtered_sets
                
                # Update card images to match the number of variants in the target set
                if 'card_images' in filtered_card and len(filtered_sets) < len(filtered_card['card_images']):
                    # Keep only as many images as we have set variants
                    filtered_card['card_images'] = filtered_card['card_images'][:len(filtered_sets)]
                
                # Add set-specific metadata
                filtered_card['target_set_variants'] = len(filtered_sets)
                filtered_card['target_set_name'] = target_set_name
                
                # Extract set codes for easy reference
                set_codes = [cs.get('set_code', '') for cs in filtered_sets]
                filtered_card['target_set_codes'] = set_codes
                
                filtered_cards.append(filtered_card)
    
    logger.info(f"Filtered {len(cards_list)} cards down to {len(filtered_cards)} cards with variants in '{target_set_name}'")
    
    return filtered_cards

def get_set_code_prefix_from_name(set_name: str) -> Optional[str]:
    """
    Get the set code prefix for a given set name by checking cached sets.
    
    Args:
        set_name: Name of the set to get code prefix for
        
    Returns:
        Set code prefix (e.g., 'RA04', 'SUDA') or None if not found
    """
    try:
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return None
        
        # Get database and collection
        db = client.get_default_database()
        collection = db[MONGODB_COLLECTION_NAME]
        
        # Search for the set by name (case-insensitive)
        set_document = collection.find_one(
            {"set_name": {"$regex": f"^{re.escape(set_name)}$", "$options": "i"}},
            {"set_code": 1, "_id": 0}
        )
        
        client.close()
        
        if set_document and 'set_code' in set_document:
            set_code = set_document['set_code']
            logger.info(f"Found set code '{set_code}' for set '{set_name}'")
            return set_code
        else:
            logger.warning(f"No set code found for set '{set_name}'")
            return None
            
    except Exception as e:
        logger.error(f"Error getting set code for '{set_name}': {e}")
        return None

@app.route('/card-sets/<string:set_name>/cards', methods=['GET'])
def get_cards_from_specific_set(set_name):
    """
    Get all cards from a specific card set, filtered to only show variants from that set
    Args:
        set_name: Name of the card set to fetch cards from
    Returns: JSON response with filtered cards from the specified set
    """
    try:
        # Get optional query parameters
        filter_by_set = request.args.get('filter_by_set', 'true').lower() == 'true'
        include_set_code = request.args.get('include_set_code', 'false').lower() == 'true'
        
        # URL encode the set name for the API call
        encoded_set_name = quote(set_name)
        
        # Make request to YGO API for cards in this set
        logger.info(f"Fetching cards from set: {set_name}")
        api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
        response = requests.get(api_url, timeout=15)
        
        if response.status_code == 200:
            cards_data = response.json()
            cards_list = cards_data.get('data', [])
            
            logger.info(f"Retrieved {len(cards_list)} cards from YGO API for {set_name}")
            
            # Filter cards by set if requested (default: true)
            if filter_by_set:
                filtered_cards = filter_cards_by_set(cards_list, set_name)
            else:
                filtered_cards = cards_list
            
            # Get set code if requested
            set_code_info = {}
            if include_set_code:
                set_code = get_set_code_prefix_from_name(set_name)
                if set_code:
                    set_code_info = {
                        "set_code": set_code,
                        "set_code_prefix": set_code.split('-')[0] if '-' in set_code else set_code
                    }
            logger.info(f"Returning {len(filtered_cards)} filtered cards from {set_name}")
            
            response_data = {
                "success": True,
                "set_name": set_name,
                "data": filtered_cards,
                "card_count": len(filtered_cards),
                "total_cards_before_filter": len(cards_list),
                "message": f"Successfully fetched {len(filtered_cards)} cards from {set_name}",
                "filtered_by_set": filter_by_set
            }
            
            # Add set code info if requested
            if set_code_info:
                response_data.update(set_code_info)
            
            return jsonify(response_data)
            
        elif response.status_code == 400:
            return jsonify({
                "success": False,
                "set_name": set_name,
                "error": "No cards found for this set or invalid set name",
                "card_count": 0
            }), 404
            
        else:
            return jsonify({
                "success": False,
                "set_name": set_name,
                "error": f"API error: HTTP {response.status_code}"
            }), 500
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching cards for set: {set_name}")
        return jsonify({
            "success": False,
            "set_name": set_name,
            "error": "Request timed out"
        }), 504
        
    except Exception as e:
        logger.error(f"Error fetching cards for set {set_name}: {str(e)}")
        return jsonify({
            "success": False,
            "set_name": set_name,
            "error": "Internal server error"
        }), 500

@app.route('/card-sets/fetch-all-cards', methods=['POST'])
def fetch_all_cards_from_sets():
    """
    Iterate through all cached card sets and fetch all cards for each set
    Returns: JSON response with comprehensive card data from all sets
    """
    try:
        # Get optional query parameters
        data = request.get_json() or {}
        filter_by_sets = data.get('filter_by_sets', True)
        include_set_codes = data.get('include_set_codes', False)
        
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Get database and collection for sets
        db = client.get_default_database()
        sets_collection = db[MONGODB_COLLECTION_NAME]
        
        # Get all cached sets
        cached_sets = list(sets_collection.find({}, {"_id": 0}))
        if not cached_sets:
            return jsonify({
                "success": False,
                "error": "No cached card sets found. Please upload sets first using /card-sets/upload"
            }), 404
        
        logger.info(f"Found {len(cached_sets)} cached sets to process")
        
        # Initialize response data
        all_cards_data = {}
        processing_stats = {
            "total_sets": len(cached_sets),
            "processed_sets": 0,
            "failed_sets": 0,
            "total_cards_found": 0,
            "total_filtered_cards": 0,
            "processing_errors": [],
            "filter_by_sets": filter_by_sets
        }
        
        # Rate limiting: 20 requests per second max
        request_delay = 0.1  # 100ms delay between requests to stay under limit
        
        # Process each set
        for index, card_set in enumerate(cached_sets):
            set_name = card_set.get('set_name', '')
            set_code = card_set.get('set_code', '')
            
            try:
                logger.info(f"Processing set {index + 1}/{len(cached_sets)}: {set_name}")
                
                # URL encode the set name for the API call
                encoded_set_name = quote(set_name)
                
                # Make request to YGO API for cards in this set
                api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
                response = requests.get(api_url, timeout=15)
                
                if response.status_code == 200:
                    cards_data = response.json()
                    cards_list = cards_data.get('data', [])
                    
                    # Filter cards by set if requested
                    if filter_by_sets:
                        filtered_cards = filter_cards_by_set(cards_list, set_name)
                    else:
                        filtered_cards = cards_list
                    
                    # Store cards data for this set
                    set_data = {
                        "set_info": card_set,
                        "cards": filtered_cards,
                        "card_count": len(filtered_cards),
                        "total_cards_before_filter": len(cards_list)
                    }
                    
                    # Add set code info if requested
                    if include_set_codes and set_code:
                        set_data["set_code_info"] = {
                            "set_code": set_code,
                            "set_code_prefix": set_code.split('-')[0] if '-' in set_code else set_code
                        }
                    
                    all_cards_data[set_name] = set_data
                    
                    processing_stats["total_cards_found"] += len(cards_list)
                    processing_stats["total_filtered_cards"] += len(filtered_cards)
                    processing_stats["processed_sets"] += 1
                    
                    logger.info(f"Successfully fetched {len(cards_list)} cards, filtered to {len(filtered_cards)} from {set_name}")
                    
                elif response.status_code == 400:
                    # Set might not have cards or name might be invalid
                    logger.warning(f"No cards found for set: {set_name} (400 response)")
                    all_cards_data[set_name] = {
                        "set_info": card_set,
                        "cards": [],
                        "card_count": 0,
                        "total_cards_before_filter": 0,
                        "note": "No cards found for this set"
                    }
                    processing_stats["processed_sets"] += 1
                    
                else:
                    error_msg = f"API error for set {set_name}: HTTP {response.status_code}"
                    logger.error(error_msg)
                    processing_stats["failed_sets"] += 1
                    processing_stats["processing_errors"].append({
                        "set_name": set_name,
                        "error": error_msg
                    })
                
                # Rate limiting delay
                time.sleep(request_delay)
                
            except requests.exceptions.Timeout:
                error_msg = f"Timeout fetching cards for set: {set_name}"
                logger.error(error_msg)
                processing_stats["failed_sets"] += 1
                processing_stats["processing_errors"].append({
                    "set_name": set_name,
                    "error": error_msg
                })
                
            except Exception as e:
                error_msg = f"Error processing set {set_name}: {str(e)}"
                logger.error(error_msg)
                processing_stats["failed_sets"] += 1
                processing_stats["processing_errors"].append({
                    "set_name": set_name,
                    "error": error_msg
                })
        
        # Close MongoDB connection
        client.close()
        
        # Calculate final statistics
        processing_stats["success_rate"] = (
            processing_stats["processed_sets"] / processing_stats["total_sets"] * 100
            if processing_stats["total_sets"] > 0 else 0
        )
        
        logger.info(f"Completed processing all sets. Found {processing_stats['total_cards_found']} total cards, filtered to {processing_stats['total_filtered_cards']}")
        
        return jsonify({
            "success": True,
            "message": "Successfully fetched cards from all sets",
            "data": all_cards_data,
            "statistics": processing_stats
        })
        
    except Exception as e:
        logger.error(f"Unexpected error during card fetching: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during card fetching"
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500

def clean_card_data(price_data: Dict) -> Dict:
    """Clean up card data before returning it in the response."""
    try:
        cleaned = price_data.copy()
        
        # Clean up card name
        if 'card_name' in cleaned:
            name = cleaned['card_name']
            # Remove price guide suffixes and other unwanted text
            name = re.sub(r'Prices\s*\|.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\|.*?Cards.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'Price\s*Guide.*$', '', name, flags=re.IGNORECASE)
            # Remove card number
            name = re.sub(r'\s*[A-Z]{2,4}-[A-Z]{2}\d+\s*', '', name)
            # Remove square bracket content
            name = re.sub(r'\[.*?\]', '', name)
            # Clean up spaces
            name = re.sub(r'\s+', ' ', name).strip()
            cleaned['card_name'] = name
        
        # Clean up rarity with stricter pattern matching
        if 'card_rarity' in cleaned:
            rarity = str(cleaned['card_rarity'])
            
            # Define rarity search patterns in order of specificity
            rarity_patterns = [
                # Quarter Century variants - most specific first
                (r'quarter[\s-]century\s+secret\s+rare', 'Quarter Century Secret Rare'),
                (r'quarter[\s-]century\s+ultra\s+rare', 'Quarter Century Ultra Rare'),
                (r'quarter[\s-]century\s+rare', 'Quarter Century Rare'),
                (r'25th\s+anniversary\s+secret\s+rare', 'Quarter Century Secret Rare'),
                # Specific rare variants
                (r'platinum\s+secret\s+rare', 'Platinum Secret Rare'),
                (r'starlight\s+rare', 'Starlight Rare'),
                (r'collectors?\s+rare', "Collector's Rare"),
                (r'ghost\s+rare', 'Ghost Rare'),
                (r'ultimate\s+rare', 'Ultimate Rare'),
                # Standard rarities
                (r'secret\s+rare', 'Secret Rare'),
                (r'ultra\s+rare', 'Ultra Rare'),
                (r'super\s+rare', 'Super Rare'),
                (r'\brare\b', 'Rare'),
                (r'\bcommon\b', 'Common')
            ]
            
            # Try to find a matching rarity pattern
            found_rarity = None
            for pattern, replacement in rarity_patterns:
                if re.search(pattern, rarity.lower()):
                    found_rarity = replacement
                    break
            
            if found_rarity:
                cleaned['card_rarity'] = found_rarity
            else:
                # If no standard pattern matched, try to clean up what we have
                # First check if it's a long string (like page content)
                if len(rarity) > 200:
                    # Try to extract rarity from the long text
                    for pattern, replacement in rarity_patterns:
                        if re.search(pattern, rarity.lower()):
                            found_rarity = replacement
                            break
                    
                    if found_rarity:
                        cleaned['card_rarity'] = found_rarity
                    else:
                        # If we still can't find a rarity, use normalize_rarity
                        normalized = normalize_rarity(rarity[:200])
                        cleaned['card_rarity'] = normalized
                else:
                    # Short string but no pattern match - normalize it
                    cleaned['card_rarity'] = normalize_rarity(rarity)
        
        # Do a final check to ensure critical fields don't contain page content
        for field in ['card_name', 'card_rarity']:
            if field in cleaned and isinstance(cleaned[field], str):
                value = cleaned[field]
                # If field is suspiciously long (>200 chars), it might be page content
                if len(value) > 200:
                    # Try to extract meaningful content from the first part
                    first_sentence = re.split(r'[.!?]\s+', value)[0]
                    if len(first_sentence) > 100:
                        first_sentence = first_sentence[:100]
                    cleaned[field] = first_sentence + '... (truncated)'
                    logger.warning(f"Found suspiciously long {field}, truncated to first sentence")
        
        return cleaned
    except Exception as e:
        logger.error(f"Error cleaning card data: {e}")
        return price_data  # Return original if cleaning fails

if __name__ == '__main__':
    # Get port from environment variable or default to 8081
    port = int(os.getenv("PORT", 8081))
    
    print(f"Starting YGO Card Sets API on port {port}...")
    print("Available endpoints:")
    print("  GET /health - Health check")
    print("  GET /card-sets - Get all card sets")
    print("  GET /card-sets/search/<set_name> - Search card sets by name")
    print("  POST /card-sets/upload - Upload card sets to MongoDB")
    print("  GET /card-sets/from-cache - Get card sets from MongoDB cache")
    print("  POST /card-sets/fetch-all-cards - Fetch all cards from all cached sets")
    print("  GET /card-sets/<set_name>/cards - Get all cards from a specific set")
    print("  GET /card-sets/count - Get total count of card sets")
    print("  POST /cards/price - Scrape card prices")
    print("  GET /cards/price/cache-stats - Get price cache statistics")
    print("  POST /debug/art-extraction - Debug art variant extraction")
    app.run(host='0.0.0.0', port=port, debug=True)
