"""
TCGcsv Service - Core service for fetching and processing TCGcsv data
Replaces MongoDB with in-memory caching and optional disk persistence
"""

import asyncio
import aiohttp
import csv
import io
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor

from tcgcsv_config import (
    TCGCSV_GROUPS_URL,
    get_tcgcsv_products_url,
    CACHE_EXPIRY_HOURS,
    DOWNLOAD_TIMEOUT_SECONDS,
    DOWNLOAD_RETRY_ATTEMPTS,
    DOWNLOAD_RETRY_DELAY_SECONDS,
    EXCLUDE_SEALED_PRODUCTS,
    EXCLUDE_ACCESSORIES,
    INCLUDE_PRICE_DATA,
    ENABLE_DISK_PERSISTENCE,
    get_data_storage_path,
    USE_TCGCSV_IMAGES,
    YGOPRODECK_IMAGE_BASE_URL,
)

logger = logging.getLogger(__name__)

@dataclass
class CardSet:
    """Represents a Yu-Gi-Oh card set from TCGcsv."""
    group_id: int
    name: str
    abbreviation: str
    is_supplemental: bool
    published_on: str
    modified_on: str
    category_id: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass 
class Card:
    """Represents a Yu-Gi-Oh card from TCGcsv."""
    product_id: int
    name: str
    clean_name: str
    image_url: str
    category_id: int
    group_id: int
    url: str
    modified_on: str
    
    # Card-specific attributes
    ext_number: Optional[str] = None
    ext_rarity: Optional[str] = None
    ext_attribute: Optional[str] = None
    ext_monster_type: Optional[str] = None
    ext_card_type: Optional[str] = None
    ext_attack: Optional[int] = None
    ext_defense: Optional[int] = None
    ext_link_rating: Optional[int] = None
    ext_link_arrows: Optional[str] = None
    
    # Pricing information
    low_price: Optional[float] = None
    mid_price: Optional[float] = None
    high_price: Optional[float] = None
    market_price: Optional[float] = None
    direct_low_price: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def get_primary_price(self) -> Optional[float]:
        """Get the primary price for this card."""
        return self.market_price or self.mid_price or self.low_price
    
    def get_image_url(self, fallback_to_ygoprodeck: bool = True) -> Optional[str]:
        """Get the best available image URL."""
        if USE_TCGCSV_IMAGES and self.image_url:
            return self.image_url
        
        # Try to extract card ID for YGOProdeck fallback
        if fallback_to_ygoprodeck and self.ext_number:
            # This would need card ID mapping logic
            pass
            
        return self.image_url

class TCGcsvCache:
    """In-memory cache for TCGcsv data with optional disk persistence."""
    
    def __init__(self):
        self.card_sets: Dict[int, CardSet] = {}
        self.cards: Dict[int, List[Card]] = {}  # group_id -> cards
        self.last_updated: Optional[datetime] = None
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Load from disk if enabled
        if ENABLE_DISK_PERSISTENCE:
            self._load_from_disk()
    
    def is_expired(self) -> bool:
        """Check if cache is expired."""
        if not self.last_updated:
            return True
        return datetime.now() - self.last_updated > timedelta(hours=CACHE_EXPIRY_HOURS)
    
    def get_card_sets(self) -> List[CardSet]:
        """Get all cached card sets."""
        if self.is_expired():
            self.cache_misses += 1
            return []
        
        self.cache_hits += 1
        return list(self.card_sets.values())
    
    def get_cards_for_set(self, group_id: int) -> List[Card]:
        """Get all cards for a specific set."""
        if self.is_expired() or group_id not in self.cards:
            self.cache_misses += 1
            return []
        
        self.cache_hits += 1
        return self.cards[group_id]
    
    def update_sets(self, sets: List[CardSet]):
        """Update cached card sets."""
        self.card_sets = {s.group_id: s for s in sets}
        self.last_updated = datetime.now()
        
        if ENABLE_DISK_PERSISTENCE:
            self._save_to_disk()
    
    def update_cards(self, group_id: int, cards: List[Card]):
        """Update cached cards for a specific set."""
        self.cards[group_id] = cards
        
        if ENABLE_DISK_PERSISTENCE:
            self._save_to_disk()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": self.cache_hits / max(1, self.cache_hits + self.cache_misses),
            "sets_count": len(self.card_sets),
            "cards_count": sum(len(cards) for cards in self.cards.values()),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "is_expired": self.is_expired()
        }
    
    def _save_to_disk(self):
        """Save cache to disk."""
        try:
            data_path = get_data_storage_path()
            
            # Save sets
            sets_file = os.path.join(data_path, "card_sets.json")
            with open(sets_file, 'w') as f:
                json.dump([s.to_dict() for s in self.card_sets.values()], f, indent=2)
            
            # Save cards
            cards_file = os.path.join(data_path, "cards.json")
            cards_data = {}
            for group_id, cards in self.cards.items():
                cards_data[str(group_id)] = [c.to_dict() for c in cards]
            
            with open(cards_file, 'w') as f:
                json.dump(cards_data, f, indent=2)
            
            # Save metadata
            meta_file = os.path.join(data_path, "cache_meta.json")
            with open(meta_file, 'w') as f:
                json.dump({
                    "last_updated": self.last_updated.isoformat() if self.last_updated else None,
                    "cache_hits": self.cache_hits,
                    "cache_misses": self.cache_misses
                }, f, indent=2)
                
            logger.info(f"Cache saved to disk: {len(self.card_sets)} sets, {sum(len(c) for c in self.cards.values())} cards")
            
        except Exception as e:
            logger.error(f"Failed to save cache to disk: {e}")
    
    def _load_from_disk(self):
        """Load cache from disk."""
        try:
            data_path = get_data_storage_path()
            
            # Load metadata
            meta_file = os.path.join(data_path, "cache_meta.json")
            if os.path.exists(meta_file):
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                    if meta.get("last_updated"):
                        self.last_updated = datetime.fromisoformat(meta["last_updated"])
                    self.cache_hits = meta.get("cache_hits", 0)
                    self.cache_misses = meta.get("cache_misses", 0)
            
            # Check if cache is still valid
            if self.is_expired():
                logger.info("Disk cache is expired, will refresh from TCGcsv")
                return
            
            # Load sets
            sets_file = os.path.join(data_path, "card_sets.json")
            if os.path.exists(sets_file):
                with open(sets_file, 'r') as f:
                    sets_data = json.load(f)
                    for set_dict in sets_data:
                        card_set = CardSet(**set_dict)
                        self.card_sets[card_set.group_id] = card_set
            
            # Load cards
            cards_file = os.path.join(data_path, "cards.json")
            if os.path.exists(cards_file):
                with open(cards_file, 'r') as f:
                    cards_data = json.load(f)
                    for group_id_str, cards_list in cards_data.items():
                        group_id = int(group_id_str)
                        self.cards[group_id] = [Card(**card_dict) for card_dict in cards_list]
            
            logger.info(f"Cache loaded from disk: {len(self.card_sets)} sets, {sum(len(c) for c in self.cards.values())} cards")
            
        except Exception as e:
            logger.error(f"Failed to load cache from disk: {e}")

class TCGcsvService:
    """Service for fetching and processing TCGcsv data."""
    
    def __init__(self):
        self.cache = TCGcsvCache()
        self.session: Optional[aiohttp.ClientSession] = None
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT_SECONDS)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
        self._executor.shutdown(wait=True)
    
    async def get_card_sets(self, force_refresh: bool = False) -> List[CardSet]:
        """Get all Yu-Gi-Oh card sets."""
        if not force_refresh:
            cached_sets = self.cache.get_card_sets()
            if cached_sets:
                return cached_sets
        
        logger.info("Fetching card sets from TCGcsv...")
        sets = await self._fetch_card_sets()
        self.cache.update_sets(sets)
        return sets
    
    async def get_cards_for_set(self, group_id: int, force_refresh: bool = False) -> List[Card]:
        """Get all cards for a specific set."""
        if not force_refresh:
            cached_cards = self.cache.get_cards_for_set(group_id)
            if cached_cards:
                return cached_cards
        
        logger.info(f"Fetching cards for set {group_id} from TCGcsv...")
        cards = await self._fetch_cards_for_set(group_id)
        self.cache.update_cards(group_id, cards)
        return cards
    
    async def search_cards(self, query: str, group_id: Optional[int] = None) -> List[Card]:
        """Search for cards by name."""
        all_cards = []
        
        if group_id:
            # Search in specific set
            cards = await self.get_cards_for_set(group_id)
            all_cards.extend(cards)
        else:
            # Search in all sets
            sets = await self.get_card_sets()
            for card_set in sets:
                cards = await self.get_cards_for_set(card_set.group_id)
                all_cards.extend(cards)
        
        # Filter by query
        query_lower = query.lower()
        matching_cards = [
            card for card in all_cards
            if query_lower in card.name.lower() or query_lower in card.clean_name.lower()
        ]
        
        return matching_cards
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self.cache.get_cache_stats()
    
    async def _fetch_card_sets(self) -> List[CardSet]:
        """Fetch card sets from TCGcsv."""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        for attempt in range(DOWNLOAD_RETRY_ATTEMPTS):
            try:
                async with self.session.get(TCGCSV_GROUPS_URL) as response:
                    response.raise_for_status()
                    csv_content = await response.text()
                    
                    # Parse CSV
                    sets = []
                    csv_reader = csv.DictReader(io.StringIO(csv_content))
                    
                    for row in csv_reader:
                        card_set = CardSet(
                            group_id=int(row['groupId']),
                            name=row['name'],
                            abbreviation=row['abbreviation'],
                            is_supplemental=row['isSupplemental'].lower() == 'true',
                            published_on=row['publishedOn'],
                            modified_on=row['modifiedOn'],
                            category_id=int(row['categoryId'])
                        )
                        sets.append(card_set)
                    
                    logger.info(f"Fetched {len(sets)} card sets from TCGcsv")
                    return sets
                    
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed to fetch sets: {e}")
                if attempt < DOWNLOAD_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(DOWNLOAD_RETRY_DELAY_SECONDS)
                else:
                    raise
        
        return []
    
    async def _fetch_cards_for_set(self, group_id: int) -> List[Card]:
        """Fetch cards for a specific set from TCGcsv."""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        url = get_tcgcsv_products_url(group_id)
        
        for attempt in range(DOWNLOAD_RETRY_ATTEMPTS):
            try:
                async with self.session.get(url) as response:
                    response.raise_for_status()
                    csv_content = await response.text()
                    
                    # Parse CSV
                    cards = []
                    csv_reader = csv.DictReader(io.StringIO(csv_content))
                    
                    for row in csv_reader:
                        # Skip sealed products if configured
                        if EXCLUDE_SEALED_PRODUCTS and self._is_sealed_product(row['name']):
                            continue
                        
                        # Skip accessories if configured  
                        if EXCLUDE_ACCESSORIES and self._is_accessory(row['name']):
                            continue
                        
                        card = self._parse_card_from_row(row)
                        cards.append(card)
                    
                    logger.info(f"Fetched {len(cards)} cards for set {group_id}")
                    return cards
                    
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed to fetch cards for set {group_id}: {e}")
                if attempt < DOWNLOAD_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(DOWNLOAD_RETRY_DELAY_SECONDS)
                else:
                    raise
        
        return []
    
    def _parse_card_from_row(self, row: Dict[str, str]) -> Card:
        """Parse a card from CSV row data."""
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
        
        return Card(
            product_id=int(row['productId']),
            name=row['name'],
            clean_name=row['cleanName'],
            image_url=row['imageUrl'],
            category_id=int(row['categoryId']),
            group_id=int(row['groupId']),
            url=row['url'],
            modified_on=row['modifiedOn'],
            ext_number=row.get('extNumber'),
            ext_rarity=row.get('extRarity'),
            ext_attribute=row.get('extAttribute'),
            ext_monster_type=row.get('extMonsterType'),
            ext_card_type=row.get('extCardType'),
            ext_attack=safe_int(row.get('extAttack')),
            ext_defense=safe_int(row.get('extDefense')),
            ext_link_rating=safe_int(row.get('extLinkRating')),
            ext_link_arrows=row.get('extLinkArrows'),
            low_price=safe_float(row.get('lowPrice')) if INCLUDE_PRICE_DATA else None,
            mid_price=safe_float(row.get('midPrice')) if INCLUDE_PRICE_DATA else None,
            high_price=safe_float(row.get('highPrice')) if INCLUDE_PRICE_DATA else None,
            market_price=safe_float(row.get('marketPrice')) if INCLUDE_PRICE_DATA else None,
            direct_low_price=safe_float(row.get('directLowPrice')) if INCLUDE_PRICE_DATA else None,
        )
    
    def _is_sealed_product(self, name: str) -> bool:
        """Check if a product is a sealed product."""
        sealed_keywords = [
            'booster box', 'booster pack', 'structure deck', 'starter deck',
            'tin', 'collection', 'set', 'bundle', 'case', 'display'
        ]
        name_lower = name.lower()
        return any(keyword in name_lower for keyword in sealed_keywords)
    
    def _is_accessory(self, name: str) -> bool:
        """Check if a product is an accessory."""
        accessory_keywords = [
            'sleeves', 'deck box', 'playmat', 'binder', 'portfolio',
            'dice', 'token', 'counter', 'mat', 'protector'
        ]
        name_lower = name.lower()
        return any(keyword in name_lower for keyword in accessory_keywords)

# Global service instance
_service_instance: Optional[TCGcsvService] = None

async def get_tcgcsv_service() -> TCGcsvService:
    """Get or create the global TCGcsv service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = TCGcsvService()
        await _service_instance.__aenter__()
    return _service_instance

async def cleanup_tcgcsv_service():
    """Cleanup the global TCGcsv service instance."""
    global _service_instance
    if _service_instance:
        await _service_instance.__aexit__(None, None, None)
        _service_instance = None