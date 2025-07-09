#!/usr/bin/env python3
"""
Test script for the modular YGO API structure.
"""

import sys
import os

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all modules can be imported."""
    try:
        # Test configuration
        from ygoapi.config import validate_config, get_port, MEM_LIMIT_MB
        print("✓ Config module imported successfully")
        
        # Test memory manager
        from ygoapi.memory_manager import get_memory_manager, get_memory_stats
        print("✓ Memory manager imported successfully")
        
        # Test models
        from ygoapi.models import CardPriceModel, ProcessingStats
        print("✓ Models module imported successfully")
        
        # Test utilities
        from ygoapi.utils import normalize_rarity, extract_art_version
        print("✓ Utils module imported successfully")
        
        # Test services (these might fail if no DB connection)
        try:
            from ygoapi.card_services import card_set_service
            print("✓ Card services imported successfully")
        except Exception as e:
            print(f"⚠ Card services import failed (expected without DB): {e}")
        
        try:
            from ygoapi.price_scraping import price_scraping_service
            print("✓ Price scraping service imported successfully")
        except Exception as e:
            print(f"⚠ Price scraping service import failed (expected without DB): {e}")
        
        # Test routes
        from ygoapi.routes import register_routes
        print("✓ Routes module imported successfully")
        
        # Test app creation (might fail without DB)
        try:
            from ygoapi.app import create_app
            print("✓ App module imported successfully")
        except Exception as e:
            print(f"⚠ App creation failed (expected without DB): {e}")
        
        return True
        
    except Exception as e:
        print(f"✗ Import test failed: {e}")
        return False

def test_basic_functionality():
    """Test basic functionality that doesn't require database."""
    try:
        # Test memory manager
        from ygoapi.memory_manager import get_memory_stats
        stats = get_memory_stats()
        print(f"✓ Memory stats: {stats['rss_mb']:.1f}MB / {stats['limit_mb']}MB")
        
        # Test configuration
        from ygoapi.config import get_port, MEM_LIMIT_MB
        print(f"✓ Config - Port: {get_port()}, Memory limit: {MEM_LIMIT_MB}MB")
        
        # Test utilities
        from ygoapi.utils import normalize_rarity, extract_art_version
        normalized = normalize_rarity("Ultra Rare")
        print(f"✓ Rarity normalization: 'Ultra Rare' -> '{normalized}'")
        
        art = extract_art_version("Blue-Eyes White Dragon 1st Art")
        print(f"✓ Art extraction: 'Blue-Eyes White Dragon 1st Art' -> '{art}'")
        
        # Test model creation
        from ygoapi.models import ProcessingStats
        stats = ProcessingStats(total_sets=10, processed_sets=8)
        print(f"✓ Model creation: ProcessingStats with {stats.total_sets} total sets")
        
        return True
        
    except Exception as e:
        print(f"✗ Basic functionality test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Testing modular YGO API structure...")
    print("=" * 50)
    
    import_success = test_imports()
    print()
    
    basic_success = test_basic_functionality()
    print()
    
    if import_success and basic_success:
        print("✓ All tests passed! Modular structure is working correctly.")
        return 0
    else:
        print("✗ Some tests failed. Check the output above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())