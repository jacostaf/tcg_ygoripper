"""
Card set management service for YGO API

Handles card set operations and YGO API integration.
"""

import logging
import requests
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from urllib.parse import quote

from ..database import get_database_manager
from ..memory import get_memory_manager, memory_check_decorator
from ..config import YGO_API_BASE_URL
from ..utils import batch_process_generator

logger = logging.getLogger(__name__)

class CardSetService:
    """Service for managing card sets and YGO API integration."""
    
    def __init__(self):
        self.db_manager = get_database_manager()
        self.memory_manager = get_memory_manager()
        self.api_base_url = YGO_API_BASE_URL
    
    @memory_check_decorator("fetch_card_sets")
    def fetch_all_card_sets(self) -> Dict[str, Any]:
        """Fetch all card sets from YGO API."""
        
        try:
            logger.info("🔄 Fetching all card sets from YGO API...")
            
            # Make request to YGO API
            api_url = f"{self.api_base_url}/cardsets.php"
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Handle both list and object responses from API
                if isinstance(data, list):
                    card_sets = data
                else:
                    card_sets = data.get('data', [])
                
                logger.info(f"✅ Successfully fetched {len(card_sets)} card sets from YGO API")
                
                return {
                    "success": True,
                    "data": card_sets,
                    "count": len(card_sets),
                    "source": "ygo_api"
                }
            else:
                logger.error(f"❌ YGO API returned status code: {response.status_code}")
                return {
                    "success": False,
                    "error": f"API returned status code {response.status_code}",
                    "data": []
                }
        
        except requests.exceptions.Timeout:
            logger.error("⏰ Request to YGO API timed out")
            return {
                "success": False,
                "error": "Request timed out",
                "data": []
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"🔌 Request error: {str(e)}")
            return {
                "success": False,
                "error": "Failed to connect to YGO API",
                "data": []
            }
        except Exception as e:
            logger.error(f"💥 Unexpected error: {str(e)}")
            return {
                "success": False,
                "error": "Internal server error",
                "data": []
            }
    
    @memory_check_decorator("search_card_sets")
    def search_card_sets(self, set_name: str) -> Dict[str, Any]:
        """Search for card sets by name."""
        
        try:
            logger.info(f"🔍 Searching for card sets with name: {set_name}")
            
            # Make request to YGO API
            encoded_name = quote(set_name)
            api_url = f"{self.api_base_url}/cardsets.php"
            response = requests.get(api_url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Handle both list and object responses from API
                if isinstance(data, list):
                    all_sets = data
                else:
                    all_sets = data.get('data', [])
                
                # Filter sets by name (case-insensitive)
                matching_sets = [
                    card_set for card_set in all_sets
                    if set_name.lower() in card_set.get('set_name', '').lower()
                ]
                
                logger.info(f"✅ Found {len(matching_sets)} matching card sets")
                
                return {
                    "success": True,
                    "data": matching_sets,
                    "count": len(matching_sets),
                    "search_term": set_name,
                    "source": "ygo_api"
                }
            else:
                logger.error(f"❌ YGO API returned status code: {response.status_code}")
                return {
                    "success": False,
                    "error": f"API returned status code {response.status_code}",
                    "data": []
                }
        
        except Exception as e:
            logger.error(f"Error searching card sets: {str(e)}")
            return {
                "success": False,
                "error": "Failed to search card sets",
                "data": []
            }
    
    @memory_check_decorator("upload_card_sets")
    def upload_card_sets_to_cache(self) -> Dict[str, Any]:
        """Upload card sets to MongoDB cache."""
        
        try:
            logger.info("📤 Starting card sets upload to MongoDB cache...")
            
            # Fetch fresh data from YGO API
            fetch_result = self.fetch_all_card_sets()
            
            if not fetch_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to fetch card sets: {fetch_result['error']}",
                    "statistics": {}
                }
            
            card_sets = fetch_result["data"]
            
            # Add upload metadata
            upload_timestamp = datetime.now(UTC)
            for card_set in card_sets:
                card_set['_uploaded_at'] = upload_timestamp
                card_set['_source'] = 'ygoprodeck_api'
            
            # Upload to database
            upload_result = self.db_manager.upload_card_sets(card_sets)
            
            logger.info(f"✅ Successfully uploaded {upload_result['inserted_count']} card sets to MongoDB")
            
            return {
                "success": True,
                "message": "Card sets uploaded successfully to MongoDB",
                "statistics": {
                    "total_sets_uploaded": upload_result['inserted_count'],
                    "previous_documents_cleared": upload_result['deleted_count'],
                    "upload_timestamp": upload_timestamp.isoformat()
                }
            }
        
        except Exception as e:
            logger.error(f"Error uploading card sets: {str(e)}")
            return {
                "success": False,
                "error": "Internal server error during upload",
                "statistics": {}
            }
    
    @memory_check_decorator("get_cached_card_sets")
    def get_card_sets_from_cache(self) -> Dict[str, Any]:
        """Get card sets from MongoDB cache."""
        
        try:
            logger.info("📂 Retrieving card sets from MongoDB cache...")
            
            card_sets = self.db_manager.get_card_sets_from_cache()
            
            if not card_sets:
                return {
                    "success": False,
                    "error": "No card sets found in cache",
                    "data": [],
                    "count": 0
                }
            
            # Build cache info
            cache_info = {
                "last_updated": None,
                "source": None
            }
            
            if card_sets:
                first_set = card_sets[0]
                cache_info["last_updated"] = first_set.get('_uploaded_at')
                cache_info["source"] = first_set.get('_source')
            
            logger.info(f"✅ Retrieved {len(card_sets)} card sets from MongoDB cache")
            
            return {
                "success": True,
                "data": card_sets,
                "count": len(card_sets),
                "cache_info": cache_info,
                "message": f"Retrieved {len(card_sets)} card sets from cache"
            }
        
        except Exception as e:
            logger.error(f"Error retrieving card sets from cache: {str(e)}")
            return {
                "success": False,
                "error": "Failed to retrieve card sets from cache",
                "data": [],
                "count": 0
            }
    
    def get_card_sets_count(self) -> Dict[str, Any]:
        """Get count of card sets in cache."""
        
        try:
            count = self.db_manager.get_card_sets_count()
            
            return {
                "success": True,
                "count": count,
                "message": f"Total card sets in cache: {count}"
            }
        
        except Exception as e:
            logger.error(f"Error getting card sets count: {str(e)}")
            return {
                "success": False,
                "error": "Failed to get card sets count",
                "count": 0
            }
    
    @memory_check_decorator("fetch_cards_from_set")
    def get_cards_from_set(self, set_name: str) -> Dict[str, Any]:
        """Get all cards from a specific set."""
        
        try:
            logger.info(f"🔍 Fetching cards from set: {set_name}")
            
            # URL encode the set name for the API call
            encoded_set_name = quote(set_name)
            api_url = f"{self.api_base_url}/cardinfo.php?cardset={encoded_set_name}"
            
            response = requests.get(api_url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                cards = data.get('data', [])
                
                logger.info(f"✅ Successfully fetched {len(cards)} cards from {set_name}")
                
                return {
                    "success": True,
                    "data": cards,
                    "count": len(cards),
                    "set_name": set_name,
                    "source": "ygo_api"
                }
            
            elif response.status_code == 400:
                logger.warning(f"⚠️ No cards found for set: {set_name}")
                return {
                    "success": False,
                    "error": f"No cards found for set: {set_name}",
                    "data": [],
                    "count": 0
                }
            
            else:
                logger.error(f"❌ API error for set {set_name}: HTTP {response.status_code}")
                return {
                    "success": False,
                    "error": f"API error: HTTP {response.status_code}",
                    "data": [],
                    "count": 0
                }
        
        except requests.exceptions.Timeout:
            logger.error(f"⏰ Timeout fetching cards for set: {set_name}")
            return {
                "success": False,
                "error": "Request timed out",
                "data": [],
                "count": 0
            }
        except Exception as e:
            logger.error(f"Error fetching cards from set {set_name}: {str(e)}")
            return {
                "success": False,
                "error": "Failed to fetch cards from set",
                "data": [],
                "count": 0
            }
    
    @memory_check_decorator("fetch_all_cards_from_sets")
    def fetch_all_cards_from_sets(self) -> Dict[str, Any]:
        """Fetch all cards from all cached sets."""
        
        try:
            logger.info("🔄 Starting to fetch all cards from all cached sets...")
            
            # Get cached sets
            cached_sets_result = self.get_card_sets_from_cache()
            
            if not cached_sets_result["success"]:
                return {
                    "success": False,
                    "error": "No cached card sets found. Please upload sets first.",
                    "statistics": {}
                }
            
            cached_sets = cached_sets_result["data"]
            
            # Initialize processing statistics
            processing_stats = {
                "total_sets": len(cached_sets),
                "processed_sets": 0,
                "failed_sets": 0,
                "total_cards_found": 0,
                "processing_errors": []
            }
            
            all_cards_data = {}
            
            # Process sets in batches to manage memory
            for batch in batch_process_generator(cached_sets, batch_size=10):
                for card_set in batch:
                    set_name = card_set.get('set_name', '')
                    
                    try:
                        # Fetch cards from this set
                        cards_result = self.get_cards_from_set(set_name)
                        
                        if cards_result["success"]:
                            cards_list = cards_result["data"]
                            
                            # Store cards data for this set
                            all_cards_data[set_name] = {
                                "set_info": card_set,
                                "cards": cards_list,
                                "card_count": len(cards_list)
                            }
                            
                            processing_stats["total_cards_found"] += len(cards_list)
                            processing_stats["processed_sets"] += 1
                            
                            logger.info(f"✅ Successfully fetched {len(cards_list)} cards from {set_name}")
                        
                        else:
                            processing_stats["failed_sets"] += 1
                            processing_stats["processing_errors"].append({
                                "set_name": set_name,
                                "error": cards_result["error"]
                            })
                        
                        # Rate limiting delay
                        time.sleep(0.1)  # 100ms delay between requests
                    
                    except Exception as e:
                        error_msg = f"Error processing set {set_name}: {str(e)}"
                        logger.error(error_msg)
                        processing_stats["failed_sets"] += 1
                        processing_stats["processing_errors"].append({
                            "set_name": set_name,
                            "error": error_msg
                        })
                
                # Force garbage collection between batches
                if self.memory_manager.get_memory_level() != "normal":
                    self.memory_manager.force_garbage_collection()
            
            # Calculate success rate
            processing_stats["success_rate"] = (
                processing_stats["processed_sets"] / processing_stats["total_sets"] * 100
                if processing_stats["total_sets"] > 0 else 0
            )
            
            logger.info(f"✅ Completed fetching cards from {processing_stats['processed_sets']} sets")
            
            return {
                "success": True,
                "message": f"Successfully fetched cards from {processing_stats['processed_sets']} sets",
                "data": all_cards_data,
                "statistics": processing_stats
            }
        
        except Exception as e:
            logger.error(f"Unexpected error during card fetching: {str(e)}")
            return {
                "success": False,
                "error": "Internal server error during card fetching",
                "statistics": {}
            }

# Global service instance
_card_set_service: Optional[CardSetService] = None

def get_card_set_service() -> CardSetService:
    """Get the global card set service instance."""
    global _card_set_service
    if _card_set_service is None:
        _card_set_service = CardSetService()
    return _card_set_service