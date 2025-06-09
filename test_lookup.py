#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import lookup_card_name_from_ygo_api, normalize_rarity, normalize_rarity_for_matching

def test_card_lookup():
    """Test the card name lookup functionality."""
    print("Testing card name lookup for RA04-EN016...")
    
    # Test YGO API lookup (this should work even without MongoDB)
    card_name = lookup_card_name_from_ygo_api("RA04-EN016")
    print(f"Result: {card_name}")
    
    if card_name:
        print(f"✅ Successfully found card name: {card_name}")
    else:
        print("❌ Could not find card name")

def test_rarity_normalization():
    """Test rarity normalization functions."""
    print("\nTesting rarity normalization...")
    
    test_rarities = [
        "quarter century secret rare",
        "Quarter Century Secret Rare", 
        "QUARTER-CENTURY SECRET RARE",
        "secret rare",
        "ultra rare",
        "starlight rare",
        "collector's rare",
        "prismatic secret rare"
    ]
    
    for rarity in test_rarities:
        normalized = normalize_rarity(rarity)
        variants = normalize_rarity_for_matching(rarity)
        print(f"Original: '{rarity}' -> Normalized: '{normalized}'")
        print(f"  Variants: {variants[:3]}...")  # Show first 3 variants
        print()

if __name__ == "__main__":
    test_card_lookup()
    test_rarity_normalization()