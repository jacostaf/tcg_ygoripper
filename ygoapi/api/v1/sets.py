"""
Sets API Endpoints

This module defines the API endpoints for set-related operations.
"""
from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from typing import Dict, List, Optional, Any

from ...services.set_service import SetService
from ..decorators import validate_json, paginate

# Create blueprint
bp = Blueprint('sets', __name__, url_prefix='/sets')

@bp.route('', methods=['GET'])
@paginate()
def list_sets():
    """
    List all card sets with optional filtering and pagination.
    
    Query Parameters:
        q: Search query string
        sort: Field to sort by (default: release_date)
        order: Sort order (asc or desc, default: desc)
        page: Page number (default: 1)
        per_page: Items per page (default: 20)
    
    Returns:
        Paginated list of card sets
    """
    try:
        # Get query parameters
        query = request.args.get('q', '').strip()
        sort_by = request.args.get('sort', 'release_date')
        sort_order = request.args.get('order', 'desc')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        
        # Get all sets with pagination
        sets, total = SetService.get_all_sets(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Convert ObjectId to string for JSON serialization
        for set_data in sets:
            set_data['_id'] = str(set_data['_id'])
        
        # Apply search filter if query is provided
        if query:
            query = query.lower()
            sets = [
                s for s in sets
                if query in s.get('set_name', '').lower() or
                   query in s.get('set_code', '').lower()
            ]
            total = len(sets)
        
        return {
            'data': sets,
            'meta': {
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }
        }
        
    except Exception as e:
        current_app.logger.error(f"Error listing sets: {str(e)}")
        return {'error': 'Failed to fetch sets'}, 500

@bp.route('/<set_id>', methods=['GET'])
def get_set(set_id: str):
    """
    Get a set by ID or set code.
    
    Args:
        set_id: Set ID or set code
        
    Returns:
        Set details
    """
    try:
        # Get the set by ID or code
        set_data = SetService.get_set_by_id(set_id)
        
        if not set_data:
            return {'error': 'Set not found'}, 404
        
        # Convert ObjectId to string for JSON serialization
        set_data['_id'] = str(set_data['_id'])
        
        return set_data
        
    except Exception as e:
        current_app.logger.error(f"Error getting set {set_id}: {str(e)}")
        return {'error': 'Failed to fetch set'}, 500

@bp.route('/<set_id>/cards', methods=['GET'])
@paginate()
def get_set_cards(set_id: str):
    """
    Get all cards in a set with optional filtering and pagination.
    
    Args:
        set_id: Set ID or set code
        
    Query Parameters:
        q: Search query string
        rarity: Filter by rarity
        type: Filter by card type
        attribute: Filter by attribute
        race: Filter by race
        sort: Field to sort by (default: card_number)
        order: Sort order (asc or desc, default: asc)
        page: Page number (default: 1)
        per_page: Items per page (default: 20)
    
    Returns:
        Paginated list of cards in the set
    """
    try:
        # Get the set to verify it exists
        set_data = SetService.get_set_by_id(set_id)
        if not set_data:
            return {'error': 'Set not found'}, 404
        
        # Get query parameters
        query = request.args.get('q', '').strip()
        rarity = request.args.get('rarity', '').strip()
        card_type = request.args.get('type', '').strip()
        attribute = request.args.get('attribute', '').strip()
        race = request.args.get('race', '').strip()
        sort_by = request.args.get('sort', 'card_number')
        sort_order = request.args.get('order', 'asc')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        
        # Get cards in the set with filtering
        cards, total = SetService.get_cards_in_set(
            set_code=set_data['set_code'],
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Apply additional filters
        filtered_cards = []
        for card in cards:
            # Skip if it doesn't match the search query
            if query and query.lower() not in card.get('name', '').lower():
                continue
                
            # Apply other filters
            if rarity and card.get('rarity', '').lower() != rarity.lower():
                continue
                
            if card_type and card_type.lower() not in card.get('type', '').lower():
                continue
                
            if attribute and card.get('attribute', '').lower() != attribute.lower():
                continue
                
            if race and card.get('race', '').lower() != race.lower():
                continue
                
            # Convert ObjectId to string for JSON serialization
            card['_id'] = str(card['_id'])
            filtered_cards.append(card)
        
        # Update total based on filtered results
        total = len(filtered_cards)
        
        # Apply pagination
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_cards = filtered_cards[start_idx:end_idx]
        
        return {
            'data': paginated_cards,
            'meta': {
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }
        }
        
    except Exception as e:
        current_app.logger.error(f"Error getting cards in set {set_id}: {str(e)}")
        return {'error': 'Failed to fetch set cards'}, 500

@bp.route('/<set_id>/stats', methods=['GET'])
def get_set_statistics(set_id: str):
    """
    Get statistics for a set.
    
    Args:
        set_id: Set ID or set code
        
    Returns:
        Set statistics
    """
    try:
        # Get the set to verify it exists and get the set code
        set_data = SetService.get_set_by_id(set_id)
        if not set_data:
            return {'error': 'Set not found'}, 404
        
        # Get set statistics
        stats = SetService.get_set_statistics(set_data['set_code'])
        
        if not stats.get('success', False):
            return {'error': stats.get('message', 'Failed to fetch set statistics')}, 500
        
        return stats
        
    except Exception as e:
        current_app.logger.error(f"Error getting statistics for set {set_id}: {str(e)}")
        return {'error': 'Failed to fetch set statistics'}, 500

@bp.route('/sync', methods=['POST'])
def sync_sets():
    """
    Sync sets from the YGO API.
    
    Returns:
        Sync results
    """
    try:
        # Only allow admin users to sync
        # Add authentication check here if needed
        
        # Sync sets from YGO API
        result = SetService.sync_sets_from_ygo_api()
        
        if not result.get('success', False):
            return {'error': result.get('message', 'Failed to sync sets')}, 500
        
        return {
            'message': result.get('message', 'Sets synced successfully'),
            'stats': result.get('stats', {})
        }
        
    except Exception as e:
        current_app.logger.error(f"Error syncing sets: {str(e)}")
        return {'error': 'Failed to sync sets'}, 500
