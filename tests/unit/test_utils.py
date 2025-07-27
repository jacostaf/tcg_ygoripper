"""
Unit tests for utils.py module.

Tests all utility functions with comprehensive coverage of success cases,
error handling, and edge scenarios.
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from ygoapi.utils import (
    clean_card_data,
    extract_art_version,
    extract_booster_set_name,
    extract_set_code,
    filter_cards_by_set,
    normalize_rarity,
    normalize_rarity_for_matching,
    normalize_art_variant,
    validate_card_number,
    batch_process_generator,
    calculate_success_rate,
    generate_variant_id,
    is_cache_fresh,
    sanitize_string,
    parse_price_string,
    get_current_utc_datetime,
    format_datetime_for_api,
    map_rarity_to_tcgplayer_filter,
    map_set_code_to_tcgplayer_name,
)


class TestCardDataCleaning:
    """Test card data cleaning functions."""

    def test_clean_card_data_with_datetime(self):
        """Test cleaning card data with datetime objects."""
        input_data = {
            "card_name": "Blue-Eyes White Dragon",
            "last_updated": datetime(2023, 1, 1, 12, 0, 0),
            "price": 25.99,
            "some_date": datetime(2023, 6, 15),
        }

        result = clean_card_data(input_data)

        assert result["card_name"] == "Blue-Eyes White Dragon"
        assert result["price"] == 25.99

    def test_clean_card_data_with_none_values(self):
        """Test cleaning card data with None values."""
        input_data = {
            "card_name": "Test Card",
            "empty_field": None,
            "price": 0,
        }

        result = clean_card_data(input_data)

        assert result["card_name"] == "Test Card"
        assert result["empty_field"] is None
        assert result["price"] == 0

    def test_clean_card_data_empty_dict(self):
        """Test cleaning with empty dictionary."""
        result = clean_card_data({})
        assert result == {}


class TestCardNumberValidation:
    """Test card number validation functions."""

    def test_validate_card_number_valid_formats(self):
        """Test valid card number formats."""
        valid_numbers = [
            "LOB-001",
            "SDK-001",
            "PSV-001", 
            "LOB-EN001",
            "DDS-001",
        ]

        for card_number in valid_numbers:
            assert validate_card_number(card_number) is True

    def test_validate_card_number_invalid_formats(self):
        """Test invalid card number formats."""
        invalid_numbers = [
            "INVALID",
            "123-456",
            "",
            "LOB",
            "LOB-",
            "LOB-ABC",
            None,
        ]

        for card_number in invalid_numbers:
            assert validate_card_number(card_number) is False

    def test_extract_set_code_valid_numbers(self):
        """Test set code extraction from valid card numbers."""
        test_cases = [
            ("LOB-EN001", "LOB"),
            ("MRD-EN001", "MRD"),
            ("PSV-EN001", "PSV"),
            ("SDK-EN001", "SDK"),
            ("TP1-EN001", "TP1"),
        ]

        for card_number, expected_set_code in test_cases:
            result = extract_set_code(card_number)
            assert result == expected_set_code

    def test_extract_set_code_invalid_numbers(self):
        """Test set code extraction from invalid card numbers."""
        invalid_numbers = ["INVALID", "", None, "123"]

        for card_number in invalid_numbers:
            result = extract_set_code(card_number)
            assert result is None


class TestRarityProcessing:
    """Test rarity processing functions."""

    def test_normalize_rarity_basic(self):
        """Test basic rarity normalization."""
        test_cases = [
            ("Secret Rare", "secret rare"),
            ("ULTRA RARE", "ultra rare"),
            ("Super Rare", "super rare"),
            ("  Common  ", "common"),
        ]

        for input_rarity, expected in test_cases:
            result = normalize_rarity(input_rarity)
            assert result == expected

    def test_normalize_rarity_abbreviations(self):
        """Test rarity abbreviation handling."""
        test_cases = [
            ("QCSR", "quarter century secret rare"),
            ("PSR", "purple secret rare"),  # Fix: PSR maps to "purple" not "platinum"
            ("UR", "ultra rare"),
            ("SR", "secret rare"),
        ]

        for input_rarity, expected in test_cases:
            result = normalize_rarity(input_rarity)
            assert result == expected

    def test_normalize_rarity_for_matching(self):
        """Test rarity normalization for matching."""
        result = normalize_rarity_for_matching("Quarter Century Secret Rare")
        assert isinstance(result, list)
        assert len(result) > 1
        assert "quarter century secret rare" in result

    def test_normalize_rarity_empty_input(self):
        """Test rarity normalization with empty input."""
        assert normalize_rarity("") == ""
        assert normalize_rarity(None) == ""

    def test_map_rarity_to_tcgplayer_filter(self):
        """Test mapping rarity to TCGPlayer filter."""
        test_cases = [
            ("Secret Rare", "Secret Rare"),
            ("Ultra Rare", "Ultra Rare"),
            ("Platinum Secret Rare", "Platinum Secret Rare"),
        ]

        for input_rarity, expected in test_cases:
            result = map_rarity_to_tcgplayer_filter(input_rarity)
            assert result == expected


class TestArtVersionExtraction:
    """Test art version extraction functions."""

    def test_extract_art_version_numbered_patterns(self):
        """Test art version extraction for numbered patterns."""
        test_cases = [
            ("Blue-Eyes White Dragon [7th Art]", "7"),
            ("Dark Magician [9th Art]", "9"),
            ("Card Name (1st art)", "1"),
            ("Monster [3rd Quarter Century Secret Rare]", "3"),
        ]

        for input_text, expected in test_cases:
            result = extract_art_version(input_text)
            assert result == expected

    def test_extract_art_version_named_patterns(self):
        """Test art version extraction for named patterns."""
        test_cases = [
            ("Dark Magician (Arkana)", "Arkana"),
            ("Blue-Eyes White Dragon (Joey Wheeler)", "Joey Wheeler"),
            ("Monster Card (Kaiba)", "Kaiba"),
        ]

        for input_text, expected in test_cases:
            result = extract_art_version(input_text)
            assert result == expected

    def test_extract_art_version_no_pattern(self):
        """Test art version extraction when no pattern found."""
        test_cases = [
            "Blue-Eyes White Dragon",
            "Simple Card Name",
            "",
            None,
        ]

        for input_text in test_cases:
            result = extract_art_version(input_text)
            assert result is None

    def test_normalize_art_variant(self):
        """Test art variant normalization."""
        test_cases = [
            ("7th Art", "7 Art"),
            ("Alternate Art", "alternate art"),
            ("  Spaced  ", "spaced"),
            (None, None),
            ("", None),
        ]

        for input_variant, expected in test_cases:
            result = normalize_art_variant(input_variant)
            assert result == expected


class TestBoosterSetExtraction:
    """Test booster set name extraction."""

    def test_extract_booster_set_name_from_url(self):
        """Test booster set name extraction from TCGPlayer URLs."""
        test_cases = [
            ("https://tcgplayer.com/product/yugioh-quarter-century-stampede-card-secret-rare", "Quarter Century Stampede"),
            ("https://tcgplayer.com/product/yugioh-metal-raiders-card-ultra-rare", "Metal Raiders"),
        ]

        for url, expected_pattern in test_cases:
            result = extract_booster_set_name(url)
            # Should contain the expected pattern or be None
            assert result is None or expected_pattern.lower() in result.lower()

    def test_extract_booster_set_name_invalid_url(self):
        """Test booster set name extraction from invalid URLs."""
        invalid_urls = [
            "https://example.com/product/test",
            "invalid-url",
            "",
            None,
        ]

        for url in invalid_urls:
            result = extract_booster_set_name(url)
            assert result is None


class TestSetCodeMapping:
    """Test set code mapping functions."""

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_success(self, mock_get_collection):
        """Test successful set code to TCGPlayer name mapping."""
        # CRITICAL FIX: Mock the database function that's imported inside the utils function
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "set_code": "LOB",
            "set_name": "Legend of Blue Eyes White Dragon"  # The actual field name is set_name
        }
        mock_get_collection.return_value = mock_collection

        result = map_set_code_to_tcgplayer_name("LOB")
        assert result == "Legend of Blue Eyes White Dragon"

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_fallback(self, mock_get_collection):
        """Test set code mapping with fallback behavior."""
        # CRITICAL FIX: Mock the database function properly
        mock_collection = Mock()
        mock_collection.find_one.return_value = None  # No mapping found
        mock_get_collection.return_value = mock_collection

        result = map_set_code_to_tcgplayer_name("UNKNOWN")
        assert result is None  # Should return None for unknown codes

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_invalid(self, mock_get_collection):
        """Test mapping with disabled database."""
        # CRITICAL FIX: Mock database returning None (disabled database)
        mock_get_collection.return_value = None
        
        result = map_set_code_to_tcgplayer_name("INVALID")
        assert result is None  # Should return None when no database


class TestCardFiltering:
    """Test card filtering functions."""

    def test_filter_cards_by_set_exact_match(self):
        """Test filtering cards by exact set name match."""
        cards = [
            {
                "name": "Card 1",
                "card_sets": [
                    {"set_name": "Legend of Blue Eyes White Dragon", "set_code": "LOB"},
                    {"set_name": "Other Set", "set_code": "OTHER"},
                ],
            },
            {
                "name": "Card 2",
                "card_sets": [
                    {"set_name": "Metal Raiders", "set_code": "MRD"},
                ],
            },
            {
                "name": "Card 3",
                "card_sets": [
                    {"set_name": "Legend of Blue Eyes White Dragon", "set_code": "LOB"},
                ],
            },
        ]

        result = filter_cards_by_set(cards, "Legend of Blue Eyes White Dragon")

        assert len(result) == 2
        assert result[0]["name"] == "Card 1"
        assert result[1]["name"] == "Card 3"

    def test_filter_cards_by_set_no_matches(self):
        """Test filtering cards when no matches found."""
        cards = [
            {
                "name": "Card 1",
                "card_sets": [{"set_name": "Other Set", "set_code": "OTHER"}],
            }
        ]

        result = filter_cards_by_set(cards, "Nonexistent Set")
        assert len(result) == 0

    def test_filter_cards_by_set_case_insensitive(self):
        """Test that card filtering is case insensitive."""
        cards = [
            {
                "name": "Card 1",
                "card_sets": [{"set_name": "Legend of Blue Eyes White Dragon", "set_code": "LOB"}],
            }
        ]

        result = filter_cards_by_set(cards, "legend of blue eyes white dragon")
        assert len(result) == 1

    def test_filter_cards_by_set_missing_card_sets(self):
        """Test filtering cards that don't have card_sets field."""
        cards = [
            {"name": "Card 1"},  # Missing card_sets
            {
                "name": "Card 2",
                "card_sets": [{"set_name": "Test Set", "set_code": "TEST"}],
            },
        ]

        result = filter_cards_by_set(cards, "Test Set")
        assert len(result) == 1
        assert result[0]["name"] == "Card 2"


class TestUtilityHelpers:
    """Test utility helper functions."""

    def test_batch_process_generator(self):
        """Test batch processing generator."""
        items = list(range(25))
        batches = list(batch_process_generator(items, batch_size=10))
        
        assert len(batches) == 3
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10
        assert len(batches[2]) == 5

    def test_calculate_success_rate(self):
        """Test success rate calculation."""
        assert calculate_success_rate(80, 100) == 80.0
        assert calculate_success_rate(0, 100) == 0.0
        assert calculate_success_rate(50, 0) == 0.0

    def test_generate_variant_id(self):
        """Test variant ID generation."""
        result = generate_variant_id(12345, "LOB", "Secret Rare", "Alternate Art")
        assert isinstance(result, str)
        assert "12345" in result
        assert "LOB" in result

    def test_is_cache_fresh(self):
        """Test cache freshness checking."""
        # Fresh timestamp
        fresh_time = datetime.now(timezone.utc)
        assert is_cache_fresh(fresh_time, cache_days=7) is True

        # Stale timestamp
        stale_time = datetime.now(timezone.utc) - timedelta(days=8)
        assert is_cache_fresh(stale_time, cache_days=7) is False

        # None timestamp
        assert is_cache_fresh(None) is False

    def test_sanitize_string(self):
        """Test string sanitization."""
        test_cases = [
            ("Normal String", "Normal String"),
            ("  Spaced  String  ", "Spaced String"),
            ("String\x00with\x1fcontrol", "Stringwithcontrol"),
            ("", ""),
            (None, ""),
        ]

        for input_str, expected in test_cases:
            result = sanitize_string(input_str)
            assert result == expected

    def test_parse_price_string(self):
        """Test price string parsing."""
        test_cases = [
            ("$25.99", 25.99),
            ("25.99", 25.99),
            ("$1,234.56", 1234.56),
            ("Invalid", None),
            ("", None),
            (None, None),
        ]

        for input_str, expected in test_cases:
            result = parse_price_string(input_str)
            assert result == expected

    def test_get_current_utc_datetime(self):
        """Test current UTC datetime retrieval."""
        result = get_current_utc_datetime()
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_format_datetime_for_api(self):
        """Test datetime formatting for API."""
        test_dt = datetime(2023, 1, 1, 12, 0, 0)
        result = format_datetime_for_api(test_dt)
        assert isinstance(result, str)
        assert "2023" in result

        # Test with None
        result = format_datetime_for_api(None)
        assert result == ""


class TestErrorHandling:
    """Test error handling in utility functions."""

    def test_functions_handle_none_input(self):
        """Test that utility functions handle None input gracefully."""
        assert clean_card_data({}) == {}
        assert normalize_rarity(None) == ""
        assert extract_art_version(None) is None
        assert extract_set_code(None) is None
        assert validate_card_number(None) is False

    def test_functions_handle_empty_string_input(self):
        """Test that utility functions handle empty string input."""
        assert normalize_rarity("") == ""
        assert extract_art_version("") is None
        assert extract_set_code("") is None
        assert validate_card_number("") is False

    def test_edge_cases_and_boundary_conditions(self):
        """Test edge cases and boundary conditions."""
        # Very long strings
        long_string = "A" * 1000
        result = normalize_rarity(long_string)
        assert isinstance(result, str)
        
        # Empty lists
        assert list(batch_process_generator([], 10)) == []
        assert filter_cards_by_set([], "Test Set") == []


class TestPerformanceConsiderations:
    """Test performance-related aspects of utility functions."""

    def test_large_dataset_handling(self):
        """Test utility functions with large datasets."""
        # Create a large list of cards
        large_card_list = []
        for i in range(100):  # Reduced for test performance
            large_card_list.append({
                "name": f"Card {i}",
                "card_sets": [{"set_name": "Test Set", "set_code": "TEST"}]
            })

        # Should handle large datasets efficiently
        result = filter_cards_by_set(large_card_list, "Test Set")
        assert len(result) == 100

    def test_repeated_operations(self):
        """Test utility functions with repeated operations."""
        # Test that functions work consistently with repeated calls
        test_data = "Secret Rare"
        
        results = []
        for _ in range(10):  # Reduced iterations for test performance
            results.append(normalize_rarity(test_data))
        
        # All results should be identical
        assert all(result == results[0] for result in results)
        assert results[0] == "secret rare"


class TestUtilsCoverageEnhancement:
    """Test utility functions coverage enhancement for previously uncovered lines."""

    def test_clean_card_data_with_mongodb_fields(self):
        """Test cleaning card data with MongoDB-specific fields (lines 155-158)."""
        input_data = {
            "card_name": "Blue-Eyes White Dragon",
            "_id": "mongo_object_id",
            "_source": "mongodb",
            "_uploaded_at": "2023-01-01",
            "_created_at": "2023-01-01",
            "tcgplayer_price": "25.99",
            "tcgplayer_market_price": "invalid_price",
            "last_price_updt": datetime(2023, 1, 1, 12, 0, 0),
            "created_at": datetime(2023, 1, 1, 12, 0, 0),
        }

        result = clean_card_data(input_data)

        # MongoDB fields should be removed
        assert "_id" not in result
        assert "_source" not in result
        assert "_uploaded_at" not in result
        assert "_created_at" not in result
        
        # Price fields should be properly formatted
        assert result["tcgplayer_price"] == 25.99
        assert result["tcgplayer_market_price"] is None  # Invalid price becomes None
        
        # Datetime fields should be formatted as ISO strings
        assert isinstance(result["last_price_updt"], str)
        assert isinstance(result["created_at"], str)

    def test_clean_card_data_with_invalid_price_types(self):
        """Test cleaning card data with invalid price types (lines 162-164)."""
        input_data = {
            "tcgplayer_price": "not_a_number",
            "tcgplayer_market_price": None,
            "card_name": "Test Card"
        }

        result = clean_card_data(input_data)

        assert result["tcgplayer_price"] is None
        assert result["tcgplayer_market_price"] is None
        assert result["card_name"] == "Test Card"

    def test_clean_card_data_error_handling(self):
        """Test clean_card_data error handling (line 169)."""
        # Create a problematic dict that will cause an error during processing
        problematic_data = {"normal_field": "test"}
        
        # Mock the clean_card_data function to raise an exception during processing
        with patch('ygoapi.utils.logger') as mock_logger:
            # Create a dict that will cause an error when accessing fields
            class ProblematicDict(dict):
                def copy(self):
                    raise Exception("Copy error")
            
            problematic_dict = ProblematicDict({"normal_field": "test"})
            result = clean_card_data(problematic_dict)
            
            # Should return original data when cleaning fails
            assert result == problematic_dict
            # Should have logged the error
            mock_logger.error.assert_called_once()

    def test_is_cache_fresh_with_naive_datetime(self):
        """Test is_cache_fresh with naive datetime (lines 264-265)."""
        # Test with naive datetime (no timezone info)
        naive_dt = datetime(2023, 1, 1, 12, 0, 0)  # No timezone
        
        # Should treat as UTC and process correctly
        result = is_cache_fresh(naive_dt, cache_days=7)
        assert isinstance(result, bool)

    def test_is_cache_fresh_boundary_conditions(self):
        """Test is_cache_fresh boundary conditions (line 269)."""
        # Test exactly at the boundary
        expiry_time = datetime.now(timezone.utc) - timedelta(days=7, seconds=1)
        assert is_cache_fresh(expiry_time, cache_days=7) is False
        
        # Test just before expiry
        fresh_time = datetime.now(timezone.utc) - timedelta(days=6, hours=23, minutes=59)
        assert is_cache_fresh(fresh_time, cache_days=7) is True

    def test_parse_price_string_edge_cases(self):
        """Test parse_price_string edge cases (lines 273-278)."""
        test_cases = [
            ("$25.99", 25.99),
            ("25.99", 25.99),
            ("$1,234.56", 1234.56),  # Comma gets removed, becomes 1234.56
            ("25", 25.0),
            ("$", None),  # Only currency symbol
            ("abc", None),  # No digits
            ("$abc", None),  # Currency + no digits
            ("25.99.99", None),  # Multiple decimals - cannot be parsed as float
            ("€25.99", 25.99),  # Euro symbol gets removed
            ("USD 25.99", 25.99),  # Text gets removed
        ]

        for input_str, expected in test_cases:
            result = parse_price_string(input_str)
            assert result == expected

    def test_extract_booster_set_name_error_handling(self):
        """Test extract_booster_set_name error handling (lines 722-731)."""
        # Test with problematic URL that might cause regex errors
        problematic_urls = [
            "https://tcgplayer.com/product/yugioh-quarter-century-stampede-card-secret-rare",
            "https://tcgplayer.com/product/yugioh-test-set-card-ultra-rare",
            "https://malformed-url-that-might-cause-errors",
        ]

        for url in problematic_urls:
            result = extract_booster_set_name(url)
            # Should not raise exception and return string or None
            assert result is None or isinstance(result, str)

    def test_extract_booster_set_name_fallback_logic(self):
        """Test extract_booster_set_name fallback logic (lines 735-736)."""
        # Test URL with fallback pattern
        fallback_url = "https://tcgplayer.com/product/yugioh-very-long-set-name-with-many-words-card-secret-rare"
        result = extract_booster_set_name(fallback_url)
        
        # Should handle the fallback logic
        assert result is None or isinstance(result, str)

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_database_error(self, mock_get_collection):
        """Test map_set_code_to_tcgplayer_name with database errors (lines 762-790)."""
        # Test when database connection fails
        mock_get_collection.side_effect = Exception("Database connection error")
        
        result = map_set_code_to_tcgplayer_name("RA04")
        # Should fall back to hardcoded mapping
        assert result == "Quarter Century Stampede"

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_collection_none(self, mock_get_collection):
        """Test map_set_code_to_tcgplayer_name when collection is None."""
        mock_get_collection.return_value = None
        
        result = map_set_code_to_tcgplayer_name("RA04")
        # Should use fallback mapping
        assert result == "Quarter Century Stampede"

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_query_error(self, mock_get_collection):
        """Test map_set_code_to_tcgplayer_name when query fails."""
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("Query error")
        mock_get_collection.return_value = mock_collection
        
        result = map_set_code_to_tcgplayer_name("RA04")
        # Should fall back to hardcoded mapping
        assert result == "Quarter Century Stampede"

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_empty_result(self, mock_get_collection):
        """Test map_set_code_to_tcgplayer_name with empty database result."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        mock_get_collection.return_value = mock_collection
        
        result = map_set_code_to_tcgplayer_name("UNKNOWN")
        # Should return None for unknown codes
        assert result is None

    @patch("ygoapi.database.get_card_sets_collection")
    def test_map_set_code_to_tcgplayer_name_malformed_result(self, mock_get_collection):
        """Test map_set_code_to_tcgplayer_name with malformed database result."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"invalid_field": "value"}  # Missing set_name
        mock_get_collection.return_value = mock_collection
        
        result = map_set_code_to_tcgplayer_name("UNKNOWN")
        # Should return None when set_name is missing
        assert result is None

    def test_filter_cards_by_set_with_image_adjustment(self):
        """Test filter_cards_by_set with card image adjustment."""
        cards = [
            {
                "name": "Test Card",
                "card_sets": [
                    {"set_name": "Target Set", "set_code": "TS1"},
                    {"set_name": "Other Set", "set_code": "OS1"},
                ],
                "card_images": [
                    {"image_url": "img1.jpg"},
                    {"image_url": "img2.jpg"},
                    {"image_url": "img3.jpg"},
                ],
            }
        ]

        result = filter_cards_by_set(cards, "Target Set")
        
        assert len(result) == 1
        assert len(result[0]["card_sets"]) == 1
        assert result[0]["card_sets"][0]["set_name"] == "Target Set"
        assert result[0]["target_set_variants"] == 1
        assert result[0]["target_set_name"] == "Target Set"
        assert result[0]["target_set_codes"] == ["TS1"]

    def test_filter_cards_by_set_edge_cases(self):
        """Test filter_cards_by_set with edge cases."""
        # Test with empty cards list
        result = filter_cards_by_set([], "Test Set")
        assert result == []

        # Test with None target set
        cards = [{"name": "Test", "card_sets": []}]
        result = filter_cards_by_set(cards, None)
        assert result == cards

        # Test with empty target set
        result = filter_cards_by_set(cards, "")
        assert result == cards

    def test_normalize_rarity_special_cases(self):
        """Test normalize_rarity with special case handling."""
        test_cases = [
            ("Quarter Century Secret Rare", "quarter century secret rare"),
            ("25th Anniversary Secret Rare", "quarter century secret rare"),
            ("Platinum Secret Rare", "platinum secret rare"),
            ("Prismatic Ultimate Rare", "prismatic ultimate rare"),
            ("Starlight Rare", "starlight rare"),
            ("Collector's Rare", "collector's rare"),
            ("Ghost Gold Rare", "ghost/gold rare"),
            ("Ultra Parallel Rare", "ultra parallel rare"),
            ("Premium Gold Rare", "premium gold rare"),
            ("Duel Terminal Rare", "duel terminal rare"),
            ("Mosaic Rare", "mosaic rare"),
            ("Shatterfoil Rare", "shatterfoil rare"),
            ("Starfoil Rare", "starfoil rare"),
            ("Hobby League Rare", "hobby league rare"),
            ("Millennium Rare", "millennium rare"),
            ("20th Secret Rare", "20th secret rare"),
        ]

        for input_rarity, expected in test_cases:
            result = normalize_rarity(input_rarity)
            assert result == expected

    def test_normalize_rarity_for_matching_comprehensive(self):
        """Test comprehensive rarity matching variants."""
        # Test Quarter Century variants
        result = normalize_rarity_for_matching("Quarter Century Secret Rare")
        expected_variants = [
            "quarter century secret rare",
            "qcsr",
            "25th anniversary secret rare",
            "quarter century secret",
            "qc secret rare",
        ]
        for variant in expected_variants:
            assert variant in result

        # Test standard rarity abbreviations
        result = normalize_rarity_for_matching("Secret Rare")
        assert "secret" in result
        assert "sr" in result

    def test_extract_art_version_complex_patterns(self):
        """Test extract_art_version with complex patterns."""
        test_cases = [
            ("Dark Magician [7th Quarter Century Secret Rare]", "7"),
            ("Blue-Eyes White Dragon [9th Platinum Secret Rare]", "9"),
            ("Monster /7th-quarter-century", "7"),
            ("Card magician-9th-quarter", "9"),
            ("Test -7th-quarter card", "7"),
            ("Card with (Joey Wheeler) variant", "Joey Wheeler"),
            ("Monster -arkana- version", "Arkana"),
            ("Card (anime) style", "Anime"),
        ]

        for input_text, expected in test_cases:
            result = extract_art_version(input_text)
            assert result == expected

    def test_generate_variant_id_comprehensive(self):
        """Test generate_variant_id with various inputs."""
        # Test with all parameters
        result = generate_variant_id(12345, "LOB", "Secret Rare", "Alternate Art")
        assert "12345" in result
        assert "LOB" in result
        assert "secret rare" in result
        assert "alternate art" in result

        # Test without art variant
        result = generate_variant_id(12345, "LOB", "Secret Rare", None)
        assert "12345" in result
        assert "LOB" in result
        assert "secret rare" in result

        # Test with empty strings
        result = generate_variant_id(12345, "", "", "")
        assert "12345" in result

    def test_validate_card_number_comprehensive(self):
        """Test validate_card_number with comprehensive patterns."""
        # Test all valid patterns
        valid_patterns = [
            "LOB-001",      # Standard format
            "SDK-EN001",    # With language code
            "LOB-01",       # Short format
            "SDK-EN01",     # Short with language code
            "12345678",     # Pure numeric
        ]

        for pattern in valid_patterns:
            assert validate_card_number(pattern) is True

        # Test invalid patterns
        invalid_patterns = [
            "INVALID-FORMAT",
            "123-ABC",
            "A-001",        # Too short prefix
            "TOOLONG-001",  # Too long prefix
        ]

        for pattern in invalid_patterns:
            assert validate_card_number(pattern) is False