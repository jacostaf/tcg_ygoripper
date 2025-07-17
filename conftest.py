"""
Test configuration and fixtures for Yu-Gi-Oh! Pack Opener App backend tests.

This module provides pytest fixtures for Flask app testing, database mocking,
and external API mocking to ensure isolated and reliable test execution.
"""

import os

# CRITICAL: Set test environment variables BEFORE any other imports
# This ensures config validation passes during app creation
os.environ.update({
    "TESTING": "true",
    "MONGODB_URI": "mongodb://localhost:27017/yugioh_test",
    "MONGODB_CONNECTION_STRING": "mongodb://localhost:27017/yugioh_test",
    "ALLOW_START_WITHOUT_DATABASE": "true",
    "DISABLE_DB_CONNECTION": "1",
    "DEBUG": "false",
    "FLASK_ENV": "testing",
    "SECRET_KEY": "test-secret-key",
    "LOG_LEVEL": "WARNING",
    "ENVIRONMENT": "testing",  # Add explicit environment flag
})

# Import the application modules
import sys
import tempfile
from typing import Any, Dict, Generator
from unittest.mock import Mock, patch, MagicMock

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pymongo import MongoClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ygoapi.app import create_app


@pytest.fixture(scope="function")  # Changed from "session" to "function" for proper isolation
def app() -> Flask:
    """Create and configure a test Flask application instance.

    This fixture creates a Flask app with test configuration that isolates
    tests from production data and settings. Each test gets a fresh app instance.
    """
    # Create comprehensive mock collections with all required methods
    def create_mock_collection():
        mock_collection = MagicMock()
        # Database operation methods
        mock_collection.find.return_value = []
        mock_collection.find_one.return_value = None
        mock_collection.insert_one.return_value = MagicMock(inserted_id="test_id")
        mock_collection.insert_many.return_value = MagicMock(inserted_ids=["test_id1", "test_id2"])
        mock_collection.update_one.return_value = MagicMock(modified_count=1)
        mock_collection.update_many.return_value = MagicMock(modified_count=1)
        mock_collection.delete_many.return_value = MagicMock(deleted_count=1)
        mock_collection.delete_one.return_value = MagicMock(deleted_count=1)
        mock_collection.estimated_document_count.return_value = 0
        mock_collection.count_documents.return_value = 0
        mock_collection.create_index.return_value = "test_index"
        mock_collection.aggregate.return_value = []
        return mock_collection

    # Create comprehensive mock database with all required methods
    def create_mock_database():
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=create_mock_collection())
        mock_db.get_collection = MagicMock(return_value=create_mock_collection())
        mock_db.list_collection_names.return_value = ["card_sets", "card_variants", "price_cache"]
        mock_db.create_collection.return_value = create_mock_collection()
        return mock_db

    # Create comprehensive mock client with all required methods
    def create_mock_client():
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=create_mock_database())
        mock_client.get_default_database.return_value = create_mock_database()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client.close.return_value = None
        return mock_client

    # Mock all external dependencies and validation comprehensively
    with patch("ygoapi.database.test_database_connection", return_value=True), \
         patch("ygoapi.database.DatabaseManager.test_connection", return_value=True), \
         patch("ygoapi.database.DatabaseManager.get_client", return_value=create_mock_client()), \
         patch("ygoapi.database.DatabaseManager.get_database", return_value=create_mock_database()), \
         patch("ygoapi.database.DatabaseManager.get_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.DatabaseManager.get_card_sets_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.DatabaseManager.get_card_variants_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.DatabaseManager.get_price_cache_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.get_database_manager") as mock_get_manager, \
         patch("ygoapi.database.get_mongo_client", return_value=create_mock_client()), \
         patch("ygoapi.database.get_database", return_value=create_mock_database()), \
         patch("ygoapi.database.get_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.get_card_sets_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.get_card_variants_collection", return_value=create_mock_collection()), \
         patch("ygoapi.database.get_price_cache_collection", return_value=create_mock_collection()), \
         patch("ygoapi.memory_manager.get_memory_manager") as mock_memory:
        
        # Mock database manager singleton
        mock_manager = MagicMock()
        mock_manager.get_client.return_value = create_mock_client()
        mock_manager.get_database.return_value = create_mock_database() 
        mock_manager.get_collection.return_value = create_mock_collection()
        mock_manager.get_card_sets_collection.return_value = create_mock_collection()
        mock_manager.get_card_variants_collection.return_value = create_mock_collection()
        mock_manager.get_price_cache_collection.return_value = create_mock_collection()
        mock_manager.test_connection.return_value = True
        mock_get_manager.return_value = mock_manager

        # Mock memory manager with proper serializable responses
        mock_memory_instance = Mock()
        mock_memory_instance.limit_mb = 512
        mock_memory_instance.register_cleanup_callback = Mock()
        mock_memory_instance.get_current_memory_usage.return_value = {
            "rss_mb": 128.5,
            "vms_mb": 256.0,
            "percent": 12.5,
            "limit_mb": 512,
            "usage_ratio": 0.25
        }

        # Create a proper decorator mock that preserves function attributes
        def mock_decorator(func):
            # Preserve the original function's attributes
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            wrapper.__name__ = func.__name__
            wrapper.__doc__ = func.__doc__
            return wrapper

        mock_memory_instance.memory_limit_decorator = Mock(side_effect=mock_decorator)
        mock_memory.return_value = mock_memory_instance

        # Create a fresh Flask app instance for each test
        app = create_app()
        app.config.update(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "test-secret-key",
                "DEBUG": False,
            }
        )

        yield app


@pytest.fixture(scope="function")
def client(app: Flask) -> FlaskClient:
    """Create a test client for the Flask application.

    Args:
        app: The Flask application fixture

    Returns:
        FlaskClient: Test client for making HTTP requests
    """
    return app.test_client()


@pytest.fixture(scope="function")
def test_db():
    """Create a test database connection with cleanup.

    This fixture provides a clean database state for each test.
    """
    # Use a test-specific database
    client = MongoClient("mongodb://localhost:27017/")
    db = client["yugioh_test"]

    yield db

    # Cleanup: Drop all collections after each test
    for collection_name in db.list_collection_names():
        db[collection_name].drop()

    client.close()


@pytest.fixture(scope="function")
def mock_ygoprodeck_api():
    """Mock YGOProDeck API responses for consistent testing.

    Returns:
        Mock: Configured mock object for YGOProDeck API calls
    """
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
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
                "card_sets": [
                    {
                        "set_name": "Legend of Blue Eyes White Dragon",
                        "set_code": "LOB-001",
                        "set_rarity": "Ultra Rare",
                        "set_price": "291.46",
                    }
                ],
                "card_images": [
                    {
                        "id": 46986414,
                        "image_url": "https://images.ygoprodeck.com/images/cards/46986414.jpg",
                        "image_url_small": "https://images.ygoprodeck.com/images/cards_small/46986414.jpg",
                    }
                ],
            }
        ]
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        yield mock_get


@pytest.fixture(scope="function")
def mock_tcgplayer_api():
    """Mock TCGPlayer price scraping responses for testing.

    Returns:
        Mock: Configured mock object for TCGPlayer scraping
    """
    mock_prices = {"low": 15.99, "market": 25.50, "high": 45.00, "currency": "USD"}

    with patch(
        "ygoapi.price_scraping.scrape_tcgplayer_prices", return_value=mock_prices
    ) as mock_scraper:
        yield mock_scraper


@pytest.fixture(scope="function")
def sample_card_data() -> Dict[str, Any]:
    """Provide sample card data for testing.

    Returns:
        Dict: Sample card data matching the application's data model
    """
    return {
        "id": 46986414,
        "name": "Blue-Eyes White Dragon",
        "type": "Normal Monster",
        "desc": "This legendary dragon is a powerful engine of destruction.",
        "atk": 3000,
        "def": 2500,
        "level": 8,
        "race": "Dragon",
        "attribute": "LIGHT",
        "set_code": "LOB-001",
        "rarity": "Ultra Rare",
        "image_url": "https://images.ygoprodeck.com/images/cards/46986414.jpg",
    }


@pytest.fixture(scope="function")
def sample_price_data() -> Dict[str, Any]:
    """Provide sample price data for testing.

    Returns:
        Dict: Sample price data matching the application's data model
    """
    return {
        "card_id": "46986414",
        "tcgplayer_id": "12345",
        "prices": {"low": 15.99, "market": 25.50, "high": 45.00},
        "last_scraped": "2025-07-16T10:00:00Z",
        "currency": "USD",
    }


@pytest.fixture(scope="function")
def sample_session_data() -> Dict[str, Any]:
    """Provide sample session data for testing.

    Returns:
        Dict: Sample session data matching the application's data model
    """
    return {
        "user_id": "test_user_123",
        "session_name": "Test Pack Opening",
        "cards": [
            {
                "card_id": "46986414",
                "name": "Blue-Eyes White Dragon",
                "rarity": "Ultra Rare",
                "price": 25.50,
            }
        ],
        "total_value": 25.50,
        "created_at": "2025-07-16T10:00:00Z",
        "updated_at": "2025-07-16T10:00:00Z",
    }


@pytest.fixture(scope="function", autouse=True)
def isolate_external_calls():
    """Automatically isolate external API calls for all tests.

    This fixture ensures no real external API calls are made during testing.
    """
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        # Default mock responses
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"data": []}
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True}

        yield {"get": mock_get, "post": mock_post}


@pytest.fixture(scope="function")
def auth_headers() -> Dict[str, str]:
    """Provide authentication headers for API testing.

    Returns:
        Dict: HTTP headers for authenticated requests
    """
    return {"Content-Type": "application/json", "Authorization": "Bearer test-token"}


# Test data validation helpers
def validate_card_response(response_data: Dict[str, Any]) -> bool:
    """Validate card response data structure.

    Args:
        response_data: Response data to validate

    Returns:
        bool: True if valid card response structure
    """
    required_fields = ["id", "name", "type", "desc"]
    return all(field in response_data for field in required_fields)


def validate_price_response(response_data: Dict[str, Any]) -> bool:
    """Validate price response data structure.

    Args:
        response_data: Response data to validate

    Returns:
        bool: True if valid price response structure
    """
    required_fields = ["card_id", "prices"]
    return all(field in response_data for field in required_fields)


# Performance testing helpers
@pytest.fixture(scope="function")
def performance_threshold():
    """Set performance thresholds for testing.

    Returns:
        Dict: Performance thresholds for various operations
    """
    return {
        "api_response_time": 2.0,  # seconds
        "database_query_time": 0.1,  # seconds
        "external_api_timeout": 5.0,  # seconds
    }
