# YGO PY GUY - Yu-Gi-Oh! Card Database API

A comprehensive Flask API for fetching, caching, and managing Yu-Gi-Oh! card data using the YGOPRODeck API and MongoDB, with integrated price scraping from PriceCharting.com.

## Features

- **Card Sets Management**: Fetch and cache all Yu-Gi-Oh! card sets
- **Card Variants Database**: Create unique entries for each card variant (different rarities, sets, and artworks)
- **Price Scraping**: Automated price collection from TCGPlayer.com with intelligent variant selection
- **MongoDB Integration**: Efficient caching and storage of card data and pricing information
- **Rate Limiting Compliance**: Respects YGOPRODeck API rate limits (20 requests/second)
- **Comprehensive API**: Multiple endpoints for different data access patterns

## Endpoints

### Card Sets
- `GET /health` - Health check
- `GET /card-sets` - Get all card sets from YGO API
- `POST /card-sets/upload` - Upload card sets to MongoDB cache
- `GET /card-sets/from-cache` - Get cached card sets from MongoDB
- `GET /card-sets/search/<set_name>` - Search for card sets by name
- `GET /card-sets/count` - Get total count of card sets

### Card Data
- `POST /card-sets/fetch-all-cards` - Fetch all cards from all cached sets
- `GET /card-sets/<set_name>/cards` - Get all cards from a specific set
- `POST /cards/upload-variants` - Upload card variants to MongoDB
- `GET /cards/variants` - Get card variants with pagination

### Price Data
- `POST /cards/price` - Scrape price data for a specific card from TCGPlayer.com
- `GET /cards/price/cache-stats` - Get statistics about the price cache collection

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/jacostaf/YGOPYGUY.git
   cd YGOPYGUY
   ```

2. **Create virtual environment**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   
   **Having installation issues?** See [INSTALLATION.md](INSTALLATION.md) for troubleshooting guide, especially for Python 3.13 and macOS users.
   ```

4. **Configure environment variables**
   Create a `.env` file in the project root:
   ```
   MONGODB_CONNECTION_STRING=mongodb://localhost:27017/ygo_database
   ```

5. **Run the application**
   ```bash
   python main.py
   ```

The API will be available at `http://localhost:5001`

## Usage Workflow

1. **Upload card sets**: `POST /card-sets/upload`
2. **Upload card variants**: `POST /cards/upload-variants`
3. **Query data**: Use various GET endpoints to access cached data

## Database Collections

- `YGO_SETS_CACHE_V1` - Cached card sets
- `YGO_CARD_VARIANT_CACHE_V1` - Unique card variants
- `YGO_CARD_VARIANT_PRICE_CACHE_V1` - Cached price data with multiple grade levels

## Price Scraping Features

### Intelligent Variant Selection
- Automatically selects the best matching card variant based on:
  - Card number matching
  - Rarity matching (Quarter Century, Platinum Secret Rare, etc.)
  - Art version matching (1st Art, 7th Art, etc.)
  - Advanced scoring algorithm for precise variant identification

### Price Data Collection
- **TCGPlayer Prices**: Direct market prices from TCGPlayer including both regular and market prices
- **Smart Caching**: 7-day cache expiry with force refresh option

### Supported Card Features
- Quarter Century Secret/Ultra Rare variants
- Platinum Secret Rare variants
- Multiple art versions (1st, 2nd, 3rd, etc.)
- Set-specific rarities and variants

## API Usage Examples

### Scrape Card Price
```bash
curl -X POST http://localhost:8080/cards/price \
  -H "Content-Type: application/json" \
  -d '{
    "card_number": "RA04-EN016",
    "card_name": "Black Metal Dragon",
    "card_rarity": "Secret Rare",
    "art_variant": "",
    "force_refresh": "true"
  }'
```

### Get Cache Statistics
```bash
curl http://localhost:8080/cards/price/cache-stats
```

## Data Sources

This project uses:
- [YGOPRODeck API](https://ygoprodeck.com/api-guide/) for all Yu-Gi-Oh! card data
- [TCGPlayer.com](https://www.tcgplayer.com/) for market price data and card pricing information

## Rate Limiting

The application includes built-in rate limiting to comply with:
- YGOPRODeck API limits (20 requests per second with 100ms delays between requests)
- TCGPlayer.com scraping with respectful delays and browser automation

## License

This project is open source and available under the [MIT License](LICENSE).