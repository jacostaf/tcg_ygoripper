"""
Test fixtures for comprehensive price scraping test coverage.

Provides realistic mock data, database mocks, and utilities for testing
all aspects of the PriceScrapingService including art variant handling,
rarity validation, cache operations, and TCGPlayer scraping logic.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


@pytest.fixture
def mock_price_cache_collection():
    """Mock price cache collection with realistic behavior."""
    mock_collection = MagicMock()
    
    # Default empty responses
    mock_collection.find.return_value = []
    mock_collection.find_one.return_value = None
    mock_collection.count_documents.return_value = 0
    mock_collection.distinct.return_value = []
    mock_collection.create_index.return_value = "test_index"
    mock_collection.list_indexes.return_value = []
    
    # Mock successful operations
    mock_result = MagicMock()
    mock_result.upserted_id = "test_id"
    mock_result.modified_count = 1
    mock_collection.replace_one.return_value = mock_result
    
    return mock_collection


@pytest.fixture
def mock_card_variants_collection():
    """Mock card variants collection with realistic card data."""
    mock_collection = MagicMock()
    
    # Default responses
    mock_collection.find.return_value = []
    mock_collection.find_one.return_value = None
    
    return mock_collection


@pytest.fixture
def sample_card_variants_data():
    """Sample card variants data for database mocking."""
    return [
        {
            "_id": "test_id_1",
            "card_name": "Blue-Eyes White Dragon",
            "set_code": "LOB-001",
            "set_name": "Legend of Blue Eyes White Dragon",
            "set_rarity": "Ultra Rare",
        },
        {
            "_id": "test_id_2", 
            "card_name": "Blue-Eyes White Dragon",
            "set_code": "SDK-001",
            "set_name": "Starter Deck: Kaiba",
            "set_rarity": "Common",
        },
        {
            "_id": "test_id_3",
            "card_name": "Dark Magician",
            "set_code": "LOB-005",
            "set_name": "Legend of Blue Eyes White Dragon", 
            "set_rarity": "Secret Rare",
        },
        {
            "_id": "test_id_4",
            "card_name": "Black Luster Soldier",
            "set_code": "BPT-005",
            "set_name": "Black Power Tournament",
            "set_rarity": "Ultimate Rare",
        },
        {
            "_id": "test_id_5",
            "card_name": "Black Luster Soldier",
            "set_code": "25AP-001", 
            "set_name": "25th Anniversary Pack",
            "set_rarity": "Prismatic Ultimate Rare",
        },
    ]


@pytest.fixture
def sample_cached_price_data():
    """Sample cached price data for testing cache operations."""
    now = datetime.now(timezone.utc)
    
    return [
        {
            "_id": "cache_id_1",
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "ultra rare",
            "art_variant": None,
            "tcgplayer_price": 25.99,
            "tcgplayer_market_price": 28.50,
            "tcgplayer_url": "https://tcgplayer.com/product/test1",
            "last_price_updt": now,
            "created_at": now,
            "source": "tcgplayer",
        },
        {
            "_id": "cache_id_2",
            "card_number": "LOB-005", 
            "card_name": "Dark Magician",
            "card_rarity": "secret rare",
            "art_variant": "7",
            "tcgplayer_price": 45.00,
            "tcgplayer_market_price": 50.00,
            "tcgplayer_url": "https://tcgplayer.com/product/test2",
            "last_price_updt": now - timedelta(days=2),  # Stale data
            "created_at": now - timedelta(days=2),
            "source": "tcgplayer",
        },
        {
            "_id": "cache_id_3",
            "card_number": "BPT-005",
            "card_name": "Black Luster Soldier", 
            "card_rarity": "ultimate rare",
            "art_variant": "arkana",
            "tcgplayer_price": 120.00,
            "tcgplayer_market_price": 135.00,
            "tcgplayer_url": "https://tcgplayer.com/product/test3",
            "last_price_updt": now,
            "created_at": now,
            "source": "tcgplayer",
        },
    ]


@pytest.fixture
def tcgplayer_mock_variants():
    """Mock TCGPlayer search result variants for testing variant selection."""
    return [
        {
            "url": "https://www.tcgplayer.com/product/12345/test-card-1",
            "title": "Blue-Eyes White Dragon [LOB-001] Ultra Rare",
            "card_name": "Blue-Eyes White Dragon",
            "set_name": "Legend of Blue Eyes White Dragon",
            "rarity": "Ultra Rare",
            "card_number": "LOB-001",
        },
        {
            "url": "https://www.tcgplayer.com/product/12346/test-card-2", 
            "title": "Blue-Eyes White Dragon [SDK-001] Common",
            "card_name": "Blue-Eyes White Dragon",
            "set_name": "Starter Deck: Kaiba",
            "rarity": "Common",
            "card_number": "SDK-001",
        },
        {
            "url": "https://www.tcgplayer.com/product/12347/test-card-3",
            "title": "Dark Magician [LOB-005] 7th Art Secret Rare",
            "card_name": "Dark Magician",
            "set_name": "Legend of Blue Eyes White Dragon",
            "rarity": "Secret Rare", 
            "card_number": "LOB-005",
        },
        {
            "url": "https://www.tcgplayer.com/product/12348/test-card-4",
            "title": "Black Luster Soldier [25AP-001] Quarter Century Secret Rare",
            "card_name": "Black Luster Soldier",
            "set_name": "25th Anniversary Pack",
            "rarity": "Quarter Century Secret Rare",
            "card_number": "25AP-001",
        },
        {
            "url": "https://www.tcgplayer.com/product/12349/test-card-5",
            "title": "Black Luster Soldier [BPT-005] Arkana Prismatic Ultimate Rare",
            "card_name": "Black Luster Soldier", 
            "set_name": "Black Power Tournament",
            "rarity": "Prismatic Ultimate Rare",
            "card_number": "BPT-005",
        },
    ]


@pytest.fixture 
def tcgplayer_mock_price_data():
    """Mock TCGPlayer price extraction data."""
    return {
        "tcg_price": 25.99,
        "tcg_market_price": 28.50,
        "debug_info": ["Found prices in table rows"],
    }


@pytest.fixture
def mock_playwright_page():
    """Mock Playwright page with realistic behavior."""
    mock_page = AsyncMock()
    
    # Mock basic page operations
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.url = "https://www.tcgplayer.com/product/12345/test-card"
    
    # Mock context and browser for cleanup
    mock_context = AsyncMock()
    mock_browser = AsyncMock()
    mock_page.context = mock_context
    mock_context.new_page.return_value = mock_page
    
    return mock_page


@pytest.fixture
def mock_playwright_browser():
    """Mock Playwright browser with context management."""
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    
    # Set up the chain: browser -> context -> page
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
    mock_page.context = mock_context
    
    # Mock page operations
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.url = "https://www.tcgplayer.com/test"
    
    return mock_browser


@pytest.fixture
def mock_playwright():
    """Mock entire Playwright async context manager."""
    
    async def mock_playwright_context():
        mock_p = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        # Set up the chain
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        
        # Mock page operations
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        mock_page.url = "https://www.tcgplayer.com/test"
        
        # Mock cleanup
        mock_browser.close = AsyncMock()
        
        return mock_p
    
    return mock_playwright_context


@pytest.fixture
def art_variant_test_cases():
    """Test cases for art variant normalization and alternative generation."""
    return [
        # Numbered variants
        {"input": "1", "normalized": "1", "alternatives": ["1", "1st", "one", "oneth"]},
        {"input": "2nd", "normalized": "2", "alternatives": ["2", "2nd", "two", "twoth"]},
        {"input": "7th", "normalized": "7", "alternatives": ["7", "7th", "seven", "seventh"]},
        {"input": "10", "normalized": "10", "alternatives": ["10", "10th", "ten", "tenth"]},
        
        # Word numbers
        {"input": "first", "normalized": "1", "alternatives": ["1", "1st", "one", "oneth"]},
        {"input": "seventh", "normalized": "7", "alternatives": ["7", "7th", "seven", "seventh"]},
        
        # Named variants
        {"input": "arkana", "normalized": "arkana", "alternatives": ["arkana"]},
        {"input": "Kaiba", "normalized": "kaiba", "alternatives": ["kaiba"]},
        {"input": "Joey Wheeler", "normalized": "joey wheeler", "alternatives": ["joey wheeler"]},
        
        # Edge cases
        {"input": "", "normalized": "", "alternatives": []},
        {"input": "   ", "normalized": "", "alternatives": []},
        {"input": "special-art", "normalized": "special-art", "alternatives": ["special-art"]},
    ]


@pytest.fixture 
def rarity_equivalence_test_cases():
    """Test cases for rarity equivalence validation."""
    return [
        # Ultimate Rare equivalences
        {"rarity1": "ultimate rare", "rarity2": "prismatic ultimate rare", "equivalent": True},
        {"rarity1": "prismatic ultimate rare", "rarity2": "ultimate rare", "equivalent": True},
        
        # Collector's Rare equivalences
        {"rarity1": "collector's rare", "rarity2": "prismatic collector's rare", "equivalent": True},
        {"rarity1": "prismatic collector's rare", "rarity2": "collector's rare", "equivalent": True},
        
        # Non-equivalent cases
        {"rarity1": "secret rare", "rarity2": "ultra rare", "equivalent": False},
        {"rarity1": "common", "rarity2": "rare", "equivalent": False},
        {"rarity1": "quarter century secret rare", "rarity2": "platinum secret rare", "equivalent": False},
    ]


@pytest.fixture
def cache_query_test_cases():
    """Test cases for cache query construction with art variants."""
    return [
        {
            "card_number": "LOB-001",
            "card_rarity": "Ultra Rare",
            "art_variant": None,
            "expected_query": {
                "card_number": "LOB-001",
                "card_rarity": {"$regex": "^ultra rare$", "$options": "i"},
            },
        },
        {
            "card_number": "LOB-005",
            "card_rarity": "Secret Rare",
            "art_variant": "7",
            "expected_or_clause": True,  # Should include $or clause for art variant alternatives
        },
        {
            "card_number": "BPT-005", 
            "card_rarity": "Ultimate Rare",
            "art_variant": "arkana",
            "expected_or_clause": True,
        },
    ]


@pytest.fixture
def database_error_scenarios():
    """Database error scenarios for testing error handling."""
    return [
        {
            "scenario": "connection_timeout",
            "exception": Exception("Connection timeout"),
            "expected_fallback": True,
        },
        {
            "scenario": "collection_not_found",
            "exception": Exception("Collection does not exist"),
            "expected_fallback": True,
        },
        {
            "scenario": "invalid_query",
            "exception": Exception("Invalid query syntax"),
            "expected_fallback": True,
        },
        {
            "scenario": "network_error",
            "exception": Exception("Network unreachable"),
            "expected_fallback": True,
        },
    ]


@pytest.fixture
def tcgplayer_error_scenarios():
    """TCGPlayer scraping error scenarios for testing resilience."""
    return [
        {
            "scenario": "timeout_error",
            "exception": Exception("Timeout waiting for page load"),
            "expected_result": {"error": True, "prices": None},
        },
        {
            "scenario": "element_not_found",
            "exception": Exception("Element not found"),
            "expected_result": {"error": True, "prices": None},
        },
        {
            "scenario": "malformed_html",
            "page_content": "<html><body>Invalid page</body></html>",
            "expected_result": {"tcg_price": None, "tcg_market_price": None},
        },
        {
            "scenario": "no_results",
            "results_count": 0,
            "expected_result": {"error": "No results found on TCGPlayer"},
        },
    ]


@pytest.fixture
def performance_test_data():
    """Performance test data for large-scale operations."""
    return {
        "large_cache_dataset": [
            {
                "card_number": f"TEST-{i:03d}",
                "card_name": f"Test Card {i}",
                "card_rarity": "common" if i % 2 == 0 else "rare",
                "tcgplayer_price": float(i * 1.5),
                "last_price_updt": datetime.now(timezone.utc),
            }
            for i in range(1, 101)  # 100 test records
        ],
        "concurrent_requests": [
            {"card_number": f"CONC-{i:03d}", "card_name": f"Concurrent Test {i}", "card_rarity": "ultra rare"}
            for i in range(1, 11)  # 10 concurrent requests
        ],
    }


@pytest.fixture
def memory_optimization_mocks():
    """Mocks for testing memory optimization and cleanup paths."""
    mock_memory_manager = MagicMock()
    mock_memory_manager.register_cleanup_callback = MagicMock()
    mock_memory_manager.get_current_memory_usage.return_value = {
        "rss_mb": 256.0,
        "vms_mb": 512.0,
        "percent": 25.0,
        "limit_mb": 1024,
        "usage_ratio": 0.25,
    }
    
    # Mock cleanup decorator
    def mock_decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    
    mock_memory_manager.memory_limit_decorator = MagicMock(side_effect=mock_decorator)
    
    return mock_memory_manager


@pytest.fixture
def integration_test_patches():
    """Comprehensive patches for integration testing."""
    def _create_patches():
        return [
            patch("ygoapi.price_scraping.get_price_cache_collection"),
            patch("ygoapi.price_scraping.get_card_variants_collection"),
            patch("ygoapi.price_scraping.get_memory_manager"),
            patch("ygoapi.price_scraping.asyncio.run"),
            patch("ygoapi.price_scraping.async_playwright"),
        ]
    
    return _create_patches


# Utility functions for test validation

def validate_cache_query(query: Dict[str, Any], expected_fields: List[str]) -> bool:
    """Validate that a cache query contains expected fields."""
    return all(field in query for field in expected_fields)


def validate_art_variant_alternatives(alternatives: List[str], expected_count: int) -> bool:
    """Validate art variant alternatives generation."""
    return len(alternatives) >= expected_count and all(isinstance(alt, str) for alt in alternatives)


def validate_price_data_structure(price_data: Dict[str, Any]) -> bool:
    """Validate price data structure compliance."""
    required_fields = ["card_number", "card_name", "card_rarity", "tcgplayer_price", "last_price_updt"]
    return all(field in price_data for field in required_fields)


def create_mock_tcgplayer_response(variants: List[Dict[str, Any]]) -> MagicMock:
    """Create a mock TCGPlayer page response with specified variants."""
    mock_page = AsyncMock()
    mock_page.evaluate.return_value = variants
    mock_page.goto = AsyncMock()
    return mock_page


def create_mock_database_response(data: List[Dict[str, Any]], find_one: bool = False) -> MagicMock:
    """Create a mock database response with specified data."""
    mock_collection = MagicMock()
    if find_one:
        mock_collection.find_one.return_value = data[0] if data else None
    else:
        mock_collection.find.return_value = data
    return mock_collection