"""
Utilities Module

Provides utility functions for data processing, normalization, and cleaning
used throughout the YGO API application.
"""

import re
import logging
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime, timedelta, timezone
from .memory_manager import monitor_memory

logger = logging.getLogger(__name__)

@monitor_memory
def extract_art_version(card_name: str) -> Optional[str]:
    """
    Extract art version from card name using regex patterns for both numbered and named variants.
    
    Args:
        card_name: Card name to extract art version from
        
    Returns:
        Optional[str]: Art version if found, None otherwise
    """
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
    
    # Handle special cases for quarter century variations
    if 'quarter century' in normalized or '25th anniversary' in normalized:
        if 'secret' in normalized:
            return 'quarter century secret rare'
        elif 'ultra' in normalized:
            return 'quarter century ultra rare'
        elif 'rare' in normalized:
            return 'quarter century rare'
    
    # Handle Platinum variations
    if 'platinum' in normalized:
        if 'secret' in normalized:
            return 'platinum secret rare'
        return 'platinum rare'
    
    # Handle Prismatic variations  
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
    
    # Special handling for Ghost Rare variants
    if 'ghost' in normalized:
        if 'gold' in normalized:
            return 'ghost/gold rare'
        return 'ghost rare'
    
    # Special handling for Parallel Rare variants
    if 'parallel' in normalized:
        if 'ultra' in normalized:
            return 'ultra parallel rare'
        elif 'secret' in normalized:
            return 'parallel secret rare'
        return 'parallel rare'
    
    # Special handling for Gold Rare variants
    if 'gold' in normalized:
        if 'premium' in normalized:
            return 'premium gold rare'
        return 'gold rare'
    
    # Special handling for Duel Terminal Rare
    if 'duel terminal' in normalized:
        return 'duel terminal rare'
    
    # Special handling for Mosaic Rare
    if 'mosaic' in normalized:
        return 'mosaic rare'
    
    # Special handling for Shatterfoil Rare
    if 'shatterfoil' in normalized:
        return 'shatterfoil rare'
    
    # Special handling for Starfoil Rare
    if 'starfoil' in normalized:
        return 'starfoil rare'
    
    # Special handling for Hobby League Rare
    if 'hobby league' in normalized:
        return 'hobby league rare'
    
    # Special handling for Millennium Rare
    if 'millennium' in normalized:
        return 'millennium rare'
    
    # Special handling for 20th Secret Rare
    if '20th' in normalized and 'secret' in normalized:
        return '20th secret rare'
    
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
        return []
    
    # Start with the simple lowercased version like the original implementation
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
    
    # Handle Duel Terminal Rare
    if 'duel terminal' in normalized:
        variants.extend([
            'duel terminal rare',
            'dt rare'
        ])
    
    # Handle Mosaic Rare
    if 'mosaic' in normalized:
        variants.extend([
            'mosaic rare',
            'mosaic'
        ])
    
    # Handle Shatterfoil Rare
    if 'shatterfoil' in normalized:
        variants.extend([
            'shatterfoil rare',
            'shatterfoil'
        ])
    
    # Handle Starfoil Rare
    if 'starfoil' in normalized:
        variants.extend([
            'starfoil rare',
            'starfoil'
        ])
    
    # Handle Hobby League Rare
    if 'hobby league' in normalized:
        variants.extend([
            'hobby league rare',
            'hl rare'
        ])
    
    # Handle Millennium Rare
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
    if ('red' in normalized or 'blue' in normalized) and 'secret' in normalized:
        variants.extend([
            'red secret rare' if 'red' in normalized else 'blue secret rare'
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
    
    # Ensure last_updated is timezone-aware (assume UTC if naive)
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    
    # Calculate expiry time
    expiry_time = last_updated + timedelta(days=cache_days)
    current_time = datetime.now(timezone.utc)
    
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
def validate_input_security(value: str, field_name: str = "") -> bool:
    """
    Validate input for security threats like XSS and SQL injection.
    
    Args:
        value: Input value to validate
        field_name: Name of the field for logging
        
    Returns:
        bool: True if input is safe, False if potentially malicious
    """
    if not value:
        return True
    
    # Convert to lowercase for pattern matching
    value_lower = value.lower()
    
    # Check for XSS patterns
    xss_patterns = [
        r'<script[^>]*>',
        r'javascript:',
        r'on\w+\s*=',  # Event handlers like onclick=
        r'<iframe[^>]*>',
        r'<object[^>]*>',
        r'<embed[^>]*>',
        r'<link[^>]*>',
        r'<meta[^>]*>',
        r'<style[^>]*>',
        r'<img[^>]*onerror',
        r'<img[^>]*onload',
        r'vbscript:',
        r'expression\s*\(',
        r'url\s*\(',
        r'@import',
    ]
    
    # Check for SQL injection patterns
    sql_patterns = [
        r';\s*drop\s+table',
        r';\s*delete\s+from',
        r';\s*insert\s+into',
        r';\s*update\s+\w+\s+set',
        r'union\s+select',
        r'or\s+1\s*=\s*1',
        r'and\s+1\s*=\s*1',
        r'or\s+\'1\'\s*=\s*\'1\'',
        r'and\s+\'1\'\s*=\s*\'1\'',
        r'--\s*$',  # SQL comments
        r'/\*.*?\*/',  # SQL block comments
        r';\s*exec\s*\(',
        r';\s*sp_',
        r'xp_cmdshell',
        r';\s*shutdown',
    ]
    
    # Check for path traversal patterns
    path_patterns = [
        r'\.\./+',
        r'\.\.\\+',
        r'/etc/passwd',
        r'/proc/self',
        r'c:\\windows',
        r'%2e%2e%2f',  # URL encoded ../
        r'%2e%2e%5c',  # URL encoded ..\
    ]
    
    # Check for command injection patterns
    command_patterns = [
        r';\s*cat\s+',
        r';\s*ls\s+',
        r';\s*dir\s+',
        r';\s*rm\s+',
        r';\s*del\s+',
        r';\s*curl\s+',
        r';\s*wget\s+',
        r';\s*nc\s+',
        r';\s*netcat\s+',
        r'`[^`]*`',  # Backticks for command substitution
        r'\$\([^)]*\)',  # Command substitution
    ]
    
    all_patterns = xss_patterns + sql_patterns + path_patterns + command_patterns
    
    for pattern in all_patterns:
        if re.search(pattern, value_lower, re.IGNORECASE):
            logger.warning(f"Potentially malicious input detected in {field_name}: {pattern}")
            return False
    
    # Check for suspicious character sequences
    suspicious_chars = ['<script', '</script>', 'javascript:', 'vbscript:', 'data:', 'onload=', 'onerror=']
    for char_seq in suspicious_chars:
        if char_seq in value_lower:
            logger.warning(f"Suspicious character sequence detected in {field_name}: {char_seq}")
            return False
    
    return True

@monitor_memory
def validate_card_input(card_number: str = None, card_rarity: str = None, card_name: str = None, art_variant: str = None) -> tuple[bool, str]:
    """
    Validate card input parameters for security and format.
    
    Args:
        card_number: Card number to validate
        card_rarity: Card rarity to validate  
        card_name: Card name to validate
        art_variant: Art variant to validate
        
    Returns:
        tuple[bool, str]: (is_valid, error_message)
    """
    # Validate card_number if provided
    if card_number:
        if not validate_input_security(card_number, "card_number"):
            return False, "Invalid card number: contains potentially malicious content"
        
        # Basic format validation for card numbers
        if len(card_number) > 50:  # Reasonable length limit
            return False, "Invalid card number: too long"
            
        # Card numbers should only contain alphanumeric characters, hyphens, and underscores
        if not re.match(r'^[A-Za-z0-9\-_]+$', card_number):
            return False, "Invalid card number: contains invalid characters"
    
    # Validate card_rarity if provided
    if card_rarity:
        if not validate_input_security(card_rarity, "card_rarity"):
            return False, "Invalid card rarity: contains potentially malicious content"
            
        # Length validation
        if len(card_rarity) > 100:  # Reasonable length limit
            return False, "Invalid card rarity: too long"
            
        # Rarity should only contain letters, spaces, apostrophes, and common punctuation
        if not re.match(r'^[A-Za-z0-9\s\'\-\.\/\(\)]+$', card_rarity):
            return False, "Invalid card rarity: contains invalid characters"
    
    # Validate card_name if provided
    if card_name:
        if not validate_input_security(card_name, "card_name"):
            return False, "Invalid card name: contains potentially malicious content"
            
        # Length validation
        if len(card_name) > 200:  # Reasonable length limit
            return False, "Invalid card name: too long"
    
    # Validate art_variant if provided
    if art_variant:
        if not validate_input_security(art_variant, "art_variant"):
            return False, "Invalid art variant: contains potentially malicious content"
            
        # Length validation
        if len(art_variant) > 100:  # Reasonable length limit
            return False, "Invalid art variant: too long"
    
    return True, ""

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

@monitor_memory
def get_current_utc_datetime() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)

@monitor_memory
def format_datetime_for_api(dt: datetime) -> str:
    """Format datetime for API response."""
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT") if dt else ""


def extract_set_code(card_number: str) -> Optional[str]:
    """Extract set code from card number."""
    if not card_number:
        return None
    
    # Most Yu-Gi-Oh card numbers follow the pattern: SETCODE-REGION###
    # Handle both numeric and alphanumeric card numbers
    match = re.match(r'^([A-Z]+\d*)-[A-Z]{2}\d+$', card_number.upper())
    if match:
        set_code = match.group(1)
        return set_code
    
    # Fallback: try to extract the first part before the hyphen
    if '-' in card_number:
        potential_set_code = card_number.split('-')[0].upper()
        if len(potential_set_code) >= 2 and potential_set_code.isalpha():
            return potential_set_code
    
    return None


def map_rarity_to_tcgplayer_filter(rarity: str) -> Optional[str]:
    """Map YGO rarity to TCGPlayer rarity filter value."""
    if not rarity:
        return None
    
    rarity_lower = rarity.lower().strip()
    
    # Map common rarity variations to TCGPlayer filter values
    # These need to match exactly how they appear in TCGPlayer's filter dropdown
    rarity_mappings = {
        'platinum secret rare': 'Platinum Secret Rare',
        'quarter century secret rare': 'Quarter Century Secret Rare', 
        'secret rare': 'Secret Rare',
        'ultra rare': 'Ultra Rare',
        'super rare': 'Super Rare',
        'rare': 'Rare',
        'common': 'Common / Short Print',
        'common / short print': 'Common / Short Print',
        'starlight rare': 'Starlight Rare',
        'collector\'s rare': 'Collector\'s Rare',
        'collectors rare': 'Collector\'s Rare',
        'ghost rare': 'Ghost Rare',
        'ghost/gold rare': 'Ghost/Gold Rare',
        'gold rare': 'Gold Rare',
        'premium gold rare': 'Premium Gold Rare',
        'prismatic secret rare': 'Prismatic Secret Rare',
        'prismatic ultimate rare': 'Prismatic Ultimate Rare',
        'prismatic collector\'s rare': 'Prismatic Collector\'s Rare',
        'ultimate rare': 'Ultimate Rare',
        'starfoil rare': 'Starfoil Rare',
        'parallel rare': 'Parallel Rare',
        'ultra parallel rare': 'Ultra Parallel Rare',
        'parallel secret rare': 'Parallel Secret Rare',
        'duel terminal rare': 'Duel Terminal Rare',
        'mosaic rare': 'Mosaic Rare',
        'shatterfoil rare': 'Shatterfoil Rare',
        'hobby league rare': 'Hobby League Rare',
        'millennium rare': 'Millennium Rare',
        '20th secret rare': '20th Secret Rare',
        'quarter century ultra rare': 'Quarter Century Ultra Rare',
        'quarter century rare': 'Quarter Century Rare',
        'platinum rare': 'Platinum Rare'
    }
    
    tcgplayer_rarity = rarity_mappings.get(rarity_lower)
    if tcgplayer_rarity:
        return tcgplayer_rarity
    
    return None


def extract_booster_set_name(source_url: str) -> Optional[str]:
    """Extract booster set name from TCGPlayer URL."""
    if not source_url:
        return None
    
    try:
        # TCGPlayer URLs often contain set information in the path
        # Example: https://www.tcgplayer.com/product/626754/yugioh-quarter-century-stampede-black-metal-dragon-secret-rare
        
        # Look for yugioh-{set-name} pattern in TCGPlayer URLs
        set_match = re.search(r'/yugioh-([^/]+?)(?:-[^-/]*?-(?:secret|ultra|super|rare|common))', source_url, re.IGNORECASE)
        if set_match:
            set_name = set_match.group(1)
            # Clean and format set name
            set_name = set_name.replace('-', ' ').title()
            # Handle specific known abbreviations
            if 'quarter-century' in set_name.lower() or 'quarter century' in set_name.lower():
                return 'Quarter Century Stampede'
            return set_name
            
        # Fallback: look for any meaningful set identifier in the URL
        path_parts = source_url.split('/')
        for part in path_parts:
            if 'yugioh-' in part.lower() and len(part) > 10:
                set_candidate = part.replace('yugioh-', '').replace('-', ' ').title()
                # Remove card-specific terms
                set_candidate = re.sub(r'\b(Secret|Ultra|Super|Rare|Common)\b.*$', '', set_candidate, flags=re.IGNORECASE).strip()
                if len(set_candidate) > 3:  # Avoid single words
                    return set_candidate
                    
        return None
        
    except Exception as e:
        return None


def map_set_code_to_tcgplayer_name(set_code: str) -> Optional[str]:
    """Map YGO set code to TCGPlayer set name using MongoDB cache."""
    if not set_code:
        return None
    
    try:
        from .database import get_card_sets_collection
        
        # Get the sets collection
        sets_collection = get_card_sets_collection()
        
        if sets_collection is None:
            # Database not available, use fallback mappings
            fallback_mappings = {
                'RA04': 'Quarter Century Stampede',
                'RA03': 'Quarter Century Bonanza',
                'SUDA': 'Supreme Darkness',
                'BLTR': 'Battles of Legend: Terminal Revenge',
               # 'BLMM': 'Battles of Legend: Monster Mayhem'
            }
            
            return fallback_mappings.get(set_code.upper())
        
        # Search for the set by code (case-insensitive)
        set_document = sets_collection.find_one(
            {"set_code": {"$regex": f"^{re.escape(set_code)}$", "$options": "i"}},
            {"set_name": 1, "_id": 0}
        )
        
        if set_document and 'set_name' in set_document:
            set_name = set_document['set_name']
            return set_name
        else:
            # Fallback to hardcoded mappings for critical sets if MongoDB lookup fails
            fallback_mappings = {
                'RA04': 'Quarter Century Stampede',
                'RA03': 'Quarter Century Bonanza',
                'SUDA': 'Supreme Darkness',
                'BLTR': 'Battles of Legend: Terminal Revenge',
               # 'BLMM': 'Battles of Legend: Monster Mayhem'
            }
            
            return fallback_mappings.get(set_code.upper())
            
    except Exception as e:
        # Fallback to hardcoded mappings if MongoDB fails
        fallback_mappings = {
            'RA04': 'Quarter Century Stampede',
            'RA03': 'Quarter Century Bonanza', 
            'SUDA': 'Supreme Darkness',
            'BLTR': 'Battles of Legend: Terminal Revenge',
           # 'BLMM': 'Battles of Legend: Monster Mayhem'
        }
        
        return fallback_mappings.get(set_code.upper())


def filter_cards_by_set(cards_list: List[Dict], target_set_name: str) -> List[Dict]:
    """
    Filter cards to only include variants from the target set.
    
    Args:
        cards_list: List of card dictionaries from YGO API
        target_set_name: Name of the set to filter by
        
    Returns:
        List of filtered card dictionaries with only relevant set variants
    """
    if not cards_list or not target_set_name:
        return cards_list
    
    filtered_cards = []
    target_set_name_lower = target_set_name.lower().strip()
    
    for card in cards_list:
        # Create a copy of the card to avoid modifying the original
        filtered_card = card.copy()
        
        # Filter the card_sets array to only include the target set
        if 'card_sets' in card and isinstance(card['card_sets'], list):
            filtered_sets = []
            
            for card_set in card['card_sets']:
                set_name = card_set.get('set_name', '').lower().strip()
                
                # Check if this set matches the target set
                if set_name == target_set_name_lower:
                    filtered_sets.append(card_set)
            
            # Only include the card if it has variants in the target set
            if filtered_sets:
                filtered_card['card_sets'] = filtered_sets
                
                # Update card images to match the number of variants in the target set
                if 'card_images' in filtered_card and len(filtered_sets) < len(filtered_card['card_images']):
                    # Keep only as many images as we have set variants
                    filtered_card['card_images'] = filtered_card['card_images'][:len(filtered_sets)]
                
                # Add set-specific metadata
                filtered_card['target_set_variants'] = len(filtered_sets)
                filtered_card['target_set_name'] = target_set_name
                
                # Extract set codes for easy reference
                set_codes = [cs.get('set_code', '') for cs in filtered_sets]
                filtered_card['target_set_codes'] = set_codes
                
                filtered_cards.append(filtered_card)
    
    return filtered_cards