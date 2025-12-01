"""
Local unit tests for Bearer token authentication
"""
import pytest
import os
from flask import Flask, jsonify
from functools import wraps
from flask import request, abort


def require_api_key(api_key):
    """Auth decorator factory - auth disabled if api_key not set"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # If API_KEY is not set, auth is disabled - allow all requests
            if not api_key:
                return f(*args, **kwargs)

            # API_KEY is set, require Bearer token
            if request.headers.get("Authorization") != f"Bearer {api_key}":
                abort(401)

            return f(*args, **kwargs)
        return wrapped
    return decorator


@pytest.fixture
def app():
    """Create test Flask app with auth"""
    app = Flask(__name__)
    API_KEY = "test-secret-key-123"

    @app.post("/test-endpoint")
    @require_api_key(API_KEY)
    def test_endpoint():
        return jsonify({"success": True, "message": "Authenticated!"})

    return app


@pytest.fixture
def client(app):
    """Test client"""
    return app.test_client()


def test_no_auth_header_returns_401(client):
    """Request without Authorization header should return 401"""
    response = client.post("/test-endpoint")
    assert response.status_code == 401


def test_wrong_bearer_token_returns_401(client):
    """Request with wrong Bearer token should return 401"""
    response = client.post(
        "/test-endpoint",
        headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


def test_correct_bearer_token_returns_200(client):
    """Request with correct Bearer token should return 200"""
    response = client.post(
        "/test-endpoint",
        headers={"Authorization": "Bearer test-secret-key-123"}
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


def test_malformed_auth_header_returns_401(client):
    """Request with malformed Authorization header should return 401"""
    # Missing "Bearer " prefix
    response = client.post(
        "/test-endpoint",
        headers={"Authorization": "test-secret-key-123"}
    )
    assert response.status_code == 401


def test_empty_api_key_allows_all_requests():
    """When API_KEY is empty, auth is disabled - all requests should pass"""
    app = Flask(__name__)
    API_KEY = ""  # Empty key - auth disabled

    @app.post("/test-endpoint")
    @require_api_key(API_KEY)
    def test_endpoint():
        return jsonify({"success": True})

    test_client = app.test_client()

    # No auth header - should pass because auth is disabled
    response = test_client.post("/test-endpoint")
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    # With any token - should also pass because auth is disabled
    response = test_client.post(
        "/test-endpoint",
        headers={"Authorization": "Bearer any-token"}
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True
