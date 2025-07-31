"""
Comprehensive test suite for card_services module.

This test suite aims for 100% coverage of the CardSetService, CardVariantService,
and CardLookupService classes and all related functionality.
"""

import pytest
import requests
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, Mock

from ygoapi.card_services import (
    CardSetService, CardVariantService, CardLookupService,
    card_set_service, card_variant_service, card_lookup_service
)
from ygoapi.models import ProcessingStats


class TestCardSetService:
    """Comprehensive test cases for CardSetService."""

    @pytest.fixture
    def service(self):
        """Create a CardSetService instance for testing."""
        with patch('ygoapi.card_services.get_memory_manager'), \
             patch('ygoapi.card_services.get_database_manager'):
            return CardSetService()

    def test_service_initialization(self, service):
        """Test service initialization."""
        assert service.memory_manager is not None
        assert service.db_manager is not None

    @patch('ygoapi.card_services.requests.get')
    def test_fetch_all_card_sets_success(self, mock_get, service):
        """Test successful fetching of all card sets."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {'set_name': 'Test Set 1', 'set_code': 'TEST1'},
            {'set_name': 'Test Set 2', 'set_code': 'TEST2'}
        ]
        mock_get.return_value = mock_response
        
        result = service.fetch_all_card_sets()
        
        assert len(result) == 2
        assert result[0]['set_name'] == 'Test Set 1'

    @patch('ygoapi.card_services.requests.get')
    def test_fetch_all_card_sets_api_error(self, mock_get, service):
        """Test fetching card sets with API error."""
        mock_get.side_effect = requests.exceptions.RequestException('API error')
        
        with pytest.raises(requests.exceptions.RequestException):
            service.fetch_all_card_sets()

    @patch('ygoapi.card_services.requests.get')
    def test_fetch_all_card_sets_invalid_response(self, mock_get, service):
        """Test fetching card sets with invalid response."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        with pytest.raises(Exception):
            service.fetch_all_card_sets()

    def test_search_card_sets_success(self, service):
        """Test successful card sets search."""
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {'set_name': 'Legend of Blue Eyes', 'set_code': 'LOB'},
            {'set_name': 'Blue Eyes Saga', 'set_code': 'BES'}
        ]
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection):
            result = service.search_card_sets('Blue Eyes')
            
            assert len(result) == 2
            mock_collection.find.assert_called_once()

    def test_search_card_sets_no_collection(self, service):
        """Test card sets search when no collection available."""
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=None):
            result = service.search_card_sets('Test')
            
            assert result == []

    def test_search_card_sets_exception(self, service):
        """Test card sets search with exception."""
        mock_collection = Mock()
        mock_collection.find.side_effect = Exception('Database error')
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection):
            with pytest.raises(Exception):
                service.search_card_sets('Test')

    def test_get_card_sets_count_success(self, service):
        """Test successful card sets count."""
        mock_collection = Mock()
        mock_collection.count_documents.return_value = 100
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection):
            result = service.get_card_sets_count()
            
            assert result == 100

    def test_get_card_sets_count_no_collection(self, service):
        """Test card sets count when no collection available."""
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=None):
            result = service.get_card_sets_count()
            
            assert result == 0

    def test_get_card_sets_count_exception(self, service):
        """Test card sets count with exception."""
        mock_collection = Mock()
        mock_collection.count_documents.side_effect = Exception('Database error')
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection):
            with pytest.raises(Exception):
                service.get_card_sets_count()

    def test_get_cached_card_sets_success(self, service):
        """Test successful retrieval of cached card sets."""
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {'set_name': 'Cached Set 1', 'set_code': 'CACHE1'},
            {'set_name': 'Cached Set 2', 'set_code': 'CACHE2'}
        ]
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection):
            result = service.get_cached_card_sets()
            
            assert len(result) == 2

    def test_get_cached_card_sets_no_collection(self, service):
        """Test cached card sets when no collection available."""
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=None):
            result = service.get_cached_card_sets()
            
            assert result == []

    def test_upload_card_sets_to_cache_success(self, service):
        """Test successful upload of card sets to cache."""
        mock_collection = Mock()
        mock_collection.delete_many.return_value = Mock(deleted_count=0)
        mock_collection.insert_many.return_value = Mock(inserted_ids=['id1'])
        mock_card_sets = [
            {'set_name': 'Test Set', 'set_code': 'TEST'}
        ]
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection), \
             patch.object(service, 'fetch_all_card_sets', return_value=mock_card_sets), \
             patch('ygoapi.card_services.get_current_utc_datetime', return_value=datetime.now(timezone.utc)), \
             patch('ygoapi.card_services.batch_process_generator', return_value=[mock_card_sets]):
            
            result = service.upload_card_sets_to_cache()
            
            assert result['total_sets_uploaded'] == 1
            mock_collection.insert_many.assert_called_once()

    def test_upload_card_sets_to_cache_no_collection(self, service):
        """Test upload card sets when no collection available."""
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=None), \
             patch.object(service, 'fetch_all_card_sets', return_value=[]):
            
            with pytest.raises(AttributeError):  # None.delete_many() will raise
                service.upload_card_sets_to_cache()

    def test_upload_card_sets_to_cache_no_sets(self, service):
        """Test upload card sets when no sets available."""
        mock_collection = Mock()
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection), \
             patch.object(service, 'fetch_all_card_sets', return_value=[]):
            
            result = service.upload_card_sets_to_cache()
            
            assert result['total_sets_uploaded'] == 0

    def test_upload_card_sets_to_cache_exception(self, service):
        """Test upload card sets with exception."""
        mock_collection = Mock()
        mock_collection.delete_many.side_effect = Exception('Database error')
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection), \
             patch.object(service, 'fetch_all_card_sets', return_value=[{'set_name': 'Test'}]), \
             patch('ygoapi.card_services.get_current_utc_datetime', return_value=datetime.now(timezone.utc)):
            
            with pytest.raises(Exception):
                service.upload_card_sets_to_cache()


class TestCardVariantService:
    """Comprehensive test cases for CardVariantService."""

    @pytest.fixture
    def service(self):
        """Create a CardVariantService instance for testing."""
        with patch('ygoapi.card_services.get_memory_manager'), \
             patch('ygoapi.card_services.get_database_manager'):
            return CardVariantService()

    def test_service_initialization(self, service):
        """Test service initialization."""
        assert service.memory_manager is not None
        assert service.db_manager is not None

    @patch('ygoapi.card_services.requests.get')
    def test_fetch_cards_from_set_success(self, mock_get, service):
        """Test successful fetching of cards from set."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': [
                {'name': 'Blue-Eyes White Dragon', 'card_sets': [{'set_name': 'Test Set'}]},
                {'name': 'Dark Magician', 'card_sets': [{'set_name': 'Test Set'}]}
            ]
        }
        mock_get.return_value = mock_response
        
        with patch('ygoapi.card_services.filter_cards_by_set') as mock_filter:
            mock_filter.return_value = [{'name': 'Blue-Eyes White Dragon'}]
            
            result = service.fetch_cards_from_set('Test Set')
            
            assert len(result) == 1

    @patch('ygoapi.card_services.requests.get')
    def test_fetch_cards_from_set_api_error(self, mock_get, service):
        """Test fetching cards from set with API error."""
        mock_get.side_effect = requests.exceptions.RequestException('API error')
        
        with pytest.raises(requests.exceptions.RequestException):
            service.fetch_cards_from_set('Test Set')

    def test_get_cached_card_variants_success(self, service):
        """Test successful retrieval of cached card variants."""
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {'_variant_id': 'variant1', 'card_name': 'Test Card 1'},
            {'_variant_id': 'variant2', 'card_name': 'Test Card 2'}
        ]
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection):
            result = service.get_cached_card_variants()
            
            assert len(result) == 2

    def test_get_cached_card_variants_no_collection(self, service):
        """Test cached card variants when no collection available."""
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=None):
            with pytest.raises(AttributeError):  # None.find() will raise
                service.get_cached_card_variants()

    def test_get_cached_card_variants_exception(self, service):
        """Test cached card variants with exception."""
        mock_collection = Mock()
        mock_collection.find.side_effect = Exception('Database error')
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection):
            with pytest.raises(Exception):
                service.get_cached_card_variants()

    def test_create_card_variants_success(self, service):
        """Test successful creation of card variants."""
        mock_cards = [
            {
                'id': 12345,
                'name': 'Blue-Eyes White Dragon',
                'card_sets': [
                    {'set_name': 'Test Set', 'set_code': 'TEST-001', 'set_rarity': 'Ultra Rare'}
                ]
            }
        ]
        
        with patch('ygoapi.card_services.generate_variant_id', return_value='variant_123'), \
             patch('ygoapi.card_services.extract_art_version', return_value=None), \
             patch('ygoapi.card_services.get_current_utc_datetime', return_value=datetime.now(timezone.utc)):
            
            result = list(service.create_card_variants(mock_cards))
            
            assert len(result) == 1
            assert result[0]['_variant_id'] == 'variant_123'

    def test_create_card_variants_with_art_variant(self, service):
        """Test creating card variants with art variant."""
        mock_cards = [
            {
                'id': 12345,
                'name': 'Blue-Eyes White Dragon (Alternate Art)',
                'card_sets': [
                    {'set_name': 'Test Set', 'set_code': 'TEST-001', 'set_rarity': 'Ultra Rare'}
                ]
            }
        ]
        
        with patch('ygoapi.card_services.generate_variant_id', return_value='variant_123'), \
             patch('ygoapi.card_services.extract_art_version', return_value='Alternate Art'), \
             patch('ygoapi.card_services.get_current_utc_datetime', return_value=datetime.now(timezone.utc)):
            
            result = list(service.create_card_variants(mock_cards))
            
            assert len(result) == 1
            assert result[0]['art_variant'] == 'Alternate Art'

    def test_create_card_variants_empty_card_sets(self, service):
        """Test creating card variants with empty card sets."""
        mock_cards = [
            {
                'id': 12345,
                'name': 'Blue-Eyes White Dragon',
                'card_sets': []
            }
        ]
        
        result = list(service.create_card_variants(mock_cards))
        
        assert len(result) == 0

    def test_create_card_variants_missing_card_sets(self, service):
        """Test creating card variants with missing card_sets key."""
        mock_cards = [
            {
                'id': 12345,
                'name': 'Blue-Eyes White Dragon'
            }
        ]
        
        result = list(service.create_card_variants(mock_cards))
        
        assert len(result) == 0

    def test_upload_card_variants_to_cache_success(self, service):
        """Test successful upload of card variants to cache."""
        mock_collection = Mock()
        mock_collection.delete_many.return_value = Mock(deleted_count=0)
        mock_collection.insert_many.return_value = Mock(inserted_ids=['id1'])
        mock_cards = [{'id': 12345, 'name': 'Test Card', 'card_sets': [{'set_code': 'TEST'}]}]
        mock_cached_sets = [{'set_name': 'Test Set'}]
        
        # Create a proper mock for ProcessingStats that supports arithmetic operations
        class MockProcessingStats:
            def __init__(self, total_sets=0):
                self.total_sets = total_sets
                self.processed_sets = 0
                self.failed_sets = 0
                self.total_cards_processed = 0
                self.unique_variants_created = 0
                self.duplicate_variants_skipped = 0
                self.processing_errors = []
                self.success_rate = None
            
            def dict(self):
                return {}
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection), \
             patch.object(service, 'fetch_cards_from_set', return_value=mock_cards), \
             patch.object(service, 'create_card_variants') as mock_create, \
             patch('ygoapi.card_services.CardSetService') as mock_set_service_class, \
             patch('ygoapi.card_services.ProcessingStats', return_value=MockProcessingStats(1)), \
             patch('ygoapi.card_services.batch_process_generator', return_value=[[{'_variant_id': 'variant1'}]]):
            
            mock_set_service = Mock()
            mock_set_service.get_cached_card_sets.return_value = mock_cached_sets
            mock_set_service_class.return_value = mock_set_service
            mock_create.return_value = [{'_variant_id': 'variant1'}]
            
            result = service.upload_card_variants_to_cache()
            
            assert result['total_variants_created'] == 1

    def test_upload_card_variants_to_cache_no_cached_sets(self, service):
        """Test upload card variants when no cached sets available."""
        with patch('ygoapi.card_services.CardSetService') as mock_set_service_class:
            mock_set_service = Mock()
            mock_set_service.get_cached_card_sets.return_value = []
            mock_set_service_class.return_value = mock_set_service
            
            with pytest.raises(Exception, match="No cached card sets found"):
                service.upload_card_variants_to_cache()

    def test_upload_card_variants_to_cache_exception(self, service):
        """Test upload card variants with exception."""
        mock_collection = Mock()
        mock_collection.delete_many.side_effect = Exception('Database error')
        mock_cached_sets = [{'set_name': 'Test Set'}]
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection), \
             patch('ygoapi.card_services.CardSetService') as mock_set_service_class:
            
            mock_set_service = Mock()
            mock_set_service.get_cached_card_sets.return_value = mock_cached_sets
            mock_set_service_class.return_value = mock_set_service
            
            with pytest.raises(Exception):
                service.upload_card_variants_to_cache()


class TestCardLookupService:
    """Comprehensive test cases for CardLookupService."""

    @pytest.fixture
    def service(self):
        """Create a CardLookupService instance for testing."""
        return CardLookupService()

    def test_service_initialization(self, service):
        """Test service initialization."""
        assert service is not None

    def test_lookup_card_info_from_cache_success(self, service):
        """Test successful card info lookup from cache."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            'card_name': 'Blue-Eyes White Dragon',
            'set_code': 'LOB-001',
            'set_rarity': 'Ultra Rare'
        }
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection):
            result = service.lookup_card_info_from_cache('LOB-001')
            
            assert result['card_name'] == 'Blue-Eyes White Dragon'

    def test_lookup_card_info_from_cache_not_found(self, service):
        """Test card info lookup when not found in cache."""
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection):
            result = service.lookup_card_info_from_cache('INVALID-001')
            
            assert result is None

    def test_lookup_card_info_from_cache_no_collection(self, service):
        """Test card info lookup when no collection available."""
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=None):
            result = service.lookup_card_info_from_cache('LOB-001')
            
            assert result is None

    def test_lookup_card_info_from_cache_exception(self, service):
        """Test card info lookup with exception."""
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception('Database error')
        
        with patch('ygoapi.card_services.get_card_variants_collection', return_value=mock_collection):
            result = service.lookup_card_info_from_cache('LOB-001')
            
            assert result is None


class TestCardServicesBatchProcessing:
    """Test batch processing functionality in card services."""

    @pytest.fixture
    def variant_service(self):
        """Create a CardVariantService instance for testing."""
        with patch('ygoapi.card_services.get_memory_manager'), \
             patch('ygoapi.card_services.get_database_manager'):
            return CardVariantService()

    def test_create_card_variants_batch_processing(self, variant_service):
        """Test card variants creation works with multiple cards."""
        mock_cards = [
            {
                'id': 1,
                'name': 'Card 1',
                'card_sets': [{'set_name': 'Set1', 'set_code': 'S1-001', 'set_rarity': 'Common'}]
            },
            {
                'id': 2,
                'name': 'Card 2',
                'card_sets': [{'set_name': 'Set2', 'set_code': 'S2-001', 'set_rarity': 'Rare'}]
            }
        ]
        
        with patch('ygoapi.card_services.generate_variant_id', side_effect=['variant1', 'variant2']), \
             patch('ygoapi.card_services.extract_art_version', return_value=None), \
             patch('ygoapi.card_services.get_current_utc_datetime', return_value=datetime.now(timezone.utc)):
            
            result = list(variant_service.create_card_variants(mock_cards))
            
            assert len(result) == 2
            assert result[0]['_variant_id'] == 'variant1'
            assert result[1]['_variant_id'] == 'variant2'


class TestGlobalServiceInstances:
    """Test global service instances."""

    def test_card_set_service_instance(self):
        """Test global card set service instance."""
        with patch('ygoapi.card_services.CardSetService'):
            from ygoapi.card_services import card_set_service
            assert card_set_service is not None

    def test_card_variant_service_instance(self):
        """Test global card variant service instance."""
        with patch('ygoapi.card_services.CardVariantService'):
            from ygoapi.card_services import card_variant_service
            assert card_variant_service is not None

    def test_card_lookup_service_instance(self):
        """Test global card lookup service instance."""
        with patch('ygoapi.card_services.CardLookupService'):
            from ygoapi.card_services import card_lookup_service
            assert card_lookup_service is not None


class TestCardServicesEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def set_service(self):
        """Create a CardSetService instance for testing."""
        with patch('ygoapi.card_services.get_memory_manager'), \
             patch('ygoapi.card_services.get_database_manager'):
            return CardSetService()

    def test_fetch_all_card_sets_empty_response(self, set_service):
        """Test fetching card sets with empty response."""
        with patch('ygoapi.card_services.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            mock_get.return_value = mock_response
            
            result = set_service.fetch_all_card_sets()
            
            assert result == []

    def test_fetch_all_card_sets_malformed_response(self, set_service):
        """Test fetching card sets with malformed response."""
        with patch('ygoapi.card_services.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError('Invalid JSON')
            mock_get.return_value = mock_response
            
            with pytest.raises(ValueError):
                set_service.fetch_all_card_sets()

    def test_search_card_sets_empty_query(self, set_service):
        """Test searching card sets with empty query."""
        mock_collection = Mock()
        mock_collection.find.return_value = []
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection):
            result = set_service.search_card_sets('')
            
            assert result == []

    def test_upload_card_sets_memory_optimization(self, set_service):
        """Test upload card sets with memory optimization."""
        mock_collection = Mock()
        mock_collection.delete_many.return_value = Mock(deleted_count=0)
        mock_collection.insert_many.return_value = Mock(inserted_ids=['id'] * 1000)
        large_set_list = [{'set_name': f'Set {i}', 'set_code': f'SET{i}'} for i in range(1000)]
        
        with patch('ygoapi.card_services.get_card_sets_collection', return_value=mock_collection), \
             patch.object(set_service, 'fetch_all_card_sets', return_value=large_set_list), \
             patch('ygoapi.card_services.get_current_utc_datetime', return_value=datetime.now(timezone.utc)), \
             patch('ygoapi.card_services.batch_process_generator', return_value=[large_set_list]):
            
            result = set_service.upload_card_sets_to_cache()
            
            assert result['total_sets_uploaded'] == 1000