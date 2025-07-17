#!/usr/bin/env python3
"""
Installation verification script for YGO Card Sets API

This script verifies that all required dependencies are installed
and can be imported successfully.
"""

import importlib
import sys
import traceback


def check_import(module_name, package_name=None):
    """Check if a module can be imported."""
    try:
        importlib.import_module(module_name)
        print(f"✓ {package_name or module_name}")
        return True
    except ImportError as e:
        print(f"✗ {package_name or module_name}: {e}")
        return False


def main():
    """Main verification function."""
    print("YGO Card Sets API - Installation Verification")
    print("=" * 50)

    # Core dependencies
    dependencies = [
        ("flask", "Flask"),
        ("requests", "Requests"),
        ("dotenv", "python-dotenv"),
        ("pymongo", "PyMongo"),
        ("playwright", "Playwright"),
        ("pydantic", "Pydantic"),
        ("psutil", "psutil"),
        ("certifi", "certifi"),
        ("urllib3", "urllib3"),
        ("OpenSSL", "pyOpenSSL"),
    ]

    print("\nChecking core dependencies:")
    print("-" * 30)

    all_good = True
    for module, package in dependencies:
        if not check_import(module, package):
            all_good = False

    # Check if the application can be created
    print("\nChecking application modules:")
    print("-" * 30)

    try:
        # Check if our modules can be imported
        app_modules = [
            "ygoapi.config",
            "ygoapi.models",
            "ygoapi.utils",
            "ygoapi.memory_manager",
            "ygoapi.database",
            "ygoapi.card_services",
            "ygoapi.price_scraping",
            "ygoapi.routes",
            "ygoapi.app",
        ]

        for module in app_modules:
            if not check_import(module):
                all_good = False

    except Exception as e:
        print(f"✗ Error checking application modules: {e}")
        all_good = False

    print("\n" + "=" * 50)
    if all_good:
        print("✓ All dependencies are installed and working!")
        print("\nNext steps:")
        print("1. Copy .env.example to .env and configure your settings")
        print("2. Run: python main_modular.py")
        print("3. Visit: http://localhost:8081/health")
        return 0
    else:
        print("✗ Some dependencies are missing or broken.")
        print("\nTroubleshooting:")
        print("1. Check INSTALLATION.md for common issues")
        print("2. Try: pip install -r requirements.txt --upgrade")
        print("3. For Python 3.13: pip install -r requirements.txt --upgrade --force-reinstall")
        return 1


if __name__ == "__main__":
    sys.exit(main())
