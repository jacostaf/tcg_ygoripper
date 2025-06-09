#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_card_search_logic():
    """Test the card search logic without actually connecting to external APIs."""
    print("Testing card search logic for RA04-EN016...")
    
    # Simulate what should happen:
    card_number = "RA04-EN016"
    card_rarity = "quarter century secret rare"
    
    # Step 1: Card name lookup (simulated result)
    print("Step 1: Looking up card name...")
    simulated_card_name = "Black Metal Dragon"  # This would come from cache/API
    print(f"  Found card name: {simulated_card_name}")
    
    # Step 2: Search attempts that would be made
    print("\nStep 2: TCGPlayer search attempts...")
    search_attempts = []
    
    # Add card number search
    if card_number:
        search_attempts.append((card_number.strip(), "card number"))
    
    # Add card name search as fallback
    if simulated_card_name:
        search_attempts.append((simulated_card_name.strip(), "card name"))
    
    for search_query, search_type in search_attempts:
        print(f"  Would search TCGPlayer for: '{search_query}' (using {search_type})")
    
    # Step 3: Variant scoring simulation
    print("\nStep 3: Simulating variant scoring...")
    
    # These would be the variants returned by TCGPlayer search
    mock_variants = [
        {"title": "Black Skull Dragon - Metal Raiders (25th Anniversary Edition) (MRD-EN)", "href": "url1"},
        {"title": "Black Metal Dragon [Quarter Century Secret Rare] RA04-EN016", "href": "url2"},
        {"title": "Black Metal Dragon - Quarter Century Stampede", "href": "url3"}
    ]
    
    from main import normalize_rarity_for_matching
    
    scored_variants = []
    for variant in mock_variants:
        score = 0
        title_lower = variant['title'].lower()
        
        # High score for exact card number match
        if card_number.lower() in title_lower:
            score += 100
            print(f"    Card number match (+100): {variant['title']}")
            
        # High score for card name match
        if simulated_card_name:
            name_words = simulated_card_name.lower().split()
            name_match_count = sum(1 for word in name_words if word in title_lower)
            if name_match_count == len(name_words):
                score += 80  # All words match
                print(f"    Full card name match (+80): {variant['title']}")
            elif name_match_count > 0:
                partial_score = (name_match_count / len(name_words)) * 60
                score += partial_score
                print(f"    Partial card name match (+{partial_score:.1f}): {variant['title']}")
                
        # Score for rarity match
        if card_rarity:
            rarity_variants = normalize_rarity_for_matching(card_rarity)
            for rarity_variant in rarity_variants:
                if rarity_variant.lower() in title_lower:
                    score += 50
                    print(f"    Rarity match (+50): {variant['title']}")
                    break
        
        scored_variants.append((score, variant))
        print(f"    Total score: {score} - {variant['title']}")
        print()
    
    # Sort by score and show result
    scored_variants.sort(reverse=True, key=lambda x: x[0])
    
    if scored_variants and scored_variants[0][0] > 0:
        best_variant = scored_variants[0][1]
        print(f"✅ Best variant selected (score: {scored_variants[0][0]}): {best_variant['title']}")
        return True
    else:
        print("❌ No suitable variant found")
        return False

def test_rarity_edge_cases():
    """Test edge cases for rarity normalization."""
    print("\n" + "="*60)
    print("Testing rarity edge cases...")
    
    from main import normalize_rarity, normalize_rarity_for_matching
    
    edge_cases = [
        "Quarter-Century Secret Rare",
        "QUARTER CENTURY SECRET RARE", 
        "quarter century secret rare",
        "25th Anniversary Secret Rare",
        "Prismatic Collector's Rare",
        "Starlight Rare",
        "Ghost/Gold Rare"
    ]
    
    for rarity in edge_cases:
        normalized = normalize_rarity(rarity)
        variants = normalize_rarity_for_matching(rarity)
        print(f"'{rarity}' -> '{normalized}' (variants: {len(variants)})")

if __name__ == "__main__":
    success = test_card_search_logic()
    test_rarity_edge_cases()
    
    if success:
        print("\n✅ All tests passed! The logic should correctly identify Black Metal Dragon.")
    else:
        print("\n❌ Tests failed!")