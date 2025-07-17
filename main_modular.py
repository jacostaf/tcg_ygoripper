#!/usr/bin/env python3
"""
YGO Card Sets API - Main Entry Point

This is the main entry point for the YGO Card Sets API application.
The application has been modularized into the ygoapi package for better
maintainability, memory management, and code organization.

Features:
- Modular architecture with separate services
- Memory management with MEM_LIMIT enforcement
- Card set and variant management
- Price scraping with caching
- MongoDB integration
- Rate limiting compliance
"""

import os
import sys

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ygoapi.app import run_app

if __name__ == "__main__":
    run_app()
