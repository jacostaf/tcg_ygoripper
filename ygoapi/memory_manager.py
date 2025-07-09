"""
Memory Manager Module

Provides memory monitoring and management capabilities with MEM_LIMIT enforcement.
Tracks memory usage and takes appropriate action when limits are approached.
"""

import os
import gc
import psutil
import logging
from typing import Optional, Callable, Dict, Any
from functools import wraps

logger = logging.getLogger(__name__)

class MemoryManager:
    """
    Memory manager that enforces memory limits and provides monitoring capabilities.
    
    Uses the MEM_LIMIT environment variable to set memory limits in MB.
    When memory usage approaches the limit, it triggers garbage collection and
    optional cleanup callbacks.
    """
    
    def __init__(self, limit_mb: Optional[int] = None):
        """
        Initialize the memory manager.
        
        Args:
            limit_mb: Memory limit in MB. If None, reads from MEM_LIMIT env var.
        """
        self.limit_mb = limit_mb or int(os.getenv('MEM_LIMIT', '512'))
        self.limit_bytes = self.limit_mb * 1024 * 1024
        self.warning_threshold = 0.8  # Warn at 80% of limit
        self.critical_threshold = 0.9  # Critical at 90% of limit
        self.cleanup_callbacks: Dict[str, Callable] = {}
        self.process = psutil.Process()
        
        logger.info(f"Memory manager initialized with limit: {self.limit_mb}MB")
    
    def get_current_memory_usage(self) -> Dict[str, Any]:
        """
        Get current memory usage statistics.
        
        Returns:
            Dict containing memory usage information
        """
        memory_info = self.process.memory_info()
        memory_percent = self.process.memory_percent()
        usage_mb = memory_info.rss / 1024 / 1024
        usage_percentage = (memory_info.rss / self.limit_bytes) * 100
        
        return {
            'rss_mb': usage_mb,
            'vms_mb': memory_info.vms / 1024 / 1024,
            'percent': memory_percent,
            'usage_percentage': usage_percentage,
            'usage_mb': usage_mb,
            'limit_mb': self.limit_mb,
            'usage_ratio': memory_info.rss / self.limit_bytes,
            'warning_threshold': self.warning_threshold,
            'critical_threshold': self.critical_threshold
        }
    
    def is_memory_critical(self) -> bool:
        """Check if memory usage is at critical levels."""
        usage = self.get_current_memory_usage()
        return usage['usage_ratio'] >= self.critical_threshold
    
    def is_memory_warning(self) -> bool:
        """Check if memory usage is at warning levels."""
        usage = self.get_current_memory_usage()
        return usage['usage_ratio'] >= self.warning_threshold
    
    def register_cleanup_callback(self, name: str, callback: Callable):
        """
        Register a cleanup callback that will be called when memory is critical.
        
        Args:
            name: Name of the callback
            callback: Function to call for cleanup
        """
        self.cleanup_callbacks[name] = callback
        logger.debug(f"Registered cleanup callback: {name}")
    
    def force_cleanup(self):
        """Force garbage collection and run cleanup callbacks."""
        logger.info("Forcing memory cleanup...")
        
        # Run registered cleanup callbacks
        for name, callback in self.cleanup_callbacks.items():
            try:
                logger.debug(f"Running cleanup callback: {name}")
                callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback {name}: {e}")
        
        # Force garbage collection
        collected = gc.collect()
        logger.info(f"Garbage collection freed {collected} objects")
        
        # Log memory usage after cleanup
        usage = self.get_current_memory_usage()
        logger.info(f"Memory usage after cleanup: {usage['rss_mb']:.1f}MB ({usage['usage_ratio']:.1%})")
    
    def check_memory_and_cleanup(self):
        """Check memory usage and perform cleanup if necessary."""
        if self.is_memory_critical():
            usage = self.get_current_memory_usage()
            logger.warning(f"Memory usage critical: {usage['rss_mb']:.1f}MB ({usage['usage_ratio']:.1%})")
            self.force_cleanup()
            
            # Check if cleanup helped
            new_usage = self.get_current_memory_usage()
            if new_usage['usage_ratio'] >= self.critical_threshold:
                logger.error(f"Memory usage still critical after cleanup: {new_usage['rss_mb']:.1f}MB")
                
        elif self.is_memory_warning():
            usage = self.get_current_memory_usage()
            logger.info(f"Memory usage warning: {usage['rss_mb']:.1f}MB ({usage['usage_ratio']:.1%})")
    
    def memory_limit_decorator(self, func: Callable) -> Callable:
        """
        Decorator that checks memory usage before and after function execution.
        
        Args:
            func: Function to wrap
            
        Returns:
            Wrapped function with memory monitoring
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check memory before execution
            self.check_memory_and_cleanup()
            
            try:
                result = func(*args, **kwargs)
                
                # Check memory after execution
                self.check_memory_and_cleanup()
                
                return result
            except Exception as e:
                # If function fails, still check memory
                self.check_memory_and_cleanup()
                raise e
        
        return wrapper

# Global memory manager instance
_memory_manager: Optional[MemoryManager] = None

def get_memory_manager() -> MemoryManager:
    """Get the global memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

def monitor_memory(func: Callable) -> Callable:
    """
    Decorator to monitor memory usage for a function.
    
    Args:
        func: Function to monitor
        
    Returns:
        Decorated function with memory monitoring
    """
    memory_manager = get_memory_manager()
    return memory_manager.memory_limit_decorator(func)

def get_memory_stats() -> Dict[str, Any]:
    """Get current memory statistics."""
    memory_manager = get_memory_manager()
    return memory_manager.get_current_memory_usage()

def force_memory_cleanup():
    """Force memory cleanup."""
    memory_manager = get_memory_manager()
    memory_manager.force_cleanup()