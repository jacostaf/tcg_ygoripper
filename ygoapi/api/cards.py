"""
Card-related API endpoints.

This module contains all the card-related API endpoints for the YGOAPI.
"""
from flask import Blueprint, jsonify, request, current_app
from bson import ObjectId
from typing import Dict, Any, Optional, List

from ...models.card import CardVariant
from ...extensions import mongo

bp = Blueprint('cards', __name__)

@bp.route('/', methods=['GET'])
def get_cards():
    """
    Get a list of all cards with optional filtering.
    
    Query Parameters:
        set_code: Filter by set code (e.g., 'BLAR')
        rarity: Filter by rarity (e.g., 'Secret Rare')
        name: Filter by card name (partial match, case-insensitive)
        limit: Maximum number of results to return (default: 50, max: 100)
        offset: Number of results to skip (for pagination)
    
    Returns:
        JSON response with list of cards and pagination info
    """
    # Parse query parameters
    set_code = request.args.get('set_code')
    rarity = request.args.get('rarity')
    name = request.args.get('name')
    
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid limit or offset value"}), 400
    
    # Build query
    query: Dict[str, Any] = {}
    if set_code:
        query['set_code'] = set_code.upper()
    if rarity:
        query['rarity'] = {'$regex': f'^{re.escape(rarity)}$', '$options': 'i'}
    if name:
        query['$or'] = [
            {'card_name': {'$regex': name, '$options': 'i'}},
            {'card_number': {'$regex': name, '$options': 'i'}}
        ]
    
    try:
        # Get total count for pagination
        total = mongo.get_collection('cards').count_documents(query)
        
        # Get paginated results
        cursor = mongo.get_collection('cards').find(query)\
            .sort([('set_code', 1), ('card_number', 1)])\
            .skip(offset)\
            .limit(limit)
        
        cards = list(cursor)
        
        # Convert ObjectId to string for JSON serialization
        for card in cards:
            card['_id'] = str(card['_id'])
        
        return jsonify({
            'data': cards,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + len(cards)) < total
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error fetching cards: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/<card_id>', methods=['GET'])
def get_card(card_id: str):
    """
    Get details for a specific card by ID.
    
    Args:
        card_id: The ID of the card to retrieve
    
    Returns:
        JSON response with card details
    """
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(card_id):
            return jsonify({"error": "Invalid card ID format"}), 400
        
        card = mongo.get_collection('cards').find_one({"_id": ObjectId(card_id)})
        
        if not card:
            return jsonify({"error": "Card not found"}), 404
        
        # Convert ObjectId to string for JSON serialization
        card['_id'] = str(card['_id'])
        
        return jsonify(card)
    except Exception as e:
        current_app.logger.error(f"Error fetching card {card_id}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/number/<card_number>', methods=['GET'])
def get_card_by_number(card_number: str):
    """
    Get details for a specific card by its set number.
    
    Args:
        card_number: The card number (e.g., 'BLAR-EN051')
    
    Returns:
        JSON response with card details
    """
    try:
        card = mongo.get_collection('cards').find_one({"card_number": card_number.upper()})
        
        if not card:
            return jsonify({"error": "Card not found"}), 404
        
        # Convert ObjectId to string for JSON serialization
        card['_id'] = str(card['_id'])
        
        return jsonify(card)
    except Exception as e:
        current_app.logger.error(f"Error fetching card {card_number}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/<card_id>/variants', methods=['GET'])
def get_card_variants(card_id: str):
    """
    Get all variants of a specific card.
    
    Args:
        card_id: The ID of the card
    
    Returns:
        JSON response with list of card variants
    """
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(card_id):
            return jsonify({"error": "Invalid card ID format"}), 400
        
        variants = list(mongo.get_collection('card_variants')
                       .find({"card_id": ObjectId(card_id)})
                       .sort([("rarity", 1), ("set_code", 1)]))
        
        # Convert ObjectId to string for JSON serialization
        for variant in variants:
            variant['_id'] = str(variant['_id'])
            variant['card_id'] = str(variant['card_id'])
        
        return jsonify({"data": variants})
    except Exception as e:
        current_app.logger.error(f"Error fetching variants for card {card_id}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
