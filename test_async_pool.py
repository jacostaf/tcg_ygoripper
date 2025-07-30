#!/usr/bin/env python3
"""
Test script for the async browser pool implementation.
Tests concurrent price scraping with the new async architecture.
"""

import asyncio
import aiohttp
import json
from datetime import datetime
import time


# Test configuration
API_URL = "http://localhost:8081/cards/price"  # Adjust port as needed
BROWSER_STATS_URL = "http://localhost:8081/browser/stats"

# Test cards
test_cards = [
    {
        "card_number": "BLMM-EN039",
        "card_name": "Revelation of Hope",
        "card_rarity": "Ultra Rare",
        "art_variant": ""
    },
    {
        "card_number": "BLMM-EN137",
        "card_name": "Gem-Knight Aquamarine", 
        "card_rarity": "Ultra Rare",
        "art_variant": ""
    },
    {
        "card_number": "BLMM-EN001",
        "card_name": "Elemental HERO Neos", 
        "card_rarity": "Secret Rare",
        "art_variant": ""
    }
]


async def get_browser_stats(session):
    """Get browser pool statistics."""
    try:
        async with session.get(BROWSER_STATS_URL) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('stats', {})
            else:
                print(f"Failed to get browser stats: {response.status}")
                return {}
    except Exception as e:
        print(f"Error getting browser stats: {e}")
        return {}


async def scrape_card_price(session, card_data, card_index):
    """Scrape a single card price asynchronously."""
    print(f"\n[Card {card_index}] Starting async scrape for {card_data['card_number']} at {datetime.now().strftime('%H:%M:%S')}")
    
    try:
        start_time = time.time()
        
        async with session.post(API_URL, json=card_data, timeout=aiohttp.ClientTimeout(total=300)) as response:
            data = await response.json()
            
            end_time = time.time()
            duration = end_time - start_time
            
            print(f"\n[Card {card_index}] Results for {card_data['card_number']} (took {duration:.2f}s):")
            print("-" * 80)
            
            if response.status == 200:
                price_data = data.get('data', {})
                
                print(f"Success: {data.get('success', False)}")
                print(f"TCG Price: ${price_data.get('tcg_price')}")
                print(f"Market Price: ${price_data.get('tcg_market_price')}")
                print(f"Cached: {data.get('cached', False)}")
                print(f"URL: {price_data.get('source_url', 'N/A')}")
                
                # Check for null prices
                if price_data.get('tcg_price') is None or price_data.get('tcg_market_price') is None:
                    print("\n⚠️  NULL PRICES DETECTED!")
                else:
                    print("✅ Prices extracted successfully")
                
                return card_data['card_number'], data, duration
            else:
                print(f"[Card {card_index}] Error: HTTP {response.status}")
                return card_data['card_number'], {"error": await response.text()}, duration
                
    except asyncio.TimeoutError:
        print(f"[Card {card_index}] Timeout after 5 minutes")
        return card_data['card_number'], {"error": "Timeout"}, 300.0
    except Exception as e:
        print(f"[Card {card_index}] Error: {e}")
        return card_data['card_number'], {"error": str(e)}, 0.0


async def main():
    """Run concurrent price scraping tests."""
    print(f"Testing Async Browser Pool Implementation")
    print(f"API URL: {API_URL}")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)
    
    async with aiohttp.ClientSession() as session:
        # Get initial browser stats
        initial_stats = await get_browser_stats(session)
        print(f"\nInitial browser pool stats: {initial_stats}")
        
        # Run all requests concurrently
        start_time = time.time()
        
        tasks = []
        for i, card in enumerate(test_cards, 1):
            task = scrape_card_price(session, card, i)
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_duration = end_time - start_time
        
        # Get final browser stats
        final_stats = await get_browser_stats(session)
        print(f"\nFinal browser pool stats: {final_stats}")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY:")
        print("=" * 80)
        
        null_count = 0
        success_count = 0
        total_scrape_time = 0
        
        for card_number, data, duration in results:
            total_scrape_time += duration
            
            if "error" in data:
                print(f"❌ {card_number}: ERROR - {data['error']}")
            else:
                price_data = data.get('data', {})
                tcg_price = price_data.get('tcg_price')
                market_price = price_data.get('tcg_market_price')
                cached = data.get('cached', False)
                
                if tcg_price is None or market_price is None:
                    print(f"❌ {card_number}: NULL PRICES (cached: {cached})")
                    null_count += 1
                else:
                    print(f"✅ {card_number}: ${tcg_price} / ${market_price} (cached: {cached}, {duration:.2f}s)")
                    success_count += 1
        
        print(f"\nTotal wall time: {total_duration:.2f}s")
        print(f"Total scraping time: {total_scrape_time:.2f}s")
        print(f"Concurrent speedup: {total_scrape_time / total_duration:.2f}x")
        print(f"Successful: {success_count}")
        print(f"Null prices: {null_count}")
        
        if null_count > 0:
            print("\n⚠️  NULL PRICE ISSUE DETECTED!")
        
        print("\n" + "=" * 80)
        print("Browser Pool Benefits:")
        print("- Browsers are reused across requests")
        print("- No startup overhead after initial pool creation")
        print("- Better resource utilization")
        print("- True concurrent scraping with async/await")


if __name__ == "__main__":
    asyncio.run(main())
