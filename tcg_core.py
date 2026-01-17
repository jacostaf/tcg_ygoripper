"""
TCGcsv Core Services
Handles data fetching, caching, and persistence.
"""

import csv
import io
import logging
import json
import os
import requests
import threading
import pickle
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

# Configuration
TCGCSV_BASE_URL = "https://tcgcsv.com"
YUGIOH_CATEGORY_ID = 2
CACHE_EXPIRY_HOURS = 24
CACHE_FILE = "card_cache.pkl"

# YGOProDeck API for fallback set codes
YGOPRODECK_SETS_URL = "https://db.ygoprodeck.com/api/v7/cardsets.php"

logger = logging.getLogger(__name__)

def fetch_ygoprodeck_sets() -> Dict[str, str]:
    """
    Fetch set name -> set_code mapping from YGOProDeck API.
    Used as fallback when TCGcsv lacks abbreviations for certain sets.
    """
    try:
        response = requests.get(YGOPRODECK_SETS_URL, timeout=30)
        response.raise_for_status()
        sets = response.json()
        # Create mapping: set_name (lowercase) -> set_code
        mapping = {s['set_name'].lower(): s['set_code'] for s in sets if s.get('set_code')}
        logger.info(f"Fetched {len(mapping)} set codes from YGOProDeck API")
        return mapping
    except Exception as e:
        logger.error(f"Failed to fetch YGOProDeck sets: {e}")
        return {}

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

class PersistentCache:
    """Thread-safe cache with disk persistence."""
    def __init__(self):
        self._lock = threading.RLock()
        self.card_sets: List[CardSet] = []
        self.set_map: Dict[int, CardSet] = {}
        self.cards: Dict[int, List[Card]] = {}
        self.global_index: Dict[str, List[Card]] = {}
        self.product_id_index: Dict[int, Card] = {}  # O(1) lookup by product_id
        self.last_updated = None
        # YGOProDeck fallback cache for set codes
        self.ygoprodeck_set_codes: Dict[str, str] = {}  # set_name_lower -> set_code
        self.ygoprodeck_last_updated: Optional[datetime] = None
        self.load_from_disk()

    def is_expired(self) -> bool:
        with self._lock:
            if not self.last_updated:
                return True
            return datetime.now() - self.last_updated > timedelta(hours=CACHE_EXPIRY_HOURS)

    def save_to_disk(self):
        """Save cache state to disk."""
        try:
            with self._lock:
                data = {
                    'card_sets': self.card_sets,
                    'set_map': self.set_map,
                    'cards': self.cards,
                    'global_index': self.global_index,
                    'product_id_index': self.product_id_index,
                    'last_updated': self.last_updated,
                    'ygoprodeck_set_codes': self.ygoprodeck_set_codes,
                    'ygoprodeck_last_updated': self.ygoprodeck_last_updated
                }
                with open(CACHE_FILE, 'wb') as f:
                    pickle.dump(data, f)
                logger.info(f"Cache saved to {CACHE_FILE}")
        except Exception as e:
            logger.error(f"Failed to save cache to disk: {e}")

    def load_from_disk(self):
        """Load cache state from disk."""
        if not os.path.exists(CACHE_FILE):
            logger.info("No cache file found, starting fresh.")
            return

        try:
            with self._lock:
                with open(CACHE_FILE, 'rb') as f:
                    data = pickle.load(f)
                    self.card_sets = data.get('card_sets', [])
                    self.set_map = data.get('set_map', {})
                    self.cards = data.get('cards', {})
                    self.global_index = data.get('global_index', {})
                    self.product_id_index = data.get('product_id_index', {})
                    self.last_updated = data.get('last_updated')
                    # Load YGOProDeck fallback cache
                    self.ygoprodeck_set_codes = data.get('ygoprodeck_set_codes', {})
                    self.ygoprodeck_last_updated = data.get('ygoprodeck_last_updated')
                # Rebuild product_id_index if missing (for existing caches)
                if not self.product_id_index and self.cards:
                    for cards_list in self.cards.values():
                        for card in cards_list:
                            if card.product_id:
                                self.product_id_index[card.product_id] = card
                    logger.info(f"Rebuilt product_id_index with {len(self.product_id_index)} entries")
                logger.info(f"Loaded cache from disk. Sets: {len(self.card_sets)}, Cards: {sum(len(c) for c in self.cards.values())}, YGOProDeck codes: {len(self.ygoprodeck_set_codes)}")
        except Exception as e:
            logger.error(f"Failed to load cache from disk: {e}")
            # Start fresh if load fails
            self.card_sets = []
            self.set_map = {}
            self.cards = {}
            self.global_index = {}
            self.last_updated = None
            self.ygoprodeck_set_codes = {}
            self.ygoprodeck_last_updated = None

    def get_sets(self) -> List[CardSet]:
        with self._lock:
            return self.card_sets

    def update_sets(self, sets: List[CardSet]):
        with self._lock:
            self.card_sets = sets
            self.set_map = {s.group_id: s for s in sets}
            self.last_updated = datetime.now()
            self.save_to_disk()

    def get_set_by_id(self, group_id: int) -> Optional[CardSet]:
        with self._lock:
            return self.set_map.get(group_id)

    def get_cards(self, group_id: int) -> List[Card]:
        with self._lock:
            return self.cards.get(group_id, [])

    def get_card_by_product_id(self, product_id: int) -> Optional[Card]:
        """O(1) lookup by TCGcsv product_id."""
        with self._lock:
            return self.product_id_index.get(product_id)

    def update_cards(self, group_id: int, cards: List[Card]):
        with self._lock:
            self.cards[group_id] = cards
            # Update global index and product_id index
            for card in cards:
                if card.name not in self.global_index:
                    self.global_index[card.name] = []
                # Avoid duplicates
                if card not in self.global_index[card.name]:
                    self.global_index[card.name].append(card)
                # Build product_id index for O(1) lookup
                if card.product_id:
                    self.product_id_index[card.product_id] = card
            self.save_to_disk()

    def search_global_index(self, query: str) -> List[Card]:
        query_lower = query.lower()
        results = []
        with self._lock:
            for name, cards in self.global_index.items():
                if query_lower in name.lower():
                    results.extend(cards)
        return results

    # =========================================================================
    # YGOProDeck Set Code Fallback Cache
    # =========================================================================

    def get_ygoprodeck_set_code(self, set_name: str) -> Optional[str]:
        """
        Get set code from YGOProDeck cache, refreshing if needed.
        Used as fallback when TCGcsv lacks abbreviations.
        """
        with self._lock:
            # Refresh cache if expired (24 hours) or empty
            if not self.ygoprodeck_set_codes or self._is_ygoprodeck_cache_expired():
                self._refresh_ygoprodeck_cache()
            return self.ygoprodeck_set_codes.get(set_name.lower())

    def _is_ygoprodeck_cache_expired(self) -> bool:
        """Check if YGOProDeck cache has expired (24 hours)."""
        if not self.ygoprodeck_last_updated:
            return True
        return datetime.now() - self.ygoprodeck_last_updated > timedelta(hours=CACHE_EXPIRY_HOURS)

    def _refresh_ygoprodeck_cache(self):
        """Refresh the YGOProDeck set codes cache from API."""
        new_codes = fetch_ygoprodeck_sets()
        if new_codes:
            self.ygoprodeck_set_codes = new_codes
            self.ygoprodeck_last_updated = datetime.now()
            logger.info(f"Refreshed YGOProDeck set codes cache: {len(new_codes)} sets")
            self.save_to_disk()
        else:
            logger.warning("Failed to refresh YGOProDeck cache, keeping existing data")

    def clear(self):
        """Clear all cache data from memory and disk."""
        with self._lock:
            self.card_sets = []
            self.set_map = {}
            self.cards = {}
            self.global_index = {}
            self.product_id_index = {}
            self.last_updated = None
            self.ygoprodeck_set_codes = {}
            self.ygoprodeck_last_updated = None
            if os.path.exists(CACHE_FILE):
                try:
                    os.remove(CACHE_FILE)
                    logger.info("Cache file deleted.")
                except Exception as e:
                    logger.error(f"Failed to delete cache file: {e}")

    def refresh(self):
        """Force refresh the entire cache."""
        logger.info("Refreshing cache...")
        self.clear()
        
        # Fetch sets
        sets = fetch_card_sets()
        self.update_sets(sets)
        
        # Fetch cards for all sets
        total_sets = len(sets)
        logger.info(f"Found {total_sets} sets. Fetching cards...")
        
        for i, card_set in enumerate(sets):
            cards = fetch_cards_for_set(card_set.group_id)
            self.update_cards(card_set.group_id, cards)
            if (i + 1) % 10 == 0:
                logger.info(f"Refreshed {i + 1}/{total_sets} sets")
                
        logger.info("Cache refresh complete.")

# Global cache instance
cache = PersistentCache()

def get_effective_set_code(card_set: CardSet) -> str:
    """
    Get the effective set code for a card set.
    Priority: TCGcsv abbreviation > YGOProDeck lookup > fallback to SET{group_id}

    This is the canonical function for resolving set codes - used by both
    the API server and the Supabase sync.
    """
    # 1. Use TCGcsv abbreviation if available
    if card_set.abbreviation:
        return card_set.abbreviation

    # 2. Try YGOProDeck fallback (cached, auto-refreshes every 24h)
    ygoprodeck_code = cache.get_ygoprodeck_set_code(card_set.name)
    if ygoprodeck_code:
        logger.debug(f"Using YGOProDeck code for '{card_set.name}': {ygoprodeck_code}")
        return ygoprodeck_code

    # 3. Fallback - prefix with SET to indicate synthetic code
    logger.warning(f"No set code found for '{card_set.name}', using fallback SET{card_set.group_id}")
    return f"SET{card_set.group_id}"

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
