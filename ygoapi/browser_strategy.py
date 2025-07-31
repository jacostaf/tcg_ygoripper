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
    
    # Check if we're on Render
    if os.getenv('RENDER'):
        logger.info("Detected Render environment - using Optimized Browser Pool for memory-aware scaling")
        return 'optimized'
    
    # Check memory limit if available
    memory_limit_mb = int(os.getenv('MEMORY_LIMIT_MB', '0'))
    if memory_limit_mb > 0 and memory_limit_mb < 1024:
        logger.info(f"Memory limit {memory_limit_mb}MB < 1024MB - using Optimized Browser Pool")
        return 'optimized'
    
    # Default to pool for better performance
    logger.info("Using Browser Pool for optimal performance")
    return 'pool'
