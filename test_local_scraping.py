#!/usr/bin/env python3
"""
Test script for local price scraping
"""
import asyncio
import aiohttp
import json
import sys
from datetime import datetime

# Test cards
TEST_CARDS = [
    {"card_number": "BLMM-EN001", "card_name": "", "card_rarity": "Starlight Rare", "art_variant": "", "force_refresh": True},
    {"card_number": "BLMM-EN039", "card_name": "Revelation of Hope", "card_rarity": "Ultra Rare"},
    {"card_number": "BLMM-EN137", "card_name": "Gem-Knight Aquamarine", "card_rarity": "Ultra Rare"}
]

BASE_URL = "http://localhost:8082"

async def test_single_card(session, card_data):
    """Test scraping a single card."""
    start_time = datetime.now()
    card_num = card_data["card_number"]
    
    print(f"[{card_num}] Starting request at {start_time.strftime('%H:%M:%S')}")
    
    try:
        async with session.post(f"{BASE_URL}/cards/price", json=card_data) as response:
            elapsed = (datetime.now() - start_time).total_seconds()
            
            if response.status == 200:
                result = await response.json()
                success = result.get("success", False)
                data = result.get("data", {})
                
                if success and (data.get("tcg_price") or data.get("tcgplayer_price")):
                    price = data.get("tcg_price") or data.get("tcgplayer_price")
                    print(f"[{card_num}] ✅ SUCCESS in {elapsed:.2f}s - Price: ${price}")
                else:
                    error_msg = data.get("error_message", "Unknown error")
                    print(f"[{card_num}] ❌ FAILED in {elapsed:.2f}s - Error: {error_msg}")
                
                return card_num, result
            else:
                print(f"[{card_num}] ❌ HTTP {response.status} in {elapsed:.2f}s")
                return card_num, {"error": f"HTTP {response.status}"}
                
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[{card_num}] ❌ ERROR in {elapsed:.2f}s - {str(e)}")
        return card_num, {"error": str(e)}

async def test_concurrent():
    """Test concurrent price scraping."""
    print("Testing concurrent price scraping...")
    print("=" * 80)
    
    async with aiohttp.ClientSession() as session:
        # Test concurrent requests
        tasks = [test_single_card(session, card) for card in TEST_CARDS]
        results = await asyncio.gather(*tasks)
        
    print("\n" + "=" * 80)
    print("RESULTS:")
    print("=" * 80)
    
    successful = 0
    for card_num, result in results:
        if isinstance(result, dict):
            data = result.get("data", {})
            if result.get("success") and (data.get("tcg_price") or data.get("tcgplayer_price")):
                successful += 1
                price = data.get("tcg_price") or data.get("tcgplayer_price")
                print(f"✅ {card_num}: ${price}")
            else:
                error = data.get("error_message", result.get("error", "Unknown error"))
                print(f"❌ {card_num}: {error}")
    
    print(f"\nSuccessful: {successful}/{len(TEST_CARDS)}")

async def test_single():
    """Test single card scraping."""
    print("Testing single card scraping...")
    print("=" * 80)
    
    async with aiohttp.ClientSession() as session:
        card_num, result = await test_single_card(session, TEST_CARDS[0])
        
    print("\n" + "=" * 80)
    print("RESULT:")
    print("=" * 80)
    
    if isinstance(result, dict):
        print(json.dumps(result, indent=2))

async def main():
    # Check which test to run
    if len(sys.argv) > 1 and sys.argv[1] == "--single":
        await test_single()
    else:
        await test_concurrent()

if __name__ == "__main__":
    asyncio.run(main())
