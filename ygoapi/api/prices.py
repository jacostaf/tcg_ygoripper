"""
Price-related API endpoints.

This module contains all the price-related API endpoints for the YGOAPI.
"""
import re
from flask import Blueprint, jsonify, request, current_app
from bson import ObjectId
from datetime import datetime, timedelta, UTC
from typing import Dict, Any, Optional, List, Tuple

from ...models.price import CardPriceModel
from ...extensions import mongo
from ...utils.scraping import scrape_price_from_tcgplayer

bp = Blueprint('prices', __name__)

@bp.route('/card/<card_number>', methods=['GET'])
def get_card_price(card_number: str):
    """
    Get price data for a specific card by its set number.
    
    Args:
        card_number: The card number (e.g., 'BLAR-EN051')
    
    Query Parameters:
        rarity: Filter by specific rarity (e.g., 'Secret Rare')
        force_refresh: If 'true', forces a fresh scrape of the price data
    
    Returns:
        JSON response with price data for the card
    """
    try:
        # Validate card number format (e.g., 'BLAR-EN051' or 'BLAR-EN051-1st')
        if not re.match(r'^[A-Z0-9]+-EN[0-9]+(?:-[A-Za-z0-9]+)?$', card_number.upper()):
            return jsonify({"error": "Invalid card number format"}), 400
        
        rarity = request.args.get('rarity')
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        
        # Try to get from cache first if not forcing refresh
        cached_data = None
        if not force_refresh:
            cached_data = find_cached_price_data_sync(
                card_number=card_number,
                card_rarity=rarity
            )
            
            if cached_data:
                return jsonify({
                    "data": cached_data,
                    "cached": True,
                    "last_updated": cached_data.get('last_price_updt')
                })
        
        # If no cached data or force refresh, scrape fresh data
        price_data = scrape_price_from_tcgplayer(
            card_number=card_number,
            card_rarity=rarity
        )
        
        if not price_data:
            return jsonify({"error": "Could not retrieve price data"}), 404
        
        # Save the scraped data to cache
        saved_data = save_price_data_sync(price_data, requested_art_variant=None)
        
        return jsonify({
            "data": saved_data,
            "cached": False,
            "last_updated": saved_data.get('last_price_updt')
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting price for card {card_number}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


def find_cached_price_data_sync(
    card_number: Optional[str] = None, 
    card_name: Optional[str] = None,
    card_rarity: Optional[str] = None,
    art_variant: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Check if we have fresh price data in cache using synchronous MongoDB client.
    
    Args:
        card_number: The card number (e.g., 'BLAR-EN051')
        card_name: The card name (alternative to card_number)
        card_rarity: Filter by specific rarity
        art_variant: Filter by specific art variant
        
    Returns:
        Cached price data if found and fresh, None otherwise
    """
    try:
        collection = mongo.get_collection('card_prices')
        
        # Build query
        query = {}
        if card_number:
            query['card_number'] = card_number.upper()
        if card_name:
            query['card_name'] = {'$regex': f'^{re.escape(card_name)}$', '$options': 'i'}
        if card_rarity:
            # Try to match normalized rarity
            normalized_rarity = normalize_rarity(card_rarity)
            query['$or'] = [
                {'card_rarity': {'$regex': f'^{re.escape(card_rarity)}$', '$options': 'i'}},
                {'card_rarity': normalized_rarity}
            ]
        
        # Get most recent result
        result = collection.find_one(
            query,
            sort=[('last_price_updt', -1)]
        )
        
        if not result:
            return None
            
        # Check if the data is fresh (less than 24 hours old)
        last_update = result.get('last_price_updt')
        if isinstance(last_update, str):
            from dateutil.parser import parse
            last_update = parse(last_update)
        
        if not last_update or (datetime.now(UTC) - last_update) > timedelta(hours=24):
            return None
            
        # Convert ObjectId to string for JSON serialization
        if '_id' in result:
            result['_id'] = str(result['_id'])
            
        return result
        
    except Exception as e:
        current_app.logger.error(f"Error finding cached price data: {str(e)}")
        return None


def save_price_data_sync(price_data: Dict, requested_art_variant: Optional[str] = None) -> Dict:
    """
    Save price data to MongoDB using synchronous client.
    
    Args:
        price_data: The price data to save
        requested_art_variant: The requested art variant (if any)
        
    Returns:
        The saved price data with _id
    """
    try:
        collection = mongo.get_collection('card_prices')
        
        # Clean up the data
        if '_id' in price_data:
            del price_data['_id']
            
        # Update timestamp
        price_data['last_price_updt'] = datetime.now(UTC)
        
        # Insert or update the document
        result = collection.update_one(
            {
                'card_number': price_data.get('card_number'),
                'card_rarity': price_data.get('card_rarity'),
                'card_art_variant': price_data.get('card_art_variant')
            },
            {'$set': price_data},
            upsert=True
        )
        
        # Get the saved document
        if result.upserted_id:
            price_data['_id'] = result.upserted_id
        else:
            # Find the existing document
            existing = collection.find_one({
                'card_number': price_data.get('card_number'),
                'card_rarity': price_data.get('card_rarity'),
                'card_art_variant': price_data.get('card_art_variant')
            })
            if existing and '_id' in existing:
                price_data['_id'] = existing['_id']
        
        return price_data
        
    except Exception as e:
        current_app.logger.error(f"Error saving price data: {str(e)}")
        return price_data  # Return original data even if save fails


# Import utility functions at the bottom to avoid circular imports
from ...utils.rarity import normalize_rarity
