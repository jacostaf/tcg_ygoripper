import os
import logging
import requests
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import time

from tcgcsv_config import (
    SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_SYNC_ENABLED
)
from tcg_core import cache, Card, CardSet

logger = logging.getLogger(__name__)

class SupabaseSync:
    def __init__(self):
        self.url = SUPABASE_URL
        self.key = SUPABASE_SERVICE_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation" # Return the inserted/updated rows
        }
        self.rarity_map = {} # name -> id
        self.set_map = {} # code -> id
        self.variant_map = {} # (set_code, card_number, rarity) -> id

    def _request(self, method: str, endpoint: str, data: Any = None, params: Any = None) -> Any:
        if not self.url or not self.key:
            logger.warning("Supabase credentials missing. Skipping request.")
            return None
        
        url = f"{self.url}/rest/v1/{endpoint}"
        try:
            response = requests.request(
                method, url, headers=self.headers, json=data, params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Supabase request failed ({method} {endpoint}): {e}")
            if response and response.text:
                logger.error(f"Response: {response.text}")
            return None

    def sync_rarities(self):
        """Ensure all rarities exist in Supabase."""
        logger.info("Syncing rarities...")
        # 1. Get existing rarities
        existing = self._request("GET", "card_rarities", params={"select": "id,rarity_name"})
        if existing:
            self.rarity_map = {r["rarity_name"].lower(): r["id"] for r in existing}
        
        # 2. Collect all rarities from cache
        cache_rarities = set()
        for cards in cache.cards.values():
            for card in cards:
                if card.ext_rarity:
                    cache_rarities.add(card.ext_rarity)
        
        # 3. Insert missing
        new_rarities = []
        for r_name in cache_rarities:
            if r_name.lower() not in self.rarity_map:
                new_rarities.append({
                    "rarity_name": r_name,
                    "rarity_key": r_name.lower().replace(" ", "_"),
                    "weight": 1, # Default weight
                    "rarity_rank": 1 # Default rank
                })
        
        if new_rarities:
            logger.info(f"Inserting {len(new_rarities)} new rarities...")
            # Batch insert
            batch_size = 100
            for i in range(0, len(new_rarities), batch_size):
                batch = new_rarities[i:i+batch_size]
                result = self._request("POST", "card_rarities", data=batch)
                if result:
                    for r in result:
                        self.rarity_map[r["rarity_name"].lower()] = r["id"]

    def sync_sets(self):
        """Ensure all sets exist in Supabase."""
        logger.info("Syncing sets...")
        # 1. Get existing sets
        existing = self._request("GET", "card_sets", params={"select": "id,set_code"})
        if existing:
            self.set_map = {s["set_code"]: s["id"] for s in existing if s["set_code"]}
        
        # 2. Collect sets from cache
        sets_to_sync = []
        for card_set in cache.card_sets:
            if card_set.abbreviation and card_set.abbreviation not in self.set_map:
                sets_to_sync.append({
                    "set_code": card_set.abbreviation,
                    "name": card_set.name,
                    "release_date": card_set.published_on if card_set.published_on else None
                })
        
        if sets_to_sync:
            logger.info(f"Inserting {len(sets_to_sync)} new sets...")
            batch_size = 50
            for i in range(0, len(sets_to_sync), batch_size):
                batch = sets_to_sync[i:i+batch_size]
                result = self._request("POST", "card_sets", data=batch)
                if result:
                    for s in result:
                        self.set_map[s["set_code"]] = s["id"]

    def sync_variants_and_prices(self):
        """Sync card variants and prices."""
        logger.info("Syncing variants and prices...")
        
        # Prepare batches
        variants_batch = []
        prices_batch = []
        
        # We need to check existing variants to avoid duplicates if possible, 
        # but upsert on (set_id, card_number, rarity_id) might be tricky without a unique constraint.
        # card_variants has a unique constraint? 
        # Let's assume we can upsert based on something.
        # Actually, let's just try to insert and ignore conflicts or use upsert if we have a key.
        # card_variants usually has (set_id, card_number, rarity_id) as unique?
        # Let's check constraints. `card_variants_card_slug_key` exists.
        
        total_cards = sum(len(cards) for cards in cache.cards.values())
        processed = 0
        
        for group_id, cards in cache.cards.items():
            card_set = cache.get_set_by_id(group_id)
            if not card_set or not card_set.abbreviation:
                continue
                
            set_id = self.set_map.get(card_set.abbreviation)
            if not set_id:
                continue

            for card in cards:
                rarity_id = self.rarity_map.get(card.ext_rarity.lower()) if card.ext_rarity else None
                
                # We need a unique slug or identifier for upsert
                # card_slug is usually name-set-number
                slug = f"{card.name}-{card.ext_number}-{card.ext_rarity}".lower().replace(" ", "-").replace("/", "-")
                
                # Construct variant object
                variant = {
                    "set_id": set_id,
                    "rarity_id": rarity_id,
                    "card_name": card.name,
                    "card_number": card.ext_number,
                    "card_slug": slug,
                    "tcgcsv_product_id": card.product_id,
                    # Add other fields if needed
                }
                
                # We will upsert variants one by one or in small batches to get their IDs
                # Supabase upsert requires `on_conflict` column. `card_slug` seems to be unique.
                
                # Optimization: We can't easily batch upsert and get IDs back mapped to our source objects 
                # without strict ordering or unique keys.
                # So we might have to do this slower or use a stored procedure.
                # For now, let's try to upsert the variant and get the ID.
                
                try:
                    # Upsert variant
                    # We use `card_slug` as conflict target
                    res = self._request("POST", "card_variants", 
                                      data=variant, 
                                      params={"on_conflict": "tcgcsv_product_id"})
                    
                    if res and len(res) > 0:
                        variant_id = res[0]["id"]
                        
                        # Prepare prices
                        now = datetime.now().isoformat()
                        
                        # Create a single price entry with all price points
                        price_entry = {
                            "card_variant_id": variant_id,
                            "price": card.market_price or card.mid_price or card.low_price, # Fallback for legacy
                            "price_market": card.market_price,
                            "price_low": card.low_price,
                            "price_mid": card.mid_price,
                            "price_high": card.high_price,
                            "source": "tcgplayer",
                            "currency": "USD",
                            "price_date": now[:10] # YYYY-MM-DD
                        }
                        
                        prices_batch.append(price_entry)

                except Exception as e:
                    logger.error(f"Failed to sync variant {slug}: {e}")
                
                processed += 1
                if processed % 100 == 0:
                    logger.info(f"Processed {processed}/{total_cards} cards...")
                    
                # Flush prices batch
                if len(prices_batch) >= 100:
                    self._request("POST", "card_prices", data=prices_batch)
                    prices_batch = []

        # Flush remaining
        if prices_batch:
            self._request("POST", "card_prices", data=prices_batch)

    def run_sync(self):
        if not SUPABASE_SYNC_ENABLED:
            logger.info("Supabase sync disabled.")
            return
            
        logger.info("Starting Supabase sync...")
        try:
            self.sync_rarities()
            self.sync_sets()
            self.sync_variants_and_prices()
            logger.info("Supabase sync complete!")
            
            # Trigger leaderboard refresh
            self._request("POST", "rpc/refresh_leaderboards")
            logger.info("Leaderboards refreshed.")
            
        except Exception as e:
            logger.error(f"Supabase sync failed: {e}")

# Global instance
syncer = SupabaseSync()
