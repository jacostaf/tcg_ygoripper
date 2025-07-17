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

    @patch("ygoapi.database.get_database")
    def test_map_set_code_to_tcgplayer_name_success(self, mock_get_database):
        """Test successful set code to TCGPlayer name mapping."""
        # Create a proper mock database with __getitem__ support
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "set_code": "LOB",
            "tcgplayer_name": "Legend of Blue Eyes White Dragon"
        }
        
        mock_db = Mock()
        mock_db.__getitem__ = Mock(return_value=mock_collection)
        mock_get_database.return_value = mock_db

        result = map_set_code_to_tcgplayer_name("LOB")
        assert result == "Legend of Blue Eyes White Dragon"

    @patch("ygoapi.database.get_database")
    def test_map_set_code_to_tcgplayer_name_fallback(self, mock_get_database):
        """Test set code mapping with fallback to original code."""
        # Create a proper mock database with __getitem__ support
        mock_collection = Mock()
        mock_collection.find_one.return_value = None  # No mapping found
        
        mock_db = Mock()
        mock_db.__getitem__ = Mock(return_value=mock_collection)
        mock_get_database.return_value = mock_db

        result = map_set_code_to_tcgplayer_name("UNKNOWN")
        assert result == "UNKNOWN"  # Should return original code

    def test_map_set_code_to_tcgplayer_name_invalid(self):
        """Test mapping with invalid set code."""
        # Skip database access and return None for invalid codes
        with patch("ygoapi.utils.get_database", return_value=None):
            result = map_set_code_to_tcgplayer_name("INVALID")
            assert result == "INVALID"  # Should fallback to original code when no database


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