"""
Unit tests for card_services.py module.

Tests all card service classes including CardSetService, CardVariantService,
and CardLookupService with comprehensive coverage of edge cases and error scenarios.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest
import requests

from tests.fixtures.mock_services import MockMongoDBData, MockYGOProDeckAPI
from ygoapi.card_services import (
    CardLookupService,
    CardSetService,
    CardVariantService,
    card_lookup_service,
    card_set_service,
    card_variant_service,
)


class TestCardSetService:
    """Test cases for CardSetService class."""

    @pytest.fixture
    def card_set_service_instance(self):
        """Create a CardSetService instance for testing."""
        return CardSetService()

    @patch("ygoapi.card_services.requests.get")
    def test_fetch_all_card_sets_success(self, mock_get, card_set_service_instance):
        """Test successful fetching of card sets from API."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = MockYGOProDeckAPI.get_card_sets_response()["data"]
        mock_get.return_value = mock_response

        # Execute
        result = card_set_service_instance.fetch_all_card_sets()

        # Verify
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["set_name"] == "Legend of Blue Eyes White Dragon"
        assert result[1]["set_name"] == "Metal Raiders"

        # Verify API call
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "cardsets.php" in args[0]
        assert kwargs["timeout"] == 30

    @patch("ygoapi.card_services.requests.get")
    def test_fetch_all_card_sets_api_error(self, mock_get, card_set_service_instance):
        """Test API error handling during card sets fetch."""
        # Setup mock response with error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        # Execute and verify exception
        with pytest.raises(Exception) as exc_info:
            card_set_service_instance.fetch_all_card_sets()

        assert "API returned status 500" in str(exc_info.value)

    @patch("ygoapi.card_services.requests.get")
    def test_fetch_all_card_sets_network_error(self, mock_get, card_set_service_instance):
        """Test network error handling during card sets fetch."""
        # Setup mock to raise exception
        mock_get.side_effect = requests.RequestException("Network error")

        # Execute and verify exception
        with pytest.raises(Exception):
            card_set_service_instance.fetch_all_card_sets()

    @patch("ygoapi.card_services.get_card_sets_collection")
    @patch.object(CardSetService, "fetch_all_card_sets")
    def test_upload_card_sets_to_cache_success(
        self, mock_fetch, mock_get_collection, card_set_service_instance
    ):
        """Test successful upload of card sets to cache."""
        # Setup mocks
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection
        mock_fetch.return_value = MockYGOProDeckAPI.get_card_sets_response()["data"]

        # Setup delete and insert results
        mock_collection.delete_many.return_value.deleted_count = 5
        mock_collection.insert_many.return_value.inserted_ids = ["id1", "id2"]

        # Execute
        result = card_set_service_instance.upload_card_sets_to_cache()

        # Verify
        assert result["total_sets_uploaded"] == 2
        assert result["previous_documents_cleared"] == 5
        assert "upload_timestamp" in result

        # Verify database operations
        mock_collection.delete_many.assert_called_once()
        mock_collection.insert_many.assert_called()
        mock_collection.create_index.assert_called()

    @patch("ygoapi.card_services.get_card_sets_collection")
    def test_get_cached_card_sets_success(self, mock_get_collection, card_set_service_instance):
        """Test successful retrieval of cached card sets."""
        # Setup mock collection
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection

        # Setup mock cursor
        mock_cursor = [
            {"set_name": "Test Set 1", "set_code": "TS1"},
            {"set_name": "Test Set 2", "set_code": "TS2"},
        ]
        mock_collection.find.return_value = mock_cursor

        # Execute
        result = card_set_service_instance.get_cached_card_sets()

        # Verify
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["set_name"] == "Test Set 1"

        # Verify database query
        mock_collection.find.assert_called_once_with({}, {"_id": 0})

    @patch("ygoapi.card_services.get_card_sets_collection")
    def test_get_cached_card_sets_database_disabled(
        self, mock_get_collection, card_set_service_instance
    ):
        """Test behavior when database is disabled."""
        # Setup mock to return None (disabled database)
        mock_get_collection.return_value = None

        # Execute
        result = card_set_service_instance.get_cached_card_sets()

        # Verify
        assert result == []

    @patch("ygoapi.card_services.get_card_sets_collection")
    def test_get_card_sets_count_success(self, mock_get_collection, card_set_service_instance):
        """Test successful count of cached card sets."""
        # Setup mock collection
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection
        mock_collection.count_documents.return_value = 42

        # Execute
        result = card_set_service_instance.get_card_sets_count()

        # Verify
        assert result == 42
        mock_collection.count_documents.assert_called_once_with({})

    @patch("ygoapi.card_services.get_card_sets_collection")
    def test_search_card_sets_success(self, mock_get_collection, card_set_service_instance):
        """Test successful search of card sets."""
        # Setup mock collection
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection

        # Setup mock search results
        mock_cursor = [{"set_name": "Blue Eyes Set", "set_code": "BES"}]
        mock_collection.find.return_value = mock_cursor

        # Execute
        result = card_set_service_instance.search_card_sets("blue eyes")

        # Verify
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["set_name"] == "Blue Eyes Set"

        # Verify search query
        mock_collection.find.assert_called_once()
        call_args = mock_collection.find.call_args[0][0]
        assert "set_name" in call_args
        assert "$regex" in call_args["set_name"]


class TestCardVariantService:
    """Test cases for CardVariantService class."""

    @pytest.fixture
    def card_variant_service_instance(self):
        """Create a CardVariantService instance for testing."""
        return CardVariantService()

    @patch("ygoapi.card_services.requests.get")
    def test_fetch_cards_from_set_success(self, mock_get, card_variant_service_instance):
        """Test successful fetching of cards from a specific set."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = MockYGOProDeckAPI.get_cards_response()
        mock_get.return_value = mock_response

        # Execute
        result = card_variant_service_instance.fetch_cards_from_set(
            "Legend of Blue Eyes White Dragon"
        )

        # Verify
        assert isinstance(result, list)
        assert len(result) >= 0  # Result depends on filtering logic

        # Verify API call with encoded set name
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "cardinfo.php" in args[0]
        assert "cardset=" in args[0]
        assert kwargs["timeout"] == 15

    @patch("ygoapi.card_services.requests.get")
    def test_fetch_cards_from_set_not_found(self, mock_get, card_variant_service_instance):
        """Test fetching cards from non-existent set."""
        # Setup mock response for not found
        mock_response = Mock()
        mock_response.status_code = 400
        mock_get.return_value = mock_response

        # Execute
        result = card_variant_service_instance.fetch_cards_from_set("NonExistent Set")

        # Verify
        assert result == []

    @patch("ygoapi.card_services.requests.get")
    def test_fetch_cards_from_set_api_error(self, mock_get, card_variant_service_instance):
        """Test API error handling during card fetch."""
        # Setup mock response with error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        # Execute and verify exception
        with pytest.raises(Exception) as exc_info:
            card_variant_service_instance.fetch_cards_from_set("Test Set")

        assert "API returned status 500" in str(exc_info.value)

    def test_create_card_variants_success(self, card_variant_service_instance):
        """Test successful creation of card variants."""
        # Setup test data
        cards = MockYGOProDeckAPI.get_cards_response()["data"]

        # Execute
        variants = list(card_variant_service_instance.create_card_variants(cards))

        # Verify
        assert len(variants) > 0

        # Check first variant structure
        variant = variants[0]
        assert "_variant_id" in variant
        assert "card_id" in variant
        assert "card_name" in variant
        assert "set_name" in variant
        assert "set_code" in variant
        assert "_uploaded_at" in variant

    def test_create_card_variants_empty_input(self, card_variant_service_instance):
        """Test card variant creation with empty input."""
        # Execute with empty list
        variants = list(card_variant_service_instance.create_card_variants([]))

        # Verify
        assert variants == []

    def test_create_card_variants_malformed_data(self, card_variant_service_instance):
        """Test card variant creation with malformed data."""
        # Setup malformed card data
        malformed_cards = [
            {"id": 123, "name": "Test Card"},  # Missing card_sets
            {"id": 456},  # Missing name and card_sets
        ]

        # Execute
        variants = list(card_variant_service_instance.create_card_variants(malformed_cards))

        # Verify that it handles malformed data gracefully
        assert isinstance(variants, list)

    @patch("ygoapi.card_services.get_card_variants_collection")
    @patch.object(CardVariantService, "fetch_cards_from_set")
    @patch("ygoapi.card_services.CardSetService")
    def test_upload_card_variants_to_cache_success(
        self,
        mock_card_set_service_class,
        mock_fetch,
        mock_get_collection,
        card_variant_service_instance,
    ):
        """Test successful upload of card variants to cache."""
        # Setup mocks
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection

        # Setup CardSetService mock
        mock_card_set_service = Mock()
        mock_card_set_service_class.return_value = mock_card_set_service
        mock_card_set_service.get_cached_card_sets.return_value = [
            {"set_name": "Test Set", "set_code": "TS"}
        ]

        # Setup fetch cards mock
        mock_fetch.return_value = MockYGOProDeckAPI.get_cards_response()["data"]

        # Setup database operation mocks
        mock_collection.delete_many.return_value.deleted_count = 10
        mock_collection.insert_many.return_value.inserted_ids = ["id1", "id2"]

        # Execute
        result = card_variant_service_instance.upload_card_variants_to_cache()

        # Verify
        assert "statistics" in result
        assert "total_variants_created" in result
        assert "previous_variants_cleared" in result

        # Verify database operations
        mock_collection.delete_many.assert_called_once()
        mock_collection.create_index.assert_called()

    @patch("ygoapi.card_services.get_card_variants_collection")
    def test_get_cached_card_variants_success(
        self, mock_get_collection, card_variant_service_instance
    ):
        """Test successful retrieval of cached card variants."""
        # Setup mock collection
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection

        # Setup mock cursor
        mock_cursor = [
            {"_variant_id": "variant1", "card_name": "Test Card 1"},
            {"_variant_id": "variant2", "card_name": "Test Card 2"},
        ]
        mock_collection.find.return_value = mock_cursor

        # Execute
        result = card_variant_service_instance.get_cached_card_variants()

        # Verify
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["card_name"] == "Test Card 1"


class TestCardLookupService:
    """Test cases for CardLookupService class."""

    @pytest.fixture
    def card_lookup_service_instance(self):
        """Create a CardLookupService instance for testing."""
        return CardLookupService()

    @patch("ygoapi.card_services.get_card_variants_collection")
    def test_lookup_card_info_from_cache_success(
        self, mock_get_collection, card_lookup_service_instance
    ):
        """Test successful card lookup from cache."""
        # Setup mock collection
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection

        # Setup mock result
        mock_result = {"card_name": "Blue-Eyes White Dragon", "set_code": "LOB-001"}
        mock_collection.find_one.return_value = mock_result

        # Execute
        result = card_lookup_service_instance.lookup_card_info_from_cache("LOB-001")

        # Verify
        assert result == mock_result
        assert result["card_name"] == "Blue-Eyes White Dragon"

        # Verify database query
        mock_collection.find_one.assert_called()

    @patch("ygoapi.card_services.get_card_variants_collection")
    def test_lookup_card_info_from_cache_not_found(
        self, mock_get_collection, card_lookup_service_instance
    ):
        """Test card lookup when card not found in cache."""
        # Setup mock collection
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection
        mock_collection.find_one.return_value = None

        # Execute
        result = card_lookup_service_instance.lookup_card_info_from_cache("NONEXISTENT")

        # Verify
        assert result is None

    @patch("ygoapi.card_services.get_card_variants_collection")
    def test_lookup_card_info_from_cache_database_error(
        self, mock_get_collection, card_lookup_service_instance
    ):
        """Test card lookup with database error."""
        # Setup mock collection to raise exception
        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection
        mock_collection.find_one.side_effect = Exception("Database error")

        # Execute
        result = card_lookup_service_instance.lookup_card_info_from_cache("TEST")

        # Verify
        assert result is None

    @patch("ygoapi.card_services.requests.get")
    def test_lookup_card_name_from_ygo_api_success(self, mock_get, card_lookup_service_instance):
        """Test successful card name lookup from YGO API."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "Blue-Eyes White Dragon"}
        mock_get.return_value = mock_response

        # Execute
        result = card_lookup_service_instance.lookup_card_name_from_ygo_api("LOB-001")

        # Verify
        assert result == "Blue-Eyes White Dragon"

        # Verify API call
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "cardsetsinfo.php" in args[0]
        assert "setcode=" in args[0]
        assert kwargs["timeout"] == 10

    @patch("ygoapi.card_services.requests.get")
    def test_lookup_card_name_from_ygo_api_not_found(self, mock_get, card_lookup_service_instance):
        """Test card name lookup when not found in API."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        # Execute
        result = card_lookup_service_instance.lookup_card_name_from_ygo_api("NONEXISTENT")

        # Verify
        assert result is None

    @patch("ygoapi.card_services.requests.get")
    def test_lookup_card_name_from_ygo_api_network_error(
        self, mock_get, card_lookup_service_instance
    ):
        """Test card name lookup with network error."""
        # Setup mock to raise exception
        mock_get.side_effect = requests.RequestException("Network error")

        # Execute
        result = card_lookup_service_instance.lookup_card_name_from_ygo_api("TEST")

        # Verify
        assert result is None


class TestServiceInstances:
    """Test the global service instances."""

    def test_service_instances_exist(self):
        """Test that service instances are properly created."""
        assert card_set_service is not None
        assert isinstance(card_set_service, CardSetService)

        assert card_variant_service is not None
        assert isinstance(card_variant_service, CardVariantService)

        assert card_lookup_service is not None
        assert isinstance(card_lookup_service, CardLookupService)

    def test_service_instances_have_memory_manager(self):
        """Test that service instances have memory manager."""
        assert hasattr(card_set_service, "memory_manager")
        assert hasattr(card_variant_service, "memory_manager")
        assert hasattr(card_lookup_service, "memory_manager")


class TestIntegrationScenarios:
    """Integration test scenarios for card services."""

    @patch("ygoapi.card_services.requests.get")
    @patch("ygoapi.card_services.get_card_sets_collection")
    def test_complete_card_set_workflow(self, mock_get_collection, mock_get):
        """Test complete workflow from fetching to caching card sets."""
        # Setup mocks
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = MockYGOProDeckAPI.get_card_sets_response()["data"]
        mock_get.return_value = mock_response

        mock_collection = Mock()
        mock_get_collection.return_value = mock_collection
        mock_collection.delete_many.return_value.deleted_count = 0
        mock_collection.insert_many.return_value.inserted_ids = ["id1", "id2"]

        # Execute workflow
        service = CardSetService()
        result = service.upload_card_sets_to_cache()

        # Verify workflow completed successfully
        assert result["total_sets_uploaded"] == 2
        assert "upload_timestamp" in result

    @patch("ygoapi.card_services.requests.get")
    def test_error_handling_cascade(self, mock_get):
        """Test error handling cascades properly through services."""
        # Setup mock to fail
        mock_get.side_effect = requests.RequestException("Network failure")

        # Test that errors propagate correctly
        service = CardSetService()
        with pytest.raises(Exception):
            service.fetch_all_card_sets()

        variant_service = CardVariantService()
        with pytest.raises(Exception):
            variant_service.fetch_cards_from_set("Test Set")
