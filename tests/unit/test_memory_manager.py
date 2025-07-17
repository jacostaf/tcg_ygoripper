"""
Unit tests for memory_manager.py module.

Tests memory monitoring, cleanup callbacks, and memory limit enforcement
with comprehensive coverage of edge cases and error scenarios.
"""

import gc
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from ygoapi.memory_manager import (
    MemoryManager,
    get_memory_manager,
    monitor_memory,
    get_memory_stats,
    force_memory_cleanup,
)


class TestMemoryManager:
    """Test MemoryManager class functionality."""

    def test_init_with_default_limit(self):
        """Test MemoryManager initialization with default limit."""
        with patch.dict(os.environ, {"MEM_LIMIT": "1024"}):
            manager = MemoryManager()
            assert manager.limit_mb == 1024
            assert manager.limit_bytes == 1024 * 1024 * 1024
            assert manager.warning_threshold == 0.8
            assert manager.critical_threshold == 0.9

    def test_init_with_custom_limit(self):
        """Test MemoryManager initialization with custom limit."""
        manager = MemoryManager(limit_mb=256)
        assert manager.limit_mb == 256
        assert manager.limit_bytes == 256 * 1024 * 1024

    def test_init_without_env_var(self):
        """Test MemoryManager initialization without MEM_LIMIT env var."""
        with patch.dict(os.environ, {}, clear=True):
            manager = MemoryManager()
            assert manager.limit_mb == 512  # Default value

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_get_current_memory_usage(self, mock_process_class):
        """Test getting current memory usage statistics."""
        # Mock psutil.Process and its methods
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 100 * 1024 * 1024  # 100MB
        mock_memory_info.vms = 200 * 1024 * 1024  # 200MB
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 5.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=512)
        usage = manager.get_current_memory_usage()

        assert usage["rss_mb"] == 100.0
        assert usage["vms_mb"] == 200.0
        assert usage["percent"] == 5.0
        assert usage["limit_mb"] == 512
        assert usage["usage_ratio"] == 100.0 / 512.0
        assert "warning_threshold" in usage
        assert "critical_threshold" in usage

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_is_memory_critical(self, mock_process_class):
        """Test memory critical threshold detection."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 90 * 1024 * 1024  # 90MB out of 100MB limit
        mock_memory_info.vms = 90 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 90.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        assert manager.is_memory_critical() is True

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_is_memory_warning(self, mock_process_class):
        """Test memory warning threshold detection."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 80 * 1024 * 1024  # 80MB out of 100MB limit
        mock_memory_info.vms = 80 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 80.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        assert manager.is_memory_warning() is True

    def test_register_cleanup_callback(self):
        """Test registering cleanup callbacks."""
        manager = MemoryManager()
        
        def dummy_callback():
            pass
        
        manager.register_cleanup_callback("test_callback", dummy_callback)
        assert "test_callback" in manager.cleanup_callbacks
        assert manager.cleanup_callbacks["test_callback"] == dummy_callback

    @patch("ygoapi.memory_manager.gc.collect")
    def test_force_cleanup_with_callbacks(self, mock_gc_collect):
        """Test force cleanup with registered callbacks."""
        mock_gc_collect.return_value = 42
        
        manager = MemoryManager()
        
        # Register mock callbacks
        callback1 = Mock()
        callback2 = Mock()
        manager.register_cleanup_callback("callback1", callback1)
        manager.register_cleanup_callback("callback2", callback2)
        
        manager.force_cleanup()
        
        # Verify callbacks were called
        callback1.assert_called_once()
        callback2.assert_called_once()
        mock_gc_collect.assert_called_once()

    @patch("ygoapi.memory_manager.gc.collect")
    def test_force_cleanup_with_failing_callback(self, mock_gc_collect):
        """Test force cleanup when callback raises exception."""
        mock_gc_collect.return_value = 42
        
        manager = MemoryManager()
        
        # Register a failing callback
        def failing_callback():
            raise Exception("Callback failed")
        
        working_callback = Mock()
        manager.register_cleanup_callback("failing", failing_callback)
        manager.register_cleanup_callback("working", working_callback)
        
        # Should not raise exception, should continue with other callbacks
        manager.force_cleanup()
        
        # Working callback should still be called
        working_callback.assert_called_once()
        mock_gc_collect.assert_called_once()

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_check_memory_and_cleanup_critical(self, mock_process_class):
        """Test memory check and cleanup when memory is critical."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 95 * 1024 * 1024  # 95MB out of 100MB limit
        mock_memory_info.vms = 95 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 95.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        with patch.object(manager, 'force_cleanup') as mock_cleanup:
            manager.check_memory_and_cleanup()
            mock_cleanup.assert_called_once()

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_check_memory_and_cleanup_warning(self, mock_process_class):
        """Test memory check when memory is at warning level."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 85 * 1024 * 1024  # 85MB out of 100MB limit
        mock_memory_info.vms = 85 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 85.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        with patch.object(manager, 'force_cleanup') as mock_cleanup:
            manager.check_memory_and_cleanup()
            mock_cleanup.assert_not_called()  # Should not cleanup at warning level

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_check_memory_and_cleanup_still_critical_after_cleanup(self, mock_process_class):
        """Test memory check when memory is still critical after cleanup."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 95 * 1024 * 1024  # 95MB out of 100MB limit
        mock_memory_info.vms = 95 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 95.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        # Mock force_cleanup to not actually change memory usage
        with patch.object(manager, 'force_cleanup'):
            manager.check_memory_and_cleanup()
            # Should log error about still being critical after cleanup

    def test_memory_limit_decorator_normal_execution(self):
        """Test memory limit decorator with normal function execution."""
        manager = MemoryManager()
        
        @manager.memory_limit_decorator
        def test_function(x, y):
            return x + y
        
        with patch.object(manager, 'check_memory_and_cleanup') as mock_check:
            result = test_function(2, 3)
            assert result == 5
            assert mock_check.call_count == 2  # Before and after execution

    def test_memory_limit_decorator_with_exception(self):
        """Test memory limit decorator when function raises exception."""
        manager = MemoryManager()
        
        @manager.memory_limit_decorator
        def failing_function():
            raise ValueError("Test error")
        
        with patch.object(manager, 'check_memory_and_cleanup') as mock_check:
            with pytest.raises(ValueError, match="Test error"):
                failing_function()
            assert mock_check.call_count == 2  # Before and after exception


class TestMemoryManagerCoverageEnhancement:
    """Test memory manager coverage enhancement for previously uncovered lines."""

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_memory_monitoring_edge_cases(self, mock_process_class):
        """Test memory monitoring edge cases (lines 91-107)."""
        mock_process = Mock()
        mock_memory_info = Mock()
        
        # Test with very high memory usage
        mock_memory_info.rss = 1024 * 1024 * 1024  # 1GB
        mock_memory_info.vms = 2048 * 1024 * 1024  # 2GB
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 99.9
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=512)
        usage = manager.get_current_memory_usage()
        
        # Should handle high memory usage gracefully
        assert usage["rss_mb"] == 1024.0
        assert usage["vms_mb"] == 2048.0
        assert usage["usage_ratio"] > 1.0  # Over limit
        assert usage["percent"] == 99.9

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_cleanup_callback_registration_and_execution(self, mock_process_class):
        """Test cleanup callback registration and execution (lines 114-123)."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 95 * 1024 * 1024  # Critical memory usage
        mock_memory_info.vms = 95 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 95.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        # Test callback registration
        callback_called = []
        def test_callback():
            callback_called.append(True)
        
        manager.register_cleanup_callback("test", test_callback)
        
        # Test callback execution during cleanup
        with patch("ygoapi.memory_manager.gc.collect", return_value=10):
            manager.force_cleanup()
        
        assert len(callback_called) == 1
        assert "test" in manager.cleanup_callbacks

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_memory_limit_enforcement_scenarios(self, mock_process_class):
        """Test memory limit enforcement scenarios (lines 128-129)."""
        mock_process = Mock()
        mock_memory_info = Mock()
        
        # Test scenario where cleanup doesn't help
        mock_memory_info.rss = 95 * 1024 * 1024  # Critical memory usage
        mock_memory_info.vms = 95 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 95.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        # Mock force_cleanup to not reduce memory usage
        with patch.object(manager, 'force_cleanup'):
            manager.check_memory_and_cleanup()
            # Should trigger the "still critical after cleanup" logic

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_complex_callback_error_handling(self, mock_process_class):
        """Test complex callback error handling scenarios."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 50 * 1024 * 1024
        mock_memory_info.vms = 50 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 50.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        # Register multiple callbacks with different failure modes
        exception_count = []
        
        def callback_raises_exception():
            exception_count.append(1)
            raise RuntimeError("Callback failed")
        
        def callback_raises_type_error():
            exception_count.append(2)
            raise TypeError("Type error in callback")
        
        def successful_callback():
            exception_count.append(3)
        
        manager.register_cleanup_callback("exception", callback_raises_exception)
        manager.register_cleanup_callback("type_error", callback_raises_type_error)
        manager.register_cleanup_callback("success", successful_callback)
        
        # All callbacks should be attempted despite failures
        with patch("ygoapi.memory_manager.gc.collect", return_value=5):
            manager.force_cleanup()
        
        assert len(exception_count) == 3  # All callbacks attempted
        assert 1 in exception_count
        assert 2 in exception_count
        assert 3 in exception_count

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_memory_thresholds_boundary_conditions(self, mock_process_class):
        """Test memory threshold boundary conditions."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 50.0
        mock_process_class.return_value = mock_process

        manager = MemoryManager(limit_mb=100)
        
        # Test exactly at warning threshold
        mock_memory_info.rss = 80 * 1024 * 1024  # Exactly 80% of 100MB
        mock_memory_info.vms = 80 * 1024 * 1024
        assert manager.is_memory_warning() is True
        assert manager.is_memory_critical() is False
        
        # Test exactly at critical threshold  
        mock_memory_info.rss = 90 * 1024 * 1024  # Exactly 90% of 100MB
        mock_memory_info.vms = 90 * 1024 * 1024
        assert manager.is_memory_warning() is True
        assert manager.is_memory_critical() is True
        
        # Test just below warning threshold
        mock_memory_info.rss = 79 * 1024 * 1024  # Just below 80%
        mock_memory_info.vms = 79 * 1024 * 1024
        assert manager.is_memory_warning() is False
        assert manager.is_memory_critical() is False

    def test_decorator_preserves_function_metadata(self):
        """Test that memory limit decorator preserves function metadata."""
        manager = MemoryManager()
        
        @manager.memory_limit_decorator
        def test_function(x, y):
            """Test function docstring."""
            return x + y
        
        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "Test function docstring."

    @patch("ygoapi.memory_manager.psutil.Process")
    def test_memory_stats_with_zero_limit(self, mock_process_class):
        """Test memory stats calculation with edge case limits."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 100 * 1024 * 1024
        mock_memory_info.vms = 100 * 1024 * 1024
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.memory_percent.return_value = 50.0
        mock_process_class.return_value = mock_process

        # Test with very small limit
        manager = MemoryManager(limit_mb=1)
        usage = manager.get_current_memory_usage()
        
        assert usage["usage_ratio"] == 100.0  # 100MB / 1MB = 100
        assert usage["limit_mb"] == 1


class TestGlobalMemoryManagerFunctions:
    """Test global memory manager functions."""

    def test_get_memory_manager_singleton(self):
        """Test that get_memory_manager returns singleton instance."""
        # Clear any existing instance
        import ygoapi.memory_manager
        ygoapi.memory_manager._memory_manager = None
        
        manager1 = get_memory_manager()
        manager2 = get_memory_manager()
        
        assert manager1 is manager2
        assert isinstance(manager1, MemoryManager)

    def test_monitor_memory_decorator(self):
        """Test monitor_memory decorator function."""
        @monitor_memory
        def test_func(x):
            return x * 2
        
        # Should wrap function with memory monitoring
        result = test_func(5)
        assert result == 10

    def test_get_memory_stats_function(self):
        """Test get_memory_stats global function."""
        stats = get_memory_stats()
        
        assert isinstance(stats, dict)
        assert "rss_mb" in stats
        assert "usage_ratio" in stats
        assert "limit_mb" in stats

    def test_force_memory_cleanup_function(self):
        """Test force_memory_cleanup global function."""
        with patch.object(MemoryManager, 'force_cleanup') as mock_cleanup:
            force_memory_cleanup()
            # Should have been called on the global manager instance
            mock_cleanup.assert_called_once()

    def test_monitor_memory_with_function_args(self):
        """Test monitor_memory decorator with various function signatures."""
        @monitor_memory
        def func_with_args(a, b, c=None):
            return a + b + (c or 0)
        
        @monitor_memory
        def func_with_kwargs(**kwargs):
            return sum(kwargs.values())
        
        result1 = func_with_args(1, 2, c=3)
        assert result1 == 6
        
        result2 = func_with_kwargs(x=1, y=2, z=3)
        assert result2 == 6

    def test_memory_manager_environment_integration(self):
        """Test memory manager integration with environment variables."""
        # Test with different MEM_LIMIT values
        test_cases = [
            ("256", 256),
            ("1024", 1024),
            ("2048", 2048),
        ]
        
        for env_value, expected_limit in test_cases:
            with patch.dict(os.environ, {"MEM_LIMIT": env_value}):
                manager = MemoryManager()
                assert manager.limit_mb == expected_limit
                assert manager.limit_bytes == expected_limit * 1024 * 1024