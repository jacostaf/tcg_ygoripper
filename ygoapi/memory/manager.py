"""
Memory management module for YGO API

Implements memory monitoring and management with configurable limits.
"""

import gc
import logging
import os
import threading
import time
from typing import Optional, Callable, Dict, Any
from contextlib import contextmanager

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from ..config import MEM_LIMIT, MEM_CHECK_INTERVAL, MEM_WARNING_THRESHOLD, MEM_CRITICAL_THRESHOLD

logger = logging.getLogger(__name__)

class MemoryManager:
    """Memory manager that monitors and enforces memory limits."""
    
    def __init__(self, limit_mb: int = MEM_LIMIT):
        self.limit_mb = limit_mb
        self.limit_bytes = limit_mb * 1024 * 1024
        self.warning_threshold = MEM_WARNING_THRESHOLD
        self.critical_threshold = MEM_CRITICAL_THRESHOLD
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.cleanup_callbacks: list[Callable] = []
        
        # Get process object for memory monitoring if psutil is available
        if PSUTIL_AVAILABLE:
            self.process = psutil.Process(os.getpid())
        else:
            self.process = None
            logger.warning("psutil not available - memory monitoring will be limited")
        
        logger.info(f"Memory manager initialized with limit: {limit_mb}MB")
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """Get current memory usage statistics."""
        if not PSUTIL_AVAILABLE or not self.process:
            return {
                'rss_mb': 0,
                'vms_mb': 0,
                'percent': 0,
                'limit_mb': self.limit_mb,
                'usage_ratio': 0,
                'available_mb': self.limit_mb
            }
        
        try:
            memory_info = self.process.memory_info()
            memory_percent = self.process.memory_percent()
            
            return {
                'rss_mb': memory_info.rss / (1024 * 1024),  # Resident Set Size in MB
                'vms_mb': memory_info.vms / (1024 * 1024),  # Virtual Memory Size in MB
                'percent': memory_percent,
                'limit_mb': self.limit_mb,
                'usage_ratio': memory_info.rss / self.limit_bytes if self.limit_bytes > 0 else 0,
                'available_mb': max(0, self.limit_mb - (memory_info.rss / (1024 * 1024)))
            }
        except Exception as e:
            logger.error(f"Error getting memory usage: {e}")
            return {}
    
    def is_memory_limit_exceeded(self) -> bool:
        """Check if memory usage exceeds the configured limit."""
        if not PSUTIL_AVAILABLE or not self.process:
            return False
        
        try:
            memory_info = self.process.memory_info()
            return memory_info.rss > self.limit_bytes
        except Exception:
            return False
    
    def get_memory_level(self) -> str:
        """Get current memory usage level (normal, warning, critical)."""
        if not PSUTIL_AVAILABLE or not self.process:
            return "unknown"
        
        try:
            memory_info = self.process.memory_info()
            usage_ratio = memory_info.rss / self.limit_bytes
            
            if usage_ratio >= self.critical_threshold:
                return "critical"
            elif usage_ratio >= self.warning_threshold:
                return "warning"
            else:
                return "normal"
        except Exception:
            return "unknown"
    
    def force_garbage_collection(self):
        """Force garbage collection to free up memory."""
        logger.info("🗑️ Forcing garbage collection...")
        collected = gc.collect()
        logger.info(f"🗑️ Garbage collection freed {collected} objects")
        return collected
    
    def add_cleanup_callback(self, callback: Callable):
        """Add a callback function to be called when memory needs to be freed."""
        self.cleanup_callbacks.append(callback)
    
    def trigger_cleanup(self):
        """Trigger all registered cleanup callbacks."""
        logger.info("🧹 Triggering memory cleanup callbacks...")
        for callback in self.cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback: {e}")
    
    def check_memory_and_cleanup(self) -> bool:
        """Check memory usage and perform cleanup if needed. Returns True if cleanup was performed."""
        usage = self.get_memory_usage()
        level = self.get_memory_level()
        
        if level == "critical":
            logger.error(f"🚨 CRITICAL memory usage: {usage['rss_mb']:.1f}MB / {self.limit_mb}MB ({usage['usage_ratio']:.1%})")
            self.trigger_cleanup()
            self.force_garbage_collection()
            return True
        elif level == "warning":
            logger.warning(f"⚠️ HIGH memory usage: {usage['rss_mb']:.1f}MB / {self.limit_mb}MB ({usage['usage_ratio']:.1%})")
            self.force_garbage_collection()
            return True
        else:
            logger.debug(f"✅ Normal memory usage: {usage['rss_mb']:.1f}MB / {self.limit_mb}MB ({usage['usage_ratio']:.1%})")
            return False
    
    def start_monitoring(self):
        """Start background memory monitoring."""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"Memory monitoring started (checking every {MEM_CHECK_INTERVAL}s)")
    
    def stop_monitoring(self):
        """Stop background memory monitoring."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("Memory monitoring stopped")
    
    def _monitor_loop(self):
        """Background monitoring loop."""
        while self.monitoring:
            try:
                self.check_memory_and_cleanup()
                time.sleep(MEM_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in memory monitoring loop: {e}")
                time.sleep(MEM_CHECK_INTERVAL)
    
    @contextmanager
    def memory_context(self, operation_name: str = "operation"):
        """Context manager for memory-conscious operations."""
        start_usage = self.get_memory_usage()
        logger.debug(f"🔍 Starting {operation_name} - Memory: {start_usage.get('rss_mb', 0):.1f}MB")
        
        try:
            yield self
        finally:
            end_usage = self.get_memory_usage()
            memory_diff = end_usage.get('rss_mb', 0) - start_usage.get('rss_mb', 0)
            
            if memory_diff > 0:
                logger.debug(f"📈 {operation_name} increased memory by {memory_diff:.1f}MB")
            else:
                logger.debug(f"📉 {operation_name} decreased memory by {abs(memory_diff):.1f}MB")
            
            # Check if cleanup is needed after operation
            self.check_memory_and_cleanup()

# Global memory manager instance
_memory_manager: Optional[MemoryManager] = None

def get_memory_manager() -> MemoryManager:
    """Get the global memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

def initialize_memory_manager(limit_mb: int = MEM_LIMIT) -> MemoryManager:
    """Initialize the global memory manager."""
    global _memory_manager
    _memory_manager = MemoryManager(limit_mb)
    return _memory_manager

def start_memory_monitoring():
    """Start memory monitoring."""
    get_memory_manager().start_monitoring()

def stop_memory_monitoring():
    """Stop memory monitoring."""
    if _memory_manager:
        _memory_manager.stop_monitoring()

def memory_check_decorator(operation_name: str = "operation"):
    """Decorator for memory-conscious operations."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with get_memory_manager().memory_context(operation_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator