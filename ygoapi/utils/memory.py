"""
Memory Optimization and Profiling Utilities

This module provides tools for monitoring and optimizing memory usage in the YGOAPI application.
It includes decorators for memory profiling and utilities for tracking memory consumption.
"""

import os
import logging
import functools
from typing import Callable, Any, Dict, Optional
from flask import current_app

# Try to import memory_profiler, but make it optional
try:
    from memory_profiler import profile
    MEMORY_PROFILER_AVAILABLE = True
except ImportError:
    MEMORY_PROFILER_AVAILABLE = False
    # Create a dummy profile decorator if memory_profiler is not available
    def profile(func=None, *args, **kwargs):
        if func:
            return func
        return lambda f: f

# Configure logging
logger = logging.getLogger(__name__)

class MemoryOptimizer:
    """
    Utility class for memory optimization and profiling.
    
    This class provides decorators and methods to help monitor and optimize
    memory usage in the application.
    """
    
    @staticmethod
    def memory_profiler(func: Callable) -> Callable:
        """
        Decorator to profile memory usage of a function.
        
        This decorator will track memory usage of the decorated function
        and log the results. It's designed to be used with class methods.
        
        Args:
            func: The function to profile
            
        Returns:
            A wrapped function that includes memory profiling
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Skip profiling if memory_profiler is not available
            if not MEMORY_PROFILER_AVAILABLE:
                return func(*args, **kwargs)
                
            # Only profile if explicitly enabled in config
            if not current_app or not current_app.config.get('ENABLE_MEMORY_PROFILING', False):
                return func(*args, **kwargs)
                
            # Run the function with memory profiling
            profiled_func = profile(func)
            result = profiled_func(*args, **kwargs)
            
            # Log memory usage if profiling was successful
            if hasattr(result, 'get'):
                mem_usage = result.get('memory_usage', {})
                if mem_usage:
                    logger.info(
                        f"Memory usage for {func.__name__}: "
                        f"Peak: {mem_usage.get('peak', 0):.2f} MB, "
                        f"Current: {mem_usage.get('current', 0):.2f} MB"
                    )
            
            return result
            
        return wrapper

    @staticmethod
    def get_memory_usage() -> Dict[str, float]:
        """
        Get current memory usage statistics.
        
        Returns:
            Dictionary containing memory usage information in MB:
            - 'current': Current memory usage
            - 'peak': Peak memory usage
            - 'rss': Resident Set Size
        """
        if not MEMORY_PROFILER_AVAILABLE:
            return {'current': 0, 'peak': 0, 'rss': 0}
            
        import psutil
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        return {
            'current': mem_info.rss / (1024 * 1024),  # Convert to MB
            'peak': mem_info.peak_wset / (1024 * 1024) if hasattr(mem_info, 'peak_wset') else 0,
            'rss': mem_info.rss / (1024 * 1024)  # Resident Set Size in MB
        }

    @staticmethod
    def log_memory_usage(label: str = "Memory Usage") -> None:
        """
        Log the current memory usage.
        
        Args:
            label: Optional label to include in the log message
        """
        mem_usage = MemoryOptimizer.get_memory_usage()
        logger.info(
            f"{label}: "
            f"Current: {mem_usage.get('current', 0):.2f} MB, "
            f"Peak: {mem_usage.get('peak', 0):.2f} MB"
        )

# Add memory profiling to the Flask app context
class MemoryProfilerExtension:
    """Flask extension for memory profiling."""
    
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the memory profiler extension."""
        # Default configuration
        app.config.setdefault('ENABLE_MEMORY_PROFILING', False)
        app.config.setdefault('MEMORY_PROFILE_LOG', 'memory_profiler.log')
        
        # Add memory profiler to template context
        @app.context_processor
        def inject_memory_profiler():
            return dict(
                memory_profiler=MemoryOptimizer(),
                get_memory_usage=MemoryOptimizer.get_memory_usage
            )

# Create extension instance
memory_profiler = MemoryProfilerExtension()
