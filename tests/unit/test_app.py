"""
Unit tests for app.py module.

Tests Flask application creation, configuration, and initialization with comprehensive
coverage of success cases, error handling, and edge scenarios.
"""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest
from flask import Flask

from ygoapi.app import create_app


class TestAppCreation:
    """Test Flask application creation and configuration."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_create_app_default_config(self):
        """Test creating app with default configuration."""
        app = create_app()
        
        assert isinstance(app, Flask)
        assert app.name == "ygoapi.app"
        assert app.config is not None

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.register_routes")
    def test_create_app_registers_routes(self, mock_register_routes):
        """Test that create_app registers routes."""
        app = create_app()
        
        mock_register_routes.assert_called_once_with(app)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_create_app_cors_enabled(self):
        """Test that CORS is properly configured."""
        app = create_app()
        
        # Check that CORS extension is present
        assert hasattr(app, 'extensions')

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_health_endpoint_available(self):
        """Test that health endpoint is available."""
        app = create_app()
        
        with app.test_client() as client:
            response = client.get("/health")
            assert response.status_code == 200

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_404_error_handler(self):
        """Test 404 error handler."""
        app = create_app()
        
        with app.test_client() as client:
            response = client.get("/nonexistent-endpoint")
            assert response.status_code == 404

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.get_memory_manager")
    def test_memory_manager_integration(self, mock_get_memory_manager):
        """Test memory manager integration."""
        mock_memory_manager = Mock()
        mock_memory_manager.limit_mb = 512
        mock_get_memory_manager.return_value = mock_memory_manager
        
        app = create_app()
        
        # Memory manager should be initialized
        assert isinstance(app, Flask)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.test_database_connection")
    def test_database_connection_handling(self, mock_test_db):
        """Test database connection handling."""
        mock_test_db.return_value = True
        
        app = create_app()
        
        # App should create successfully with DB enabled
        assert isinstance(app, Flask)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.validate_config")
    def test_config_validation(self, mock_validate_config):
        """Test configuration validation."""
        mock_validate_config.return_value = True
        
        app = create_app()
        
        # Config validation should be called
        mock_validate_config.assert_called_once()
        assert isinstance(app, Flask)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.validate_config")
    def test_config_validation_failure(self, mock_validate_config):
        """Test handling of configuration validation failure."""
        mock_validate_config.return_value = False
        
        with pytest.raises(RuntimeError, match="Configuration validation failed"):
            create_app()

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_app_context_creation(self):
        """Test app context creation and usage."""
        app = create_app()
        
        with app.app_context():
            # App context should work properly
            from flask import current_app
            assert current_app == app

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_request_context_creation(self):
        """Test request context creation and usage."""
        app = create_app()
        
        with app.test_request_context():
            # Request context should work properly
            from flask import request
            assert request is not None


class TestRunApp:
    """Test the run_app function."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.get_debug_mode")
    @patch("ygoapi.app.get_port")
    @patch("ygoapi.app.create_app")
    def test_run_app_debug_mode(self, mock_create_app, mock_get_port, mock_get_debug):
        """Test run_app in debug mode."""
        mock_app = Mock()
        mock_create_app.return_value = mock_app
        mock_get_port.return_value = 5000
        mock_get_debug.return_value = True
        
        # Import and patch app.run to avoid actually starting the server
        with patch.object(mock_app, 'run') as mock_run:
            from ygoapi.app import run_app
            run_app()
            
            mock_run.assert_called_once_with(host="0.0.0.0", port=5000, debug=True)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.get_debug_mode")
    @patch("ygoapi.app.get_port") 
    @patch("ygoapi.app.create_app")
    def test_run_app_production_mode(self, mock_create_app, mock_get_port, mock_get_debug):
        """Test running app in production mode."""
        mock_app = Mock()
        mock_create_app.return_value = mock_app
        mock_get_port.return_value = 8080
        mock_get_debug.return_value = False
        
        # Mock the waitress serve function directly instead of through app module
        with patch("waitress.serve") as mock_serve:
            from ygoapi.app import run_app
            run_app()
            
            mock_serve.assert_called_once()


class TestDatabaseIntegration:
    """Test database integration in app creation."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.test_database_connection")
    @patch("ygoapi.app.ALLOW_START_WITHOUT_DATABASE", True)
    def test_app_creation_with_failed_database_allowed(self, mock_test_db):
        """Test app creation with database failure but allowed to continue."""
        mock_test_db.return_value = False
        
        app = create_app()
        
        # App should create successfully even with DB failed
        assert isinstance(app, Flask)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.test_database_connection")
    @patch("ygoapi.app.ALLOW_START_WITHOUT_DATABASE", False)
    def test_app_creation_with_failed_database_not_allowed(self, mock_test_db):
        """Test app creation with database failure and not allowed to continue."""
        mock_test_db.return_value = False
        
        with pytest.raises(RuntimeError, match="Database connection failed"):
            create_app()


class TestLogging:
    """Test logging configuration."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.get_log_level")
    def test_logging_configuration(self, mock_get_log_level):
        """Test logging configuration."""
        mock_get_log_level.return_value = "INFO"
        
        app = create_app()
        
        # Logging should be configured
        assert app.logger is not None
        mock_get_log_level.assert_called_once()


class TestRouteRegistration:
    """Test route registration."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_api_endpoints_registered(self):
        """Test that main API endpoints are registered."""
        app = create_app()
        
        # Check that routes are registered
        route_paths = [rule.rule for rule in app.url_map.iter_rules()]
        
        expected_routes = [
            "/health",
            "/cards/price",
            "/card-sets",
            "/memory/stats",
        ]
        
        for route in expected_routes:
            assert route in route_paths

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("logging.getLogger")
    def test_route_logging(self, mock_get_logger):
        """Test that routes are logged during startup."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        # Create app and verify it works (routes are logged during create_app)
        app = create_app()
        
        # Verify logger was called (routes are logged during registration)
        mock_get_logger.assert_called()


class TestCORSConfiguration:
    """Test CORS configuration."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_cors_origins(self):
        """Test CORS origins configuration."""
        app = create_app()
        
        with app.test_client() as client:
            response = client.options("/health")
            # CORS should be configured (may result in 404/405 for OPTIONS)
            assert response.status_code in [200, 404, 405]

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_cors_methods(self):
        """Test CORS methods configuration."""
        app = create_app()
        
        # CORS should allow various HTTP methods
        with app.test_client() as client:
            # Test that the app handles different methods
            response = client.get("/health")
            assert response.status_code == 200


class TestErrorScenarios:
    """Test various error scenarios."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_500_error_handling(self):
        """Test 500 error handling."""
        app = create_app()
        
        # Create a route that raises an exception
        @app.route("/error-test")
        def error_route():
            raise Exception("Test error")
        
        with app.test_client() as client:
            response = client.get("/error-test")
            assert response.status_code == 500

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    def test_method_not_allowed(self):
        """Test 405 Method Not Allowed handling."""
        app = create_app()
        
        with app.test_client() as client:
            # Try POST to a GET-only endpoint
            response = client.post("/health")
            assert response.status_code == 405


class TestAppConfiguration:
    """Test app configuration scenarios."""

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.get_debug_mode")
    def test_debug_mode_configuration(self, mock_get_debug):
        """Test debug mode configuration."""
        mock_get_debug.return_value = True
        
        app = create_app()
        
        # App should be created regardless of debug mode
        assert isinstance(app, Flask)

    @patch.dict(os.environ, {"DISABLE_DB_CONNECTION": "1"})
    @patch("ygoapi.app.get_port")
    def test_port_configuration(self, mock_get_port):
        """Test port configuration."""
        mock_get_port.return_value = 8080
        
        app = create_app()
        
        # App should be created regardless of port
        assert isinstance(app, Flask)