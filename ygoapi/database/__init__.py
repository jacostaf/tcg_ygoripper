"""
Database module for YGO API

MongoDB connection management and database operations.
"""

from .manager import DatabaseManager, get_database_manager

__all__ = ['DatabaseManager', 'get_database_manager']