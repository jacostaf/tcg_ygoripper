# YGO API - Modular Architecture Overview

## What Changed

The original 4170-line `main.py` file has been completely refactored into a well-structured, modular Python package with memory optimization and monitoring capabilities.

## New Module Structure

```
ygoapi/
├── __init__.py              # Package initialization
├── config.py                # Configuration management
├── main.py                  # Streamlined entry point (100 lines vs 4170)
├── models/
│   ├── __init__.py          # Model exports
│   └── schemas.py           # Pydantic data models
├── database/
│   ├── __init__.py          # Database exports
│   └── manager.py           # MongoDB connection and operations
├── services/
│   ├── __init__.py          # Service exports
│   ├── price_scraping.py    # Price scraping logic
│   └── card_sets.py         # Card set management
├── routes/
│   ├── __init__.py          # Route exports
│   └── handlers.py          # Flask route handlers
├── utils/
│   ├── __init__.py          # Utility exports
│   └── helpers.py           # Data normalization and helpers
└── memory/
    ├── __init__.py          # Memory management exports
    └── manager.py           # Memory monitoring and optimization
```

## Key Improvements

### 1. Memory Management with MEM_LIMIT
- **Environment Variable**: `MEM_LIMIT` sets memory limit in MB (default: 512MB)
- **Real-time Monitoring**: Background thread monitors memory usage every 30 seconds
- **Automatic Cleanup**: Triggers garbage collection and cleanup callbacks when approaching limits
- **Memory Levels**: Normal (< 80%), Warning (80-95%), Critical (> 95%)
- **Debug Endpoints**: `/debug/memory-stats` and `/debug/memory-cleanup`

### 2. Modular Architecture
- **Separation of Concerns**: Each module has a specific responsibility
- **Clean Interfaces**: Well-defined public APIs for each module
- **Maintainability**: Easy to modify individual components without affecting others
- **Testability**: Each module can be tested in isolation

### 3. Memory Optimizations
- **Context Managers**: Memory-conscious operations with automatic cleanup
- **Batch Processing**: Large datasets processed in chunks to prevent memory spikes
- **Generator Patterns**: Used for streaming large data sets
- **Connection Pooling**: Database connections properly managed and cleaned up
- **Lazy Loading**: Resources loaded only when needed

### 4. Enhanced Error Handling
- **Graceful Degradation**: System continues operating even with memory pressure
- **Comprehensive Logging**: Detailed logging with memory usage context
- **Error Recovery**: Automatic cleanup and recovery from memory issues

## Memory Manager Features

```python
# Memory usage monitoring
memory_manager = get_memory_manager()
stats = memory_manager.get_memory_usage()
# Returns: rss_mb, vms_mb, percent, limit_mb, usage_ratio, available_mb

# Memory-conscious operations
@memory_check_decorator("operation_name")
def my_function():
    # Function automatically monitored for memory usage
    pass

# Context manager for memory tracking
with memory_manager.memory_context("bulk_operation"):
    # Memory usage tracked and cleaned up automatically
    process_large_dataset()
```

## Configuration

All configuration is centralized in `ygoapi/config.py`:

```python
# Memory Management
MEM_LIMIT = 512  # MB
MEM_CHECK_INTERVAL = 30  # seconds
MEM_WARNING_THRESHOLD = 0.8  # 80%
MEM_CRITICAL_THRESHOLD = 0.95  # 95%

# Application
PORT = 8081
DEBUG_MODE = False

# Database
MONGODB_CONNECTION_STRING = "..."
CACHE_EXPIRY_DAYS = 7
```

## API Endpoints

The API maintains full backward compatibility with the original endpoints:

### Core Endpoints
- `GET /health` - Health check with memory usage
- `GET /debug/memory-stats` - Detailed memory statistics
- `POST /debug/memory-cleanup` - Manual memory cleanup

### Card Sets
- `GET /card-sets` - Get all card sets
- `GET /card-sets/search/<name>` - Search card sets
- `POST /card-sets/upload` - Upload to MongoDB cache
- `GET /card-sets/from-cache` - Get from cache
- `GET /card-sets/count` - Count cached sets
- `GET /card-sets/<name>/cards` - Get cards from set
- `POST /card-sets/fetch-all-cards` - Fetch all cards

### Price Scraping
- `POST /cards/price` - Scrape price data
- `GET /cards/price/cache-stats` - Cache statistics

## Memory Optimization Techniques Used

1. **Streaming Data Processing**: Large datasets processed incrementally
2. **Garbage Collection**: Proactive cleanup when memory pressure detected
3. **Connection Management**: Database connections closed promptly
4. **Batch Operations**: Large operations split into manageable chunks
5. **Memory Monitoring**: Continuous tracking prevents memory leaks
6. **Context Managers**: Automatic resource cleanup
7. **Lazy Initialization**: Services created only when needed

## Running the Application

```bash
# Set memory limit (optional, defaults to 512MB)
export MEM_LIMIT=1024

# Start the server
python3 main.py
```

The application will:
1. Initialize the memory manager with the specified limit
2. Start background memory monitoring
3. Load all modular components
4. Start the Flask server with all endpoints

## Benefits of the New Architecture

1. **Memory Safety**: Prevents out-of-memory errors in production
2. **Maintainability**: Easy to modify and extend individual components
3. **Debugging**: Clear module boundaries make issues easier to isolate
4. **Performance**: Optimized memory usage and automatic cleanup
5. **Scalability**: Modular design supports future enhancements
6. **Testability**: Each module can be unit tested independently
7. **Documentation**: Self-documenting code structure

## Preserved Functionality

✅ **All original endpoints preserved**  
✅ **Same request/response formats**  
✅ **Same business logic**  
✅ **Same external API integrations**  
✅ **Same database operations**  
✅ **Compatible with existing clients**  

The refactored application maintains 100% backward compatibility while adding significant improvements in memory management, code organization, and maintainability.