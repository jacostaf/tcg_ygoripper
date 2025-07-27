#!/usr/bin/env python3
"""
Requirements validation test script
Tests that all dependencies can be imported and basic functionality works
"""

import os
import sys


def test_requirements():
    """Test that all required packages can be imported"""
    try:
        # Test Flask
        import flask

        print(f"✓ Flask {flask.__version__} imported successfully")

        # Test requests
        import requests

        print(f"✓ Requests {requests.__version__} imported successfully")

        # Test python-dotenv
        import dotenv

        print("✓ python-dotenv imported successfully")

        # Test pymongo
        import pymongo

        print(f"✓ pymongo {pymongo.__version__} imported successfully")

        # Test bson (comes with pymongo)
        import bson

        print("✓ bson imported successfully")

        # Test playwright
        import playwright

        print("✓ playwright imported successfully")

        # Test pydantic
        import pydantic

        print(f"✓ pydantic {pydantic.__version__} imported successfully")

        # Test psutil
        import psutil

        print(f"✓ psutil {psutil.__version__} imported successfully")

        # Test SSL/TLS libraries
        import ssl

        print("✓ ssl imported successfully")

        import certifi

        print("✓ certifi imported successfully")

        import urllib3

        print("✓ urllib3 imported successfully")

        import OpenSSL

        print("✓ pyOpenSSL imported successfully")

        print("\n✅ All requirements imported successfully!")
        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False


def test_modular_app():
    """Test that modular app components can be imported"""
    try:
        # Test all modular components
        from ygoapi.card_services import card_set_service
        from ygoapi.config import validate_config
        from ygoapi.database import get_database_manager
        from ygoapi.memory_manager import MemoryManager
        from ygoapi.models import CardModel, CardVariantModel
        from ygoapi.price_scraping import price_scraping_service
        from ygoapi.routes import register_routes
        from ygoapi.utils import extract_art_version

        print("✅ All modular components imported successfully!")
        return True

    except ImportError as e:
        print(f"❌ Modular import error: {e}")
        return False


def test_flask_app_creation():
    """Test basic Flask app creation without database"""
    try:
        # Disable database connection for test
        os.environ["DISABLE_DB_CONNECTION"] = "1"

        from flask import Flask

        app = Flask(__name__)

        # Test that Flask app can be created
        print("✅ Flask app creation test passed!")
        return True

    except Exception as e:
        print(f"❌ Flask app creation error: {e}")
        return False


if __name__ == "__main__":
    print("🧪 Testing requirements.txt dependencies...")
    print("=" * 50)

    success = True

    # Test 1: Requirements import
    print("\n1. Testing package imports...")
    success &= test_requirements()

    # Test 2: Modular components
    print("\n2. Testing modular components...")
    success &= test_modular_app()

    # Test 3: Flask app creation
    print("\n3. Testing Flask app creation...")
    success &= test_flask_app_creation()

    print("\n" + "=" * 50)
    if success:
        print("🎉 All tests passed! requirements.txt is valid.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please check requirements.txt.")
        sys.exit(1)
