import os
import logging
import re
import requests
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from tcgcsv_config import (
    SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_SYNC_ENABLED
)
from tcg_core import cache, Card, CardSet, get_effective_set_code
from ygoapi.utils import extract_art_version

logger = logging.getLogger(__name__)

# Global sync progress state (thread-safe)
sync_progress = {
    "status": "idle",  # idle, running, complete, error
    "phase": "",
    "current": 0,
    "total": 0,
    "message": "",
    "started_at": None,
    "completed_at": None,
    "stats": {}
}
_progress_lock = threading.Lock()

def update_progress(status=None, phase=None, current=None, total=None, message=None, stats=None, started_at=None, completed_at=None):
    """Thread-safe progress update."""
    with _progress_lock:
        if status is not None:
            sync_progress["status"] = status
        if phase is not None:
            sync_progress["phase"] = phase
        if current is not None:
            sync_progress["current"] = current
        if total is not None:
            sync_progress["total"] = total
        if message is not None:
            sync_progress["message"] = message
        if stats is not None:
            sync_progress["stats"] = stats
        if started_at is not None:
            sync_progress["started_at"] = started_at
        if completed_at is not None:
            sync_progress["completed_at"] = completed_at

def get_progress():
    """Thread-safe progress read."""
    with _progress_lock:
        return dict(sync_progress)


class SupabaseSync:
    def __init__(self):
        self.url = SUPABASE_URL
        self.key = SUPABASE_SERVICE_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.rarity_map = {}
        self.set_map = {}
        self.variant_map = {}

    def _request(self, method: str, endpoint: str, data: Any = None, params: Any = None, upsert: bool = False) -> Any:
        if not self.url or not self.key:
            logger.warning("Supabase credentials missing. Skipping request.")
            return None

        url = f"{self.url}/rest/v1/{endpoint}"
        headers = self.headers.copy()

        if upsert:
            headers["Prefer"] = "return=representation,resolution=merge-duplicates"

        response = None
        try:
            response = requests.request(
                method, url, headers=headers, json=data, params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Supabase request failed ({method} {endpoint}): {e}")
            if response is not None and response.text:
                logger.error(f"Response: {response.text[:500]}")
            return None

    def sync_rarities(self):
        """Ensure all rarities exist in Supabase with intelligent defaults."""
        update_progress(phase="rarities", message="Syncing rarities...")
        logger.info("Syncing rarities...")

        # Fetch existing rarities
        existing = self._request("GET", "card_rarities", params={"select": "id,rarity_name"})
        if existing:
            self.rarity_map = {r["rarity_name"].lower(): r["id"] for r in existing}

        # Collect all rarities from cache
        cache_rarities = set()
        for cards in cache.cards.values():
            for card in cards:
                if card.ext_rarity:
                    cache_rarities.add(card.ext_rarity)

        # Process new rarities using RPC with intelligent defaults
        new_rarities = []
        review_needed = []
        for r_name in cache_rarities:
            if r_name.lower() not in self.rarity_map:
                # Call RPC function for intelligent weight assignment
                result = self._request(
                    "POST",
                    "rpc/upsert_rarity_with_defaults",
                    data={"p_rarity_name": r_name, "p_source": "tcgcsv"}
                )

                if result and len(result) > 0:
                    rarity_data = result[0]
                    self.rarity_map[r_name.lower()] = rarity_data["id"]

                    if rarity_data.get("is_new"):
                        new_rarities.append({
                            "name": rarity_data["rarity_name"],
                            "weight": float(rarity_data["weight"]),
                            "rank": rarity_data["rarity_rank"],
                            "needs_review": rarity_data["needs_review"]
                        })
                        logger.info(
                            f"Auto-discovered rarity: {rarity_data['rarity_name']} "
                            f"(weight={rarity_data['weight']}, rank={rarity_data['rarity_rank']}, "
                            f"review={rarity_data['needs_review']})"
                        )
                        if rarity_data["needs_review"]:
                            review_needed.append(rarity_data["rarity_name"])

        if new_rarities:
            logger.info(f"Discovered {len(new_rarities)} new rarities with intelligent defaults")
        if review_needed:
            logger.warning(f"{len(review_needed)} rarities flagged for admin review: {review_needed}")

    def sync_sets(self):
        """Ensure all sets exist in Supabase."""
        update_progress(phase="sets", message="Syncing sets...")
        logger.info("Syncing sets...")

        existing = self._request("GET", "card_sets", params={"select": "id,set_code"})
        if existing:
            self.set_map = {s["set_code"]: s["id"] for s in existing if s["set_code"]}

        sets_by_code = {}
        for card_set in cache.card_sets:
            # Use get_effective_set_code() to resolve set codes for ALL sets
            # including those without TCGcsv abbreviations (uses YGOProDeck fallback)
            set_code = get_effective_set_code(card_set)
            if set_code and set_code not in sets_by_code:
                sets_by_code[set_code] = {
                    "set_code": set_code,
                    "name": card_set.name,
                    "release_date": card_set.published_on if card_set.published_on else None
                }
        sets_to_sync = list(sets_by_code.values())

        if sets_to_sync:
            logger.info(f"Upserting {len(sets_to_sync)} unique sets...")
            batch_size = 100
            for i in range(0, len(sets_to_sync), batch_size):
                batch = sets_to_sync[i:i+batch_size]
                result = self._request("POST", "card_sets", data=batch,
                                       params={"on_conflict": "set_code"}, upsert=True)
                if result:
                    for s in result:
                        self.set_map[s["set_code"]] = s["id"]

    def _build_slug(self, card, card_set):
        """Build canonical slug for a card variant."""
        art_version = extract_art_version(card.name)

        # Clean card name - remove rarity suffix in parentheses like "(Quarter Century Secret Rare)"
        clean_name = re.sub(r'\s*\([^)]*(?:rare|common|secret|ultra|super|prismatic|starlight|collector)[^)]*\)\s*$', '', card.name, flags=re.IGNORECASE)

        # Convert to slug format
        name_part = clean_name.lower().replace(" ", "-").replace("/", "-").replace("(", "").replace(")", "")
        # Remove art version patterns from name
        name_part = re.sub(r'-*\d+(st|nd|rd|th)?-*art-*', '', name_part, flags=re.IGNORECASE).strip('-')

        set_code = get_effective_set_code(card_set).lower()
        rarity_part = card.ext_rarity.lower().replace(" ", "-") if card.ext_rarity else ""

        # Handle card number - may already contain set code like "SUDA-EN050"
        if card.ext_number:
            number_part = card.ext_number.lower()
            # If number starts with set code, don't duplicate it
            if set_code and number_part.startswith(set_code + "-"):
                # Number already has set code, use full number as combined set+number
                slug_parts = [name_part, number_part, rarity_part]
            else:
                # Number doesn't have set code, add both
                slug_parts = [name_part, set_code, number_part, rarity_part]
        else:
            slug_parts = [name_part, set_code, rarity_part]

        # Only add numeric art versions (not rarity names accidentally captured)
        if art_version and art_version.isdigit():
            slug_parts.append(f"art-{art_version}")

        return "-".join(filter(None, slug_parts))

    def _fetch_all_variants(self):
        """Fetch ALL existing variants with pagination."""
        update_progress(phase="fetching", message="Fetching existing variants...")
        all_variants = []
        offset = 0
        limit = 1000

        while True:
            batch = self._request("GET", "card_variants",
                                 params={
                                     "select": "id,card_slug,tcgcsv_product_id",
                                     "offset": offset,
                                     "limit": limit,
                                     "order": "id"
                                 })
            if not batch:
                break

            all_variants.extend(batch)
            update_progress(message=f"Fetched {len(all_variants)} variants...")
            logger.info(f"Fetched {len(all_variants)} variants so far...")

            if len(batch) < limit:
                break

            offset += limit

        return all_variants

    def _process_single_variant(self, card, card_set, set_id, rarity_id, slug, existing_by_product_id, existing_by_slug):
        """Process a single variant - returns (variant_id, action, price_entry)."""
        variant_id = None
        action = None  # 'updated', 'inserted', 'merged', 'skipped'

        try:
            existing_by_pid = existing_by_product_id.get(card.product_id) if card.product_id else None
            existing_by_sl = existing_by_slug.get(slug)

            if existing_by_pid and existing_by_sl:
                if existing_by_pid["id"] == existing_by_sl["id"]:
                    res = self._request("PATCH", "card_variants",
                                      data={"set_id": set_id, "rarity_id": rarity_id,
                                            "card_name": card.name, "card_number": card.ext_number},
                                      params={"id": f"eq.{existing_by_pid['id']}"})
                    if res and len(res) > 0:
                        variant_id = res[0]["id"]
                        action = "updated"
                else:
                    old_id = existing_by_pid["id"]
                    new_id = existing_by_sl["id"]
                    self._request("DELETE", "card_variants", params={"id": f"eq.{old_id}"})
                    res = self._request("PATCH", "card_variants",
                                      data={"set_id": set_id, "rarity_id": rarity_id,
                                            "card_name": card.name, "card_number": card.ext_number,
                                            "tcgcsv_product_id": card.product_id},
                                      params={"id": f"eq.{new_id}"})
                    if res and len(res) > 0:
                        variant_id = res[0]["id"]
                        action = "merged"

            elif existing_by_pid:
                res = self._request("PATCH", "card_variants",
                                  data={"set_id": set_id, "rarity_id": rarity_id,
                                        "card_name": card.name, "card_number": card.ext_number,
                                        "card_slug": slug},
                                  params={"id": f"eq.{existing_by_pid['id']}"})
                if res and len(res) > 0:
                    variant_id = res[0]["id"]
                    action = "updated"

            elif existing_by_sl:
                res = self._request("PATCH", "card_variants",
                                  data={"set_id": set_id, "rarity_id": rarity_id,
                                        "card_name": card.name, "card_number": card.ext_number,
                                        "tcgcsv_product_id": card.product_id},
                                  params={"id": f"eq.{existing_by_sl['id']}"})
                if res and len(res) > 0:
                    variant_id = res[0]["id"]
                    action = "updated"

            else:
                res = self._request("POST", "card_variants",
                                  data={"set_id": set_id, "rarity_id": rarity_id,
                                        "card_name": card.name, "card_number": card.ext_number,
                                        "card_slug": slug, "tcgcsv_product_id": card.product_id})
                if res and len(res) > 0:
                    variant_id = res[0]["id"]
                    action = "inserted"

            # Build price entry with ALL keys (required for batch consistency)
            price_entry = None
            if variant_id:
                now = datetime.now().isoformat()[:10]
                base_price = card.market_price or card.mid_price or card.low_price or 0
                price_entry = {
                    "card_variant_id": variant_id,
                    "price": base_price,
                    "price_market": card.market_price,  # Can be None
                    "price_low": card.low_price,        # Can be None
                    "price_mid": card.mid_price,        # Can be None
                    "price_high": card.high_price,      # Can be None
                    "source": "tcgplayer",
                    "currency": "USD",
                    "price_date": now
                }

            return variant_id, action, price_entry

        except Exception as e:
            logger.error(f"Failed to sync variant {slug}: {e}")
            return None, "error", None

    def sync_variants_and_prices(self):
        """Sync card variants and prices with parallel processing."""
        logger.info("Syncing variants and prices...")
        update_progress(phase="variants", current=0)

        # Fetch existing variants
        existing = self._fetch_all_variants()
        existing_by_product_id = {}
        existing_by_slug = {}
        if existing:
            for v in existing:
                if v.get("tcgcsv_product_id"):
                    existing_by_product_id[v["tcgcsv_product_id"]] = v
                if v.get("card_slug"):
                    existing_by_slug[v["card_slug"]] = v
            logger.info(f"Found {len(existing_by_product_id)} variants with product IDs, {len(existing_by_slug)} total")

        # Prepare all cards to process
        cards_to_process = []
        for group_id, cards in cache.cards.items():
            card_set = cache.get_set_by_id(group_id)
            if not card_set:
                continue
            # Use get_effective_set_code() to resolve set codes for ALL sets
            set_code = get_effective_set_code(card_set)
            set_id = self.set_map.get(set_code)
            if not set_id:
                logger.debug(f"Skipping cards for set '{card_set.name}' - no set_id found for code '{set_code}'")
                continue

            for card in cards:
                rarity_id = self.rarity_map.get(card.ext_rarity.lower()) if card.ext_rarity else None
                if rarity_id is None:
                    continue
                slug = self._build_slug(card, card_set)
                cards_to_process.append((card, card_set, set_id, rarity_id, slug))

        total_cards = len(cards_to_process)
        update_progress(total=total_cards, message=f"Processing {total_cards} cards...")
        logger.info(f"Processing {total_cards} cards with parallel execution...")

        # Process with parallel threads
        prices_batch = []
        stats = {"updated": 0, "inserted": 0, "merged": 0, "skipped": 0, "errors": 0}
        processed = 0
        batch_size = 200  # Price batch size

        # Use ThreadPoolExecutor for parallel variant processing
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []

            for card, card_set, set_id, rarity_id, slug in cards_to_process:
                future = executor.submit(
                    self._process_single_variant,
                    card, card_set, set_id, rarity_id, slug,
                    existing_by_product_id, existing_by_slug
                )
                futures.append(future)

            for future in as_completed(futures):
                variant_id, action, price_entry = future.result()
                processed += 1

                if action == "updated":
                    stats["updated"] += 1
                elif action == "inserted":
                    stats["inserted"] += 1
                elif action == "merged":
                    stats["merged"] += 1
                elif action == "error":
                    stats["errors"] += 1
                else:
                    stats["skipped"] += 1

                if price_entry:
                    prices_batch.append(price_entry)

                # Update progress every 100 cards
                if processed % 100 == 0:
                    update_progress(
                        current=processed,
                        message=f"Processed {processed}/{total_cards} cards",
                        stats=stats
                    )
                    logger.info(f"Processed {processed}/{total_cards} (u={stats['updated']}, i={stats['inserted']}, m={stats['merged']})")

                # Flush prices batch
                if len(prices_batch) >= batch_size:
                    # Deduplicate by (card_variant_id, price_date, source) to avoid "cannot affect row a second time"
                    deduped = {(p["card_variant_id"], p["price_date"], p["source"]): p for p in prices_batch}
                    self._request("POST", "card_prices", data=list(deduped.values()),
                                 params={"on_conflict": "card_variant_id,price_date,source"},
                                 upsert=True)
                    prices_batch = []

        # Flush remaining prices
        if prices_batch:
            # Deduplicate by (card_variant_id, price_date, source)
            deduped = {(p["card_variant_id"], p["price_date"], p["source"]): p for p in prices_batch}
            self._request("POST", "card_prices", data=list(deduped.values()),
                         params={"on_conflict": "card_variant_id,price_date,source"},
                         upsert=True)

        update_progress(current=processed, stats=stats, message="Variants sync complete")
        logger.info(f"Variants sync complete: {stats}")

    def run_sync(self):
        if not SUPABASE_SYNC_ENABLED:
            logger.info("Supabase sync disabled.")
            update_progress(status="error", message="Supabase sync disabled")
            return

        update_progress(
            status="running",
            phase="starting",
            current=0,
            total=0,
            message="Starting sync...",
            started_at=datetime.now().isoformat(),
            completed_at=None,
            stats={}
        )

        logger.info("Starting Supabase sync...")
        try:
            self.sync_rarities()
            self.sync_sets()
            self.sync_variants_and_prices()

            # Trigger leaderboard refresh
            update_progress(phase="leaderboards", message="Refreshing leaderboards...")
            refresh_result = self._request("POST", "rpc/refresh_leaderboards", data={
                "p_limit": 100,
                "p_source": "sync",
                "p_include_snapshots": True
            })
            logger.info(f"Leaderboards refreshed. Snapshots inserted: {refresh_result}")

            update_progress(
                status="complete",
                phase="done",
                message="Sync complete!",
                completed_at=datetime.now().isoformat()
            )
            logger.info("Supabase sync complete!")

        except Exception as e:
            logger.error(f"Supabase sync failed: {e}")
            update_progress(
                status="error",
                message=f"Sync failed: {str(e)}",
                completed_at=datetime.now().isoformat()
            )

# Global instance
syncer = SupabaseSync()
