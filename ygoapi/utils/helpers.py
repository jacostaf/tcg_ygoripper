"""
Utility functions for YGO API

Data normalization, validation, and helper functions.
"""

import re
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

def extract_art_version(card_name: str) -> Optional[str]:
    """Extract art version from card name using regex patterns for both numbered and named variants."""
    if not card_name:
        return None
    
    # First, try numbered art variants
    numbered_patterns = [
        r'\[(\d+)(st|nd|rd|th)?\s*art\]',                         # "[9th Art]", "[7th art]"
        r'\[(\d+)(st|nd|rd|th)?\s*quarter\s*century.*?\]',        # "[7th Quarter Century Secret Rare]" 
        r'\[(\d+)(st|nd|rd|th)?\s*.*?secret.*?\]',                # "[7th Platinum Secret Rare]"
        r'\[(\d+)(st|nd|rd|th)?\]',                               # "[7th]", "[1]"
        r'\((\d+)(st|nd|rd|th)?\s*art\)',                         # "(7th art)", "(1st art)"
        r'\b(\d+)(st|nd|rd|th)?\s*art\b',                         # "7th art", "1st artwork"
        r'/(\d+)(st|nd|rd|th)?\-(?:quarter\-century|art)',        # "/7th-quarter-century", "/9th-art"
        r'magician\-(\d+)(st|nd|rd|th)?\-',                       # "dark-magician-7th-quarter"
        r'\-(\d+)(st|nd|rd|th)?\-(?:quarter|art)',                # "-7th-quarter", "-9th-art"
    ]
    
    for pattern in numbered_patterns:
        match = re.search(pattern, card_name, re.IGNORECASE)
        if match:
            art_version = match.group(1)
            logger.debug(f"Detected numbered art version: {art_version} using pattern '{pattern}' in: {card_name}")
            return art_version
    
    # Then, try named art variants (like "Arkana", "Joey Wheeler", etc.)
    named_patterns = [
        r'\b(arkana)\b',                                          # "arkana" (case insensitive)
        r'\b(joey\s+wheeler)\b',                                  # "joey wheeler"
        r'\b(kaiba)\b',                                           # "kaiba"
        r'\b(pharaoh)\b',                                         # "pharaoh"
        r'\b(anime)\b',                                           # "anime"
        r'\b(manga)\b',                                           # "manga"
        r'-([a-zA-Z]+(?:\s+[a-zA-Z]+)*)-',                       # Generic pattern for "-name-" format
        r'\(([a-zA-Z]+(?:\s+[a-zA-Z]+)*)\)',                     # Generic pattern for "(name)" format
    ]
    
    for pattern in named_patterns:
        match = re.search(pattern, card_name, re.IGNORECASE)
        if match:
            art_version = match.group(1).strip().title()  # Capitalize properly
            logger.debug(f"Detected named art version: '{art_version}' using pattern '{pattern}' in: {card_name}")
            return art_version
    
    return None

def normalize_rarity(rarity: str) -> str:
    """Normalize rarity string for consistent comparison."""
    if not rarity:
        return ''
    
    normalized = rarity.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)  # Replace multiple spaces
    normalized = re.sub(r'[-_]', ' ', normalized)  # Replace hyphens/underscores
    
    # Special handling for Quarter Century variants
    if 'quarter century' in normalized or '25th anniversary' in normalized:
        if 'secret' in normalized:
            return 'quarter century secret rare'
        elif 'ultra' in normalized:
            return 'quarter century ultra rare'
        elif 'rare' in normalized:
            return 'quarter century rare'
        return 'quarter century'
    
    # Special handling for Platinum Secret Rare
    if 'platinum' in normalized and 'secret' in normalized:
        return 'platinum secret rare'
    
    # Special handling for Prismatic variants
    if 'prismatic' in normalized:
        if 'secret' in normalized:
            return 'prismatic secret rare'
        elif 'collector' in normalized:
            return "prismatic collector's rare"
        elif 'ultimate' in normalized:
            return 'prismatic ultimate rare'
    
    # Special handling for Starlight Rare
    if 'starlight' in normalized:
        return 'starlight rare'
    
    # Special handling for Collector's Rare
    if 'collector' in normalized:
        return "collector's rare"
    
    # Special handling for Ghost variants
    if 'ghost' in normalized:
        if 'gold' in normalized:
            return 'ghost/gold rare'
        return 'ghost rare'
    
    # Special handling for Parallel variants
    if 'parallel' in normalized:
        if 'ultra' in normalized:
            return 'ultra parallel rare'
        elif 'secret' in normalized:
            return 'parallel secret rare'
        return 'parallel rare'
    
    # Special handling for Gold variants
    if 'gold' in normalized:
        if 'premium' in normalized:
            return 'premium gold rare'
        return 'gold rare'
    
    # Special handling for Platinum variants
    if 'platinum' in normalized:
        if 'secret' in normalized:
            return 'platinum secret rare'
        return 'platinum rare'
    
    # Special handling for other special rarities
    if 'duel terminal' in normalized:
        return 'duel terminal rare'
    if 'mosaic' in normalized:
        return 'mosaic rare'
    if 'shatterfoil' in normalized:
        return 'shatterfoil rare'
    if 'starfoil' in normalized:
        return 'starfoil rare'
    if 'hobby league' in normalized:
        return 'hobby league rare'
    if 'millennium' in normalized:
        return 'millennium rare'
    if '20th' in normalized and 'secret' in normalized:
        return '20th secret rare'
    
    return normalized

def normalize_rarity_for_matching(rarity: str) -> List[str]:
    """Generate multiple normalized forms of a rarity for better matching."""
    if not rarity:
        return []
    
    normalized = rarity.lower().strip()
    variants = [normalized]
    
    # Handle Quarter Century variants
    if 'quarter century' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'quarter century secret rare',
                'qcsr',
                '25th anniversary secret rare',
                'quarter century secret',
                'qc secret rare'
            ])
        elif 'ultra' in normalized:
            variants.extend([
                'quarter century ultra rare', 
                'qcur',
                '25th anniversary ultra rare'
            ])
    
    # Handle Platinum Secret Rare
    if 'platinum' in normalized and 'secret' in normalized:
        variants.extend([
            'platinum secret rare',
            'psr',
            'plat secret rare'
        ])
    
    # Handle Prismatic variants
    if 'prismatic' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'prismatic secret rare',
                'prismatic secret'
            ])
        elif 'collector' in normalized:
            variants.extend([
                'prismatic collector rare',
                "prismatic collector's rare"
            ])
        elif 'ultimate' in normalized:
            variants.extend([
                'prismatic ultimate rare'
            ])
    
    # Handle Starlight Rare
    if 'starlight' in normalized:
        variants.extend([
            'starlight rare',
            'starlight'
        ])
    
    # Handle Collector's Rare
    if 'collector' in normalized:
        variants.extend([
            "collector's rare",
            'collector rare',
            'collectors rare'
        ])
    
    # Handle Ghost Rare
    if 'ghost' in normalized:
        if 'gold' in normalized:
            variants.extend([
                'ghost gold rare',
                'ghost/gold rare'
            ])
        else:
            variants.extend([
                'ghost rare',
                'ghost'
            ])
    
    # Handle Ultimate Rare
    if 'ultimate' in normalized:
        variants.extend([
            'ultimate rare',
            'ultimate'
        ])
    
    # Handle Parallel variants
    if 'parallel' in normalized:
        if 'ultra' in normalized:
            variants.extend([
                'ultra parallel rare',
                'parallel ultra rare'
            ])
        elif 'secret' in normalized:
            variants.extend([
                'parallel secret rare'
            ])
        else:
            variants.extend([
                'parallel rare',
                'parallel'
            ])
    
    # Handle Gold variants
    if 'gold' in normalized:
        if 'premium' in normalized:
            variants.extend([
                'premium gold rare',
                'premium gold'
            ])
        else:
            variants.extend([
                'gold rare',
                'gold'
            ])
    
    # Handle Platinum variants
    if 'platinum' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'platinum secret rare',
                'psr',
                'plat secret rare'
            ])
        else:
            variants.extend([
                'platinum rare',
                'platinum'
            ])
    
    # Handle common abbreviations for standard rarities
    if 'secret rare' in normalized:
        variants.extend(['secret', 'sr'])
    if 'ultra rare' in normalized:
        variants.extend(['ultra', 'ur'])
    if 'super rare' in normalized:
        variants.extend(['super', 'sr'])
    if normalized == 'rare':
        variants.extend(['r'])
    if normalized == 'common':
        variants.extend(['c'])
    
    return list(set(variants))  # Remove duplicates

def normalize_art_variant(art_variant: Optional[str]) -> Optional[str]:
    """Normalize art variant to consistent format for cache operations."""
    if not art_variant or not art_variant.strip():
        return None
    
    art_variant_clean = art_variant.strip()
    
    # If it's a number, convert to ordinal format (e.g., "7" -> "7th")
    if art_variant_clean.isdigit():
        num = art_variant_clean
        suffix = "th"
        if num.endswith("1") and not num.endswith("11"):
            suffix = "st"
        elif num.endswith("2") and not num.endswith("12"):
            suffix = "nd"
        elif num.endswith("3") and not num.endswith("13"):
            suffix = "rd"
        return f"{num}{suffix}"
    
    # If it's already in ordinal format, keep as is
    if re.match(r'^\d+(st|nd|rd|th)(\s+[Aa]rt)?$', art_variant_clean):
        return art_variant_clean
    
    # For other formats, return as is
    return art_variant_clean

def clean_card_data(price_data: Dict) -> Dict:
    """Clean up card data before returning it in the response."""
    if not price_data:
        return {}
    
    cleaned_data = {}
    
    # Copy basic fields
    for field in ['card_number', 'card_name', 'card_art_variant', 'card_rarity', 
                  'booster_set_name', 'set_code', 'source_url', 'scrape_success']:
        if field in price_data:
            cleaned_data[field] = price_data[field]
    
    # Handle price fields with proper formatting
    price_fields = ['tcg_price', 'tcg_market_price', 'pc_ungraded_price', 
                   'pc_grade7', 'pc_grade8', 'pc_grade9', 'pc_grade9_5', 'pc_grade10']
    
    for field in price_fields:
        if field in price_data and price_data[field] is not None:
            try:
                # Convert to float and format to 2 decimal places
                price_value = float(price_data[field])
                cleaned_data[field] = round(price_value, 2)
            except (ValueError, TypeError):
                cleaned_data[field] = price_data[field]
    
    # Handle timestamp
    if 'last_price_updt' in price_data:
        timestamp = price_data['last_price_updt']
        if isinstance(timestamp, datetime):
            cleaned_data['last_price_updt'] = timestamp.isoformat()
        else:
            cleaned_data['last_price_updt'] = timestamp
    
    # Handle error messages
    if 'error_message' in price_data and price_data['error_message']:
        cleaned_data['error_message'] = price_data['error_message']
    
    return cleaned_data

def validate_card_rarity(card_number: str, card_rarity: str) -> bool:
    """Validate if the card rarity is reasonable for the given card number."""
    if not card_number or not card_rarity:
        return True  # Cannot validate without both pieces of information
    
    # List of special rarities that should be validated more strictly
    special_rarities = [
        'quarter century secret rare',
        'platinum secret rare',
        'starlight rare',
        'ghost rare',
        'collector\'s rare',
        'prismatic secret rare'
    ]
    
    normalized_rarity = normalize_rarity(card_rarity)
    
    # For special rarities, do additional validation
    if normalized_rarity in special_rarities:
        logger.info(f"🔍 Validating special rarity '{normalized_rarity}' for card {card_number}")
        # Additional validation logic could be added here
        return True
    
    return True

def format_memory_size(size_bytes: int) -> str:
    """Format memory size in bytes to human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def safe_float_conversion(value: Any) -> Optional[float]:
    """Safely convert a value to float, returning None if conversion fails."""
    if value is None:
        return None
    
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def batch_process_generator(items: List[Any], batch_size: int = 100):
    """Generator that yields batches of items for memory-efficient processing."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]

def truncate_long_strings(data: Dict, max_length: int = 500) -> Dict:
    """Truncate long strings in a dictionary to prevent memory issues."""
    if not isinstance(data, dict):
        return data
    
    truncated = {}
    for key, value in data.items():
        if isinstance(value, str) and len(value) > max_length:
            truncated[key] = value[:max_length] + "..."
        elif isinstance(value, dict):
            truncated[key] = truncate_long_strings(value, max_length)
        else:
            truncated[key] = value
    
    return truncated