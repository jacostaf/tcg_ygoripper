# Render Optimization Guide for 512MB/.5 CPU Instance

This guide explains the optimizations implemented for running the YGO API on Render's Starter plan (512MB RAM, 0.5 CPU).

## Key Optimizations Implemented

### 1. Browser Strategy Selection
- **Changed**: Default strategy on Render is now `OptimizedBrowserPool` instead of `BrowserManager`
- **Why**: The optimized pool dynamically adjusts browser count based on available memory
- **File**: `browser_strategy.py`

### 2. Enhanced Memory Optimization Flags
Added aggressive memory-saving Chrome flags:
- `--js-flags=--max-old-space-size=64`: Limits JavaScript heap to 64MB (down from 128MB)
- `--disable-extensions`, `--disable-plugins`: Removes unnecessary features
- `--disk-cache-size=1`, `--media-cache-size=1`: Minimizes disk cache usage
- Various background process disabling flags
- **File**: `optimized_browser_pool.py`

### 3. Request Queuing with 503 Responses
- **Added**: Capacity checking before processing price requests
- **Behavior**: Returns HTTP 503 with `Retry-After` header when browser pool is at capacity
- **Benefits**: Prevents memory crashes from overload, provides clear client guidance
- **File**: `async_routes.py`

### 4. Extended Timeouts
- Browser context acquisition timeout: 600 seconds (10 minutes)
- Playwright timeouts: All set to 600000ms (10 minutes) for long-running scrapes
- **Why**: Price scraping can take significant time on complex pages

## Environment Variables

Copy the contents of `.env.render` to your Render dashboard:

```bash
BROWSER_STRATEGY=optimized
PLAYWRIGHT_POOL_SIZE=1
MEMORY_LIMIT_MB=512
PLAYWRIGHT_PAGE_TIMEOUT_MS=600000
PLAYWRIGHT_NAVIGATION_TIMEOUT_MS=600000
PLAYWRIGHT_DEFAULT_TIMEOUT_MS=600000
HYPERCORN_THREADS=2
```

## Expected Behavior

1. **Cold Start**: First request will initialize a single browser instance
2. **Concurrent Requests**: 
   - 1st request: Processed immediately
   - 2nd request: Queued, waiting for browser availability
   - 3rd+ requests: Return 503 if queue is full
3. **Memory Usage**: Should stay under 400MB with single browser
4. **Response Times**: 
   - Cached: < 1 second
   - Fresh scrape: 5-30 seconds depending on TCGPlayer load

## Monitoring

Check these endpoints for system status:
- `/health`: Overall health and browser pool stats
- `/browser/stats`: Detailed browser pool statistics
- `/memory/stats`: Memory usage information

## Troubleshooting

### High Memory Usage
If memory exceeds 450MB:
1. Check `/browser/stats` for pool size
2. Reduce `PLAYWRIGHT_POOL_SIZE` to 1
3. Enable `DEBUG` logging to identify memory leaks

### Frequent 503 Errors
If getting many 503s:
1. Check average wait times in browser stats
2. Consider implementing a queue service
3. Increase cache duration to reduce fresh scrapes

### Slow Response Times
If scraping takes > 1 minute:
1. Check TCGPlayer's response time
2. Review network logs for timeouts
3. Consider reducing page complexity checks

## Future Improvements

1. **External Browser Service**: Deploy browsers on a separate, larger instance
2. **Redis Queue**: Add proper job queuing for better request management
3. **Preemptive Scaling**: Scale up browser pool before hitting capacity
4. **Image Optimization**: Selectively disable images for non-visual scraping

## Performance Expectations

With these optimizations on 512MB/.5 CPU:
- **Concurrent capacity**: 1 active scrape
- **Queue capacity**: 2-3 requests waiting
- **Average memory**: 350-400MB under load
- **Success rate**: 95%+ with proper retry logic

The system prioritizes stability over throughput, ensuring consistent operation within the tight resource constraints.