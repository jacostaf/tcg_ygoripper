from flask import Flask, jsonify
import requests
import logging
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime
import time
from urllib.parse import quote

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# YGO API base URL
YGO_API_BASE_URL = "https://db.ygoprodeck.com/api/v7"

# MongoDB configuration
MONGODB_CONNECTION_STRING = os.getenv('MONGODB_CONNECTION_STRING')
MONGODB_COLLECTION_NAME = "YGO_SETS_CACHE_V1"
MONGODB_CARD_VARIANTS_COLLECTION = "YGO_CARD_VARIANT_CACHE_V1"

def get_mongo_client():
    """Get MongoDB client connection"""
    try:
        client = MongoClient(MONGODB_CONNECTION_STRING)
        # Test the connection
        client.admin.command('ping')
        return client
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
        return None

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "message": "YGO API is running"})

@app.route('/card-sets', methods=['GET'])
def get_all_card_sets():
    """
    Get all Yu-Gi-Oh! card sets from the YGO API
    Returns: JSON response with all card sets including set name, code, number of cards, and TCG date
    """
    try:
        # Make request to YGO API cardsets endpoint
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        # Check if request was successful
        if response.status_code == 200:
            card_sets_data = response.json()
            
            # Log successful request
            logger.info(f"Successfully retrieved {len(card_sets_data)} card sets")
            
            return jsonify({
                "success": True,
                "data": card_sets_data,
                "count": len(card_sets_data),
                "message": "Card sets retrieved successfully"
            })
        
        else:
            logger.error(f"YGO API returned status code: {response.status_code}")
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API",
                "status_code": response.status_code
            }), 500
            
    except requests.exceptions.Timeout:
        logger.error("Request to YGO API timed out")
        return jsonify({
            "success": False,
            "error": "Request timed out"
        }), 504
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to connect to YGO API"
        }), 503
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@app.route('/card-sets/search/<string:set_name>', methods=['GET'])
def search_card_sets(set_name):
    """
    Search for card sets by name (case-insensitive partial match)
    Args:
        set_name: Name or partial name of the card set to search for
    Returns: JSON response with matching card sets
    """
    try:
        # Get all card sets first
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        if response.status_code == 200:
            all_sets = response.json()
            
            # Filter sets by name (case-insensitive)
            matching_sets = [
                card_set for card_set in all_sets 
                if set_name.lower() in card_set.get('set_name', '').lower()
            ]
            
            logger.info(f"Found {len(matching_sets)} card sets matching '{set_name}'")
            
            return jsonify({
                "success": True,
                "data": matching_sets,
                "count": len(matching_sets),
                "search_term": set_name,
                "message": f"Found {len(matching_sets)} matching card sets"
            })
        
        else:
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API",
                "status_code": response.status_code
            }), 500
            
    except Exception as e:
        logger.error(f"Error searching card sets: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to search card sets"
        }), 500

@app.route('/card-sets/upload', methods=['POST'])
def upload_card_sets_to_mongodb():
    """
    Upload all card sets from YGO API to MongoDB collection YGO_SETS_CACHE_V1
    Returns: JSON response with upload status and statistics
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Make request to YGO API cardsets endpoint
        logger.info("Fetching card sets from YGO API...")
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API",
                "status_code": response.status_code
            }), 500
        
        card_sets_data = response.json()
        logger.info(f"Retrieved {len(card_sets_data)} card sets from API")
        
        # Get database and collection
        db = client.get_default_database()
        collection = db[MONGODB_COLLECTION_NAME]
        
        # Add metadata to each document
        upload_timestamp = datetime.utcnow()
        for card_set in card_sets_data:
            card_set['_uploaded_at'] = upload_timestamp
            card_set['_source'] = 'ygoprodeck_api'
        
        # Clear existing data in collection
        delete_result = collection.delete_many({})
        logger.info(f"Cleared {delete_result.deleted_count} existing documents")
        
        # Insert new data
        insert_result = collection.insert_many(card_sets_data)
        inserted_count = len(insert_result.inserted_ids)
        
        # Create index on set_code for better query performance
        collection.create_index("set_code")
        collection.create_index("set_name")
        
        logger.info(f"Successfully uploaded {inserted_count} card sets to MongoDB")
        
        # Close MongoDB connection
        client.close()
        
        return jsonify({
            "success": True,
            "message": "Card sets uploaded successfully to MongoDB",
            "statistics": {
                "total_sets_uploaded": inserted_count,
                "previous_documents_cleared": delete_result.deleted_count,
                "collection_name": MONGODB_COLLECTION_NAME,
                "upload_timestamp": upload_timestamp.isoformat()
            }
        })
        
    except requests.exceptions.Timeout:
        logger.error("Request to YGO API timed out")
        return jsonify({
            "success": False,
            "error": "Request timed out"
        }), 504
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to connect to YGO API"
        }), 503
        
    except Exception as e:
        logger.error(f"Unexpected error during upload: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during upload"
        }), 500

@app.route('/card-sets/from-cache', methods=['GET'])
def get_card_sets_from_cache():
    """
    Get all card sets from MongoDB cache
    Returns: JSON response with cached card sets
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Get database and collection
        db = client.get_default_database()
        collection = db[MONGODB_COLLECTION_NAME]
        
        # Get all documents (excluding MongoDB internal fields)
        cursor = collection.find({}, {"_id": 0})
        card_sets = list(cursor)
        
        # Get cache metadata if available
        cache_info = None
        if card_sets:
            cache_info = {
                "last_updated": card_sets[0].get('_uploaded_at'),
                "source": card_sets[0].get('_source')
            }
        
        # Close MongoDB connection
        client.close()
        
        logger.info(f"Retrieved {len(card_sets)} card sets from MongoDB cache")
        
        return jsonify({
            "success": True,
            "data": card_sets,
            "count": len(card_sets),
            "cache_info": cache_info,
            "message": f"Retrieved {len(card_sets)} card sets from cache"
        })
        
    except Exception as e:
        logger.error(f"Error retrieving card sets from cache: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to retrieve card sets from cache"
        }), 500

@app.route('/card-sets/count', methods=['GET'])
def get_card_sets_count():
    """
    Get the total count of card sets
    Returns: JSON response with total count
    """
    try:
        response = requests.get(f"{YGO_API_BASE_URL}/cardsets.php", timeout=10)
        
        if response.status_code == 200:
            card_sets_data = response.json()
            total_count = len(card_sets_data)
            
            return jsonify({
                "success": True,
                "total_sets": total_count,
                "message": f"Total card sets available: {total_count}"
            })
        
        else:
            return jsonify({
                "success": False,
                "error": "Failed to fetch data from YGO API"
            }), 500
            
    except Exception as e:
        logger.error(f"Error getting card sets count: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to get card sets count"
        }), 500

@app.route('/card-sets/fetch-all-cards', methods=['POST'])
def fetch_all_cards_from_sets():
    """
    Iterate through all cached card sets and fetch all cards for each set
    Returns: JSON response with comprehensive card data from all sets
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Get database and collection for sets
        db = client.get_default_database()
        sets_collection = db[MONGODB_COLLECTION_NAME]
        
        # Get all cached sets
        cached_sets = list(sets_collection.find({}, {"_id": 0}))
        if not cached_sets:
            return jsonify({
                "success": False,
                "error": "No cached card sets found. Please upload sets first using /card-sets/upload"
            }), 404
        
        logger.info(f"Found {len(cached_sets)} cached sets to process")
        
        # Initialize response data
        all_cards_data = {}
        processing_stats = {
            "total_sets": len(cached_sets),
            "processed_sets": 0,
            "failed_sets": 0,
            "total_cards_found": 0,
            "processing_errors": []
        }
        
        # Rate limiting: 20 requests per second max
        request_delay = 0.1  # 100ms delay between requests to stay under limit
        
        # Process each set
        for index, card_set in enumerate(cached_sets):
            set_name = card_set.get('set_name', '')
            set_code = card_set.get('set_code', '')
            
            try:
                logger.info(f"Processing set {index + 1}/{len(cached_sets)}: {set_name}")
                
                # URL encode the set name for the API call
                encoded_set_name = quote(set_name)
                
                # Make request to YGO API for cards in this set
                api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
                response = requests.get(api_url, timeout=15)
                
                if response.status_code == 200:
                    cards_data = response.json()
                    cards_list = cards_data.get('data', [])
                    
                    # Store cards data for this set
                    all_cards_data[set_name] = {
                        "set_info": card_set,
                        "cards": cards_list,
                        "card_count": len(cards_list)
                    }
                    
                    processing_stats["total_cards_found"] += len(cards_list)
                    processing_stats["processed_sets"] += 1
                    
                    logger.info(f"Successfully fetched {len(cards_list)} cards from {set_name}")
                    
                elif response.status_code == 400:
                    # Set might not have cards or name might be invalid
                    logger.warning(f"No cards found for set: {set_name} (400 response)")
                    all_cards_data[set_name] = {
                        "set_info": card_set,
                        "cards": [],
                        "card_count": 0,
                        "note": "No cards found for this set"
                    }
                    processing_stats["processed_sets"] += 1
                    
                else:
                    error_msg = f"API error for set {set_name}: HTTP {response.status_code}"
                    logger.error(error_msg)
                    processing_stats["failed_sets"] += 1
                    processing_stats["processing_errors"].append({
                        "set_name": set_name,
                        "error": error_msg
                    })
                
                # Rate limiting delay
                time.sleep(request_delay)
                
            except requests.exceptions.Timeout:
                error_msg = f"Timeout fetching cards for set: {set_name}"
                logger.error(error_msg)
                processing_stats["failed_sets"] += 1
                processing_stats["processing_errors"].append({
                    "set_name": set_name,
                    "error": error_msg
                })
                
            except Exception as e:
                error_msg = f"Error processing set {set_name}: {str(e)}"
                logger.error(error_msg)
                processing_stats["failed_sets"] += 1
                processing_stats["processing_errors"].append({
                    "set_name": set_name,
                    "error": error_msg
                })
        
        # Close MongoDB connection
        client.close()
        
        # Calculate final statistics
        processing_stats["success_rate"] = (
            processing_stats["processed_sets"] / processing_stats["total_sets"] * 100
            if processing_stats["total_sets"] > 0 else 0
        )
        
        logger.info(f"Completed processing all sets. Found {processing_stats['total_cards_found']} total cards")
        
        return jsonify({
            "success": True,
            "message": "Successfully fetched cards from all sets",
            "data": all_cards_data,
            "statistics": processing_stats
        })
        
    except Exception as e:
        logger.error(f"Unexpected error during card fetching: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during card fetching"
        }), 500

@app.route('/card-sets/<string:set_name>/cards', methods=['GET'])
def get_cards_from_specific_set(set_name):
    """
    Get all cards from a specific card set
    Args:
        set_name: Name of the card set to fetch cards from
    Returns: JSON response with all cards from the specified set
    """
    try:
        # URL encode the set name for the API call
        encoded_set_name = quote(set_name)
        
        # Make request to YGO API for cards in this set
        logger.info(f"Fetching cards from set: {set_name}")
        api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
        response = requests.get(api_url, timeout=15)
        
        if response.status_code == 200:
            cards_data = response.json()
            cards_list = cards_data.get('data', [])
            
            logger.info(f"Successfully fetched {len(cards_list)} cards from {set_name}")
            
            return jsonify({
                "success": True,
                "set_name": set_name,
                "data": cards_list,
                "card_count": len(cards_list),
                "message": f"Successfully fetched {len(cards_list)} cards from {set_name}"
            })
            
        elif response.status_code == 400:
            return jsonify({
                "success": False,
                "set_name": set_name,
                "error": "No cards found for this set or invalid set name",
                "card_count": 0
            }), 404
            
        else:
            return jsonify({
                "success": False,
                "set_name": set_name,
                "error": f"API error: HTTP {response.status_code}"
            }), 500
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching cards for set: {set_name}")
        return jsonify({
            "success": False,
            "set_name": set_name,
            "error": "Request timed out"
        }), 504
        
    except Exception as e:
        logger.error(f"Error fetching cards for set {set_name}: {str(e)}")
        return jsonify({
            "success": False,
            "set_name": set_name,
            "error": "Internal server error"
        }), 500

@app.route('/cards/upload-variants', methods=['POST'])
def upload_card_variants_to_mongodb():
    """
    Fetch all cards from cached sets and upload them as unique variants to MongoDB
    Each variant is unique by: card_id, set_code, set_rarity, and card_image_id
    Returns: JSON response with upload status and statistics
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Get database and collections
        db = client.get_default_database()
        sets_collection = db[MONGODB_COLLECTION_NAME]
        variants_collection = db[MONGODB_CARD_VARIANTS_COLLECTION]
        
        # Get all cached sets
        cached_sets = list(sets_collection.find({}, {"_id": 0}))
        if not cached_sets:
            return jsonify({
                "success": False,
                "error": "No cached card sets found. Please upload sets first using /card-sets/upload"
            }), 404
        
        logger.info(f"Found {len(cached_sets)} cached sets to process for card variants")
        
        # Initialize processing data
        all_variants = []
        variant_ids_seen = set()  # Track unique variant IDs to prevent duplicates
        processing_stats = {
            "total_sets": len(cached_sets),
            "processed_sets": 0,
            "failed_sets": 0,
            "total_cards_processed": 0,
            "unique_variants_created": 0,
            "duplicate_variants_skipped": 0,
            "processing_errors": []
        }
        
        # Rate limiting: 20 requests per second max
        request_delay = 0.1  # 100ms delay between requests
        upload_timestamp = datetime.utcnow()
        
        # Process each set
        for index, card_set in enumerate(cached_sets):
            set_name = card_set.get('set_name', '')
            set_code = card_set.get('set_code', '')
            
            try:
                logger.info(f"Processing set {index + 1}/{len(cached_sets)}: {set_name}")
                
                # URL encode the set name for the API call
                encoded_set_name = quote(set_name)
                
                # Make request to YGO API for cards in this set
                api_url = f"{YGO_API_BASE_URL}/cardinfo.php?cardset={encoded_set_name}"
                response = requests.get(api_url, timeout=15)
                
                if response.status_code == 200:
                    cards_data = response.json()
                    cards_list = cards_data.get('data', [])
                    
                    # Process each card to create variants
                    for card in cards_list:
                        card_id = card.get('id')
                        card_name = card.get('name', '')
                        card_sets = card.get('card_sets', [])
                        card_images = card.get('card_images', [])
                        
                        processing_stats["total_cards_processed"] += 1
                        
                        # Create variants for each set appearance
                        for card_set_info in card_sets:
                            # Skip if this card set info doesn't match our current set
                            if card_set_info.get('set_name') != set_name:
                                continue
                                
                            # Create variants for each artwork/image
                            for image_info in card_images:
                                image_id = image_info.get('id')
                                
                                # Create unique variant identifier
                                variant_id = f"{card_id}_{card_set_info.get('set_code', '')}_{card_set_info.get('set_rarity', '')}_{image_id}"
                                
                                # Skip this variant if it has already been seen
                                if variant_id in variant_ids_seen:
                                    processing_stats["duplicate_variants_skipped"] += 1
                                    continue
                                
                                # Create variant document
                                variant_doc = {
                                    "_variant_id": variant_id,
                                    "_uploaded_at": upload_timestamp,
                                    "_source": "ygoprodeck_api",
                                    
                                    # Card basic info
                                    "card_id": card_id,
                                    "card_name": card_name,
                                    "card_type": card.get('type'),
                                    "card_frameType": card.get('frameType'),
                                    "card_desc": card.get('desc'),
                                    "ygoprodeck_url": card.get('ygoprodeck_url'),
                                    
                                    # Monster specific stats
                                    "atk": card.get('atk'),
                                    "def": card.get('def'),
                                    "level": card.get('level'),
                                    "race": card.get('race'),
                                    "attribute": card.get('attribute'),
                                    "scale": card.get('scale'),
                                    "linkval": card.get('linkval'),
                                    "linkmarkers": card.get('linkmarkers'),
                                    "archetype": card.get('archetype'),
                                    
                                    # Set specific info
                                    "set_name": card_set_info.get('set_name'),
                                    "set_code": card_set_info.get('set_code'),
                                    "set_rarity": card_set_info.get('set_rarity'),
                                    "set_rarity_code": card_set_info.get('set_rarity_code'),
                                    "set_price": card_set_info.get('set_price'),
                                    
                                    # Image/artwork specific info
                                    "image_id": image_id,
                                    "image_url": image_info.get('image_url'),
                                    "image_url_small": image_info.get('image_url_small'),
                                    "image_url_cropped": image_info.get('image_url_cropped'),
                                    
                                    # Additional data
                                    "card_prices": card.get('card_prices', []),
                                    "banlist_info": card.get('banlist_info', {}),
                                    
                                    # Set metadata
                                    "set_tcg_date": card_set.get('tcg_date'),
                                    "set_num_of_cards": card_set.get('num_of_cards')
                                }
                                
                                all_variants.append(variant_doc)
                                variant_ids_seen.add(variant_id)
                    
                    processing_stats["processed_sets"] += 1
                    logger.info(f"Successfully processed {len(cards_list)} cards from {set_name}")
                    
                elif response.status_code == 400:
                    # Set might not have cards or name might be invalid
                    logger.warning(f"No cards found for set: {set_name} (400 response)")
                    processing_stats["processed_sets"] += 1
                    
                else:
                    error_msg = f"API error for set {set_name}: HTTP {response.status_code}"
                    logger.error(error_msg)
                    processing_stats["failed_sets"] += 1
                    processing_stats["processing_errors"].append({
                        "set_name": set_name,
                        "error": error_msg
                    })
                
                # Rate limiting delay
                time.sleep(request_delay)
                
            except requests.exceptions.Timeout:
                error_msg = f"Timeout fetching cards for set: {set_name}"
                logger.error(error_msg)
                processing_stats["failed_sets"] += 1
                processing_stats["processing_errors"].append({
                    "set_name": set_name,
                    "error": error_msg
                })
                
            except Exception as e:
                error_msg = f"Error processing set {set_name}: {str(e)}"
                logger.error(error_msg)
                processing_stats["failed_sets"] += 1
                processing_stats["processing_errors"].append({
                    "set_name": set_name,
                    "error": error_msg
                })
        
        # Upload variants to MongoDB
        if all_variants:
            logger.info(f"Uploading {len(all_variants)} card variants to MongoDB...")
            
            # Clear existing data in collection
            delete_result = variants_collection.delete_many({})
            logger.info(f"Cleared {delete_result.deleted_count} existing variant documents")
            
            # Insert new variants in batches to handle large datasets
            batch_size = 1000
            inserted_total = 0
            
            for i in range(0, len(all_variants), batch_size):
                batch = all_variants[i:i + batch_size]
                try:
                    insert_result = variants_collection.insert_many(batch, ordered=False)
                    inserted_total += len(insert_result.inserted_ids)
                    logger.info(f"Inserted batch {i//batch_size + 1}: {len(insert_result.inserted_ids)} variants")
                except Exception as e:
                    logger.error(f"Error inserting batch {i//batch_size + 1}: {str(e)}")
                    processing_stats["processing_errors"].append({
                        "batch": f"{i//batch_size + 1}",
                        "error": f"Batch insert error: {str(e)}"
                    })
            
            processing_stats["unique_variants_created"] = inserted_total
            
            # Create indexes for better query performance
            try:
                variants_collection.create_index("_variant_id", unique=True)
                variants_collection.create_index("card_id")
                variants_collection.create_index("card_name")
                variants_collection.create_index("set_code")
                variants_collection.create_index("set_name")
                variants_collection.create_index("set_rarity")
                variants_collection.create_index([("card_id", 1), ("set_code", 1), ("set_rarity", 1)])
                logger.info("Created indexes for card variants collection")
            except Exception as e:
                logger.error(f"Error creating indexes: {str(e)}")
        
        # Close MongoDB connection
        client.close()
        
        # Calculate final statistics
        processing_stats["success_rate"] = (
            processing_stats["processed_sets"] / processing_stats["total_sets"] * 100
            if processing_stats["total_sets"] > 0 else 0
        )
        
        logger.info(f"Completed uploading card variants. Created {processing_stats['unique_variants_created']} unique variants")
        
        return jsonify({
            "success": True,
            "message": "Successfully uploaded card variants to MongoDB",
            "collection_name": MONGODB_CARD_VARIANTS_COLLECTION,
            "statistics": processing_stats,
            "upload_timestamp": upload_timestamp.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Unexpected error during variant upload: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error during variant upload"
        }), 500

@app.route('/cards/variants', methods=['GET'])
def get_card_variants_from_cache():
    """
    Get all card variants from MongoDB cache
    Returns: JSON response with cached card variants
    """
    try:
        # Check MongoDB connection
        if not MONGODB_CONNECTION_STRING:
            return jsonify({
                "success": False,
                "error": "MongoDB connection string not configured"
            }), 500
        
        # Get MongoDB client
        client = get_mongo_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "Failed to connect to MongoDB"
            }), 500
        
        # Get database and collection
        db = client.get_default_database()
        collection = db[MONGODB_CARD_VARIANTS_COLLECTION]
        
        # Get pagination parameters from query string
        from flask import request
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        skip = (page - 1) * limit
        
        # Get documents with pagination (excluding MongoDB internal _id field)
        cursor = collection.find({}, {"_id": 0}).skip(skip).limit(limit)
        variants = list(cursor)
        
        # Get total count
        total_count = collection.count_documents({})
        
        # Get cache metadata if available
        cache_info = None
        if variants:
            cache_info = {
                "last_updated": variants[0].get('_uploaded_at'),
                "source": variants[0].get('_source')
            }
        
        # Close MongoDB connection
        client.close()
        
        logger.info(f"Retrieved {len(variants)} card variants from MongoDB cache (page {page})")
        
        return jsonify({
            "success": True,
            "data": variants,
            "pagination": {
                "current_page": page,
                "per_page": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit,
                "has_next": skip + len(variants) < total_count,
                "has_prev": page > 1
            },
            "cache_info": cache_info,
            "message": f"Retrieved {len(variants)} card variants from cache"
        })
        
    except Exception as e:
        logger.error(f"Error retrieving card variants from cache: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to retrieve card variants from cache"
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500

if __name__ == '__main__':
    print("Starting YGO Card Sets API...")
    print("Available endpoints:")
    print("  GET /health - Health check")
    print("  GET /card-sets - Get all card sets")
    print("  GET /card-sets/search/<set_name> - Search card sets by name")
    print("  POST /card-sets/upload - Upload card sets to MongoDB")
    print("  GET /card-sets/from-cache - Get card sets from MongoDB cache")
    print("  POST /card-sets/fetch-all-cards - Fetch all cards from all cached sets")
    print("  GET /card-sets/<set_name>/cards - Get all cards from a specific set")
    print("  GET /card-sets/count - Get total count of card sets")
    print("  POST /cards/upload-variants - Upload card variants to MongoDB")
    print("  GET /cards/variants - Get card variants from MongoDB cache")