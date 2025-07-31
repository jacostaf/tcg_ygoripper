"""
Comprehensive test suite for routes module.

This test suite aims for 100% coverage of the Flask routes
and all related functionality in the routes module.
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, Mock
from flask import Flask

from ygoapi.routes import register_routes


class TestRoutesHealthCheck:
    """Test suite for health check route."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    def test_health_check_success(self, client):
        """Test successful health check."""
        with patch('ygoapi.routes.get_memory_stats') as mock_memory_stats:
            mock_memory_stats.return_value = {
                'usage_mb': 100,
                'limit_mb': 512,
                'percent': 0.2
            }
            
            response = client.get('/health')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'healthy'
            assert data['service'] == 'YGO Card Sets API'
            assert 'memory_stats' in data


class TestRoutesPriceScraping:
    """Test suite for price scraping routes."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    @patch('ygoapi.routes.price_scraping_service')
    def test_scrape_card_price_success(self, mock_service, client):
        """Test successful card price scraping."""
        mock_service.scrape_card_price.return_value = {
            'success': True,
            'data': {
                'card_number': 'LOB-001',
                'card_name': 'Blue-Eyes White Dragon',
                'tcg_price': 25.99,
                'tcg_market_price': 28.50,
                'source_url': 'https://tcgplayer.com/test',
                'scrape_success': True,
                'last_price_updt': 'Wed, 31 Jul 2025 12:00:00 GMT'
            },
            'message': 'Price data scraped successfully',
            'is_cached': False,
            'cache_age_hours': 0.0
        }
        
        data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'card_rarity': 'Ultra Rare'
        }
        
        response = client.post('/cards/price', 
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] is True

    def test_scrape_card_price_no_json(self, client):
        """Test price scraping without JSON body."""
        response = client.post('/cards/price')
        
        assert response.status_code == 500  # Flask throws 500 for missing content-type
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'Internal server error' in data['error']

    def test_scrape_card_price_missing_params(self, client):
        """Test price scraping with missing required parameters."""
        data = {'card_rarity': 'Ultra Rare'}
        
        response = client.post('/cards/price', 
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 400
        result = json.loads(response.data)
        assert result['success'] is False
        assert 'required' in result['error']

    def test_scrape_card_price_missing_rarity(self, client):
        """Test price scraping with missing rarity."""
        data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon'
        }
        
        response = client.post('/cards/price', 
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 400
        result = json.loads(response.data)
        assert result['success'] is False
        assert 'rarity' in result['error']

    @patch('ygoapi.routes.validate_card_input')
    def test_scrape_card_price_invalid_input(self, mock_validate, client):
        """Test price scraping with invalid input."""
        mock_validate.return_value = (False, 'Invalid input detected')
        
        data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'card_rarity': 'Ultra Rare'
        }
        
        response = client.post('/cards/price', 
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 400
        result = json.loads(response.data)
        assert result['success'] is False
        assert 'Invalid input' in result['error']


class TestRoutesCardSets:
    """Test suite for card sets routes."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    @patch('ygoapi.routes.card_set_service')
    def test_get_card_sets_success(self, mock_service, client):
        """Test successful card sets retrieval."""
        mock_service.fetch_all_card_sets.return_value = [
            {'set_name': 'Test Set 1', 'set_code': 'TEST1'},
            {'set_name': 'Test Set 2', 'set_code': 'TEST2'}
        ]
        
        response = client.get('/card-sets')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['data']) == 2

    @patch('ygoapi.routes.card_set_service')
    def test_get_card_sets_with_limit(self, mock_service, client):
        """Test card sets retrieval with limit parameter."""
        mock_service.fetch_all_card_sets.return_value = [
            {'set_name': 'Test Set 1', 'set_code': 'TEST1'}
        ]
        
        response = client.get('/card-sets?limit=1')
        
        assert response.status_code == 200
        # The routes.py calls fetch_all_card_sets() directly, not get_all_card_sets()


class TestRoutesMemoryManagement:
    """Test suite for memory management routes."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    @patch('ygoapi.routes.get_memory_stats')
    def test_memory_stats_success(self, mock_stats, client):
        """Test successful memory stats retrieval."""
        mock_stats.return_value = {
            'usage_mb': 150,
            'limit_mb': 512,
            'percent': 0.3
        }
        
        response = client.get('/memory/stats')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'memory_stats' in data


class TestRoutesImageProxy:
    """Test suite for image proxy routes."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    def test_proxy_card_image_missing_url(self, client):
        """Test image proxy with missing URL."""
        response = client.get('/cards/image')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'url' in data['error']

    def test_proxy_card_image_invalid_url(self, client):
        """Test image proxy with invalid URL."""
        response = client.get('/cards/image?url=https://malicious.com/image.jpg')
        
        assert response.status_code == 403
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'Only YGO API images' in data['error']


class TestRoutesAdditionalEndpoints:
    """Test suite for additional endpoints to improve coverage."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    @patch('ygoapi.routes.price_scraping_service')
    def test_get_price_cache_stats_success(self, mock_service, client):
        """Test successful price cache stats retrieval."""
        mock_service.get_cache_stats.return_value = {
            'total_cached_prices': 1500,
            'cache_hit_rate': 0.85,
            'last_updated': '2025-07-31T12:00:00Z'
        }
        
        response = client.get('/cards/price/cache-stats')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'cache_stats' in data

    @patch('ygoapi.routes.price_scraping_service')
    def test_get_price_cache_stats_exception(self, mock_service, client):
        """Test price cache stats with exception."""
        mock_service.get_cache_stats.side_effect = Exception('Cache error')
        
        response = client.get('/cards/price/cache-stats')
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False

    @patch('ygoapi.routes.card_lookup_service')
    def test_debug_cache_lookup_success(self, mock_service, client):
        """Test successful cache lookup debug."""
        mock_service.lookup_card_info_from_cache.return_value = {
            'card_name': 'Blue-Eyes White Dragon',
            'set_code': 'LOB-001'
        }
        
        data = {'card_number': 'LOB-001'}
        
        response = client.post('/debug/cache-lookup',
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] is True
        assert 'cached_data' in result

    def test_debug_cache_lookup_missing_data(self, client):
        """Test cache lookup debug with missing data."""
        response = client.post('/debug/cache-lookup',
                             data=json.dumps({}),
                             content_type='application/json')
        
        assert response.status_code == 400
        result = json.loads(response.data)
        assert result['success'] is False

    @patch('ygoapi.routes.card_set_service')
    def test_search_card_sets_success(self, mock_service, client):
        """Test successful card sets search."""
        mock_service.search_card_sets.return_value = [
            {'set_name': 'Blue-Eyes Set', 'set_code': 'BLUE1'}
        ]
        
        response = client.get('/card-sets/search/Blue-Eyes')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['data']) == 1

    @patch('ygoapi.routes.card_set_service')
    def test_upload_card_sets_success(self, mock_service, client):
        """Test successful card sets upload."""
        mock_service.upload_card_sets_to_cache.return_value = {
            'total_sets_uploaded': 100,
            'upload_timestamp': '2025-07-31T12:00:00Z'
        }
        
        response = client.post('/card-sets/upload')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'statistics' in data

    @patch('ygoapi.routes.card_set_service')
    def test_get_card_sets_from_cache_success(self, mock_service, client):
        """Test successful cached card sets retrieval."""
        mock_service.get_cached_card_sets.return_value = [
            {'set_name': 'Cached Set', 'set_code': 'CACHE1'}
        ]
        
        response = client.get('/card-sets/from-cache')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'data' in data
        assert 'count' in data

    @patch('ygoapi.routes.card_set_service')
    def test_get_card_sets_count_success(self, mock_service, client):
        """Test successful card sets count."""
        mock_service.get_card_sets_count.return_value = 250
        
        response = client.get('/card-sets/count')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['count'] == 250

    @patch('ygoapi.routes.card_variant_service')
    def test_get_cards_from_set_success(self, mock_service, client):
        """Test successful cards from set retrieval."""
        mock_service.fetch_cards_from_set.return_value = [
            {'name': 'Blue-Eyes White Dragon', 'id': 12345}
        ]
        
        response = client.get('/card-sets/test-set/cards')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['set_name'] == 'test-set'

    @patch('ygoapi.routes.card_variant_service')
    def test_upload_card_variants_success(self, mock_service, client):
        """Test successful card variants upload."""
        mock_service.upload_card_variants_to_cache.return_value = {
            'total_variants_created': 1000,
            'statistics': {'processed_sets': 10}
        }
        
        response = client.post('/cards/upload-variants')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'statistics' in data

    @patch('ygoapi.routes.card_variant_service')
    def test_get_card_variants_success(self, mock_service, client):
        """Test successful card variants retrieval."""
        mock_service.get_cached_card_variants.return_value = [
            {'_variant_id': 'variant1', 'card_name': 'Test Card'}
        ]
        
        response = client.get('/cards/variants')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['data']) == 1

    @patch('ygoapi.routes.force_memory_cleanup')
    @patch('ygoapi.routes.get_memory_stats')
    def test_force_memory_cleanup_success(self, mock_stats, mock_cleanup, client):
        """Test successful memory cleanup."""
        mock_stats.return_value = {'usage_mb': 100}
        
        response = client.post('/memory/cleanup')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'Memory cleanup completed' in data['message']
        mock_cleanup.assert_called_once()

    @patch('ygoapi.routes.extract_art_version')
    def test_debug_art_extraction_success(self, mock_extract, client):
        """Test successful art variant extraction debug."""
        mock_extract.side_effect = lambda name: 'Alternate Art' if 'Alternate' in name else None
        
        data = {
            'test_strings': [
                'Blue-Eyes White Dragon',
                'Blue-Eyes White Dragon (Alternate Art)'
            ]
        }
        
        response = client.post('/debug/art-extraction',
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] is True
        assert len(result['results']) == 2

    def test_debug_art_extraction_missing_data(self, client):
        """Test art extraction debug with missing data."""
        response = client.post('/debug/art-extraction',
                             data=json.dumps({'test_strings': []}),
                             content_type='application/json')
        
        assert response.status_code == 200  # Empty list is valid
        result = json.loads(response.data)
        assert result['success'] is True
        assert len(result['results']) == 0

    @patch('ygoapi.routes.requests.get')
    def test_proxy_card_image_success(self, mock_get, client):
        """Test successful image proxy."""
        from io import BytesIO
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'image/jpeg'}
        mock_response.iter_content.return_value = [b'image_data']
        mock_get.return_value = mock_response
        
        response = client.get('/cards/image?url=https://images.ygoprodeck.com/images/cards/12345.jpg')
        
        assert response.status_code == 200
        assert response.content_type == 'image/jpeg'

    @patch('ygoapi.routes.requests.get')
    def test_proxy_card_image_timeout(self, mock_get, client):
        """Test image proxy with timeout."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()
        
        response = client.get('/cards/image?url=https://images.ygoprodeck.com/images/cards/12345.jpg')
        
        assert response.status_code == 504
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'Timeout' in data['error']


class TestRoutesErrorHandling:
    """Test suite for error handling in routes."""

    @pytest.fixture
    def app(self):
        """Create a Flask app with routes for testing."""
        app = Flask(__name__)
        register_routes(app)
        app.config['TESTING'] = True
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    @patch('ygoapi.routes.price_scraping_service')
    def test_scrape_card_price_exception(self, mock_service, client):
        """Test price scraping with service exception."""
        mock_service.scrape_card_price.side_effect = Exception('Service error')
        
        data = {
            'card_number': 'LOB-001',
            'card_name': 'Blue-Eyes White Dragon',
            'card_rarity': 'Ultra Rare'
        }
        
        response = client.post('/cards/price', 
                             data=json.dumps(data),
                             content_type='application/json')
        
        assert response.status_code == 500
        result = json.loads(response.data)
        assert result['success'] is False
        assert 'Internal server error' in result['error']

    @patch('ygoapi.routes.card_set_service')
    def test_get_card_sets_exception(self, mock_service, client):
        """Test card sets retrieval with service exception."""
        mock_service.fetch_all_card_sets.side_effect = Exception('Service error')
        
        response = client.get('/card-sets')
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False

    @patch('ygoapi.routes.card_set_service')
    def test_search_card_sets_exception(self, mock_service, client):
        """Test card sets search with exception."""
        mock_service.search_card_sets.side_effect = Exception('Search error')
        
        response = client.get('/card-sets/search/test')
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False

    @patch('ygoapi.routes.card_set_service')
    def test_upload_card_sets_exception(self, mock_service, client):
        """Test card sets upload with exception."""
        mock_service.upload_card_sets_to_cache.side_effect = Exception('Upload error')
        
        response = client.post('/card-sets/upload')
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False