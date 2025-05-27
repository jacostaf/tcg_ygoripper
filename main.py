from flask import Flask, jsonify, request
import requests
import logging
import os
import time
import asyncio
import re
import motor.motor_asyncio
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field
from bson import ObjectId

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)  # Changed from INFO to DEBUG
logger = logging.getLogger(__name__)

# YGO API base URL
YGO_API_BASE_URL = "https://db.ygoprodeck.com/api/v7"

# MongoDB configuration
MONGODB_CONNECTION_STRING = os.getenv('MONGODB_CONNECTION_STRING')
MONGODB_COLLECTION_NAME = "YGO_SETS_CACHE_V1"
MONGODB_CARD_VARIANTS_COLLECTION = "YGO_CARD_VARIANT_CACHE_V1"

def get_mongo_client():
    """Get MongoDB client connection"""
    try:
        client = MongoClient(MONGODB_CONNECTION_STRING)
        # Test the connection
        client.admin.command('ping')
        return client
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
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
    pc_ungraded_price: Optional[float] = Field(None, description="PriceCharting ungraded price")
    pc_grade7: Optional[float] = Field(None, description="PriceCharting Grade 7 price")
    pc_grade8: Optional[float] = Field(None, description="PriceCharting Grade 8 price")
    pc_grade9: Optional[float] = Field(None, description="PriceCharting Grade 9 price")
    pc_grade9_5: Optional[float] = Field(None, description="PriceCharting Grade 9.5 price")
    pc_grade10: Optional[float] = Field(None, description="PriceCharting Grade 10/PSA 10 price")
    
    # Metadata fields
    last_price_updt: datetime = Field(default_factory=datetime.utcnow, description="Last price update time")
    source_url: Optional[str] = Field(None, description="URL where prices were scraped from")
    scrape_success: bool = Field(True, description="Whether the last scrape was successful")
    error_message: Optional[str] = Field(None, description="Error message if scrape failed")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

# Global variables for price scraping service
price_scraping_client = None
price_scraping_collection = None

# Price scraping configuration
PRICE_CACHE_COLLECTION = "YGO_CARD_VARIANT_PRICE_CACHE_V1"
CACHE_EXPIRY_DAYS = 7

async def initialize_price_scraping():
    """Initialize async MongoDB client for price scraping."""
    global price_scraping_client, price_scraping_collection
    try:
        if price_scraping_client is None:
            price_scraping_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_CONNECTION_STRING)
            db = price_scraping_client.get_default_database()
            price_scraping_collection = db[PRICE_CACHE_COLLECTION]
            
            # Create indexes for efficient querying
            await price_scraping_collection.create_index([
                ("card_number", 1),
                ("card_name", 1),
                ("card_rarity", 1),
                ("card_art_variant", 1)
            ], name="card_identification_idx")
            
            await price_scraping_collection.create_index("card_number", name="card_number_idx")
            await price_scraping_collection.create_index("last_price_updt", name="timestamp_idx")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize price scraping: {e}")
        return False

def extract_art_version(card_name: str) -> Optional[str]:
    """Extract art version from card name using regex patterns."""
    if not card_name:
        return None
    
    patterns = [
        r'\b(\d+)(st|nd|rd|th)?\s*(art|artwork)\b',  # "7th art", "1st artwork"
        r'\[(\d+)(st|nd|rd|th)?\]',                   # "[7th]", "[1]"
        r'\((\d+)(st|nd|rd|th)?\)',                   # "(7th)", "(1)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, card_name, re.IGNORECASE)
        if match:
            art_version = match.group(1)
            logger.info(f"Detected art version: {art_version} in card name: {card_name}")
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

async def find_cached_price_data(
    card_number: str, 
    card_name: Optional[str] = None,
    card_rarity: Optional[str] = None,
    art_variant: Optional[str] = None
) -> tuple[bool, Optional[Dict]]:
    """Check if we have fresh price data in cache."""
    if price_scraping_collection is None:
        return False, None
    
    try:
        # Build query
        query = {"card_number": card_number}
        
        if card_name:
            query["card_name"] = {"$regex": card_name, "$options": "i"}
        if card_rarity:
            query["card_rarity"] = {"$regex": card_rarity, "$options": "i"}
        if art_variant:
            query["card_art_variant"] = art_variant
        
        # Find most recent entry
        document = await price_scraping_collection.find_one(
            query,
            sort=[("last_price_updt", -1)]
        )
        
        if not document:
            return False, None
        
        # Check if data is fresh (within expiry period)
        expiry_date = datetime.utcnow() - timedelta(days=CACHE_EXPIRY_DAYS)
        is_fresh = document.get('last_price_updt', datetime.min) > expiry_date
        
        return is_fresh, document
        
    except Exception as e:
        logger.error(f"Error checking cached price data: {e}")
        return False, None

async def validate_card_rarity(card_number: str, card_rarity: str) -> bool:
    """Validate the requested rarity against available rarities for the card in YGO_CARD_VARIANT_CACHE_V1."""
    if not card_rarity or not card_number:
        return False
    
    try:
        # Initialize MongoDB connection if needed
        if price_scraping_client is None:
            await initialize_price_scraping()
        
        # Get the card variants collection
        db = price_scraping_client.get_default_database()
        variants_collection = db[MONGODB_CARD_VARIANTS_COLLECTION]
        
        # Search for the card in the variants collection
        # Look for cards with matching card number
        query = {"card_sets.set_rarity_code": {"$regex": f"^{re.escape(card_number)}", "$options": "i"}}
        
        card_document = await variants_collection.find_one(query)
        
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
            
            # Check for partial matches (e.g., "quarter century secret rare" contains "secret rare")
            if (normalized_requested in normalized_available or 
                normalized_available in normalized_requested):
                logger.info(f"Rarity '{card_rarity}' partially validated for card {card_number}")
                return True
        
        logger.warning(f"Rarity '{card_rarity}' not found for card {card_number}. Available rarities: {list(available_rarities)}")
        return False
        
    except Exception as e:
        logger.error(f"Error validating card rarity: {e}")
        # Return True on error to avoid blocking valid requests
        return True

async def save_price_data(price_data: Dict) -> bool:
    """Save price data to MongoDB with improved validation and error handling."""
    if price_scraping_collection is None:
        logger.error("Price scraping collection not initialized")
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
        price_data['last_price_updt'] = datetime.utcnow()
        
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
        
        logger.info(f"Saving price data with query: {query}")
        
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
        
        result = await price_scraping_collection.replace_one(
            query,
            cleaned_data,
            upsert=True
        )
        
        if result.upserted_id:
            logger.info(f"Created new price record with ID: {result.upserted_id}")
            return True
        elif result.modified_count > 0:
            logger.info(f"Updated existing price record, modified {result.modified_count} document(s)")
            return True
        else:
            logger.warning("No documents were created or modified")
            return False
        
    except Exception as e:
        logger.error(f"Error saving price data: {e}")
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
    """Enhanced variant selection logic matching the working YGOPyAPI implementation."""
    try:
        logger.debug("Using enhanced variant selection algorithm")
        
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
                    
                    // Get price if available
                    const priceCell = row.querySelector('td.price.numeric.used_price');
                    const priceText = priceCell ? priceCell.textContent.trim() : '';
                    const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                    
                    // Get game info
                    const consoleInTitle = titleCell.querySelector('.console-in-title');
                    const gameInfo = consoleInTitle ? consoleInTitle.textContent.trim() : '';
                    
                    if (href && href.includes('/game/')) {
                        variants.push({
                            title: title,
                            href: href,
                            price: price,
                            gameInfo: gameInfo
                        });
                    }
                });
                
                return variants;
            }
        """)
        
        # Log all found variants for debugging
        logger.info(f"Found {len(variants)} variants for {card_number}:")
        for i, variant in enumerate(variants[:10]):  # Log first 10 variants
            logger.info(f"  {i+1}. {variant['title']}")
        
        if len(variants) == 1:
            logger.debug("Only one variant found, selecting automatically")
            return variants[0]['href']
        
        logger.debug(f"Found {len(variants)} variants, evaluating best match...")
        
        # Phase 1: Fast-path selection for Quarter Century with art version
        want_quarter_century = card_rarity and 'quarter century' in card_rarity.lower()
        
        if target_art_version and want_quarter_century:
            logger.debug("FAST-PATH: Looking for exact Quarter Century variant with art version")
            
            for variant in variants:
                title_lower = variant['title'].lower()
                
                # Check for Quarter Century and Secret Rare
                has_quarter_century = 'quarter century' in title_lower
                has_secret_rare = 'secret rare' in title_lower
                
                # Check for target art version in various formats
                art_patterns = [
                    f'[{target_art_version}',
                    f'({target_art_version}',
                    f'{target_art_version}th art',
                    f'{target_art_version} art',
                    f'{target_art_version}th quarter',
                    f'{target_art_version} quarter'
                ]
                
                has_target_art = any(pattern in title_lower for pattern in art_patterns)
                
                if has_quarter_century and has_secret_rare and has_target_art:
                    logger.info(f"PERFECT MATCH: {variant['title']}")
                    return variant['href']
        
        # Phase 2: Detailed scoring system
        logger.debug("No perfect match found, using detailed scoring system...")
        
        normalized_target_rarity = normalize_rarity(card_rarity) if card_rarity else ''
        candidates = []
        
        for variant in variants:
            title = variant['title']
            title_lower = title.lower()
            score = 0
            
            logger.debug(f"Scoring variant: {title}")
            
            # Score card number match
            if card_number and card_number.lower() in title_lower:
                score += 50
                logger.debug(f"  +50 card number match: {score}")
            
            # Score card name match
            if card_name:
                clean_card_name = re.sub(r'\b\d+(st|nd|rd|th)?\s*(art|artwork)\b', '', card_name.lower()).strip()
                if clean_card_name in title_lower:
                    score += 20
                    logger.debug(f"  +20 card name match: {score}")
            
            # Score rarity match (critical for Quarter Century vs Platinum detection)
            title_rarity = normalize_rarity(title)
            title_has_quarter_century = 'quarter century' in title_rarity
            title_has_platinum = 'platinum' in title_rarity
            
            logger.debug(f"  title_rarity: '{title_rarity}', QC: {title_has_quarter_century}, Platinum: {title_has_platinum}")
            
            # Handle Quarter Century requests
            if 'quarter century' in normalized_target_rarity:
                # We WANT Quarter Century
                if title_has_quarter_century:
                    logger.debug(f"QUARTER CENTURY MATCH: {title}")
                    score += 800
                    logger.debug(f"  +800 QC match: {score}")
                    
                    # Extra points for specific rarity type
                    if 'secret' in normalized_target_rarity and 'secret' in title_rarity:
                        score += 300
                        logger.debug(f"  +300 secret match: {score}")
                    elif 'ultra' in normalized_target_rarity and 'ultra' in title_rarity:
                        score += 300
                        logger.debug(f"  +300 ultra match: {score}")
                else:
                    # Heavy penalty for missing Quarter Century when we want it
                    score -= 800
                    logger.debug(f"  -800 missing QC: {score}")
                    
                    # Extra penalty if this is a Platinum variant (wrong rarity)
                    if title_has_platinum:
                        score -= 500
                        logger.debug(f"PLATINUM PENALTY (want QC): {title}")
                        logger.debug(f"  -500 platinum penalty: {score}")
                        
            # Handle Platinum requests
            elif 'platinum' in normalized_target_rarity:
                # We WANT Platinum
                if title_has_platinum:
                    logger.debug(f"PLATINUM MATCH: {title}")
                    score += 800
                    logger.debug(f"  +800 platinum match: {score}")
                    
                    # Extra points for specific rarity type
                    if 'secret' in normalized_target_rarity and 'secret' in title_rarity:
                        score += 300
                        logger.debug(f"  +300 secret match: {score}")
                else:
                    # Check if this could be a Platinum variant without explicit labeling
                    # Many Platinum variants just show the art version without "Platinum" in title
                    if target_art_version:
                        # Extract the numeric part from target_art_version
                        target_art_number_match = re.search(r'(\d+)', target_art_version)
                        target_art_number = target_art_number_match.group(1) if target_art_number_match else target_art_version
                        
                        if (not title_has_quarter_century and  # Not Quarter Century
                            not any(common_rarity in title_rarity for common_rarity in ['ultra rare', 'super rare', 'rare']) and  # Not other common rarities
                            re.search(rf'\[{target_art_number}(st|nd|rd|th)?\]', title_lower)):  # Has matching art in brackets
                            
                            logger.debug(f"IMPLICIT PLATINUM MATCH (art-based): {title}")
                            score += 600  # Lower than explicit Platinum but higher than penalties
                            logger.debug(f"  +600 implicit platinum: {score}")
                        else:
                            # Heavy penalty for missing Platinum when we want it
                            score -= 800
                            logger.debug(f"  -800 missing platinum: {score}")
                    else:
                        # Heavy penalty for missing Platinum when we want it
                        score -= 800
                        logger.debug(f"  -800 missing platinum: {score}")
                        
                    # Extra penalty if this is a Quarter Century variant (wrong rarity)
                    if title_has_quarter_century:
                        score -= 500
                        logger.debug(f"QUARTER CENTURY PENALTY (want Platinum): {title}")
                        logger.debug(f"  -500 QC penalty: {score}")
            
            # Handle other rarity requests (Secret Rare, Ultra Rare, etc.)
            elif normalized_target_rarity:
                # We want a specific non-Quarter Century, non-Platinum rarity
                if title_has_quarter_century:
                    # We DON'T want Quarter Century but this has it
                    score -= 500
                    logger.debug(f"UNWANTED QUARTER CENTURY: {title}")
                    logger.debug(f"  -500 unwanted QC: {score}")
                elif title_has_platinum:
                    # We DON'T want Platinum but this has it
                    score -= 500
                    logger.debug(f"UNWANTED PLATINUM: {title}")
                    logger.debug(f"  -500 unwanted platinum: {score}")
                else:
                    # Check for exact rarity match
                    if normalized_target_rarity in title_rarity:
                        score += 400
                        logger.debug(f"EXACT RARITY MATCH: {title}")
                        logger.debug(f"  +400 exact rarity: {score}")
                    # Check for partial rarity match
                    elif any(word in title_rarity for word in normalized_target_rarity.split()):
                        score += 200
                        logger.debug(f"PARTIAL RARITY MATCH: {title}")
                        logger.debug(f"  +200 partial rarity: {score}")
            else:
                # No specific rarity requested, slight penalty for art variants
                if title_has_quarter_century or title_has_platinum:
                    score -= 100
                    logger.debug(f"  -100 special rarity penalty: {score}")
            
            # Score art version match (critical for distinguishing variants)
            if target_art_version:
                # Extract the numeric part from target_art_version (e.g., "7th Art" -> "7", "7" -> "7")
                target_art_number = re.search(r'(\d+)', target_art_version)
                target_art_number = target_art_number.group(1) if target_art_number else target_art_version
                
                art_patterns = [
                    f'{target_art_version}',  # Exact match
                    f'{target_art_number}th art',
                    f'{target_art_number} art',
                    f'[{target_art_number}',
                    f'({target_art_number}',
                    f'{target_art_number}th]',
                    f'{target_art_number}]',
                    f'[{target_art_number}th',
                    f'({target_art_number}th',
                ]
                
                has_target_art = any(pattern in title_lower for pattern in art_patterns)
                
                if has_target_art:
                    logger.debug(f"Art version match: {title}")
                    score += 500  # Increased from 300 to make art matching more important
                    logger.debug(f"  +500 art match: {score}")
                    
                    # Extra bonus for combined art + Quarter Century
                    if title_has_quarter_century and 'quarter century' in normalized_target_rarity:
                        score += 300
                        logger.debug(f"  +300 art+QC bonus: {score}")
                    # Extra bonus for combined art + Platinum
                    elif title_has_platinum and 'platinum' in normalized_target_rarity:
                        score += 300
                        logger.debug(f"  +300 art+platinum bonus: {score}")
                else:
                    # Check for wrong art version - HEAVY PENALTY
                    wrong_art_pattern = r'\b(\d+)(st|nd|rd|th)?\s*(art|artwork)\b|\[(\d+)(st|nd|rd|th)?\]|\((\d+)(st|nd|rd|th)?\)'
                    wrong_art_match = re.search(wrong_art_pattern, title_lower)
                    if wrong_art_match:
                        # Extract the art number from the wrong match
                        wrong_art_number = wrong_art_match.group(1) or wrong_art_match.group(4)
                        if wrong_art_number and wrong_art_number != target_art_number:
                            score -= 600  # Heavy penalty for wrong art version
                            logger.debug(f"WRONG ART PENALTY ({wrong_art_number} vs {target_art_version}): {title}")
                            logger.debug(f"  -600 wrong art: {score}")
            else:
                # If no art version specified, slight penalty for art variants
                art_pattern = r'\b(\d+)(st|nd|rd|th)?\s*(art|artwork)\b|\[(\d+)(st|nd|rd|th)?\]|\((\d+)(st|nd|rd|th)?\)'
                if re.search(art_pattern, title_lower):
                    score -= 50
                    logger.debug(f"  -50 art variant penalty: {score}")
            
            logger.debug(f"Final score for '{title}': {score}")
            
            candidates.append({
                'title': title,
                'href': variant['href'],
                'score': score,
                'has_quarter_century': title_has_quarter_century
            })
        
        # Sort by score (highest first)
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        # Log top candidates
        logger.debug("Top candidates after scoring:")
        for i, candidate in enumerate(candidates[:5]):
            logger.debug(f"{i+1}. Score {candidate['score']}: {candidate['title']}")
        
        # Safety check for rarity mismatch
        if candidates:
            top_candidate = candidates[0]
            
            # Special handling for non-Quarter Century requests
            want_secret_rare = (normalized_target_rarity and 
                              'secret rare' in normalized_target_rarity and 
                              'quarter century' not in normalized_target_rarity)
            
            want_ultra_rare = (normalized_target_rarity and 
                             'ultra rare' in normalized_target_rarity and 
                             'quarter century' not in normalized_target_rarity)
            
            if ((want_secret_rare or want_ultra_rare) and 
                not want_quarter_century and 
                len(candidates) > 1 and 
                top_candidate['has_quarter_century']):
                
                # Find non-Quarter Century alternative
                non_qc_candidate = next((c for c in candidates if not c['has_quarter_century']), None)
                
                if non_qc_candidate:
                    logger.info(f"SAFETY CHECK: Using regular variant: {non_qc_candidate['title']}")
                    return non_qc_candidate['href']
            
            logger.info(f"SELECTED: {top_candidate['title']} (score: {top_candidate['score']})")
            return top_candidate['href']
        
        return None
        
    except Exception as e:
        logger.error(f"Error selecting card variant: {e}")
        return None

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
                    lowPrice: null,
                    highPrice: null,
                    grade: null,
                    allGradePrices: {},
                    tcgPlayerPrice: null,
                    tcgPlayerUrl: null
                };
                
                // Used price (ungraded)
                const usedPriceElement = document.getElementById('used_price');
                if (usedPriceElement) {
                    const usedPrice = extractPrice(usedPriceElement.textContent);
                    if (usedPrice) {
                        result.marketPrice = usedPrice;
                        result.grade = 'Ungraded';
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
                
                // Find TCGPlayer price in compare prices section
                const rows = Array.from(document.querySelectorAll('tr'));
                const tcgPlayerRow = rows.find(row => 
                    row.textContent.toLowerCase().includes('tcgplayer')
                );
                
                if (tcgPlayerRow) {
                    const cells = Array.from(tcgPlayerRow.querySelectorAll('td'));
                    if (cells.length >= 2) {
                        const priceCell = cells[1];
                        if (priceCell) {
                            const priceText = priceCell.textContent.trim();
                            const priceMatch = priceText.match(/\\$?(\\d+\\.\\d{2})/);
                            if (priceMatch && priceMatch[1]) {
                                result.tcgPlayerPrice = parseFloat(priceMatch[1]);
                            }
                        }
                    }
                    
                    // Find TCGPlayer link
                    const tcgPlayerLinks = Array.from(tcgPlayerRow.querySelectorAll('a'));
                    const seeItLink = tcgPlayerLinks.find(link => 
                        link.textContent.toLowerCase().includes('see it')
                    );
                    
                    if (seeItLink) {
                        result.tcgPlayerUrl = seeItLink.href;
                    } else if (tcgPlayerLinks.length > 0) {
                        result.tcgPlayerUrl = tcgPlayerLinks[0].href;
                    }
                }
                
                return result;
            }
        """)
        
        return prices
        
    except Exception as e:
        logger.error(f"Error extracting prices from DOM: {e}")
        return {}

async def scrape_price_from_pricecharting(
    card_number: str,
    card_name: Optional[str] = None,
    card_rarity: Optional[str] = None,
    art_variant: Optional[str] = None
) -> Optional[Dict]:
    """Scrape price data from pricecharting.com using Playwright."""
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
            
            # Search using card number - FIXED URL TO MATCH WORKING YGOPyAPI
            search_query = card_number.strip()
            search_url = f"https://www.pricecharting.com/search-products?q={quote(search_query)}&type=prices"
            
            logger.info(f"Searching PriceCharting for: {search_query}")
            await page.goto(search_url, wait_until='networkidle', timeout=30000)
            
            # Check if we landed directly on a product page
            is_product_page = await page.evaluate("() => document.getElementById('product_name') !== null")
            
            if not is_product_page:
                # We're on search results, select best variant
                best_variant_url = await select_best_card_variant(
                    page, card_number, card_name, card_rarity, art_variant
                )
                
                if best_variant_url:
                    logger.info(f"Selected best variant: {best_variant_url}")
                    await page.goto(best_variant_url, wait_until='networkidle', timeout=30000)
                else:
                    logger.warning(f"No suitable variant found for {card_number}")
                    await browser.close()
                    return None
            
            # Extract prices from the product page
            price_data = await extract_prices_from_dom(page)
            
            if not price_data:
                logger.warning(f"No price data extracted for {card_number}")
                await browser.close()
                return None
            
            # Get final page URL and title
            final_url = page.url
            page_title = await page.title()
            
            # Extract set code and booster set name
            set_code = extract_set_code(card_number)
            booster_set_name = extract_booster_set_name(final_url)
            
            await browser.close()
            
            # Create price record
            price_record = {
                "card_number": card_number,
                "card_name": card_name or page_title,
                "card_art_variant": art_variant,
                "card_rarity": card_rarity,
                "set_code": set_code,
                "booster_set_name": booster_set_name,
                "tcg_price": price_data.get('tcgPlayerPrice'),
                "pc_ungraded_price": price_data.get('marketPrice'),
                "pc_grade7": price_data.get('allGradePrices', {}).get('Grade 7'),
                "pc_grade8": price_data.get('allGradePrices', {}).get('Grade 8'),
                "pc_grade9": price_data.get('allGradePrices', {}).get('Grade 9'),
                "pc_grade9_5": price_data.get('allGradePrices', {}).get('Grade 9.5'),
                "pc_grade10": price_data.get('allGradePrices', {}).get('PSA 10'),
                "source_url": final_url,
                "scrape_success": True,
                "last_price_updt": datetime.utcnow()
            }
            
            return price_record
            
    except Exception as e:
        logger.error(f"Error scraping prices for {card_number}: {e}")
        return {
            "card_number": card_number,
            "card_name": card_name or '',
            "card_art_variant": art_variant,
            "card_rarity": card_rarity,
            "scrape_success": False,
            "error_message": str(e),
            "last_price_updt": datetime.utcnow()
        }

# Card price scraping endpoint
@app.route('/cards/price', methods=['POST'])
def scrape_card_price():
    """Scrape price data for a specific card from PriceCharting."""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "success": False,
                "error": "Request body must be JSON"
            }), 400
        
        card_number = data.get('card_number')
        if not card_number or not card_number.strip():
            return jsonify({
                "success": False,
                "error": "card_number is required and cannot be empty"
            }), 400
        
        card_name = data.get('card_name', '').strip() if data.get('card_name') else None
        card_rarity = data.get('card_rarity', '').strip() if data.get('card_rarity') else None
        art_variant = data.get('art_variant', '').strip() if data.get('art_variant') else None
        force_refresh = data.get('force_refresh', False)
        
        # Validate that card_rarity is provided
        if not card_rarity:
            return jsonify({
                "success": False,
                "error": "card_rarity is required and cannot be empty"
            }), 400
        
        logger.info(f"Price request for card: {card_number}, name: {card_name}, rarity: {card_rarity}, art: {art_variant}")
        
        async def get_price_data():
            await initialize_price_scraping()
            
            # Validate card rarity against YGO_CARD_VARIANT_CACHE_V1
            logger.info(f"Validating rarity '{card_rarity}' for card {card_number}")
            is_valid_rarity = await validate_card_rarity(card_number, card_rarity)
            
            if not is_valid_rarity:
                return {
                    "success": False,
                    "error": f"Invalid rarity '{card_rarity}' for card {card_number}. Please check the card variant database for available rarities."
                }
            
            # Check cache first unless force refresh is requested
            if not force_refresh:
                is_fresh, cached_data = await find_cached_price_data(
                    card_number=card_number,
                    card_name=card_name,
                    card_rarity=card_rarity,
                    art_variant=art_variant
                )
                
                if is_fresh and cached_data:
                    logger.info(f"Using cached price data for {card_number}")
                    cache_age = datetime.utcnow() - cached_data.get('last_price_updt', datetime.utcnow())
                    
                    return {
                        "success": True,
                        "data": {
                            "card_number": cached_data.get('card_number'),
                            "card_name": cached_data.get('card_name'),
                            "card_art_variant": cached_data.get('card_art_variant'),
                            "card_rarity": cached_data.get('card_rarity'),
                            "set_code": cached_data.get('set_code'),
                            "booster_set_name": cached_data.get('booster_set_name'),
                            "tcg_price": cached_data.get('tcg_price'),
                            "pc_ungraded_price": cached_data.get('pc_ungraded_price'),
                            "pc_grade7": cached_data.get('pc_grade7'),
                            "pc_grade8": cached_data.get('pc_grade8'),
                            "pc_grade9": cached_data.get('pc_grade9'),
                            "pc_grade9_5": cached_data.get('pc_grade9_5'),
                            "pc_grade10": cached_data.get('pc_grade10'),
                            "last_price_updt": cached_data.get('last_price_updt'),
                            "source_url": cached_data.get('source_url'),
                            "is_cached": True,
                            "cache_age_hours": cache_age.total_seconds() / 3600
                        },
                        "message": "Price data retrieved from cache"
                    }
            
            # Scrape fresh data
            logger.info(f"Scraping fresh price data for {card_number}")
            price_data = await scrape_price_from_pricecharting(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=art_variant
            )
            
            if not price_data:
                return {
                    "success": False,
                    "error": "Failed to scrape price data"
                }
            
            # Save to cache
            saved = await save_price_data(price_data)
            if not saved:
                logger.warning(f"Failed to save price data to cache for {card_number}")
                return {
                    "success": False,
                    "error": "Price data scraped but failed to save to cache"
                }
            
            return {
                "success": True,
                "data": price_data,
                "message": "Price data scraped and saved successfully"
            }
        
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(get_price_data())
        finally:
            loop.close()
        
        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400 if "Invalid rarity" in result.get("error", "") else 500
        
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
        async def get_stats():
            await initialize_price_scraping()
            
            if price_scraping_collection is None:
                return {"error": "Database not connected"}
            
            try:
                total_records = await price_scraping_collection.count_documents({})
                
                # Count fresh records
                expiry_date = datetime.utcnow() - timedelta(days=CACHE_EXPIRY_DAYS)
                fresh_records = await price_scraping_collection.count_documents({
                    "last_price_updt": {"$gt": expiry_date}
                })
                
                # Count successful scrapes
                successful_records = await price_scraping_collection.count_documents({
                    "scrape_success": True
                })
                
                return {
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
                }
                
            except Exception as e:
                logger.error(f"Error getting cache stats: {e}")
                return {"success": False, "error": str(e)}
        
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(get_stats())
        finally:
            loop.close()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to get cache statistics"
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)