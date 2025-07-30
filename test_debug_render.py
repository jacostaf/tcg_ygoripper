#!/usr/bin/env python3
"""
Test script for the debug price extraction endpoint on Render deployment.
This will test both cards CONCURRENTLY to replicate the null price issue.
"""

import requests
import json
from datetime import datetime
import concurrent.futures
import time

# Render deployment URLs
DEBUG_URL = "https://ygopyguy.onrender.com/debug/price-extraction"
PRICE_URL = "https://ygopyguy.onrender.com/cards/price"

# Test cards - one that works and one that fails
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
    }#,
    # {
    #     "card_number": "BLMM-EN001",
    #     "card_name": "", 
    #     "card_rarity": "Starlight Rare",
    #     "art_variant": ""
    # },
    # {
    #     "card_number": "BLMM-EN001",
    #     "card_name": "", 
    #     "card_rarity": "Secret Rare",
    #     "art_variant": ""
    # },
    # {
    #     "card_number": "BLMM-EN129",
    #     "card_name": "", 
    #     "card_rarity": "Ultra Rare",
    #     "art_variant": ""
    # }
]

def test_card_debug(card_data, card_index):
    """Test a single card using the debug endpoint."""
    print(f"\n[Card {card_index}] Starting debug test for {card_data['card_number']} at {datetime.now().strftime('%H:%M:%S')}")
    
    try:
        response = requests.post(
            PRICE_URL,
            json=card_data,
            timeout=600  # 10 minutes
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"\n[Card {card_index}] Results for {card_data['card_number']}:")
            print("-" * 80)
            
            # Extract key info from the API response directly
            # The API returns a 'data' object with the price info
            price_data = data.get('data', {})
            
            print(f"Success: {data.get('success', False)}")
            print(f"TCG Price: ${price_data.get('tcg_price')}")
            print(f"Market Price: ${price_data.get('tcg_market_price')}")
            print(f"URL: {price_data.get('source_url', 'N/A')}")
            
            # Check for null prices
            if price_data.get('tcg_price') is None or price_data.get('tcg_market_price') is None:
                print("\n⚠️  NULL PRICES DETECTED!")
                print("Check Render logs for debug info")
            else:
                print("✅ Prices extracted successfully")
            
            return card_data['card_number'], data
        else:
            print(f"[Card {card_index}] Error: HTTP {response.status_code}")
            return card_data['card_number'], {"error": response.text}
            
    except Exception as e:
        print(f"[Card {card_index}] Error: {e}")
        return card_data['card_number'], {"error": str(e)}

# Test both cards concurrently
print(f"Testing concurrent debug extraction on Render")
print(f"URL: {PRICE_URL}")
print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
print("=" * 80)

start_time = time.time()

# Run both requests concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = []
    for i, card in enumerate(test_cards, 1):
        future = executor.submit(test_card_debug, card, i)
        futures.append(future)
    
    # Collect results
    results = {}
    for future in concurrent.futures.as_completed(futures):
        card_number, result = future.result()
        results[card_number] = result

end_time = time.time()

# Summary
print("\n" + "=" * 80)
print("SUMMARY:")
print("=" * 80)

null_count = 0
success_count = 0

for card_number, data in results.items():
    if "error" in data:
        print(f"❌ {card_number}: ERROR - {data['error']}")
    else:
        # Use the correct response structure
        price_data = data.get('data', {})
        tcg_price = price_data.get('tcg_price')
        market_price = price_data.get('tcg_market_price')
        
        if tcg_price is None or market_price is None:
            print(f"❌ {card_number}: NULL PRICES")
            null_count += 1
        else:
            print(f"✅ {card_number}: ${tcg_price} / ${market_price}")
            success_count += 1

print(f"\nTotal time: {end_time - start_time:.2f}s")
print(f"Successful: {success_count}")
print(f"Null prices: {null_count}")

if null_count > 0:
    print("\n⚠️  NULL PRICE ISSUE DETECTED!")

print("\n" + "=" * 80)
print("To view Render logs:")
print("1. Go to https://dashboard.render.com")
print("2. Navigate to your service")
print("3. Click on 'Logs' tab")
print("4. Look for entries with 'NULL PRICES DETECTED' and related debug info")
