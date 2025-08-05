# TCGcsv Yu-Gi-Oh API Implementation

A simplified Yu-Gi-Oh card database API using TCGcsv.com as the sole data source, eliminating the need for MongoDB, web scraping, and complex price fetching systems.

## 🌟 Features

- **Pure TCGcsv Integration**: Uses TCGcsv.com daily data exports from TCGPlayer
- **No Database Required**: In-memory caching with optional disk persistence
- **Complete Card Data**: Sets, cards, prices, rarities, and card attributes
- **Built-in Images**: Direct TCGPlayer CDN image URLs
- **Fast & Lightweight**: Minimal dependencies, high performance
- **YGOProdeck Fallback**: Optional image fallback for missing card images
- **RESTful API**: Compatible with existing frontend implementations

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Internet connection for TCGcsv.com access

### Installation

1. **Clone and switch to TCGcsv branch:**
   ```bash
   git checkout TCGcsvImplementation
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements-tcgcsv.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.template .env
   # Edit .env with your preferences
   ```

4. **Start the server:**
   ```bash
   python start_tcgcsv.py
   ```

The API will be available at `http://localhost:8081`

## 📊 Data Source

### TCGcsv.com Structure

TCGcsv provides daily exports from TCGPlayer's database:

- **Card Sets (Groups)**: `https://tcgcsv.com/tcgplayer/2/Groups.csv`
- **Cards (Products)**: `https://tcgcsv.com/tcgplayer/2/{groupId}/ProductsAndPrices.csv`
- **Updates**: Daily at 20:00 UTC

### Yu-Gi-Oh Category

- **Category ID**: 2 (Yu-Gi-Oh in TCGPlayer's system)
- **Data Coverage**: All TCGPlayer Yu-Gi-Oh sets and cards
- **Pricing**: Real TCGPlayer market prices included

## 🛠 API Endpoints

### Card Sets

```http
GET /card-sets                    # Get all card sets
GET /card-sets/from-cache         # Same as above (compatibility)
GET /card-sets/{set}/cards        # Get cards in a specific set
GET /card-sets/search/{query}     # Search sets by name
```

### Cards

```http
GET /cards/search?q={name}        # Search cards by name
GET /cards/search?q={name}&set={code}  # Search in specific set
POST /cards/price                 # Get card price (compatibility endpoint)
```

### System

```http
GET /health                       # Health check
GET /status                       # Detailed status
GET /cache/stats                  # Cache statistics
POST /cache/refresh               # Force cache refresh
```

### Debug (if enabled)

```http
GET /debug/config                 # Configuration status
GET /debug/raw-set/{groupId}      # Raw set data
```

## 💾 Caching Strategy

### In-Memory Cache

- **Card Sets**: Cached for 24 hours (configurable)
- **Cards**: Cached per set for 24 hours
- **Hit Rate Tracking**: Monitor cache performance

### Optional Disk Persistence

```bash
./data/
├── card_sets.json      # Cached card sets
├── cards.json          # Cached cards by set
└── cache_meta.json     # Cache metadata
```

### Cache Management

```python
# Force refresh from TCGcsv
curl -X POST http://localhost:8081/cache/refresh

# Check cache statistics
curl http://localhost:8081/cache/stats
```

## ⚙️ Configuration

### Environment Variables

Key configuration options in `.env`:

```bash
# Server
PORT=8081
DEBUG=true

# TCGcsv
TCGCSV_BASE_URL=https://tcgcsv.com
CACHE_EXPIRY_HOURS=24

# Images
USE_TCGCSV_IMAGES=true
ENABLE_YGOPRODECK_IMAGE_FALLBACK=true

# Performance
API_RATE_LIMIT_PER_MINUTE=60
MAX_CONCURRENT_DOWNLOADS=5

# Features
INCLUDE_PRICE_DATA=true
EXCLUDE_SEALED_PRODUCTS=true
ENABLE_DISK_PERSISTENCE=true
```

### Advanced Configuration

See `.env.template` for complete configuration options including:

- Memory management
- Rate limiting
- CORS settings
- Logging configuration
- Feature flags

## 🔧 Development

### Running in Development Mode

```bash
python start_tcgcsv.py --debug --log-level DEBUG
```

### Configuration Validation

```bash
python start_tcgcsv.py --validate-only
```

### Testing TCGcsv Connectivity

```bash
python -c "
import requests
response = requests.get('https://tcgcsv.com/tcgplayer/2/Groups.csv')
print(f'Status: {response.status_code}')
print(f'Sets available: {len(response.text.splitlines()) - 1}')
"
```

## 📋 Data Format

### Card Set Response

```json
{
  "success": true,
  "data": [
    {
      "group_id": 24263,
      "name": "Battles of Legend: Monster Mayhem",
      "abbreviation": "BLMM",
      "published_on": "2025-06-13T00:00:00",
      "id": "BLMM",
      "set_name": "Battles of Legend: Monster Mayhem",
      "set_code": "BLMM"
    }
  ]
}
```

### Card Response

```json
{
  "success": true,
  "data": {
    "cards": [
      {
        "product_id": 635874,
        "name": "Blue-Eyes White Dragon",
        "rarity": "Secret Rare",
        "card_number": "BLMM-EN001",
        "attack": 3000,
        "defense": 2500,
        "attribute": "LIGHT",
        "type": "Normal Monster",
        "race": "Dragon",
        "image_url": "https://tcgplayer-cdn.tcgplayer.com/product/635874_200w.jpg",
        "tcg_price": 6.63,
        "market_price": 6.63,
        "low_price": 5.92,
        "mid_price": 7.75,
        "high_price": 30.0
      }
    ]
  }
}
```

## 🖼️ Image Handling

### Primary Images (TCGcsv)

- **Source**: TCGPlayer CDN (`tcgplayer-cdn.tcgplayer.com`)
- **Format**: Direct URLs from TCGcsv data
- **Quality**: 200px width thumbnails

### Fallback Images (YGOProdeck)

- **Source**: YGOProdeck API (`images.ygoprodeck.com`)
- **Trigger**: When TCGcsv image unavailable
- **Mapping**: Requires card ID mapping logic

### Image Configuration

```bash
# Use TCGcsv images primarily
USE_TCGCSV_IMAGES=true

# Enable YGOProdeck fallback
ENABLE_YGOPRODECK_IMAGE_FALLBACK=true
YGOPRODECK_IMAGE_BASE_URL=https://images.ygoprodeck.com/images/cards
```

## 🔍 Filtering & Search

### Automatic Filtering

- **Sealed Products**: Booster boxes, packs, decks (configurable)
- **Accessories**: Sleeves, mats, dice (configurable)
- **Price Filtering**: Min/max price thresholds

### Search Features

- **Card Name Search**: Fuzzy matching across all sets
- **Set-Specific Search**: Filter by specific set
- **Rarity Filtering**: Filter by card rarity
- **Advanced Search**: Multiple criteria (if enabled)

## 📈 Performance

### Benchmarks

- **Initial Load**: ~2-5 seconds (downloading sets)
- **Set Load**: ~1-3 seconds per set (first time)
- **Cached Requests**: <100ms
- **Search**: <500ms across all cards

### Memory Usage

- **Typical Usage**: 50-100MB RAM
- **Full Cache**: 200-300MB RAM (all sets loaded)
- **Configurable Limits**: Memory thresholds and warnings

## 🔄 Data Updates

### Automatic Updates

- **TCGcsv Schedule**: Daily at 20:00 UTC
- **Cache Expiration**: 24 hours (configurable)
- **Auto-Refresh**: Optional background refresh

### Manual Updates

```bash
# Refresh all data
curl -X POST http://localhost:8081/cache/refresh

# Refresh with all cards
curl -X POST http://localhost:8081/cache/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_cards": true}'
```

## 🚦 Monitoring

### Health Checks

```bash
# Basic health check
curl http://localhost:8081/health

# Detailed status
curl http://localhost:8081/status

# Cache statistics
curl http://localhost:8081/cache/stats
```

### Logging

```bash
# View logs in real-time
python start_tcgcsv.py --log-level DEBUG

# Key log sources
- tcgcsv_service: Data fetching and caching
- tcgcsv_app: API requests and responses
- tcgcsv_config: Configuration validation
```

## ❗ Troubleshooting

### Common Issues

1. **TCGcsv Connection Failed**
   ```bash
   # Test connectivity
   curl -I https://tcgcsv.com/tcgplayer/2/Groups.csv
   ```

2. **Cache Not Refreshing**
   ```bash
   # Force refresh
   curl -X POST http://localhost:8081/cache/refresh
   ```

3. **High Memory Usage**
   ```bash
   # Check cache stats
   curl http://localhost:8081/cache/stats
   
   # Reduce cache size
   echo "CACHE_MAX_SIZE_MB=50" >> .env
   ```

4. **Missing Images**
   ```bash
   # Enable YGOProdeck fallback
   echo "ENABLE_YGOPRODECK_IMAGE_FALLBACK=true" >> .env
   ```

### Debug Mode

```bash
# Enable debug endpoints
echo "ENABLE_DEBUG_ENDPOINTS=true" >> .env

# Check configuration
curl http://localhost:8081/debug/config

# View raw set data
curl http://localhost:8081/debug/raw-set/24263
```

## 🆚 Migration from MongoDB Version

### Key Differences

| Feature | MongoDB Version | TCGcsv Version |
|---------|----------------|----------------|
| Data Source | YGOProdeck API + TCGPlayer scraping | TCGcsv.com exports |
| Storage | MongoDB | In-memory + optional disk |
| Images | YGOProdeck + proxy | TCGPlayer CDN direct |
| Pricing | Web scraping | Native TCGPlayer prices |
| Updates | Manual/scheduled | Daily automatic |
| Dependencies | Heavy (MongoDB, Playwright) | Light (Flask, aiohttp) |

### API Compatibility

- ✅ All existing endpoints supported
- ✅ Response formats maintained
- ✅ Search functionality preserved
- ✅ Price data enhanced
- ✅ Frontend compatible

## 📚 Additional Resources

- **TCGcsv.com**: https://tcgcsv.com/
- **TCGPlayer**: https://www.tcgplayer.com/
- **Yu-Gi-Oh Database**: https://www.db.yugioh-card.com/
- **Flask Documentation**: https://flask.palletsprojects.com/

## 🤝 Contributing

1. Create feature branch from `TCGcsvImplementation`
2. Make changes with tests
3. Update documentation
4. Submit pull request

## 📄 License

Same license as the main project.