#!/usr/bin/env python3
"""
Memory usage diagnostic tool to compare local vs Render environments.
"""
import os
import platform
import psutil
import subprocess


def get_memory_info():
    """Get detailed memory information."""
    process = psutil.Process()
    
    print("=== System Information ===")
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {platform.python_version()}")
    print(f"Architecture: {platform.machine()}")
    print(f"Is Render: {'RENDER' in os.environ}")
    
    print("\n=== Memory Information ===")
    # System memory
    vm = psutil.virtual_memory()
    print(f"Total System Memory: {vm.total / 1024 / 1024:.1f}MB")
    print(f"Available Memory: {vm.available / 1024 / 1024:.1f}MB")
    print(f"System Memory Used: {vm.percent}%")
    
    # Process memory
    mem_info = process.memory_info()
    print(f"\nProcess RSS: {mem_info.rss / 1024 / 1024:.1f}MB")
    print(f"Process VMS: {mem_info.vms / 1024 / 1024:.1f}MB")
    
    # Python-specific
    try:
        import tracemalloc
        tracemalloc.start()
        current, peak = tracemalloc.get_traced_memory()
        print(f"Python Traced: {current / 1024 / 1024:.1f}MB (peak: {peak / 1024 / 1024:.1f}MB)")
        tracemalloc.stop()
    except:
        pass
    
    print("\n=== Playwright Browser Size ===")
    try:
        # Check Playwright browser size
        browsers_path = os.getenv('PLAYWRIGHT_BROWSERS_PATH', 
                                  os.path.expanduser('~/.cache/ms-playwright'))
        if os.path.exists(browsers_path):
            result = subprocess.run(['du', '-sh', browsers_path], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Playwright browsers: {result.stdout.strip()}")
        else:
            print("Playwright browsers not installed")
    except:
        print("Could not check Playwright browser size")
    
    print("\n=== Running Processes ===")
    # Count processes
    all_procs = list(psutil.process_iter(['pid', 'name', 'memory_info']))
    print(f"Total processes: {len(all_procs)}")
    
    # Top 5 memory users
    procs_with_mem = []
    for p in all_procs:
        try:
            mem = p.info['memory_info'].rss / 1024 / 1024
            procs_with_mem.append((p.info['name'], mem))
        except:
            pass
    
    procs_with_mem.sort(key=lambda x: x[1], reverse=True)
    print("\nTop 5 memory users:")
    for name, mem in procs_with_mem[:5]:
        print(f"  {name}: {mem:.1f}MB")


if __name__ == "__main__":
    get_memory_info()
