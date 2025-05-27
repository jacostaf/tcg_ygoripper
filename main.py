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
                break
        
        if not document:
            logger.debug("No cached data found for any query variation")
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
        
        # Log all found variants for debugging
        logger.info(f"Found {len(variants)} variants for {card_number}:")
        for i, variant in enumerate(variants[:10]):  # Log first 10 variants
            logger.info(f"  {i+1}. {variant['title']}")
        
        if len(variants) == 1:
            logger.debug("Only one variant found, selecting automatically")
            return variants[0]['href']
        
        logger.debug(f"Found {len(variants)} variants, evaluating best match...")
        
        # Simple scoring system for demo
        best_variant = None
        best_score = -1
        
        for variant in variants:
            title = variant['title']
            score = 0
            
            # Score card number match
            if card_number and card_number.lower() in title.lower():
                score += 100
            
            # Score rarity match
            if card_rarity and card_rarity.lower() in title.lower():
                score += 50
            
            if score > best_score:
                best_score = score
                best_variant = variant
        
        if best_variant:
            logger.info(f"SELECTED: {best_variant['title']} (score: {best_score})")
            return best_variant['href']
        
        # Fallback to first variant
        if variants:
            logger.info(f"Using fallback: {variants[0]['title']}")
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)