#!/usr/bin/env python3
"""Test concurrent async API price requests."""

import asyncio
import aiohttp
import json
from datetime import datetime

async def fetch_price(session, card_data):
    """Fetch price for a single card."""
    url = "http://localhost:8081/cards/price"
    
    start_time = datetime.now()
    try:
        async with session.post(url, json=card_data) as response:
            result = await response.json()
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            return {
                "card": card_data,
                "success": result.get("success", False),
                "tcg_price": result.get("data", {}).get("tcg_price"),
                "market_price": result.get("data", {}).get("tcg_market_price"),
                "duration": duration,
                "cached": result.get("is_cached", False)
            }
    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        return {
            "card": card_data,
            "success": False,
            "error": str(e),
            "duration": duration
        }

async def test_concurrent_scraping():
    """Test multiple concurrent price requests."""
    # Test cards
    cards = [
        {"card_number": "BLMM-EN039", "card_rarity": "Ultra Rare"},  # Revelation of Hope
        {"card_number": "BLTR-EN062", "card_rarity": "Ultra Rare"},  # Infernoid Piaty
        {"card_number": "BLAR-EN067", "card_rarity": "Ultra Rare"},  # Kalantosa, Mystical Beast of the Forest
    ]
    
    print(f"\nTesting {len(cards)} concurrent async API requests...")
    print("=" * 70)
    
    async with aiohttp.ClientSession() as session:
        # Run all requests concurrently
        tasks = [fetch_price(session, card) for card in cards]
        results = await asyncio.gather(*tasks)
    
    # Print results
    total_duration = sum(r["duration"] for r in results)
    successful = sum(1 for r in results if r.get("success"))
    
    for i, result in enumerate(results, 1):
        print(f"\n{i}. Card: {result['card']['card_number']} ({result['card']['card_rarity']})")
        print(f"   Success: {result['success']}")
        print(f"   Cached: {result.get('cached', False)}")
        if result.get("success"):
            print(f"   TCG Price: ${result['tcg_price']}")
            print(f"   Market Price: ${result['market_price']}")
        else:
            print(f"   Error: {result.get('error', 'No price found')}")
        print(f"   Duration: {result['duration']:.2f}s")
    
    print("\n" + "=" * 70)
    print(f"Summary: {successful}/{len(cards)} successful")
    print(f"Total time: {total_duration:.2f}s (average: {total_duration/len(cards):.2f}s per request)")
    
    # Test second round to check caching
    print("\n\nTesting second round (should be cached)...")
    print("=" * 70)
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_price(session, cards[0]) for _ in range(3)]  # Same card 3 times
        results = await asyncio.gather(*tasks)
    
    for i, result in enumerate(results, 1):
        print(f"\n{i}. Cached: {result.get('cached', False)}, Duration: {result['duration']:.2f}s")

if __name__ == "__main__":
    asyncio.run(test_concurrent_scraping())
