"""
Unit tests for models.py module.

Tests all Pydantic models including validation, serialization, and data transformation
with comprehensive coverage of edge cases and error scenarios.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from bson import ObjectId
from pydantic import ValidationError

from ygoapi.models import (
    CardModel,
    CardPriceModel,
    CardSetModel,
    CardVariantModel,
    MemoryStats,
    PriceScrapingRequest,
    PriceScrapingResponse,
    ProcessingStats,
    PyObjectId,
)


class TestPyObjectId:
    """Test cases for PyObjectId custom ObjectId class."""

    def test_valid_object_id(self):
        """Test validation with valid ObjectId."""
        valid_id = ObjectId()
        result = PyObjectId.validate(str(valid_id))
        assert isinstance(result, ObjectId)
        assert result == valid_id

    def test_valid_object_id_string(self):
        """Test validation with valid ObjectId string."""
        valid_id_str = "507f1f77bcf86cd799439011"
        result = PyObjectId.validate(valid_id_str)
        assert isinstance(result, ObjectId)
        assert str(result) == valid_id_str

    def test_invalid_object_id(self):
        """Test validation with invalid ObjectId."""
        invalid_id = "invalid_object_id"

        with pytest.raises(ValueError) as exc_info:
            PyObjectId.validate(invalid_id)

        assert "Invalid ObjectId" in str(exc_info.value)

    def test_validators_generator(self):
        """Test that __get_validators__ returns correct validator."""
        validators = list(PyObjectId.__get_validators__())
        assert len(validators) == 1
        assert validators[0] == PyObjectId.validate

    def test_pydantic_json_schema(self):
        """Test JSON schema generation for Pydantic."""
        field_schema = {}
        PyObjectId.__get_pydantic_json_schema__(field_schema)
        assert field_schema["type"] == "string"


class TestCardPriceModel:
    """Test cases for CardPriceModel."""

    def test_valid_card_price_model(self):
        """Test creation with valid data."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "tcgplayer_price": 25.99,
            "tcgplayer_market_price": 24.50,
        }

        model = CardPriceModel(**data)

        assert model.card_number == "LOB-001"
        assert model.card_name == "Blue-Eyes White Dragon"
        assert model.card_rarity == "Ultra Rare"
        assert model.tcgplayer_price == 25.99
        assert model.tcgplayer_market_price == 24.50
        assert model.source == "tcgplayer"
        assert isinstance(model.last_price_updt, datetime)
        assert isinstance(model.created_at, datetime)

    def test_card_price_model_with_art_variant(self):
        """Test model with art variant data."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "art_variant": "Alternate Art",
        }

        model = CardPriceModel(**data)
        assert model.art_variant == "Alternate Art"

    def test_card_price_model_optional_fields(self):
        """Test model with only required fields."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
        }

        model = CardPriceModel(**data)

        assert model.art_variant is None
        assert model.tcgplayer_price is None
        assert model.tcgplayer_url is None

    def test_card_price_model_missing_required_field(self):
        """Test validation error with missing required field."""
        data = {
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare"
            # Missing card_number
        }

        with pytest.raises(ValidationError) as exc_info:
            CardPriceModel(**data)

        assert "card_number" in str(exc_info.value)

    def test_card_price_model_json_serialization(self):
        """Test JSON serialization."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "tcgplayer_price": 25.99,
        }

        model = CardPriceModel(**data)
        json_data = model.model_dump()

        assert "card_number" in json_data
        assert "card_name" in json_data
        assert "tcgplayer_price" in json_data


class TestCardSetModel:
    """Test cases for CardSetModel."""

    def test_valid_card_set_model(self):
        """Test creation with valid data."""
        data = {
            "set_name": "Legend of Blue Eyes White Dragon",
            "set_code": "LOB",
            "num_of_cards": 126,
            "tcg_date": "2002-03-08",
        }

        model = CardSetModel(**data)

        assert model.set_name == "Legend of Blue Eyes White Dragon"
        assert model.set_code == "LOB"
        assert model.num_of_cards == 126
        assert model.tcg_date == "2002-03-08"
        assert model.source == "ygoprodeck_api"

    def test_card_set_model_optional_fields(self):
        """Test model with only required fields."""
        data = {"set_name": "Metal Raiders", "set_code": "MRD", "num_of_cards": 82}

        model = CardSetModel(**data)

        assert model.tcg_date is None
        assert model.uploaded_at is None
        assert model.source == "ygoprodeck_api"

    def test_card_set_model_with_metadata(self):
        """Test model with metadata fields."""
        upload_time = datetime.now(timezone.utc)
        data = {
            "set_name": "Metal Raiders",
            "set_code": "MRD",
            "num_of_cards": 82,
            "uploaded_at": upload_time,
            "source": "custom_source",
        }

        model = CardSetModel(**data)

        assert model.uploaded_at == upload_time
        assert model.source == "custom_source"

    def test_card_set_model_invalid_num_cards(self):
        """Test validation with invalid number of cards."""
        data = {
            "set_name": "Test Set",
            "set_code": "TS",
            "num_of_cards": "invalid",  # Should be int
        }

        with pytest.raises(ValidationError):
            CardSetModel(**data)


class TestCardVariantModel:
    """Test cases for CardVariantModel."""

    def test_valid_card_variant_model(self):
        """Test creation with valid data."""
        data = {
            "variant_id": "46986414_LOB-001_Ultra_Rare",
            "card_id": 46986414,
            "card_name": "Blue-Eyes White Dragon",
            "card_type": "Normal Monster",
            "atk": 3000,
            "def": 2500,
            "level": 8,
            "race": "Dragon",
            "attribute": "LIGHT",
        }

        model = CardVariantModel(**data)

        assert model.variant_id == "46986414_LOB-001_Ultra_Rare"
        assert model.card_id == 46986414
        assert model.card_name == "Blue-Eyes White Dragon"
        assert model.atk == 3000
        assert model.def_ == 2500  # Note: def_ because 'def' is reserved
        assert model.level == 8
        assert model.source == "ygoprodeck_api"

    def test_card_variant_model_def_alias(self):
        """Test that 'def' field is properly handled with alias."""
        data = {
            "variant_id": "test_variant",
            "card_id": 123,
            "card_name": "Test Card",
            "def": 2000,  # Using 'def' key which should map to def_
        }

        model = CardVariantModel(**data)
        assert model.def_ == 2000

    def test_card_variant_model_with_set_info(self):
        """Test model with set-specific information."""
        data = {
            "variant_id": "test_variant",
            "card_id": 123,
            "card_name": "Test Card",
            "set_name": "Test Set",
            "set_code": "TS-001",
            "set_rarity": "Ultra Rare",
            "set_price": "25.99",
        }

        model = CardVariantModel(**data)

        assert model.set_name == "Test Set"
        assert model.set_code == "TS-001"
        assert model.set_rarity == "Ultra Rare"
        assert model.set_price == "25.99"

    def test_card_variant_model_with_linkmarkers(self):
        """Test model with link monster data."""
        data = {
            "variant_id": "test_link",
            "card_id": 456,
            "card_name": "Test Link Monster",
            "linkval": 2,
            "linkmarkers": ["Top", "Bottom"],
        }

        model = CardVariantModel(**data)

        assert model.linkval == 2
        assert model.linkmarkers == ["Top", "Bottom"]

    def test_card_variant_model_missing_required_fields(self):
        """Test validation with missing required fields."""
        data = {
            "card_id": 123,
            "card_name": "Test Card"
            # Missing variant_id
        }

        with pytest.raises(ValidationError) as exc_info:
            CardVariantModel(**data)

        assert "variant_id" in str(exc_info.value)


class TestCardModel:
    """Test cases for CardModel."""

    def test_valid_card_model(self):
        """Test creation with valid data."""
        data = {
            "id": 46986414,
            "name": "Blue-Eyes White Dragon",
            "type": "Normal Monster",
            "frameType": "normal",
            "desc": "This legendary dragon is a powerful engine of destruction.",
            "atk": 3000,
            "def": 2500,
            "level": 8,
            "race": "Dragon",
            "attribute": "LIGHT",
        }

        model = CardModel(**data)

        assert model.id == 46986414
        assert model.name == "Blue-Eyes White Dragon"
        assert model.type == "Normal Monster"
        assert model.atk == 3000
        assert model.def_ == 2500

    def test_card_model_with_card_sets(self):
        """Test model with card sets data."""
        card_sets = [
            {
                "set_name": "Legend of Blue Eyes White Dragon",
                "set_code": "LOB-001",
                "set_rarity": "Ultra Rare",
            }
        ]

        data = {
            "id": 46986414,
            "name": "Blue-Eyes White Dragon",
            "type": "Normal Monster",
            "card_sets": card_sets,
        }

        model = CardModel(**data)
        assert model.card_sets == card_sets
        assert len(model.card_sets) == 1

    def test_card_model_with_images_and_prices(self):
        """Test model with card images and prices."""
        card_images = [{"id": 46986414, "image_url": "http://example.com/image.jpg"}]
        card_prices = [{"tcgplayer_price": "25.99"}]

        data = {
            "id": 46986414,
            "name": "Blue-Eyes White Dragon",
            "type": "Normal Monster",
            "card_images": card_images,
            "card_prices": card_prices,
        }

        model = CardModel(**data)
        assert model.card_images == card_images
        assert model.card_prices == card_prices

    def test_card_model_required_fields_only(self):
        """Test model with only required fields."""
        data = {"id": 123, "name": "Test Card", "type": "Spell Card"}

        model = CardModel(**data)

        assert model.id == 123
        assert model.name == "Test Card"
        assert model.type == "Spell Card"
        assert model.atk is None
        assert model.card_sets is None


class TestProcessingStats:
    """Test cases for ProcessingStats."""

    def test_valid_processing_stats(self):
        """Test creation with valid data."""
        data = {
            "total_sets": 100,
            "processed_sets": 95,
            "failed_sets": 5,
            "total_cards_processed": 1500,
            "unique_variants_created": 1450,
            "duplicate_variants_skipped": 50,
        }

        model = ProcessingStats(**data)

        assert model.total_sets == 100
        assert model.processed_sets == 95
        assert model.failed_sets == 5
        assert model.success_rate is None  # Not calculated automatically
        assert model.processing_errors == []  # Default empty list

    def test_processing_stats_with_errors(self):
        """Test processing stats with errors."""
        errors = [
            {"set_name": "Test Set", "error": "API timeout"},
            {"set_name": "Another Set", "error": "Invalid data"},
        ]

        data = {"total_sets": 10, "processing_errors": errors, "success_rate": 80.0}

        model = ProcessingStats(**data)

        assert len(model.processing_errors) == 2
        assert model.processing_errors[0]["set_name"] == "Test Set"
        assert model.success_rate == 80.0

    def test_processing_stats_defaults(self):
        """Test default values."""
        model = ProcessingStats()

        assert model.total_sets == 0
        assert model.processed_sets == 0
        assert model.failed_sets == 0
        assert model.processing_errors == []
        assert model.success_rate is None


class TestPriceScrapingRequest:
    """Test cases for PriceScrapingRequest."""

    def test_valid_price_scraping_request(self):
        """Test creation with valid data."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "art_variant": "Standard",
            "force_refresh": True,
        }

        model = PriceScrapingRequest(**data)

        assert model.card_number == "LOB-001"
        assert model.card_name == "Blue-Eyes White Dragon"
        assert model.card_rarity == "Ultra Rare"
        assert model.art_variant == "Standard"
        assert model.force_refresh is True

    def test_price_scraping_request_defaults(self):
        """Test default values."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
        }

        model = PriceScrapingRequest(**data)

        assert model.art_variant is None
        assert model.force_refresh is False

    def test_price_scraping_request_missing_fields(self):
        """Test validation with missing required fields."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon"
            # Missing card_rarity
        }

        with pytest.raises(ValidationError):
            PriceScrapingRequest(**data)


class TestPriceScrapingResponse:
    """Test cases for PriceScrapingResponse."""

    def test_valid_price_scraping_response(self):
        """Test creation with valid data."""
        data = {
            "success": True,
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "tcgplayer_price": 25.99,
            "tcgplayer_market_price": 24.50,
            "cached": False,
            "last_updated": datetime.now(timezone.utc),
        }

        model = PriceScrapingResponse(**data)

        assert model.success is True
        assert model.card_number == "LOB-001"
        assert model.tcgplayer_price == 25.99
        assert model.cached is False
        assert isinstance(model.last_updated, datetime)

    def test_price_scraping_response_error(self):
        """Test response with error."""
        data = {
            "success": False,
            "card_number": "INVALID",
            "card_name": "Invalid Card",
            "card_rarity": "Unknown",
            "error": "Card not found in TCGPlayer",
        }

        model = PriceScrapingResponse(**data)

        assert model.success is False
        assert model.error == "Card not found in TCGPlayer"
        assert model.tcgplayer_price is None

    def test_price_scraping_response_json_serialization(self):
        """Test JSON serialization with datetime."""
        test_datetime = datetime.now(timezone.utc)
        data = {
            "success": True,
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "last_updated": test_datetime,
        }

        model = PriceScrapingResponse(**data)
        json_data = model.model_dump()

        # Check that datetime is properly serialized
        assert "last_updated" in json_data
        assert isinstance(json_data["last_updated"], datetime)


class TestMemoryStats:
    """Test cases for MemoryStats."""

    def test_valid_memory_stats(self):
        """Test creation with valid data."""
        data = {
            "rss_mb": 256.5,
            "vms_mb": 512.0,
            "percent": 12.5,
            "limit_mb": 1024,
            "usage_ratio": 0.25,
            "warning_threshold": 0.8,
            "critical_threshold": 0.9,
        }

        model = MemoryStats(**data)

        assert model.rss_mb == 256.5
        assert model.vms_mb == 512.0
        assert model.percent == 12.5
        assert model.limit_mb == 1024
        assert model.usage_ratio == 0.25
        assert model.warning_threshold == 0.8
        assert model.critical_threshold == 0.9

    def test_memory_stats_invalid_types(self):
        """Test validation with invalid types."""
        data = {
            "rss_mb": "invalid",  # Should be float
            "vms_mb": 512.0,
            "percent": 12.5,
            "limit_mb": 1024,
            "usage_ratio": 0.25,
            "warning_threshold": 0.8,
            "critical_threshold": 0.9,
        }

        with pytest.raises(ValidationError):
            MemoryStats(**data)


class TestModelValidation:
    """Test general model validation scenarios."""

    def test_extra_fields_ignored(self):
        """Test that extra fields are ignored in models."""
        data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
            "extra_field": "This should be ignored",
        }

        # Should not raise an error, extra field should be ignored
        model = CardPriceModel(**data)
        assert model.card_number == "LOB-001"
        assert not hasattr(model, "extra_field")

    def test_model_dict_conversion(self):
        """Test model to dict conversion."""
        data = {"variant_id": "test_variant", "card_id": 123, "card_name": "Test Card"}

        model = CardVariantModel(**data)
        model_dict = model.model_dump()

        assert isinstance(model_dict, dict)
        assert model_dict["variant_id"] == "test_variant"
        assert model_dict["card_id"] == 123

    def test_model_copy(self):
        """Test model copying functionality."""
        original_data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
        }

        original_model = CardPriceModel(**original_data)
        copied_model = original_model.model_copy()

        assert copied_model.card_number == original_model.card_number
        assert copied_model is not original_model  # Different instances

    def test_model_update(self):
        """Test model update functionality."""
        original_data = {
            "card_number": "LOB-001",
            "card_name": "Blue-Eyes White Dragon",
            "card_rarity": "Ultra Rare",
        }

        model = CardPriceModel(**original_data)

        # Update with new data
        updated_model = model.model_copy(update={"tcgplayer_price": 30.00})

        assert updated_model.tcgplayer_price == 30.00
        assert updated_model.card_number == "LOB-001"  # Original data preserved
        assert model.tcgplayer_price is None  # Original unchanged
