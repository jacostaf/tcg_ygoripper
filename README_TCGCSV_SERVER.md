# TCGcsv Server - Yu-Gi-Oh Card API

## 🎯 Entry Point
**`tcgcsv_server.py`** - Main server entry point for TCGcsv-based Yu-Gi-Oh API

## 🚀 Running the Server

### Quick Start
```bash
# Activate virtual environment (if using one)
source tcgcsv_venv/bin/activate  # or your venv name

# Run on port 8083 (matches frontend expectation)
python3 tcgcsv_server.py

# Or run on custom port
python3 tcgcsv_server.py --port 8084
```

### Configuration
- **Port**: Configured via `.env.development` (PORT=8083)
- **Data Source**: TCGcsv.com CSV files
- **Concurrency**: Thread-safe with Flask threading enabled
- **Cache**: In-memory cache with 24-hour TTL

## 📁 File Structure
```
tcg_ygoripper/
├── tcgcsv_server.py      ← MAIN ENTRY POINT
├── tcgcsv_simple_app.py  ← Core data fetching (thread-safe)
├── tcgcsv_config.py      ← Configuration settings
├── .env.development      ← Environment config (PORT=8083)
├── main_modular.py       ← Alternative MongoDB-based entry point
└── ygoapi/               ← MongoDB implementation modules
```

## 🔧 Features
- ✅ Thread-safe concurrent request handling
- ✅ In-memory caching with automatic refresh
- ✅ Direct CSV parsing from TCGcsv.com
- ✅ Full REST API compatibility
- ✅ CORS enabled for frontend integration
- ✅ Comprehensive error handling

## 🌐 API Endpoints
- `GET /health` - Health check
- `GET /card-sets/from-cache` - Get all card sets
- `GET /card-sets/<set_name>/cards` - Get cards from specific set
- `POST /cards/price` - Get card pricing data
- And more...

## 💡 Why This Implementation?
- **Simple**: Uses synchronous requests (easier to debug)
- **Fast**: Direct CSV parsing, no database overhead
- **Scalable**: Thread-safe design handles concurrent requests
- **Reliable**: Proven stable architecture with proper error handling