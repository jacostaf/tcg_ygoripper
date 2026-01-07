import logging
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

# Configure logging
logging.basicConfig(level=logging.INFO)

from supabase_sync import syncer
from tcg_core import cache

if __name__ == "__main__":
    print(f"Cache loaded. Sets: {len(cache.card_sets)}, Cards (groups): {len(cache.cards)}")
    total_cards = sum(len(cards) for cards in cache.cards.values())
    print(f"Total cards: {total_cards}")
    
    # Print sample rarities
    rarities = set()
    sample_count = 0
    for cards in cache.cards.values():
        for card in cards:
            if card.ext_rarity:
                rarities.add(card.ext_rarity)
            if sample_count < 5:
                print(f"Sample card: {card.name}, Rarity: {card.ext_rarity}")
                sample_count += 1
    print(f"Found {len(rarities)} unique rarities in cache: {list(rarities)[:10]}...")
    
    print("Starting manual sync...")
    syncer.run_sync()
    print("Sync complete.")
