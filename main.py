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
import aiohttp
from playwright.async_api import async_playwright

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
    
    # Handle common abbreviations
    if 'secret rare' in normalized:
        variants.append('secret')
    if 'ultra rare' in normalized:
        variants.append('ultra')
    if 'super rare' in normalized:
        variants.append('super')
    
    return list(set(variants))  # Remove duplicates

def find_cached_price_data_sync(
    card_number: str, 
    card_name: Optional[str] = None,
    card_rarity: Optional[str] = None,
    art_variant: Optional[str] = None
) -> tuple[bool, Optional[Dict]]:
    """Check if we have fresh price data in cache using synchronous MongoDB client."""
    if sync_price_scraping_collection is None:
        return False, None
    
    try:
        logger.info(f"🔍 CACHE LOOKUP: card_number={card_number}, rarity={card_rarity}, art_variant={art_variant}")
        
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
            "source_url": 1,
            "scrape_success": 1,
            "last_price_updt": 1,
            "error_message": 1
        }
        
        # Build query based on art variant
        if art_variant and art_variant.strip():
            normalized_art = re.sub(r'(st|nd|rd|th)$', '', art_variant.lower().strip())
            query = {
                "card_number": card_number,
                "card_rarity": {"$regex": re.escape(card_rarity), "$options": "i"},
                "card_art_variant": {"$regex": f"^{re.escape(normalized_art)}(st|nd|rd|th)?$", "$options": "i"}
            }
        else:
            query = {
                "card_number": card_number,
                "card_rarity": {"$regex": re.escape(card_rarity), "$options": "i"}
            }
        
        # Find documents with projection and sort
        documents = list(sync_price_scraping_collection.find(
            query,
            projection=projection,
            sort=[("last_price_updt", -1)]
        ).limit(5))
        
        # Process and return the first valid document
        for doc in documents:
            # Convert last_price_updt to proper format
            if 'last_price_updt' in doc:
                last_update = doc['last_price_updt']
                if isinstance(last_update, datetime):
                    doc['last_price_updt'] = last_update.strftime("%a, %d %b %Y %H:%M:%S GMT")
                elif isinstance(last_update, str):
                    # Keep string format if it's already a string
                    pass
            return _check_freshness_and_return(doc)
        
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
        
        if is_fresh:
            logger.info(f"  ✅ Found FRESH cached data (updated: {last_update})")
        else:
            logger.info(f"  ⚠️  Found STALE cached data (updated: {last_update}, expired: {expiry_date})")
        
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
        
        # Search for the card in the variants collection
        query = {"card_sets.set_rarity_code": {"$regex": f"^{re.escape(card_number)}", "$options": "i"}}
        
        card_document = variants_collection.find_one(query)
        
        if not card_document:
            logger.warning(f"Card {card_number} not found in YGO_CARD_VARIANT_CACHE_V1")
            # If card is not found in our database, allow the rarity (fallback)
            return True
        
        # Extract available rarities from the card document
        available_rarities = set()
        card_sets = card_document.get('card_sets', [])
        
        for card_set in card_sets:
            rarity = card_set.get('rarity')
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

def save_price_data_sync(price_data: Dict) -> bool:
    """Save price data to MongoDB using synchronous client."""
    if sync_price_scraping_collection is None:
        logger.error("Sync price scraping collection not initialized")
        return False
    
    try:
        # Validate required fields
        if not price_data.get("card_number"):
            logger.error("Cannot save price data: card_number is required")
            return False
        
        if not price_data.get("card_rarity"):
            logger.error("Cannot save price data: card_rarity is required")
            return False
        
        # Update timestamp
        price_data['last_price_updt'] = datetime.now(UTC)
        
        # Build query for upsert - handle empty strings properly
        query = {"card_number": price_data["card_number"]}
        
        # Only add non-empty fields to the query
        card_name = price_data.get("card_name")
        if card_name and card_name.strip():
            query["card_name"] = card_name.strip()
        
        card_rarity = price_data.get("card_rarity")
        if card_rarity and card_rarity.strip():
            query["card_rarity"] = card_rarity.strip()
        
        card_art_variant = price_data.get("card_art_variant")
        if card_art_variant and card_art_variant.strip():
            query["card_art_variant"] = card_art_variant.strip()
        
        logger.info(f"Saving price data with sync query: {query}")
        
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
        
        result = sync_price_scraping_collection.replace_one(
            query,
            cleaned_data,
            upsert=True
        )
        
        if result.upserted_id:
            logger.info(f"Created new sync price record with ID: {result.upserted_id}")
            return True
        elif result.modified_count > 0:
            logger.info(f"Updated existing sync price record, modified {result.modified_count} document(s)")
            return True
        else:
            logger.warning("No sync documents were created or modified")
            return False
        
    except Exception as e:
        logger.error(f"Error saving sync price data: {e}")
        return False

def extract_set_code(card_number: str) -> Optional[str]:
    """Extract set code from card number."""
    if not card_number:
        return None
    
    # Most Yu-Gi-Oh card numbers follow the pattern: SETCODE-REGION###
    match = re.match(r'^([A-Z]{2,4})-[A-Z]{2}\d+$', card_number.upper())
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

def extract_booster_set_name(source_url: str) -> Optional[str]:
    """Extract booster set name from PriceCharting URL."""
    if not source_url:
        return None
    
    try:
        url_parts = source_url.split('/')
        if (len(url_parts) >= 5 and 
            'yugioh-' in url_parts[4] and 
            'yugioh-prime' not in url_parts[4]):
            
            game_slug = url_parts[4]
            set_slug = game_slug.replace('yugioh-', '')
            words = set_slug.split('-')
            
            readable_words = []
            for word in words:
                if word.lower() in ['of', 'the', 'and']:
                    readable_words.append(word.lower())
                else:
                    readable_words.append(word.capitalize())
            
            return ' '.join(readable_words)
            
    except Exception as e:
        logger.error(f"Error extracting booster set name: {e}")
    
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
                    return tcgLinks[0].href;
                }
                
                console.log('NO TCGPlayer links found');
                return null;
            }
        );
        
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

# Card price scraping endpoint
@app.route('/cards/price', methods=['POST'])
def scrape_card_price():
    """Scrape price data for a specific card from TCGPlayer."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Request body must be JSON"}), 400
        card_number = data.get('card_number')
        if not card_number or not card_number.strip():
            return jsonify({"success": False, "error": "card_number is required and cannot be empty"}), 400
        card_name = data.get('card_name', '').strip() if data.get('card_name') else None
        card_rarity = data.get('card_rarity', '').strip() if data.get('card_rarity') else None
        art_variant = data.get('art_variant', '').strip() if data.get('art_variant') else None
        force_refresh = str(data.get('force_refresh', '')).lower() == 'true'
        if not card_rarity:
            return jsonify({"success": False, "error": "card_rarity is required and cannot be empty"}), 400
        logger.info(f"Price request for card: {card_number}, name: {card_name}, rarity: {card_rarity}, art: {art_variant}, force_refresh: {force_refresh}")
        initialize_sync_price_scraping()
        logger.info(f"Validating rarity '{card_rarity}' for card {card_number}")
        is_valid_rarity = validate_card_rarity_sync(card_number, card_rarity)
        if not is_valid_rarity:
            return jsonify({"success": False, "error": f"Invalid rarity '{card_rarity}' for card {card_number}. Please check the card variant database for available rarities."}), 400
        if not force_refresh:
            normalized_art = None
            if art_variant:
                if art_variant.isdigit() or any(suffix in art_variant.lower() for suffix in ['st', 'nd', 'rd', 'th']):
                    normalized_art = re.sub(r'(st|nd|rd|th)$', '', art_variant.lower().strip())
                else:
                    normalized_art = art_variant.lower().strip()
            is_fresh, cached_data = find_cached_price_data_sync(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=normalized_art
            )
            if is_fresh and cached_data:
                logger.info(f"Using cached price data for {card_number}")
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
                if not last_update.tzinfo:
                    last_update = last_update.replace(tzinfo=UTC)
                cache_age = datetime.now(UTC) - last_update
                cleaned_data = clean_card_data(cached_data)
                return jsonify({
                    "success": True,
                    "data": cleaned_data,
                    "message": "Price data retrieved from cache",
                    "is_cached": True,
                    "cache_age_hours": cache_age.total_seconds() / 3600
                })
        async def scrape_data():
            return await scrape_price_from_tcgplayer(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=art_variant
            )
        logger.info(f"Scraping fresh price data for {card_number}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            price_data = loop.run_until_complete(scrape_data())
        finally:
            loop.close()
        if not price_data:
            return jsonify({"success": False, "error": "Failed to scrape price data"}), 500
        cleaned_price_data = clean_card_data(price_data)
        try:
            saved = save_price_data_sync(cleaned_price_data)
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
        return jsonify({"success": False, "error": f"Internal error: {str(e)}"}), 500

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
            ];
            
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
                        normalized = normalize_rarity(rarity[:200]);
                        cleaned['card_rarity'] = normalized
                else:
                    # Short string but no pattern match - normalize it
                    cleaned['card_rarity'] = normalize_rarity(rarity)
        }
        
        # Do a final check to ensure critical fields don't contain page content
        for field in ['card_name', 'card_rarity']:
            if field in cleaned and isinstance(cleaned[field], str):
                value = cleaned[field];
                # If field is suspiciously long (>200 chars), it might be page content
                if len(value) > 200:
                    # Try to extract meaningful content from the first part
                    first_sentence = re.split(r'[.!?]\s+', value)[0];
                    if len(first_sentence) > 100:
                        first_sentence = first_sentence[:100];
                    cleaned[field] = first_sentence + '... (truncated)';
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
