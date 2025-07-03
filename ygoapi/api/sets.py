"""
Card set-related API endpoints.

This module contains all the card set-related API endpoints for the YGOAPI.
"""
import re
from flask import Blueprint, jsonify, request, current_app
from bson import ObjectId
from datetime import datetime, UTC
from typing import Dict, Any, List, Optional

from ...models.card import CardSet
from ...extensions import mongo
from ...utils.scraping import fetch_ygo_api

bp = Blueprint('sets', __name__)

@bp.route('/', methods=['GET'])
def get_card_sets():
    """
    Get a list of all card sets with optional filtering.
    
    Query Parameters:
        name: Filter by set name (partial match, case-insensitive)
        code: Filter by set code (exact match, case-insensitive)
        limit: Maximum number of results to return (default: 50, max: 100)
        offset: Number of results to skip (for pagination)
    
    Returns:
        JSON response with list of card sets and pagination info
    """
    try:
        # Parse query parameters
        name = request.args.get('name')
        code = request.args.get('code')
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
        
        # Build query
        query: Dict[str, Any] = {}
        if name:
            query['set_name'] = {'$regex': name, '$options': 'i'}
        if code:
            query['set_code'] = code.upper()
        
        # Get total count for pagination
        total = mongo.get_collection('sets').count_documents(query)
        
        # Get paginated results
        cursor = mongo.get_collection('sets').find(query)\
            .sort([('tcg_date', -1), ('set_name', 1)])\
            .skip(offset)\
            .limit(limit)
        
        sets = list(cursor)
        
        # Convert ObjectId to string for JSON serialization
        for set_data in sets:
            if '_id' in set_data:
                set_data['_id'] = str(set_data['_id'])
        
        return jsonify({
            'data': sets,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + len(sets)) < total
            }
        })
        
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid limit or offset value"}), 400
    except Exception as e:
        current_app.logger.error(f"Error fetching card sets: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/<set_code>', methods=['GET'])
def get_card_set(set_code: str):
    """
    Get details for a specific card set by its code.
    
    Args:
        set_code: The set code (e.g., 'BLAR')
    
    Returns:
        JSON response with set details and cards in the set
    """
    try:
        # Get set details
        set_data = mongo.get_collection('sets').find_one({
            'set_code': set_code.upper()
        })
        
        if not set_data:
            return jsonify({"error": "Set not found"}), 404
        
        # Get cards in this set
        cards = list(mongo.get_collection('cards').find({
            'set_code': set_code.upper()
        }).sort([('card_number', 1)]))
        
        # Convert ObjectId to string for JSON serialization
        if '_id' in set_data:
            set_data['_id'] = str(set_data['_id'])
        
        for card in cards:
            if '_id' in card:
                card['_id'] = str(card['_id'])
        
        return jsonify({
            'set': set_data,
            'cards': cards,
            'card_count': len(cards)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error fetching set {set_code}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/sync', methods=['POST'])
def sync_card_sets():
    """
    Sync card sets from the YGO API to the local database.
    
    This endpoint fetches the latest card set data from the YGO API and
    updates the local database.
    
    Returns:
        JSON response with sync status and statistics
    """
    try:
        # Fetch sets from YGO API
        response = fetch_ygo_api('cardsets.php')
        if not response or 'data' not in response:
            return jsonify({"error": "Failed to fetch card sets from YGO API"}), 500
        
        sets_data = response['data']
        if not isinstance(sets_data, list):
            return jsonify({"error": "Invalid data format from YGO API"}), 500
        
        # Transform and save sets
        sets_collection = mongo.get_collection('sets')
        cards_collection = mongo.get_collection('cards')
        
        stats = {
            'total_sets': 0,
            'new_sets': 0,
            'updated_sets': 0,
            'total_cards': 0,
            'new_cards': 0,
            'updated_cards': 0
        }
        
        for set_data in sets_data:
            stats['total_sets'] += 1
            
            # Transform set data
            set_code = set_data.get('set_code', '').upper()
            if not set_code:
                continue
                
            existing_set = sets_collection.find_one({'set_code': set_code})
            
            # Prepare set document
            set_doc = {
                'set_name': set_data.get('set_name', ''),
                'set_code': set_code,
                'num_of_cards': int(set_data.get('num_of_cards', 0)),
                'tcg_date': datetime.strptime(set_data['tcg_date'], '%Y-%m-%d') if set_data.get('tcg_date') else None,
                'set_image': set_data.get('set_image', ''),
                'last_updated': datetime.now(UTC)
            }
            
            # Update or insert set
            if existing_set:
                sets_collection.update_one(
                    {'_id': existing_set['_id']},
                    {'$set': set_doc}
                )
                stats['updated_sets'] += 1
            else:
                sets_collection.insert_one(set_doc)
                stats['new_sets'] += 1
            
            # Fetch cards for this set if we don't have them yet
            if not existing_set or existing_set.get('num_of_cards', 0) != set_doc['num_of_cards']:
                cards_response = fetch_ygo_api(f'cardsetsinfo.php?setcode={set_code}')
                if cards_response and 'data' in cards_response and isinstance(cards_response['data'], list):
                    for card_data in cards_response['data']:
                        stats['total_cards'] += 1
                        
                        # Transform card data
                        card_number = f"{set_code}-{card_data.get('set_rarity_code', '').upper() or 'EN'}{card_data.get('set_rarity_number', '')}"
                        
                        card_doc = {
                            'card_id': int(card_data.get('id', 0)),
                            'card_name': card_data.get('name', ''),
                            'card_type': card_data.get('type', ''),
                            'desc': card_data.get('desc', ''),
                            'atk': card_data.get('atk'),
                            'def': card_data.get('def'),
                            'level': card_data.get('level'),
                            'race': card_data.get('race', ''),
                            'attribute': card_data.get('attribute', ''),
                            'archetype': card_data.get('archetype', ''),
                            'set_code': set_code,
                            'set_name': set_doc['set_name'],
                            'card_number': card_number,
                            'rarity': card_data.get('set_rarity', ''),
                            'rarity_code': card_data.get('set_rarity_code', ''),
                            'image_url': card_data.get('card_images', [{}])[0].get('image_url', ''),
                            'image_url_small': card_data.get('card_images', [{}])[0].get('image_url_small', ''),
                            'last_updated': datetime.now(UTC)
                        }
                        
                        # Update or insert card
                        existing_card = cards_collection.find_one({
                            'card_id': card_doc['card_id'],
                            'set_code': set_code,
                            'rarity': card_doc['rarity']
                        })
                        
                        if existing_card:
                            cards_collection.update_one(
                                {'_id': existing_card['_id']},
                                {'$set': card_doc}
                            )
                            stats['updated_cards'] += 1
                        else:
                            cards_collection.insert_one(card_doc)
                            stats['new_cards'] += 1
        
        return jsonify({
            "status": "success",
            "message": "Card sets synchronized successfully",
            "stats": stats
        })
        
    except Exception as e:
        current_app.logger.error(f"Error syncing card sets: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
