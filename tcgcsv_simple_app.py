"""
Simple TCGcsv Flask Application
Basic implementation without async features for immediate testing
"""

import csv
import io
import logging
import json
import os
import requests
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from flask import Flask, jsonify, request
from flask_cors import CORS

# Simple configuration
PORT = int(os.getenv("PORT", 8081))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
TCGCSV_BASE_URL = "https://tcgcsv.com"
YUGIOH_CATEGORY_ID = 2
CACHE_EXPIRY_HOURS = 24

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8080"])

@dataclass
class CardSet:
    """Represents a Yu-Gi-Oh card set."""
    group_id: int
    name: str
    abbreviation: str
    published_on: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class Card:
    """Represents a Yu-Gi-Oh card."""
    product_id: int
    name: str
    image_url: str
    group_id: int
    ext_number: Optional[str] = None
    ext_rarity: Optional[str] = None
    ext_attribute: Optional[str] = None
    ext_monster_type: Optional[str] = None
    ext_card_type: Optional[str] = None
    ext_attack: Optional[int] = None
    ext_defense: Optional[int] = None
    market_price: Optional[float] = None
    low_price: Optional[float] = None
    mid_price: Optional[float] = None
    high_price: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# Thread-safe in-memory cache
class SimpleCache:
    def __init__(self):
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self.card_sets: List[CardSet] = []
        self.cards: Dict[int, List[Card]] = {}
        self.last_updated = None
    
    def is_expired(self) -> bool:
        with self._lock:
            if not self.last_updated:
                return True
            return datetime.now() - self.last_updated > timedelta(hours=CACHE_EXPIRY_HOURS)
    
    def get_sets(self) -> List[CardSet]:
        with self._lock:
            return self.card_sets if not self.is_expired() else []
    
    def update_sets(self, sets: List[CardSet]):
        with self._lock:
            self.card_sets = sets
            self.last_updated = datetime.now()
    
    def get_cards(self, group_id: int) -> List[Card]:
        with self._lock:
            if self.is_expired() or group_id not in self.cards:
                return []
            return self.cards[group_id]
    
    def update_cards(self, group_id: int, cards: List[Card]):
        with self._lock:
            self.cards[group_id] = cards

# Global cache instance
cache = SimpleCache()

def fetch_card_sets() -> List[CardSet]:
    """Fetch card sets from TCGcsv."""
    try:
        url = f"{TCGCSV_BASE_URL}/tcgplayer/{YUGIOH_CATEGORY_ID}/Groups.csv"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        sets = []
        csv_reader = csv.DictReader(io.StringIO(response.text))
        
        for row in csv_reader:
            card_set = CardSet(
                group_id=int(row['groupId']),
                name=row['name'],
                abbreviation=row['abbreviation'],
                published_on=row['publishedOn']
            )
            sets.append(card_set)
        
        logger.info(f"Fetched {len(sets)} card sets from TCGcsv")
        return sets
        
    except Exception as e:
        logger.error(f"Failed to fetch card sets: {e}")
        return []

def fetch_cards_for_set(group_id: int) -> List[Card]:
    """Fetch cards for a specific set."""
    try:
        url = f"{TCGCSV_BASE_URL}/tcgplayer/{YUGIOH_CATEGORY_ID}/{group_id}/ProductsAndPrices.csv"
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        cards = []
        csv_reader = csv.DictReader(io.StringIO(response.text))
        
        for row in csv_reader:
            # Skip sealed products
            if any(keyword in row['name'].lower() for keyword in ['booster', 'pack', 'box', 'tin', 'deck']):
                continue
            
            def safe_int(value: str) -> Optional[int]:
                try:
                    return int(value) if value and value.strip() else None
                except ValueError:
                    return None
            
            def safe_float(value: str) -> Optional[float]:
                try:
                    return float(value) if value and value.strip() else None
                except ValueError:
                    return None
            
            card = Card(
                product_id=int(row['productId']),
                name=row['name'],
                image_url=row['imageUrl'],
                group_id=int(row['groupId']),
                ext_number=row.get('extNumber'),
                ext_rarity=row.get('extRarity'),
                ext_attribute=row.get('extAttribute'),
                ext_monster_type=row.get('extMonsterType'),
                ext_card_type=row.get('extCardType'),
                ext_attack=safe_int(row.get('extAttack')),
                ext_defense=safe_int(row.get('extDefense')),
                market_price=safe_float(row.get('marketPrice')),
                low_price=safe_float(row.get('lowPrice')),
                mid_price=safe_float(row.get('midPrice')),
                high_price=safe_float(row.get('highPrice'))
            )
            cards.append(card)
        
        logger.info(f"Fetched {len(cards)} cards for set {group_id}")
        return cards
        
    except Exception as e:
        logger.error(f"Failed to fetch cards for set {group_id}: {e}")
        return []

def create_success_response(data: Any, message: str = "Success") -> Dict[str, Any]:
    """Create standardized success response."""
    return jsonify({
        "success": True,
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat()
    })

def create_error_response(message: str, status_code: int = 500) -> tuple:
    """Create standardized error response."""
    return jsonify({
        "success": False,
        "error": {
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
    }), status_code

# Routes
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return create_success_response({
        "status": "healthy",
        "service": "tcgcsv-api-simple",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/card-sets', methods=['GET'])
@app.route('/card-sets/from-cache', methods=['GET'])
def get_card_sets():
    """Get all card sets."""
    try:
        # Check cache first
        cached_sets = cache.get_sets()
        if cached_sets:
            logger.info(f"Returning {len(cached_sets)} sets from cache")
        else:
            logger.info("Cache expired, fetching fresh data...")
            cached_sets = fetch_card_sets()
            cache.update_sets(cached_sets)
        
        # Convert to frontend format
        sets_data = []
        for card_set in cached_sets:
            set_dict = card_set.to_dict()
            set_dict.update({
                'id': card_set.abbreviation or str(card_set.group_id),
                'set_name': card_set.name,
                'set_code': card_set.abbreviation,
                'tcg_date': card_set.published_on
            })
            sets_data.append(set_dict)
        
        return create_success_response(sets_data, f"Retrieved {len(sets_data)} card sets")
        
    except Exception as e:
        logger.error(f"Failed to get card sets: {e}")
        return create_error_response(f"Failed to retrieve card sets: {str(e)}")

@app.route('/card-sets/<set_identifier>/cards', methods=['GET'])
def get_set_cards(set_identifier: str):
    """Get cards for a specific set."""
    try:
        # Find the set
        sets = cache.get_sets()
        if not sets:
            sets = fetch_card_sets()
            cache.update_sets(sets)
        
        target_set = None
        for card_set in sets:
            if (card_set.abbreviation and card_set.abbreviation.upper() == set_identifier.upper()) or \
               str(card_set.group_id) == set_identifier:
                target_set = card_set
                break
        
        if not target_set:
            return create_error_response(f"Set '{set_identifier}' not found", 404)
        
        # Get cards
        cards = cache.get_cards(target_set.group_id)
        if not cards:
            cards = fetch_cards_for_set(target_set.group_id)
            cache.update_cards(target_set.group_id, cards)
        
        # Convert to frontend format
        cards_data = []
        for card in cards:
            card_dict = card.to_dict()
            card_dict.update({
                'id': str(card.product_id),
                'name': card.name,
                'rarity': card.ext_rarity,
                'set_code': target_set.abbreviation,
                'card_number': card.ext_number,
                'attack': card.ext_attack,
                'defense': card.ext_defense,
                'attribute': card.ext_attribute,
                'type': card.ext_card_type,
                'race': card.ext_monster_type,
                'image_url': card.image_url,
                'tcg_price': card.low_price or card.mid_price or card.market_price,
                'market_price': card.market_price
            })
            cards_data.append(card_dict)
        
        return create_success_response({
            'set_info': target_set.to_dict(),
            'cards': cards_data
        }, f"Retrieved {len(cards_data)} cards for set {set_identifier}")
        
    except Exception as e:
        logger.error(f"Failed to get cards for set {set_identifier}: {e}")
        return create_error_response(f"Failed to retrieve cards: {str(e)}")

@app.route('/cards/price', methods=['POST'])
def get_card_price():
    """Get price for a specific card."""
    try:
        data = request.get_json()
        if not data:
            return create_error_response("JSON data required", 400)
        
        card_name = data.get('cardName', '').strip()
        set_code = data.get('setCode', '').strip()
        
        if not card_name:
            return create_error_response("cardName is required", 400)
        
        # Find set if provided
        target_group_id = None
        if set_code:
            sets = cache.get_sets()
            if not sets:
                sets = fetch_card_sets()
                cache.update_sets(sets)
            
            for card_set in sets:
                if card_set.abbreviation and card_set.abbreviation.upper() == set_code.upper():
                    target_group_id = card_set.group_id
                    break
        
        # Search for card
        found_card = None
        if target_group_id:
            # Search in specific set
            cards = cache.get_cards(target_group_id)
            if not cards:
                cards = fetch_cards_for_set(target_group_id)
                cache.update_cards(target_group_id, cards)
            
            for card in cards:
                if card.name.lower() == card_name.lower():
                    found_card = card
                    break
        else:
            # Search in all sets
            sets = cache.get_sets()
            if not sets:
                sets = fetch_card_sets()
                cache.update_sets(sets)
            
            for card_set in sets:
                cards = cache.get_cards(card_set.group_id)
                if not cards:
                    cards = fetch_cards_for_set(card_set.group_id)
                    cache.update_cards(card_set.group_id, cards)
                
                for card in cards:
                    if card.name.lower() == card_name.lower():
                        found_card = card
                        break
                if found_card:
                    break
        
        if not found_card:
            return create_error_response(f"Card '{card_name}' not found", 404)
        
        # Return price data
        price_data = {
            'success': True,
            'cardName': found_card.name,
            'setCode': set_code,
            'rarity': found_card.ext_rarity,
            'tcgPrice': found_card.market_price or found_card.mid_price or found_card.low_price,
            'marketPrice': found_card.market_price,
            'lowPrice': found_card.low_price,
            'midPrice': found_card.mid_price,
            'highPrice': found_card.high_price,
            'imageUrl': found_card.image_url,
            'source': 'tcgcsv',
            'productId': found_card.product_id
        }
        
        return jsonify(price_data)
        
    except Exception as e:
        logger.error(f"Failed to get card price: {e}")
        return create_error_response(f"Failed to get card price: {str(e)}")

@app.errorhandler(404)
def not_found_error(error):
    return create_error_response("Endpoint not found", 404)

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return create_error_response("Internal server error", 500)

if __name__ == '__main__':
    try:
        logger.info("Starting TCGcsv Yu-Gi-Oh API server...")
        logger.info(f"Port: {PORT}, Debug: {DEBUG}")
        
        # Test TCGcsv connectivity
        logger.info("Testing TCGcsv connectivity...")
        test_response = requests.get(f"{TCGCSV_BASE_URL}/tcgplayer/{YUGIOH_CATEGORY_ID}/Groups.csv", timeout=10)
        if test_response.status_code == 200:
            logger.info("✅ TCGcsv connectivity test passed")
        else:
            logger.warning(f"⚠️ TCGcsv returned status {test_response.status_code}")
        
        app.run(
            host='0.0.0.0',
            port=PORT,
            debug=DEBUG,
            threaded=True
        )
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise