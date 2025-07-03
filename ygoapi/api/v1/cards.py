"""
Cards API Endpoints

This module defines the API endpoints for card-related operations.
"""
from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from typing import Dict, List, Optional, Any

from ...services.card_service import CardService
from ...models.card import CardVariant
from ..decorators import validate_json, paginate

# Create blueprint
bp = Blueprint('cards', __name__, url_prefix='/cards')

@bp.route('', methods=['GET'])
@paginate()
def list_cards():
    """
    List all cards with optional filtering and pagination.
    
    Query Parameters:
        q: Search query string
        set_code: Filter by set code
        rarity: Filter by rarity
        type: Filter by card type
        attribute: Filter by attribute
        race: Filter by race
        page: Page number (default: 1)
        per_page: Items per page (default: 20)
        sort: Field to sort by (default: name)
        order: Sort order (asc or desc, default: asc)
    
    Returns:
        Paginated list of cards
    """
    try:
        # Get query parameters
        query = request.args.get('q', '').strip()
        set_code = request.args.get('set_code', '').strip()
        rarity = request.args.get('rarity', '').strip()
        card_type = request.args.get('type', '').strip()
        attribute = request.args.get('attribute', '').strip()
        race = request.args.get('race', '').strip()
        
        # Get pagination and sorting
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        sort_by = request.args.get('sort', 'name')
        sort_order = request.args.get('order', 'asc')
        
        # Search for cards
        cards, total = CardService.search_cards(
            query=query if query else None,
            set_code=set_code if set_code else None,
            rarity=rarity if rarity else None,
            card_type=card_type if card_type else None,
            attribute=attribute if attribute else None,
            race=race if race else None,
            page=page,
            per_page=per_page,
            sort_field=sort_by,
            sort_order=sort_order
        )
        
        # Convert ObjectId to string for JSON serialization
        for card in cards:
            card['_id'] = str(card['_id'])
        
        return {
            'data': cards,
            'meta': {
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }
        }
        
    except Exception as e:
        current_app.logger.error(f"Error listing cards: {str(e)}")
        return {'error': 'Failed to fetch cards'}, 500

@bp.route('/<card_id>', methods=['GET'])
def get_card(card_id: str):
    """
    Get a card by ID or card number.
    
    Args:
        card_id: Card ID or card number
        
    Returns:
        Card details
    """
    try:
        # Try to get by ID first
        if ObjectId.is_valid(card_id):
            card = CardService.get_card_by_id(card_id)
        else:
            # Try by card number
            card = CardService.get_card_by_number(card_id)
        
        if not card:
            return {'error': 'Card not found'}, 404
        
        # Convert ObjectId to string for JSON serialization
        card['_id'] = str(card['_id'])
        
        return card
        
    except Exception as e:
        current_app.logger.error(f"Error getting card {card_id}: {str(e)}")
        return {'error': 'Failed to fetch card'}, 500

@bp.route('/<card_id>/variants', methods=['GET'])
def get_card_variants(card_id: str):
    """
    Get all variants of a card.
    
    Args:
        card_id: Card ID or card number
        
    Returns:
        List of card variants
    """
    try:
        # Get the card to determine the base card number
        if ObjectId.is_valid(card_id):
            card = CardService.get_card_by_id(card_id)
        else:
            card = CardService.get_card_by_number(card_id)
        
        if not card:
            return {'error': 'Card not found'}, 404
        
        # Get variants by card number
        variants = CardService.get_card_variants(card['card_number'])
        
        # Convert ObjectId to string for JSON serialization
        for variant in variants:
            variant['_id'] = str(variant['_id'])
        
        return {'data': variants}
        
    except Exception as e:
        current_app.logger.error(f"Error getting card variants for {card_id}: {str(e)}")
        return {'error': 'Failed to fetch card variants'}, 500

@bp.route('/<card_id>/price', methods=['GET'])
def get_card_price(card_id: str):
    """
    Get the current price for a card.
    
    Query Parameters:
        force_refresh: Force refresh the price data (true/false)
        
    Args:
        card_id: Card ID or card number
        
    Returns:
        Current price data for the card
    """
    try:
        # Get the card to determine the card number
        if ObjectId.is_valid(card_id):
            card = CardService.get_card_by_id(card_id)
        else:
            card = CardService.get_card_by_number(card_id)
        
        if not card:
            return {'error': 'Card not found'}, 404
        
        # Check if we should force a refresh
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        
        # Get the price data
        price_data = CardService.get_card_price(
            card['card_number'],
            force_refresh=force_refresh
        )
        
        if not price_data:
            return {'error': 'Price data not available'}, 404
        
        return price_data
        
    except Exception as e:
        current_app.logger.error(f"Error getting price for card {card_id}: {str(e)}")
        return {'error': 'Failed to fetch price data'}, 500

@bp.route('/<card_id>/price/history', methods=['GET'])
def get_card_price_history(card_id: str):
    """
    Get price history for a card.
    
    Query Parameters:
        days: Number of days of history to retrieve (default: 30)
        limit: Maximum number of records to return (default: 100)
        
    Args:
        card_id: Card ID or card number
        
    Returns:
        Price history for the card
    """
    try:
        # Get the card to determine the card number
        if ObjectId.is_valid(card_id):
            card = CardService.get_card_by_id(card_id)
        else:
            card = CardService.get_card_by_number(card_id)
        
        if not card:
            return {'error': 'Card not found'}, 404
        
        # Get query parameters
        days = int(request.args.get('days', 30))
        limit = int(request.args.get('limit', 100))
        
        # Get price history
        history = CardService.get_price_history(
            card['card_number'],
            days=days,
            limit=limit
        )
        
        # Convert ObjectId to string for JSON serialization
        for entry in history:
            entry['_id'] = str(entry['_id'])
        
        return {'data': history}
        
    except Exception as e:
        current_app.logger.error(f"Error getting price history for card {card_id}: {str(e)}")
        return {'error': 'Failed to fetch price history'}, 500
