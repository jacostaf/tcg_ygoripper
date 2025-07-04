"""
Utilities Module

Provides utility functions for data processing, normalization, and cleaning
used throughout the YGO API application.
"""

import re
import logging
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime, timedelta, UTC
from .memory_manager import monitor_memory

logger = logging.getLogger(__name__)

@monitor_memory
def extract_art_version(card_name: str) -> Optional[str]:
    """
    Extract art version from card name (e.g., "1st Art", "2nd Art").
    
    Args:
        card_name: Card name to extract art version from
        
    Returns:
        Optional[str]: Art version if found, None otherwise
    """
    # Pattern to match art versions like "1st Art", "2nd Art", "3rd Art", etc.
    art_pattern = r'(\d+)(?:st|nd|rd|th)\s+Art'
    
    match = re.search(art_pattern, card_name, re.IGNORECASE)
    if match:
        return f"{match.group(1)} Art"
    
    return None

@monitor_memory
def normalize_rarity(rarity: str) -> str:
    """
    Normalize rarity string for consistent comparison.
    
    Args:
        rarity: Rarity string to normalize
        
    Returns:
        str: Normalized rarity string
    """
    if not rarity:
        return ""
    
    # Convert to lowercase and remove extra spaces
    normalized = re.sub(r'\s+', ' ', rarity.lower().strip())
    
    # Handle common abbreviations and variations
    replacements = {
        'qcsr': 'quarter century secret rare',
        'qcur': 'quarter century ultra rare',
        'psr': 'platinum secret rare',
        'ur': 'ultra rare',
        'sr': 'secret rare',
        'cr': 'common rare',
        'r': 'rare',
        'c': 'common',
        'spr': 'super rare',
        'scr': 'secret rare',
        'ulr': 'ultra rare',
        'gsr': 'ghost rare',
        'gr': 'ghost rare',
        'str': 'starlight rare',
        'stsr': 'starlight rare',
        'plr': 'platinum rare',
        'phr': 'pharaoh rare',
        'kcr': 'kaiba corporation rare',
        'mlr': 'millennium rare',
        'dnr': 'duel terminal normal parallel rare',
        'dtr': 'duel terminal rare parallel rare',
        'dspr': 'duel terminal super parallel rare',
        'dur': 'duel terminal ultra parallel rare',
        'dsr': 'duel terminal secret parallel rare',
        'npr': 'normal parallel rare',
        'spr': 'super parallel rare',
        'upr': 'ultra parallel rare',
        'scpr': 'secret parallel rare',
        'exsr': 'extra secret rare',
        'prsr': 'premium secret rare',
        'hosr': 'holographic secret rare',
        'shsr': 'short print secret rare',
        'ltsr': 'limited secret rare',
        'utsr': 'ultimate secret rare',
        'gosr': 'gold secret rare',
        'plsr': 'platinum secret rare',
        'bsr': 'black secret rare',
        'rsr': 'red secret rare',
        'blsr': 'blue secret rare',
        'grsr': 'green secret rare',
        'psr': 'purple secret rare',
        'wsr': 'white secret rare',
        'ysr': 'yellow secret rare',
        'osr': 'orange secret rare',
        'pksr': 'pink secret rare',
        'slsr': 'silver secret rare'
    }
    
    # Apply replacements
    for abbr, full_name in replacements.items():
        if normalized == abbr:
            normalized = full_name
            break
    
    return normalized

@monitor_memory
def normalize_rarity_for_matching(rarity: str) -> List[str]:
    """
    Generate multiple normalized forms of a rarity for better matching.
    
    Args:
        rarity: Rarity string to normalize
        
    Returns:
        List[str]: List of normalized rarity variants
    """
    if not rarity:
        return [""]
    
    normalized = normalize_rarity(rarity)
    variants = [normalized]
    
    # Handle Quarter Century variants
    if 'quarter century' in normalized:
        if 'secret' in normalized:
            variants.extend([
                'quarter century secret rare',
                '25th anniversary secret rare',
                'qcsr',
                'quarter century secret',
                '25th secret rare',
                '25th anniversary secret'
            ])
        elif 'ultra' in normalized:
            variants.extend([
                'quarter century ultra rare',
                '25th anniversary ultra rare',
                'qcur',
                'quarter century ultra',
                '25th ultra rare',
                '25th anniversary ultra'
            ])
    
    # Handle Platinum Secret Rare
    if 'platinum' in normalized and 'secret' in normalized:
        variants.extend([
            'platinum secret rare',
            'psr',
            'platinum secret'
        ])
    
    # Handle Ghost Rare variants
    if 'ghost' in normalized:
        variants.extend([
            'ghost rare',
            'gr',
            'ghost'
        ])
    
    # Handle Starlight Rare variants
    if 'starlight' in normalized:
        variants.extend([
            'starlight rare',
            'str',
            'stsr',
            'starlight'
        ])
    
    # Handle Ultimate Rare variants
    if 'ultimate' in normalized:
        variants.extend([
            'ultimate rare',
            'ur',
            'ultimate'
        ])
    
    # Handle Millennium variants
    if 'millennium' in normalized:
        variants.extend([
            'millennium rare',
            'millennium'
        ])
    
    # Handle 25th Anniversary variants
    if '25th anniversary' in normalized:
        if 'ultra' in normalized:
            variants.extend([
                '25th anniversary ultra rare',
                'quarter century ultra rare'
            ])
        elif 'secret' in normalized:
            variants.extend([
                '25th anniversary secret rare',
                'quarter century secret rare'
            ])
    
    # Handle 20th Secret Rare
    if '20th' in normalized and 'secret' in normalized:
        variants.extend([
            '20th secret rare'
        ])
    
    # Handle Extra Secret Rare (OCG)
    if 'extra secret' in normalized:
        variants.extend([
            'extra secret rare'
        ])
    
    # Handle Red/Blue Secret Rare (OCG)
    if 'red secret' in normalized:
        variants.extend([
            'red secret rare'
        ])
    
    if 'blue secret' in normalized:
        variants.extend([
            'blue secret rare'
        ])
    
    # Remove duplicates and return
    return list(set(variants))

@monitor_memory
def normalize_art_variant(art_variant: Optional[str]) -> Optional[str]:
    """
    Normalize art variant string for consistent comparison.
    
    Args:
        art_variant: Art variant string to normalize
        
    Returns:
        Optional[str]: Normalized art variant string
    """
    if not art_variant:
        return None
    
    # Remove extra spaces and convert to lowercase
    normalized = re.sub(r'\s+', ' ', art_variant.lower().strip())
    
    # Extract art number if present
    art_match = re.search(r'(\d+)(?:st|nd|rd|th)?\s*art', normalized)
    if art_match:
        return f"{art_match.group(1)} Art"
    
    return normalized

@monitor_memory
def clean_card_data(price_data: Dict) -> Dict:
    """
    Clean up card data before returning it in the response.
    
    Args:
        price_data: Dictionary containing card price data
        
    Returns:
        Dict: Cleaned card data
    """
    try:
        # Create a copy to avoid modifying the original
        cleaned_data = price_data.copy()
        
        # Remove MongoDB-specific fields that shouldn't be in the response
        fields_to_remove = ['_id', '_source', '_uploaded_at', '_created_at']
        for field in fields_to_remove:
            if field in cleaned_data:
                del cleaned_data[field]
        
        # Ensure price fields are properly formatted
        price_fields = ['tcgplayer_price', 'tcgplayer_market_price']
        for field in price_fields:
            if field in cleaned_data and cleaned_data[field] is not None:
                try:
                    cleaned_data[field] = float(cleaned_data[field])
                except (ValueError, TypeError):
                    cleaned_data[field] = None
        
        # Format datetime fields
        datetime_fields = ['last_price_updt', 'created_at']
        for field in datetime_fields:
            if field in cleaned_data and cleaned_data[field]:
                if isinstance(cleaned_data[field], datetime):
                    cleaned_data[field] = cleaned_data[field].isoformat()
        
        return cleaned_data
        
    except Exception as e:
        logger.error(f"Error cleaning card data: {e}")
        return price_data  # Return original if cleaning fails

@monitor_memory
def batch_process_generator(items: List[Any], batch_size: int = 100) -> Generator[List[Any], None, None]:
    """
    Process items in batches to optimize memory usage.
    
    Args:
        items: List of items to process
        batch_size: Size of each batch
        
    Yields:
        List[Any]: Batch of items
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]

@monitor_memory
def validate_card_number(card_number: str) -> bool:
    """
    Validate card number format.
    
    Args:
        card_number: Card number to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not card_number:
        return False
    
    # Basic pattern matching for common card number formats
    # Examples: LOB-001, SDK-001, RA04-EN016, etc.
    patterns = [
        r'^[A-Z]{2,4}-\d{3}$',  # Standard format like LOB-001
        r'^[A-Z]{2,4}-[A-Z]{2}\d{3}$',  # Format with language code like RA04-EN016
        r'^[A-Z]{2,4}-\d{2}$',  # Short format like SDK-01
        r'^[A-Z]{2,4}-[A-Z]{2}\d{2}$',  # Short format with language code
        r'^\d{8}$'  # Pure numeric format
    ]
    
    return any(re.match(pattern, card_number.upper()) for pattern in patterns)

@monitor_memory
def calculate_success_rate(processed: int, total: int) -> float:
    """
    Calculate success rate as a percentage.
    
    Args:
        processed: Number of successfully processed items
        total: Total number of items
        
    Returns:
        float: Success rate as a percentage
    """
    if total == 0:
        return 0.0
    return (processed / total) * 100

@monitor_memory
def generate_variant_id(card_id: int, set_code: str, set_rarity: str, art_variant: Optional[str] = None) -> str:
    """
    Generate a unique variant ID for a card.
    
    Args:
        card_id: Card ID
        set_code: Set code
        set_rarity: Set rarity
        art_variant: Art variant (optional)
        
    Returns:
        str: Unique variant ID
    """
    # Normalize inputs
    set_code = set_code.upper() if set_code else ""
    set_rarity = normalize_rarity(set_rarity)
    art_variant = normalize_art_variant(art_variant) or ""
    
    # Create variant ID
    variant_parts = [str(card_id), set_code, set_rarity]
    if art_variant:
        variant_parts.append(art_variant)
    
    return "_".join(variant_parts)

@monitor_memory
def is_cache_fresh(last_updated: datetime, cache_days: int = 7) -> bool:
    """
    Check if cached data is still fresh.
    
    Args:
        last_updated: Last update timestamp
        cache_days: Number of days to consider cache fresh
        
    Returns:
        bool: True if cache is fresh, False otherwise
    """
    if not last_updated:
        return False
    
    # Calculate expiry time
    expiry_time = last_updated + timedelta(days=cache_days)
    current_time = datetime.now(UTC)
    
    return current_time < expiry_time

@monitor_memory
def sanitize_string(value: str) -> str:
    """
    Sanitize string for safe storage and processing.
    
    Args:
        value: String to sanitize
        
    Returns:
        str: Sanitized string
    """
    if not value:
        return ""
    
    # Remove control characters and normalize whitespace
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
    sanitized = re.sub(r'\s+', ' ', sanitized)
    
    return sanitized.strip()

@monitor_memory
def parse_price_string(price_str: str) -> Optional[float]:
    """
    Parse price string to float.
    
    Args:
        price_str: Price string to parse
        
    Returns:
        Optional[float]: Parsed price or None if invalid
    """
    if not price_str:
        return None
    
    try:
        # Remove currency symbols and extra characters
        cleaned = re.sub(r'[^\d.]', '', price_str)
        if cleaned:
            return float(cleaned)
    except (ValueError, TypeError):
        pass
    
    return None

def get_current_utc_datetime() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)

def format_datetime_for_api(dt: datetime) -> str:
    """Format datetime for API response."""
    return dt.isoformat() if dt else ""