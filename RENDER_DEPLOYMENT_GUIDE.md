# Render Deployment Guide for YGO API with Async Browser Pool

This guide explains how to deploy the YGO API with async Playwright browser pooling on Render.

## Prerequisites

1. A Render account (sign up at https://render.com)
2. Your MongoDB connection string
3. GitHub repository connected to Render

## Step 1: Create a New Web Service

1. Log in to Render Dashboard
2. Click "New +" → "Web Service"
3. Connect your GitHub repository (if not already connected)
4. Select the `tcg_ygoripper` repository
5. Choose the `browserPool` branch

## Step 2: Configure the Web Service

### Basic Settings
- **Name**: `ygo-api-async` (or your preferred name)
- **Region**: Choose closest to your users
- **Branch**: `browserPool`
- **Root Directory**: `tcg_ygoripper`
- **Runtime**: Python 3
- **Build Command**: 
  ```bash
  ./render_build.sh
  ```
  
  Or use the minimal version:
  ```bash
  ./build_minimal.sh
  ```
- **Start Command**:
  ```bash
  hypercorn ygoapi.async_app:app --bind 0.0.0.0:$PORT --workers 1
  ```
  
  Or if that fails, use Python directly for better error messages:
  ```bash
  python run_async.py
  ```

### Instance Type
- **Plan**: Select based on your needs
  - **Free**: Limited to 512MB RAM (sufficient for 2 browser pool)
  - **Starter**: 512MB RAM with no spin-down
  - **Standard**: 2GB RAM (can handle larger browser pool)

## Step 3: Environment Variables

Add the following environment variables in Render:

```bash
# MongoDB Configuration
MONGODB_CONNECTION_STRING=mongodb+srv://your-connection-string

# Playwright Configuration
PLAYWRIGHT_POOL_SIZE=2              # Browser pool size (2 for 512MB instances)
PLAYWRIGHT_HEADLESS=true           # Always true for servers
PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/.playwright  # Browser install path
PLAYWRIGHT_MAX_USES_PER_BROWSER=50  # Recycle browser after 50 uses

# Browser Strategy (Optional - auto-detects)
# BROWSER_STRATEGY=manager          # Force BrowserManager (memory-efficient)
# BROWSER_STRATEGY=pool            # Force BrowserPool (performance-optimized)
# Leave unset to auto-detect (uses 'manager' on Render)

# API Configuration
PRICE_CACHE_DURATION_HOURS=12       # Cache duration
PRICE_CACHE_COLLECTION=YGO_CARD_VARIANT_PRICE_CACHE_V1

# Server Configuration
HYPERCORN_WORKERS=1                 # Keep at 1 for async
PORT=10000                          # Render will set this automatically

# Optional: Logging
LOG_LEVEL=INFO
```

## Step 4: Advanced Settings

### Health Check Path
- Set to `/health` to use the built-in health endpoint

### Auto-Deploy
- Enable "Auto-Deploy" to automatically deploy when pushing to the branch

### Docker Command (if using Docker)
If you prefer Docker deployment, create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y \
    google-chrome-stable \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-kacst \
    fonts-freefont-ttf \
    libxss1 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY tcg_ygoripper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Copy application code
COPY tcg_ygoripper/ .

# Run the async server
CMD ["hypercorn", "ygoapi.async_app:create_async_app", "--bind", "0.0.0.0:$PORT", "--workers", "1"]
```

## Step 5: Deploy

1. Click "Create Web Service"
2. Wait for the build to complete (first build takes 5-10 minutes due to Playwright installation)
3. Once deployed, you'll get a URL like `https://ygo-api-async.onrender.com`

## Step 6: Test the Deployment

Test the API endpoints:

```bash
# Health check
curl https://your-app.onrender.com/health

# Browser pool stats
curl https://your-app.onrender.com/browser-stats

# Price scraping (force refresh)
curl -X POST https://your-app.onrender.com/cards/price \
  -H "Content-Type: application/json" \
  -d '{
    "card_number": "BLMM-EN039",
    "card_rarity": "Ultra Rare",
    "force_refresh": true
  }'

# Price scraping (use cache)
curl -X POST https://your-app.onrender.com/cards/price \
  -H "Content-Type: application/json" \
  -d '{
    "card_number": "BLMM-EN039",
    "card_rarity": "Ultra Rare",
    "force_refresh": false
  }'
```

## Monitoring and Troubleshooting

### View Logs
- Go to your service dashboard on Render
- Click on "Logs" tab to see real-time logs

### Common Issues

1. **"Failed to launch browser"**
   - Ensure Playwright dependencies are installed in build command
   - Check PLAYWRIGHT_HEADLESS is set to true

2. **Memory issues (OOM)**
   - Reduce PLAYWRIGHT_POOL_SIZE to 1
   - Upgrade to a larger instance

3. **Slow response times**
   - Check if browser pool is saturated via `/browser-stats`
   - Consider increasing PLAYWRIGHT_POOL_SIZE (if memory allows)

4. **Connection timeouts**
   - Increase PLAYWRIGHT_TIMEOUT
   - Check MongoDB connection string

### Performance Tuning

For 512MB instances:
- `PLAYWRIGHT_POOL_SIZE=2`
- `HYPERCORN_WORKERS=1`
- `PLAYWRIGHT_MAX_USES_PER_BROWSER=50`

For 2GB+ instances:
- `PLAYWRIGHT_POOL_SIZE=4-6`
- `HYPERCORN_WORKERS=1` (keep at 1 for async)
- `PLAYWRIGHT_MAX_USES_PER_BROWSER=100`

## Scaling

The async browser pool architecture supports:
- **Vertical scaling**: Increase instance size to support more browsers
- **Horizontal scaling**: Not recommended due to browser pool state

## Cost Optimization

1. Use caching effectively (12-24 hour cache duration)
2. Monitor browser pool usage and adjust size
3. Consider using Render's autoscale features for traffic spikes

## Security

1. Never commit `.env` files
2. Use Render's secret files for sensitive configs
3. Restrict MongoDB access to Render IPs only
4. Enable CORS in production (add to async_app.py if needed)

## Support

- Check application logs in Render dashboard
- Monitor `/browser-stats` endpoint for pool health
- Use `/health` endpoint for uptime monitoring
