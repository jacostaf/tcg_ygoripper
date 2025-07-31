"""
Browser Strategy Selector

Automatically selects the best browser strategy based on environment:
- Browser Manager: For memory-constrained environments (Render, small VPS)
- Browser Pool: For environments with adequate memory (local dev, production servers)
"""

import os
import logging
from typing import Union

logger = logging.getLogger(__name__)

def get_browser_strategy() -> str:
    """
    Determine the best browser strategy based on environment.
    
    Returns:
        'pool' for BrowserPool (performance-optimized)
        'manager' for BrowserManager (memory-efficient)
        'optimized' for OptimizedBrowserPool (memory-aware)
    """
    # Check for explicit override
    strategy = os.getenv('BROWSER_STRATEGY', '').lower()
    if strategy in ['pool', 'manager', 'optimized']:
        logger.info(f"Using explicitly set browser strategy: {strategy}")
        return strategy
    
    # Check if we're on Render or have memory constraints
    if os.getenv('RENDER'):
        logger.info("Detected Render environment - using Optimized Browser Pool with memory awareness")
        return 'optimized'
    
    # Check memory limit (MEM_LIMIT is set to 512 on Render)
    memory_limit_mb = int(os.getenv('MEM_LIMIT', '0'))
    if memory_limit_mb > 0 and memory_limit_mb <= 512:
        logger.info(f"Memory limit {memory_limit_mb}MB <= 512MB - using Optimized Browser Pool")
        return 'optimized'
    
    # Default to pool for better performance
    logger.info("Using Browser Pool for optimal performance")
    return 'pool'
