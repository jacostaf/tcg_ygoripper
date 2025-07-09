#!/usr/bin/env python3
"""
Memory usage demonstration and testing for the modular YGO API.
"""

import sys
import os
import time
import gc

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_memory_management():
    """Test memory management features."""
    from ygoapi.memory_manager import get_memory_manager, get_memory_stats, force_memory_cleanup
    from ygoapi.utils import batch_process_generator, normalize_rarity_for_matching
    
    print("Testing Memory Management Features")
    print("=" * 40)
    
    # Get initial memory stats
    initial_stats = get_memory_stats()
    print(f"Initial memory: {initial_stats['rss_mb']:.1f}MB")
    print(f"Memory limit: {initial_stats['limit_mb']}MB")
    print(f"Usage ratio: {initial_stats['usage_ratio']:.1%}")
    print()
    
    # Test memory-efficient batch processing
    print("Testing batch processing...")
    large_list = list(range(10000))  # Create a moderately large list
    batch_count = 0
    
    for batch in batch_process_generator(large_list, batch_size=1000):
        batch_count += 1
        # Simulate processing
        processed = [x * 2 for x in batch]
        del processed  # Clean up
    
    print(f"Processed {len(large_list)} items in {batch_count} batches")
    
    # Check memory after batch processing
    after_batch_stats = get_memory_stats()
    print(f"Memory after batch processing: {after_batch_stats['rss_mb']:.1f}MB")
    print()
    
    # Test memory cleanup
    print("Testing memory cleanup...")
    # Create some objects to clean up
    large_objects = []
    for i in range(1000):
        large_objects.append(f"Large string data {i} " * 100)
    
    before_cleanup = get_memory_stats()
    print(f"Memory before cleanup: {before_cleanup['rss_mb']:.1f}MB")
    
    # Clear the objects
    large_objects.clear()
    del large_objects
    
    # Force cleanup
    force_memory_cleanup()
    
    after_cleanup = get_memory_stats()
    print(f"Memory after cleanup: {after_cleanup['rss_mb']:.1f}MB")
    print(f"Memory freed: {before_cleanup['rss_mb'] - after_cleanup['rss_mb']:.1f}MB")
    print()
    
    # Test utility functions with memory monitoring
    print("Testing utility functions...")
    test_rarities = [
        "Ultra Rare", "Secret Rare", "Quarter Century Secret Rare",
        "Platinum Secret Rare", "Ghost Rare", "Starlight Rare"
    ]
    
    for rarity in test_rarities:
        variants = normalize_rarity_for_matching(rarity)
        print(f"  {rarity} -> {len(variants)} variants")
    
    final_stats = get_memory_stats()
    print()
    print(f"Final memory: {final_stats['rss_mb']:.1f}MB")
    print(f"Total change: {final_stats['rss_mb'] - initial_stats['rss_mb']:.1f}MB")
    
    # Test memory manager thresholds
    memory_manager = get_memory_manager()
    print()
    print("Memory Manager Configuration:")
    print(f"  Warning threshold: {memory_manager.warning_threshold:.0%}")
    print(f"  Critical threshold: {memory_manager.critical_threshold:.0%}")
    print(f"  Current usage: {final_stats['usage_ratio']:.1%}")
    
    if final_stats['usage_ratio'] >= memory_manager.warning_threshold:
        print("  ⚠️  Memory usage is at warning level")
    elif final_stats['usage_ratio'] >= memory_manager.critical_threshold:
        print("  🚨 Memory usage is at critical level")
    else:
        print("  ✅ Memory usage is normal")
    
    return True

def test_configuration():
    """Test configuration management."""
    from ygoapi.config import (
        get_port, get_debug_mode, get_memory_limit_mb, 
        validate_config, MEM_LIMIT_MB
    )
    
    print("Testing Configuration Management")
    print("=" * 40)
    
    print(f"Port: {get_port()}")
    print(f"Debug mode: {get_debug_mode()}")
    print(f"Memory limit: {get_memory_limit_mb()}MB")
    print(f"Environment MEM_LIMIT: {MEM_LIMIT_MB}MB")
    print(f"Config valid: {validate_config()}")
    
    return True

def test_models():
    """Test Pydantic models."""
    from ygoapi.models import ProcessingStats, MemoryStats, CardPriceModel
    from datetime import datetime
    
    print("Testing Pydantic Models")
    print("=" * 40)
    
    # Test ProcessingStats
    stats = ProcessingStats(
        total_sets=100,
        processed_sets=95,
        failed_sets=5,
        total_cards_processed=50000
    )
    print(f"ProcessingStats: {stats.processed_sets}/{stats.total_sets} sets")
    
    # Test MemoryStats
    memory_stats = MemoryStats(
        rss_mb=128.5,
        vms_mb=256.0,
        percent=12.5,
        limit_mb=512,
        usage_ratio=0.25,
        warning_threshold=0.8,
        critical_threshold=0.9
    )
    print(f"MemoryStats: {memory_stats.rss_mb}MB / {memory_stats.limit_mb}MB")
    
    # Test CardPriceModel (basic validation)
    try:
        price_model = CardPriceModel(
            card_number="LOB-001",
            card_name="Blue-Eyes White Dragon",
            card_rarity="Ultra Rare",
            tcgplayer_price=25.99
        )
        print(f"CardPriceModel: {price_model.card_name} - ${price_model.tcgplayer_price}")
    except Exception as e:
        print(f"CardPriceModel validation: {e}")
    
    return True

def main():
    """Run all tests."""
    print("YGO API Modular Structure - Comprehensive Testing")
    print("=" * 60)
    print()
    
    tests = [
        ("Memory Management", test_memory_management),
        ("Configuration", test_configuration),
        ("Models", test_models)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            print()
        except Exception as e:
            print(f"✗ {test_name} failed: {e}")
            results.append((test_name, False))
            print()
    
    # Summary
    print("Test Summary")
    print("=" * 20)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} {test_name}")
    
    print()
    print(f"Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Modular structure is working perfectly.")
        return 0
    else:
        print("❌ Some tests failed. Check output above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())