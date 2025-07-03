"""
Rarity-related utility functions for the YGOAPI application.

This module provides functions for normalizing and matching card rarities
across different data sources (TCGPlayer, YGO API, etc.).
"""
import re
from typing import List, Set, Dict, Any, Optional

def normalize_rarity(rarity: str) -> str:
    """
    Normalize rarity string for consistent comparison.
    
    Args:
        rarity: The rarity string to normalize
        
    Returns:
        Normalized rarity string
    """
    if not rarity:
        return ""
    
    rarity = rarity.strip().lower()
    
    # Rarity hierarchy from highest to lowest
    if any(x in rarity for x in ['ghost rare', 'ghost']):
        return "Ghost Rare"
    if any(x in rarity for x in ['starlight rare', 'str']):
        return "Starlight Rare"
    if any(x in rarity for x in ['collector\'s rare', 'cr']):
        return "Collector's Rare"
    if any(x in rarity for x in ['platinum secret rare', 'plsr']):
        return "Platinum Secret Rare"
    if any(x in rarity for x in ['prismatic secret rare', 'pscr']):
        return "Prismatic Secret Rare"
    if any(x in rarity for x in ['secret rare', 'scr']):
        return "Secret Rare"
    if any(x in rarity for x in ['ultimate rare', 'ulti']):
        return "Ultimate Rare"
    if any(x in rarity for x in ['ultra rare', 'ultra', 'ur']):
        return "Ultra Rare"
    if any(x in rarity for x in ['super rare', 'spr', 'sr']):
        return "Super Rare"
    if any(x in rarity for x in ['rare', 'r']):
        return "Rare"
    if any(x in rarity for x in ['common', 'c']):
        return "Common"
    if any(x in rarity for x in ['short print', 'sp']):
        return "Short Print"
    if any(x in rarity for x in ['parallel rare', 'pr']):
        return "Parallel Rare"
    if any(x in rarity for x in ['platinum rare', 'plr']):
        return "Platinum Rare"
    if any(x in rarity for x in ['gold rare', 'gr']):
        return "Gold Rare"
    if any(x in rarity for x in ['gold secret rare', 'gsr']):
        return "Gold Secret Rare"
    if any(x in rarity for x in ['parallel rare', 'par']):
        return "Parallel Rare"
    if any(x in rarity for x in ['mosaic rare', 'msr']):
        return "Mosaic Rare"
    if any(x in rarity for x in ['starfoil rare', 'sff']):
        return "Starfoil Rare"
    if any(x in rarity for x in ['shatterfoil rare', 'shf']):
        return "Shatterfoil Rare"
    if any(x in rarity for x in ['duel terminal normal parallel rare', 'dtnp']):
        return "Duel Terminal Normal Parallel Rare"
    if any(x in rarity for x in ['duel terminal normal rare parallel rare', 'dtnrp']):
        return "Duel Terminal Normal Rare Parallel Rare"
    if any(x in rarity for x in ['duel terminal rare parallel rare', 'dtrp']):
        return "Duel Terminal Rare Parallel Rare"
    if any(x in rarity for x in ['duel terminal super parallel rare', 'dtsp']):
        return "Duel Terminal Super Parallel Rare"
    if any(x in rarity for x in ['duel terminal ultra parallel rare', 'dtup']):
        return "Duel Terminal Ultra Parallel Rare"
    if any(x in rarity for x in ['duel terminal secret parallel rare', 'dtsc']):
        return "Duel Terminal Secret Parallel Rare"
    if any(x in rarity for x in ['duel terminal rare', 'dtr']):
        return "Duel Terminal Rare"
    if any(x in rarity for x in ['duel terminal super rare', 'dtsr']):
        return "Duel Terminal Super Rare"
    if any(x in rarity for x in ['duel terminal ultra rare', 'dtur']):
        return "Duel Terminal Ultra Rare"
    if any(x in rarity for x in ['duel terminal secret rare', 'dtsc']):
        return "Duel Terminal Secret Rare"
    if any(x in rarity for x in ['duel terminal normal parallel rare', 'dtnp']):
        return "Duel Terminal Normal Parallel Rare"
    if any(x in rarity for x in ['duel terminal normal rare parallel rare', 'dtnrp']):
        return "Duel Terminal Normal Rare Parallel Rare"
    
    # Fallback: capitalize first letter of each word
    return ' '.join(word.capitalize() for word in rarity.split())

def normalize_rarity_for_matching(rarity: str) -> List[str]:
    """
    Generate multiple normalized forms of a rarity for better matching.
    
    Args:
        rarity: The rarity string to normalize
        
    Returns:
        List of possible normalized forms of the rarity
    """
    if not rarity:
        return []
    
    normalized = set()
    rarity = rarity.strip().lower()
    
    # Add the fully normalized version
    normalized.add(normalize_rarity(rarity))
    
    # Add common abbreviations and variations
    if 'secret' in rarity:
        normalized.update(['Secret Rare', 'ScR', 'SCR'])
    if 'ultra' in rarity:
        normalized.update(['Ultra Rare', 'UR', 'Ultra'])
    if 'super' in rarity:
        normalized.update(['Super Rare', 'SR', 'Super'])
    if 'rare' in rarity and 'super' not in rarity and 'ultra' not in rarity and 'secret' not in rarity:
        normalized.update(['Rare', 'R'])
    if 'common' in rarity:
        normalized.update(['Common', 'C'])
    if 'ghost' in rarity:
        normalized.update(['Ghost Rare', 'GHR', 'Ghost'])
    if 'starlight' in rarity:
        normalized.update(['Starlight Rare', 'StR', 'Starlight'])
    if 'collector' in rarity:
        normalized.update(["Collector's Rare", 'CR', 'Collectors Rare'])
    if 'platinum' in rarity and 'secret' in rarity:
        normalized.update(['Platinum Secret Rare', 'PLSR'])
    if 'platinum' in rarity and 'secret' not in rarity:
        normalized.update(['Platinum Rare', 'PLR'])
    if 'gold' in rarity and 'secret' in rarity:
        normalized.update(['Gold Secret Rare', 'GSR'])
    if 'gold' in rarity and 'secret' not in rarity:
        normalized.update(['Gold Rare', 'GR'])
    if 'parallel' in rarity:
        normalized.update(['Parallel Rare', 'PAR'])
    if 'mosaic' in rarity:
        normalized.update(['Mosaic Rare', 'MSR'])
    if 'starfoil' in rarity:
        normalized.update(['Starfoil Rare', 'SFF'])
    if 'shatterfoil' in rarity:
        normalized.update(['Shatterfoil Rare', 'SHF'])
    
    # Add the original string if it's not empty
    if rarity:
        normalized.add(rarity.strip())
    
    return list(normalized)

def is_rarity_match(rarity1: str, rarity2: str) -> bool:
    """
    Check if two rarity strings match, considering all possible variations.
    
    Args:
        rarity1: First rarity string
        rarity2: Second rarity string
        
    Returns:
        True if the rarities match, False otherwise
    """
    if not rarity1 or not rarity2:
        return False
    
    # Direct match
    if rarity1.lower() == rarity2.lower():
        return True
    
    # Normalize both rarities and check for matches
    norm1 = normalize_rarity(rarity1)
    norm2 = normalize_rarity(rarity2)
    
    if norm1 and norm2 and norm1.lower() == norm2.lower():
        return True
    
    # Check all possible variations
    variations1 = normalize_rarity_for_matching(rarity1)
    variations2 = normalize_rarity_for_matching(rarity2)
    
    return any(v1.lower() == v2.lower() 
              for v1 in variations1 
              for v2 in variations2)
