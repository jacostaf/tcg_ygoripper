"""
API Decorators

This module contains custom decorators for API routes.
"""
from functools import wraps
from flask import request, jsonify, current_app
from typing import Callable, Any, Optional, Dict, List, Tuple, TypeVar, Union
from pydantic import BaseModel, ValidationError
import json

T = TypeVar('T')

class PaginationParams:
    """Pagination parameters for API endpoints."""
    def __init__(self, page: int = 1, per_page: int = 20):
        self.page = max(1, page)
        self.per_page = max(1, min(100, per_page))  # Cap at 100 items per page

def validate_json(
    model: Optional[type[BaseModel]] = None,
    schema: Optional[Dict[str, Any]] = None
):
    """
    Validate JSON request body against a Pydantic model or JSON schema.
    
    Args:
        model: Pydantic model to validate against
        schema: JSON schema to validate against (alternative to model)
    
    Returns:
        Decorator function
    """
    def decorator(f: Callable[..., T]) -> Callable[..., Union[T, Tuple[Dict[str, Any], int]]]:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Union[T, Tuple[Dict[str, Any], int]]:
            # Check if request has JSON data
            if not request.is_json:
                return jsonify({"error": "Request must be JSON"}), 400
            
            try:
                data = request.get_json()
                
                # Validate against Pydantic model if provided
                if model is not None:
                    try:
                        validated_data = model(**data)
                        # Replace the data with the validated data
                        kwargs['data'] = validated_data
                    except ValidationError as e:
                        return jsonify({
                            "error": "Validation error",
                            "details": e.errors()
                        }), 400
                # Validate against JSON schema if provided
                elif schema is not None:
                    # In a real implementation, you would use a JSON schema validator
                    # For now, we'll just pass the data through
                    kwargs['data'] = data
                
                # Call the original function
                return f(*args, **kwargs)
                
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid JSON"}), 400
            except Exception as e:
                current_app.logger.error(f"Error in validate_json: {str(e)}")
                return jsonify({"error": "Internal server error"}), 500
                
        return wrapper
    return decorator

def paginate(
    default_per_page: int = 20,
    max_per_page: int = 100
):
    """
    Add pagination to API endpoints.
    
    Args:
        default_per_page: Default number of items per page
        max_per_page: Maximum number of items per page
    
    Returns:
        Decorator function
    """
    def decorator(f: Callable[..., T]) -> Callable[..., Union[T, Tuple[Dict[str, Any], int]]]:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Union[T, Tuple[Dict[str, Any], int]]:
            try:
                # Get pagination parameters from query string
                page = max(1, int(request.args.get('page', 1)))
                per_page = min(
                    max_per_page,
                    max(1, int(request.args.get('per_page', default_per_page)))
                )
                
                # Call the original function with pagination parameters
                result = f(*args, page=page, per_page=per_page, **kwargs)
                
                # If the function returns a tuple (response, status), extract the response
                response_data = result[0] if isinstance(result, tuple) else result
                status_code = result[1] if isinstance(result, tuple) and len(result) > 1 else 200
                
                # If the response is already a dict with pagination metadata, return as is
                if isinstance(response_data, dict) and 'meta' in response_data:
                    return response_data, status_code
                
                # Otherwise, wrap the response in a standard pagination structure
                return {
                    'data': response_data,
                    'meta': {
                        'page': page,
                        'per_page': per_page,
                        'total': len(response_data) if isinstance(response_data, list) else 1,
                        'total_pages': 1
                    }
                }, status_code
                
            except (ValueError, TypeError) as e:
                return jsonify({"error": "Invalid pagination parameters"}), 400
            except Exception as e:
                current_app.logger.error(f"Error in paginate: {str(e)}")
                return jsonify({"error": "Internal server error"}), 500
                
        return wrapper
    return decorator

def handle_errors(f: Callable[..., T]) -> Callable[..., Union[T, Tuple[Dict[str, Any], int]]]:
    """
    Handle common errors in API endpoints.
    
    Returns:
        Decorator function
    """
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Union[T, Tuple[Dict[str, Any], int]]:
        try:
            return f(*args, **kwargs)
        except Exception as e:
            current_app.logger.error(f"Error in {f.__name__}: {str(e)}", exc_info=True)
            return jsonify({"error": "Internal server error"}), 500
    return wrapper

def require_auth(roles: Optional[List[str]] = None):
    """
    Require authentication (and optionally specific roles) for an endpoint.
    
    Args:
        roles: List of required roles (if any)
    
    Returns:
        Decorator function
    """
    def decorator(f: Callable[..., T]) -> Callable[..., Union[T, Tuple[Dict[str, Any], int]]]:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Union[T, Tuple[Dict[str, Any], int]]:
            # In a real implementation, you would check for a valid auth token
            # and verify the user's roles if any are required
            auth_header = request.headers.get('Authorization')
            
            if not auth_header:
                return jsonify({"error": "Missing authorization token"}), 401
                
            # Here you would validate the token and check roles
            # For now, we'll just pass through
            return f(*args, **kwargs)
            
        return wrapper
    return decorator

def cache_control(
    max_age: int = 300,
    s_maxage: Optional[int] = None,
    public: bool = True,
    must_revalidate: bool = False,
    no_cache: bool = False,
    no_store: bool = False
):
    """
    Add Cache-Control headers to the response.
    
    Args:
        max_age: Maximum age in seconds (default: 300)
        s_maxage: Shared maximum age in seconds (for CDNs)
        public: Whether the response can be cached by public caches
        must_revalidate: Whether the cache must revalidate with the server
        no_cache: Whether to prevent caching entirely
        no_store: Whether to prevent storing the response
    
    Returns:
        Decorator function
    """
    def decorator(f: Callable[..., T]) -> Callable[..., Union[T, Tuple[Dict[str, Any], int]]]:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Union[T, Tuple[Dict[str, Any], int]]:
            # Call the original function
            response = f(*args, **kwargs)
            
            # If it's a tuple (response, status), extract the response
            response_obj = response[0] if isinstance(response, tuple) else response
            status_code = response[1] if isinstance(response, tuple) and len(response) > 1 else 200
            
            # Build Cache-Control header
            cache_control = []
            
            if no_store:
                cache_control.append("no-store")
            elif no_cache:
                cache_control.append("no-cache")
            else:
                if public:
                    cache_control.append("public")
                else:
                    cache_control.append("private")
                
                cache_control.append(f"max-age={max_age}")
                
                if s_maxage is not None:
                    cache_control.append(f"s-maxage={s_maxage}")
                    
                if must_revalidate:
                    cache_control.append("must-revalidate")
            
            # Create a new response object if needed
            if not hasattr(response_obj, 'headers'):
                from flask import make_response
                response_obj = make_response(response_obj, status_code)
            
            # Set the Cache-Control header
            response_obj.headers['Cache-Control'] = ', '.join(cache_control)
            
            return response_obj
            
        return wrapper
    return decorator
