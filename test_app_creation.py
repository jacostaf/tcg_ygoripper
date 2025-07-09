#!/usr/bin/env python3
"""
Test the modular application without database requirements.
"""

import sys
import os

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_app_creation_without_db():
    """Test that we can create a Flask app without database."""
    try:
        from flask import Flask
        from ygoapi.routes import register_routes
        from ygoapi.memory_manager import get_memory_stats
        
        # Create a test Flask app
        app = Flask(__name__)
        
        # Register routes
        register_routes(app)
        
        # Check that routes were registered
        routes = [str(rule) for rule in app.url_map.iter_rules()]
        
        print("✓ Flask app created successfully")
        print(f"✓ {len(routes)} routes registered")
        print("✓ Sample routes:")
        for route in routes[:5]:
            print(f"   - {route}")
        
        # Test memory manager
        stats = get_memory_stats()
        print(f"✓ Memory manager working: {stats['rss_mb']:.1f}MB used")
        
        # Test that we can access the health endpoint (without running server)
        with app.test_client() as client:
            response = client.get('/health')
            print(f"✓ Health endpoint test: {response.status_code}")
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run the test."""
    print("Testing modular Flask app creation...")
    print("=" * 40)
    
    success = test_app_creation_without_db()
    
    if success:
        print()
        print("✓ All tests passed! The modular structure is working.")
        print("  Note: Database-dependent features will require MongoDB connection.")
        return 0
    else:
        print()
        print("✗ Tests failed. Check output above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())