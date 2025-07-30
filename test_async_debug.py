#!/usr/bin/env python3
"""
Debug test for async price scraping
"""

import asyncio
import logging
import json
from ygoapi.async_price_scraping import get_async_price_service

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_scraping():
    """Test scraping a specific card"""
    service = get_async_price_service()
    
    # Test card that should have results
    card_number = "BLMM-EN039"
    card_name = "Revelation of Hope"
    card_rarity = "Ultra Rare"
    
    print(f"\nTesting async scraping for {card_number} - {card_name} ({card_rarity})")
    print("=" * 80)
    
    result = await service.scrape_card_price(
        card_number=card_number,
        card_name=card_name,
        card_rarity=card_rarity,
        force_refresh=True  # Force fresh scrape
    )
    
    # Convert datetime objects to strings for JSON serialization
    def serialize_result(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: serialize_result(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [serialize_result(item) for item in obj]
        return obj
    
    print("\nResult:")
    print(json.dumps(serialize_result(result), indent=2))
    
    # Also test the direct scraping method
    print("\n\nTesting direct TCGPlayer scraping...")
    print("=" * 80)
    
    scrape_result = await service.scrape_price_from_tcgplayer(
        card_name=card_name,
        card_rarity=card_rarity,
        card_number=card_number
    )
    
    print("\nDirect scrape result:")
    print(json.dumps(scrape_result, indent=2))

if __name__ == "__main__":
    asyncio.run(test_scraping())
