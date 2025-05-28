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
from datetime import datetime, timedelta, UTC
from urllib.parse import quote, urlencode
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field
from bson import ObjectId

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
            sync_price_scraping_client = MongoClient(MONGODB_CONNECTION_STRING)
            db = sync_price_scraping_client.get_default_database()
            sync_price_scraping_collection = db[PRICE_CACHE_COLLECTION]
            
            # Create indexes for efficient querying
            sync_price_scraping_collection.create_index([
                ("card_number", 1),
                ("card_name", 1),
                ("card_rarity", 1),
                ("card_art_variant", 1)
            ], name="card_identification_idx", background=True)
            
            sync_price_scraping_collection.create_index("card_number", name="card_number_idx", background=True)
            sync_price_scraping_collection.create_index("last_price_updt", name="timestamp_idx", background=True)
        return True
    except Exception as e:
        logger.error(f"Failed to initialize sync price scraping: {e}")
        return False

def extract_art_version(card_name: str) -> Optional[str]:
    """Extract art version from card name using regex patterns."""
    if not card_name:
        return None
    
    patterns = [
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
    
    for pattern in patterns:
        match = re.search(pattern, card_name, re.IGNORECASE)
        if match:
            art_version = match.group(1)
            logger.debug(f"Detected art version: {art_version} using pattern '{pattern}' in: {card_name}")
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
        logger.debug(f"Sync cache lookup for card_number: {card_number}")
        
        # Start with the most specific query first
        queries_to_try = []
        
        # Query 1: Full match (card_number + rarity + art_variant if provided)
        if card_rarity and card_rarity.strip():
            full_query = {
                "card_number": card_number,
                "card_rarity": {"$regex": re.escape(card_rarity.strip()), "$options": "i"}
            }
            if art_variant and art_variant.strip():
                full_query["card_art_variant"] = art_variant.strip()
            queries_to_try.append(("full_match", full_query))
        
        # Query 2: Card number + rarity only
        if card_rarity and card_rarity.strip():
            rarity_query = {
                "card_number": card_number,
                "card_rarity": {"$regex": re.escape(card_rarity.strip()), "$options": "i"}
            }
            queries_to_try.append(("rarity_match", rarity_query))
        
        # Query 3: Card number only (fallback)
        card_only_query = {"card_number": card_number}
        queries_to_try.append(("card_only", card_only_query))
        
        # Try each query until we find a match
        for query_name, query in queries_to_try:
            logger.debug(f"Trying {query_name} query: {query}")
            
            document = sync_price_scraping_collection.find_one(
                query,
                sort=[("last_price_updt", -1)]
            )
            
            if document:
                logger.debug(f"Found match with {query_name} query")
                
                # VALIDATE: Check if cached data actually matches the request
                if art_variant and art_variant.strip():
                    cached_card_name = document.get('card_name', '')
                    cached_source_url = document.get('source_url', '')
                    cached_art_variant = document.get('card_art_variant', '')
                    
                    # Extract actual art variant from cached card name and URL
                    actual_art_from_name = extract_art_version(cached_card_name)
                    actual_art_from_url = extract_art_version(cached_source_url)
                    
                    # Use the most reliable source for actual art variant
                    actual_art_variant = actual_art_from_name or actual_art_from_url
                    
                    if actual_art_variant:
                        # Clean up for comparison
                        requested_clean = re.sub(r'(st|nd|rd|th)$', '', art_variant.lower().strip())
                        actual_clean = re.sub(r'(st|nd|rd|th)$', '', actual_art_variant.lower().strip())
                        cached_clean = re.sub(r'(st|nd|rd|th)$', '', cached_art_variant.lower().strip())
                        
                        # Check if the actual art variant matches what was requested
                        if requested_clean != actual_clean:
                            logger.warning(f"CACHE VALIDATION FAILED: Requested '{art_variant}' but cached data is actually '{actual_art_variant}' (card name: {cached_card_name[:100]}...)")
                            logger.warning(f"Stored art variant: '{cached_art_variant}', Actual from name: '{actual_art_from_name}', Actual from URL: '{actual_art_from_url}'")
                            logger.warning(f"This cache entry appears to be corrupted, skipping...")
                            continue  # Skip this corrupted cache entry
                        else:
                            logger.info(f"CACHE VALIDATION PASSED: Requested '{art_variant}' matches actual '{actual_art_variant}'")
                    else:
                        logger.warning(f"Could not extract actual art variant from cached data for validation")
                
                break
        
        if not document:
            logger.debug("No valid cached data found for any query variation")
            return False, None
        
        # Check if data is fresh (within expiry period)
        expiry_date = datetime.now(UTC) - timedelta(days=CACHE_EXPIRY_DAYS)
        last_update = document.get('last_price_updt', datetime.min)
        
        # Handle both datetime objects and timezone-naive datetime strings
        if isinstance(last_update, str):
            try:
                last_update = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            except:
                last_update = datetime.min
        
        # Ensure timezone awareness
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=UTC)
        
        is_fresh = last_update > expiry_date
        
        if is_fresh:
            logger.info(f"Found fresh sync cached data for {card_number} (updated: {last_update})")
        else:
            logger.info(f"Found stale sync cached data for {card_number} (updated: {last_update}, expired: {expiry_date})")
        
        return is_fresh, document
        
    except Exception as e:
        logger.error(f"Error checking sync cached price data: {e}")
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
    """Enhanced variant selection logic with comprehensive debugging."""
    try:
        logger.info("="*80)
        logger.info("STARTING VARIANT SELECTION WITH COMPREHENSIVE DEBUGGING")
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
        
        # Log ALL found variants
        logger.info(f"FOUND {len(variants)} TOTAL VARIANTS:")
        for i, variant in enumerate(variants):
            logger.info(f"  {i+1:2d}. {variant['title']}")
        logger.info("="*80)
        
        if len(variants) == 1:
            logger.info("Only one variant found, selecting automatically")
            return variants[0]['href']
        
        # Get normalized rarity variants for matching
        rarity_variants = normalize_rarity_for_matching(card_rarity) if card_rarity else []
        logger.info(f"RARITY MATCHING VARIANTS: {rarity_variants}")
        logger.info("="*80)
        
        # Detailed scoring for each variant
        variant_scores = []
        
        for i, variant in enumerate(variants):
            title = variant['title']
            logger.info(f"ANALYZING VARIANT {i+1}: {title}")
            
            # Initialize scoring breakdown
            score_breakdown = {
                'card_number': 0,
                'rarity': 0, 
                'art': 0,
                'perfect_bonus': 0,
                'total': 0
            }
            
            # Extract art version from this variant
            detected_art = extract_art_version(title)
            logger.info(f"  Detected Art Version: {detected_art}")
            
            # Check rarity indicators
            title_lower = title.lower()
            rarity_found = []
            for rarity_variant in rarity_variants:
                if rarity_variant in title_lower:
                    rarity_found.append(rarity_variant)
            logger.info(f"  Rarity Indicators Found: {rarity_found}")
            
            # Score card number match
            if card_number and card_number.lower() in title_lower:
                score_breakdown['card_number'] = 100
                logger.info(f"  ✓ Card Number Match: +100")
            else:
                logger.info(f"  ✗ Card Number Match: +0")
            
            # Score rarity matching
            rarity_matched = False
            if card_rarity and rarity_found:
                # Check for exact match first (full rarity name match)
                exact_rarity_match = False
                for rarity_variant in rarity_found:
                    if rarity_variant in ['platinum secret rare', 'quarter century secret rare']:
                        # For specific rare types, require exact match
                        if rarity_variant == card_rarity.lower().strip():
                            exact_rarity_match = True
                            rarity_matched = True
                            score_breakdown['rarity'] = 150
                            logger.info(f"  ✓ Exact Specific Rarity Match: +150")
                            break
                
                # If no exact match found, check for partial matches
                if not exact_rarity_match:
                    for rarity_variant in rarity_found:
                        if rarity_variant == card_rarity.lower().strip():
                            rarity_matched = True
                            score_breakdown['rarity'] = 150
                            logger.info(f"  ✓ Exact Rarity Match: +150")
                            break
                        elif rarity_variant in card_rarity.lower():
                            # Only allow partial match for non-specific rarities
                            if card_rarity.lower().strip() not in ['platinum secret rare', 'quarter century secret rare']:
                                rarity_matched = True
                                score_breakdown['rarity'] = 120
                                logger.info(f"  ✓ Rarity Variant Match: +120")
                                break
                            else:
                                # For specific rarities like "platinum secret rare", partial matches get heavy penalty
                                score_breakdown['rarity'] = -400  # Much heavier penalty
                                logger.info(f"  ✗ Wrong Specific Rarity ('{rarity_variant}' vs '{card_rarity}'): -400")
                                break
            elif card_rarity and not rarity_found and any(r in card_rarity.lower() for r in ['secret', 'ultra', 'super', 'rare']):
                score_breakdown['rarity'] = -300
                logger.info(f"  ✗ No Rarity Found (Base Version): -300")
            else:
                logger.info(f"  • No Rarity Scoring Applied")
            
            # Score art variant matching with higher priority when explicitly requested
            art_matched = False
            if target_art_version and detected_art:
                target_clean = re.sub(r'(st|nd|rd|th)$', '', target_art_version.lower().strip())
                detected_clean = re.sub(r'(st|nd|rd|th)$', '', detected_art.lower().strip())
                
                if target_clean == detected_clean:
                    art_matched = True
                    # Higher score for art match when explicitly requested
                    score_breakdown['art'] = 300  # Increased from 150
                    logger.info(f"  ✓ EXACT ART MATCH '{target_clean}' == '{detected_clean}': +300")
                else:
                    # Much higher penalty for art mismatch when specific art is requested
                    score_breakdown['art'] = -500  # Increased penalty from -200
                    logger.info(f"  ✗ ART MISMATCH '{target_clean}' != '{detected_clean}': -500")
            elif target_art_version and not detected_art:
                score_breakdown['art'] = -100
                logger.info(f"  ✗ No Art Info Found: -100")
            else:
                logger.info(f"  • No Art Scoring Applied")
            
            # Perfect match bonus - now prioritizes art+rarity combination
            if rarity_matched and art_matched and target_art_version and card_rarity:
                score_breakdown['perfect_bonus'] = 200  # Reduced from 500 since art score is higher now
                logger.info(f"  🎯 PERFECT MATCH BONUS (Rarity + Art): +200")
            
            # Calculate total
            score_breakdown['total'] = (score_breakdown['card_number'] + 
                                      score_breakdown['rarity'] + 
                                      score_breakdown['art'] + 
                                      score_breakdown['perfect_bonus'])
            
            logger.info(f"  TOTAL SCORE: {score_breakdown['total']}")
            logger.info("-" * 60)
            
            variant_scores.append({
                'variant': variant,
                'title': title,
                'detected_art': detected_art,
                'rarity_found': rarity_found,
                'score_breakdown': score_breakdown,
                'total_score': score_breakdown['total']
            })
        
        # Sort by score
        variant_scores.sort(key=lambda x: x['total_score'], reverse=True)
        
        # Show final ranking
        logger.info("FINAL VARIANT RANKING:")
        for i, vs in enumerate(variant_scores[:5]):  # Show top 5
            logger.info(f"  {i+1}. Score: {vs['total_score']:4d} | Art: {vs['detected_art'] or 'None':4s} | {vs['title'][:60]}...")
        
        if variant_scores and variant_scores[0]['total_score'] > 0:
            selected = variant_scores[0]
            logger.info("="*80)
            logger.info(f"SELECTED VARIANT:")
            logger.info(f"  Title: {selected['title']}")
            logger.info(f"  Score: {selected['total_score']}")
            logger.info(f"  Art: {selected['detected_art']}")
            logger.info(f"  Rarities Found: {selected['rarity_found']}")
            logger.info("="*80)
            return selected['variant']['href']
        
        # No good matches found
        if variants:
            logger.warning("NO GOOD MATCHES FOUND - Using first variant as fallback")
            logger.warning(f"Fallback: {variants[0]['title']}")
            return variants[0]['href']
        
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
            
            # Search using card number
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
            
            # Get final page URL and title
            final_url = page.url
            page_title = await page.title()
            
            # Extract the ACTUAL art variant from the scraped page title/URL
            actual_art_variant = extract_art_version(page_title)
            if not actual_art_variant:
                # Also try extracting from URL
                actual_art_variant = extract_art_version(final_url)
            
            # Check if we need to validate rarity from TCGPlayer
            detected_rarity_from_title = None
            if card_rarity:
                # Check if the requested rarity appears in the page title
                rarity_variants = normalize_rarity_for_matching(card_rarity)
                title_lower = page_title.lower()
                
                for rarity_variant in rarity_variants:
                    if rarity_variant in title_lower:
                        detected_rarity_from_title = rarity_variant
                        break
                
                # If no rarity detected in title but we have a specific rarity request,
                # check TCGPlayer to validate this is the correct variant
                if not detected_rarity_from_title:
                    logger.info(f"No rarity detected in title for requested '{card_rarity}', checking TCGPlayer...")
                    tcg_rarity = await extract_rarity_from_tcgplayer(page)
                    
                    if tcg_rarity:
                        # Normalize TCGPlayer rarity for comparison
                        tcg_normalized = normalize_rarity(tcg_rarity)
                        requested_normalized = normalize_rarity(card_rarity)
                        
                        if tcg_normalized == requested_normalized:
                            logger.info(f"✓ TCGPlayer confirms rarity: '{tcg_rarity}' matches requested '{card_rarity}'")
                            detected_rarity_from_title = tcg_rarity  # Use the actual rarity from TCGPlayer
                        else:
                            logger.warning(f"✗ TCGPlayer rarity mismatch: '{tcg_rarity}' vs requested '{card_rarity}'")
                            # This means we selected the wrong variant - the title has no rarity 
                            # but TCGPlayer shows a different rarity than requested
                            await browser.close()
                            return {
                                "card_number": card_number,
                                "card_name": card_name or '',
                                "card_art_variant": art_variant,
                                "card_rarity": card_rarity,
                                "scrape_success": False,
                                "error_message": f"Rarity mismatch: found '{tcg_rarity}' but requested '{card_rarity}'",
                                "last_price_updt": datetime.now(UTC)
                            }
                    else:
                        logger.warning(f"Could not validate rarity from TCGPlayer for variant with no title rarity")
            
            # Extract prices from the product page
            price_data = await extract_prices_from_dom(page)
            
            if not price_data:
                logger.warning(f"No price data extracted for {card_number}")
                await browser.close()
                return None
            
            # Log the comparison for debugging
            if art_variant and actual_art_variant and art_variant != actual_art_variant:
                logger.warning(f"Art variant mismatch! Requested: '{art_variant}', Found: '{actual_art_variant}' in page: {page_title}")
            elif actual_art_variant:
                logger.info(f"Successfully matched art variant: '{actual_art_variant}' in page: {page_title}")
            
            # Use the actual art variant found on the page, not the requested one
            final_art_variant = actual_art_variant if actual_art_variant else art_variant
            
            # Use the detected rarity (either from title or TCGPlayer validation)
            final_rarity = detected_rarity_from_title if detected_rarity_from_title else card_rarity
            
            # Extract set code and booster set name
            set_code = extract_set_code(card_number)
            booster_set_name = extract_booster_set_name(final_url)
            
            await browser.close()
            
            # Create price record with ACTUAL art variant and validated rarity
            price_record = {
                "card_number": card_number,
                "card_name": page_title,  # Use actual page title, not requested name
                "card_art_variant": final_art_variant,  # Use actual art variant found on page
                "card_rarity": final_rarity,  # Use validated rarity (from title or TCGPlayer)
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
                "last_price_updt": datetime.now(UTC)
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
            "last_price_updt": datetime.now(UTC)
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
        
        # Initialize synchronous connections
        initialize_sync_price_scraping()
        
        # Validate card rarity using synchronous function
        logger.info(f"Validating rarity '{card_rarity}' for card {card_number}")
        is_valid_rarity = validate_card_rarity_sync(card_number, card_rarity)
        
        if not is_valid_rarity:
            return jsonify({
                "success": False,
                "error": f"Invalid rarity '{card_rarity}' for card {card_number}. Please check the card variant database for available rarities."
            }), 400
        
        # Check cache first unless force refresh is requested
        if not force_refresh:
            is_fresh, cached_data = find_cached_price_data_sync(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=art_variant
            )
            
            if is_fresh and cached_data:
                logger.info(f"Using cached price data for {card_number}")
                
                # Fix cache age calculation with proper timezone handling
                last_update = cached_data.get('last_price_updt', datetime.now(UTC))
                if isinstance(last_update, str):
                    try:
                        last_update = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    except:
                        last_update = datetime.now(UTC)
                
                # Ensure timezone awareness
                if last_update.tzinfo is None:
                    last_update = last_update.replace(tzinfo=UTC)
                
                cache_age = datetime.now(UTC) - last_update
                
                return jsonify({
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
                })
        
        # Scrape fresh data using async function (only scraping is async)
        async def scrape_data():
            return await scrape_price_from_pricecharting(
                card_number=card_number,
                card_name=card_name,
                card_rarity=card_rarity,
                art_variant=art_variant
            )
        
        # Run only the scraping in async context
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
        
        # Save to cache using synchronous function (no event loop conflicts)
        try:
            saved = save_price_data_sync(price_data)
            if not saved:
                logger.warning(f"Failed to save price data to cache for {card_number}")
                # Still return the scraped data even if cache save fails
                return jsonify({
                    "success": True,
                    "data": price_data,
                    "message": "Price data scraped successfully but failed to save to cache",
                    "cache_warning": "Cache save failed"
                })
        except Exception as e:
            logger.error(f"Error saving to cache: {e}")
            # Still return the scraped data even if cache save fails
            return jsonify({
                "success": True,
                "data": price_data,
                "message": "Price data scraped successfully but failed to save to cache",
                "cache_error": str(e)
            })
        
        return jsonify({
            "success": True,
            "data": price_data,
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

async def extract_rarity_from_tcgplayer(page) -> Optional[str]:
    """Extract rarity information from TCGPlayer via the 'SEE IT' link."""
    try:
        # Look for TCGPlayer "SEE IT" link
        tcgplayer_link = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                for (const link of links) {
                    if (link.href.includes('tcgplayer.com') && 
                        (link.textContent.includes('SEE IT') || link.textContent.includes('View on TCGPlayer'))) {
                        return link.href;
                    }
                }
                return null;
            }
        """)
        
        if not tcgplayer_link:
            logger.debug("No TCGPlayer link found")
            return None
        
        logger.info(f"Found TCGPlayer link: {tcgplayer_link}")
        
        # Open TCGPlayer page in a new tab
        tcg_page = await page.context.new_page()
        try:
            await tcg_page.goto(tcgplayer_link, wait_until='networkidle', timeout=15000)
            
            # Extract rarity from TCGPlayer page
            rarity = await tcg_page.evaluate(r"""
                () => {
                    // Look for rarity information in various formats
                    const patterns = [
                        /Rarity:\s*([^\n<]+)/i,
                        /rarity["']?\s*:\s*["']?([^"',\n<]+)/i,
                        /"rarity"\s*:\s*"([^"]+)"/i
                    ];
                    
                    const text = document.body.textContent || '';
                    
                    for (const pattern of patterns) {
                        const match = text.match(pattern);
                        if (match && match[1]) {
                            return match[1].trim();
                        }
                    }
                    
                    return null;
                }
            """)
            
            if rarity:
                logger.info(f"Extracted rarity from TCGPlayer: {rarity}")
                return rarity.strip()
            else:
                logger.debug("No rarity found on TCGPlayer page")
                return None
                
        finally:
            await tcg_page.close()
            
    except Exception as e:
        logger.error(f"Error extracting rarity from TCGPlayer: {e}")
        return None

if __name__ == "__main__":
    # Initialize the price scraping system
    if initialize_sync_price_scraping():
        logger.info("Price scraping system initialized successfully")
    else:
        logger.warning("Failed to initialize price scraping system")
    
    # Run the Flask application
    logger.info("Starting YGO API server...")
    app.run(host='0.0.0.0', port=8081, debug=True)
