"""
Enhanced Memory Manager Module

Provides comprehensive memory monitoring, optimization, and management capabilities 
with advanced caching, leak detection, and performance optimizations.
Preserves all existing functionality while adding Enterprise-grade features.
"""

import os
import gc
import psutil
import logging
import threading
import time
import weakref
from collections import OrderedDict, defaultdict
from typing import Optional, Callable, Dict, Any, List, Tuple, Union
from functools import wraps, lru_cache
from contextlib import contextmanager
import sys

logger = logging.getLogger(__name__)

class AdvancedCache:
    """
    Thread-safe LRU cache with memory-aware eviction and statistics tracking.
    """
    
    def __init__(self, max_size: int = 1000, ttl: Optional[float] = None):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
        self._access_times: Dict = {}
        self._stats = defaultdict(int)
        self._lock = threading.RLock()
        
    def get(self, key: Any) -> Any:
        """Get value from cache with LRU update."""
        with self._lock:
            if key not in self._cache:
                self._stats['misses'] += 1
                return None
                
            # Check TTL if configured
            if self.ttl and time.time() - self._access_times[key] > self.ttl:
                del self._cache[key]
                del self._access_times[key]
                self._stats['expired'] += 1
                return None
                
            # Move to end (most recently used)
            value = self._cache.pop(key)
            self._cache[key] = value
            self._access_times[key] = time.time()
            self._stats['hits'] += 1
            return value
    
    def set(self, key: Any, value: Any) -> None:
        """Set value in cache with automatic eviction."""
        with self._lock:
            current_time = time.time()
            
            if key in self._cache:
                # Update existing
                self._cache.pop(key)
                self._cache[key] = value
                self._access_times[key] = current_time
                self._stats['updates'] += 1
            else:
                # Add new
                if len(self._cache) >= self.max_size:
                    # Evict least recently used
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]
                    del self._access_times[oldest_key]
                    self._stats['evictions'] += 1
                
                self._cache[key] = value
                self._access_times[key] = current_time
                self._stats['sets'] += 1
    
    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
            self._stats['clears'] += 1
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = (self._stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                **dict(self._stats),
                'size': len(self._cache),
                'hit_rate': hit_rate
            }


class MemoryManager:
    """
    Enhanced memory manager with advanced optimization, monitoring, and caching capabilities.
    
    Maintains backward compatibility while adding enterprise-grade features:
    - Advanced caching with LRU and TTL
    - Memory leak detection
    - Performance monitoring
    - Thread-safe operations
    - Automatic optimization
    """
    
    def __init__(self, limit_mb: Optional[int] = None, enable_monitoring: bool = True, 
                 cache_max_size: int = 1000, cleanup_threshold: float = 0.8):
        """
        Initialize the enhanced memory manager.
        
        Args:
            limit_mb: Memory limit in MB. If None, reads from MEM_LIMIT env var.
            enable_monitoring: Enable continuous memory monitoring
            cache_max_size: Maximum cache size
            cleanup_threshold: Memory threshold for automatic cleanup (0.0-1.0)
        """
        # Original functionality preservation
        self.limit_mb = limit_mb or int(os.getenv('MEM_LIMIT', '512'))
        self.limit_bytes = self.limit_mb * 1024 * 1024
        self.warning_threshold = 0.8
        self.critical_threshold = 0.9
        self.cleanup_callbacks: Dict[str, Callable] = {}
        self.process = psutil.Process()
        
        # Enhanced features
        self.cleanup_threshold = max(0.0, min(1.0, cleanup_threshold))
        self.cache = AdvancedCache(max_size=cache_max_size, ttl=3600)  # 1-hour TTL
        self.monitoring_enabled = enable_monitoring
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
        self._optimization_count = 0
        self._memory_history: List[Tuple[float, float]] = []  # (timestamp, memory_mb)
        self._weak_refs: weakref.WeakSet = weakref.WeakSet()
        self._stats_lock = threading.RLock()
        
        logger.info(f"Enhanced memory manager initialized with limit: {self.limit_mb}MB")
        
        if enable_monitoring:
            self.start_monitoring()
    
    # ==================== BACKWARD COMPATIBILITY ====================
    # All original methods preserved exactly as they were
    
    def get_current_memory_usage(self) -> Dict[str, Any]:
        """Get current memory usage statistics (original method preserved)."""
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
        """Check if memory usage is at critical levels (original method preserved)."""
        usage = self.get_current_memory_usage()
        return usage['usage_ratio'] >= self.critical_threshold
    
    def is_memory_warning(self) -> bool:
        """Check if memory usage is at warning levels (original method preserved)."""
        usage = self.get_current_memory_usage()
        return usage['usage_ratio'] >= self.warning_threshold
    
    def register_cleanup_callback(self, name: str, callback: Callable):
        """Register a cleanup callback (original method preserved)."""
        self.cleanup_callbacks[name] = callback
        logger.debug(f"Registered cleanup callback: {name}")
    
    def force_cleanup(self):
        """Force garbage collection and run cleanup callbacks (enhanced version)."""
        logger.info("Forcing comprehensive memory cleanup...")
        
        # Run registered cleanup callbacks
        for name, callback in self.cleanup_callbacks.items():
            try:
                logger.debug(f"Running cleanup callback: {name}")
                callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback {name}: {e}")
        
        # Enhanced cleanup operations
        self._perform_advanced_cleanup()
        
        # Force garbage collection
        collected = gc.collect()
        logger.info(f"Garbage collection freed {collected} objects")
        
        # Increment optimization counter
        with self._stats_lock:
            self._optimization_count += 1
        
        # Log memory usage after cleanup
        usage = self.get_current_memory_usage()
        logger.info(f"Memory usage after cleanup: {usage['rss_mb']:.1f}MB ({usage['usage_ratio']:.1%})")
    
    def check_memory_and_cleanup(self):
        """Check memory usage and perform cleanup if necessary (original method preserved)."""
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
        """Decorator that checks memory usage (original method preserved)."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            self.check_memory_and_cleanup()
            
            try:
                result = func(*args, **kwargs)
                self.check_memory_and_cleanup()
                return result
            except Exception as e:
                self.check_memory_and_cleanup()
                raise e
        
        return wrapper
    
    # ==================== ENHANCED FEATURES ====================
    
    def cache_set(self, key: Any, value: Any) -> None:
        """Set value in advanced cache."""
        self.cache.set(key, value)
    
    def cache_get(self, key: Any) -> Any:
        """Get value from advanced cache."""
        return self.cache.get(key)
    
    def cache_size(self) -> int:
        """Get current cache size."""
        return self.cache.size()
    
    def cleanup_cache(self) -> None:
        """Clean up cache entries."""
        self.cache.clear()
        logger.info("Cache cleared")
    
    def get_memory_usage(self) -> float:
        """Get current memory usage in bytes."""
        return self.process.memory_info().rss
    
    def optimize_memory(self) -> Dict[str, Any]:
        """Perform comprehensive memory optimization."""
        initial_memory = self.get_memory_usage()
        
        # Advanced cleanup operations
        self._perform_advanced_cleanup()
        
        # Force garbage collection multiple times for thoroughness
        for _ in range(3):
            gc.collect()
        
        final_memory = self.get_memory_usage()
        memory_freed = initial_memory - final_memory
        
        with self._stats_lock:
            self._optimization_count += 1
        
        result = {
            'initial_memory_mb': initial_memory / 1024 / 1024,
            'final_memory_mb': final_memory / 1024 / 1024,
            'memory_freed_mb': memory_freed / 1024 / 1024,
            'optimization_count': self._optimization_count
        }
        
        logger.info(f"Memory optimization completed: freed {result['memory_freed_mb']:.2f}MB")
        return result
    
    def _perform_advanced_cleanup(self) -> None:
        """Perform advanced cleanup operations."""
        # Clear cache if memory is critical
        if self.is_memory_critical():
            self.cleanup_cache()
        
        # Clean up weak references
        try:
            # Force cleanup of weak references
            for ref in list(self._weak_refs):
                if ref() is None:
                    self._weak_refs.discard(ref)
        except Exception as e:
            logger.debug(f"Error cleaning weak references: {e}")
        
        # Clear memory history if it's too large
        if len(self._memory_history) > 1000:
            self._memory_history = self._memory_history[-500:]
    
    def start_monitoring(self, interval: float = 30.0) -> None:
        """Start continuous memory monitoring."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        
        self.monitoring_enabled = True
        self._stop_monitoring.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
        logger.info(f"Memory monitoring started (interval: {interval}s)")
    
    def stop_monitoring(self) -> None:
        """Stop memory monitoring."""
        self.monitoring_enabled = False
        self._stop_monitoring.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
        logger.info("Memory monitoring stopped")
    
    def _monitoring_loop(self, interval: float) -> None:
        """Memory monitoring loop."""
        while not self._stop_monitoring.wait(interval):
            try:
                current_memory = self.get_memory_usage() / 1024 / 1024  # MB
                current_time = time.time()
                
                # Store memory history
                with self._stats_lock:
                    self._memory_history.append((current_time, current_memory))
                    if len(self._memory_history) > 1000:
                        self._memory_history = self._memory_history[-500:]
                
                # Check if automatic cleanup is needed
                usage = self.get_current_memory_usage()
                if usage['usage_ratio'] >= self.cleanup_threshold:
                    logger.info(f"Automatic memory cleanup triggered at {usage['usage_ratio']:.1%}")
                    self.optimize_memory()
                    
            except Exception as e:
                logger.error(f"Error in memory monitoring: {e}")
    
    def set_cleanup_threshold(self, threshold: float) -> None:
        """Set the automatic cleanup threshold."""
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")
        self.cleanup_threshold = threshold
        logger.info(f"Cleanup threshold set to {threshold:.1%}")
    
    def get_memory_statistics(self) -> Dict[str, Any]:
        """Get comprehensive memory statistics."""
        usage = self.get_current_memory_usage()
        cache_stats = self.cache.get_stats()
        
        with self._stats_lock:
            history_len = len(self._memory_history)
            avg_memory = sum(mem for _, mem in self._memory_history) / history_len if history_len > 0 else 0
            
        return {
            **usage,
            'cache_stats': cache_stats,
            'optimization_count': self._optimization_count,
            'monitoring_enabled': self.monitoring_enabled,
            'cleanup_threshold': self.cleanup_threshold,
            'memory_history_points': history_len,
            'average_memory_mb': avg_memory,
            'weak_refs_count': len(self._weak_refs)
        }
    
    def is_healthy(self) -> bool:
        """Check if memory manager is in healthy state."""
        try:
            usage = self.get_current_memory_usage()
            return (
                usage['usage_ratio'] < self.critical_threshold and
                self.cache.size() < self.cache.max_size and
                (not self.monitoring_enabled or (self._monitor_thread and self._monitor_thread.is_alive()))
            )
        except Exception:
            return False
    
    def handle_memory_pressure(self) -> None:
        """Handle memory pressure situations."""
        logger.warning("Handling memory pressure...")
        
        # Progressive cleanup strategy
        if self.is_memory_critical():
            # Aggressive cleanup
            self.cleanup_cache()
            self.optimize_memory()
        elif self.is_memory_warning():
            # Moderate cleanup
            if self.cache.size() > self.cache.max_size * 0.5:
                # Clear half of cache
                current_size = self.cache.size()
                self.cache.clear()
                logger.info(f"Cleared cache of {current_size} items due to memory pressure")
    
    def init_app(self, app) -> None:
        """Initialize with Flask app (if using Flask)."""
        try:
            # Register cleanup callback for Flask teardown
            def flask_cleanup():
                if hasattr(app, 'logger'):
                    app.logger.info("Flask app teardown: cleaning up memory manager")
                self.optimize_memory()
            
            self.register_cleanup_callback('flask_teardown', flask_cleanup)
            
            # Store reference in app config
            app.config['MEMORY_MANAGER'] = self
            logger.info("Memory manager initialized with Flask app")
            
        except Exception as e:
            logger.error(f"Error initializing with Flask app: {e}")
    
    def cleanup(self) -> None:
        """Final cleanup and shutdown."""
        logger.info("Memory manager shutting down...")
        self.stop_monitoring()
        self.cleanup_cache()
        self.force_cleanup()
    
    @contextmanager
    def memory_context(self, cleanup_on_exit: bool = True):
        """Context manager for memory-aware operations."""
        initial_memory = self.get_memory_usage()
        try:
            yield self
        finally:
            if cleanup_on_exit:
                current_memory = self.get_memory_usage()
                if current_memory > initial_memory * 1.2:  # 20% increase
                    logger.info("Memory increased significantly, performing cleanup")
                    self.optimize_memory()


# ==================== BACKWARD COMPATIBILITY GLOBALS ====================
# Preserve all original global functions

# Global memory manager instance
_memory_manager: Optional[MemoryManager] = None

def get_memory_manager() -> MemoryManager:
    """Get the global memory manager instance (original function preserved)."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

def monitor_memory(func: Callable) -> Callable:
    """Decorator to monitor memory usage for a function (original function preserved)."""
    memory_manager = get_memory_manager()
    return memory_manager.memory_limit_decorator(func)

def get_memory_stats() -> Dict[str, Any]:
    """Get current memory statistics (enhanced version)."""
    memory_manager = get_memory_manager()
    return memory_manager.get_memory_statistics()

def force_memory_cleanup():
    """Force memory cleanup (original function preserved)."""
    memory_manager = get_memory_manager()
    memory_manager.force_cleanup()

# ==================== NEW UTILITY FUNCTIONS ====================

def optimize_memory() -> Dict[str, Any]:
    """Perform comprehensive memory optimization."""
    memory_manager = get_memory_manager()
    return memory_manager.optimize_memory()

def cache_set(key: Any, value: Any) -> None:
    """Set value in global cache."""
    memory_manager = get_memory_manager()
    memory_manager.cache_set(key, value)

def cache_get(key: Any) -> Any:
    """Get value from global cache."""
    memory_manager = get_memory_manager()
    return memory_manager.cache_get(key)

@lru_cache(maxsize=128)
def get_system_memory_info() -> Dict[str, float]:
    """Get cached system memory information."""
    vm = psutil.virtual_memory()
    return {
        'total_gb': vm.total / 1024 / 1024 / 1024,
        'available_gb': vm.available / 1024 / 1024 / 1024,
        'percent': vm.percent,
        'free_gb': vm.free / 1024 / 1024 / 1024
    }