"""
Utility functions and helpers for the YGOAPI application.

This package contains various utility modules used throughout the application.
"""
from .rarity import normalize_rarity, normalize_rarity_for_matching
from .scraping import (
    fetch_ygo_api,
    scrape_price_from_tcgplayer,
    extract_art_version,
    extract_rarity_from_tcgplayer,
    extract_prices_from_tcgplayer_dom,
    extract_prices_from_dom
)

__all__ = [
    'normalize_rarity',
    'normalize_rarity_for_matching',
    'fetch_ygo_api',
    'scrape_price_from_tcgplayer',
    'extract_art_version',
    'extract_rarity_from_tcgplayer',
    'extract_prices_from_tcgplayer_dom',
    'extract_prices_from_dom'
]
