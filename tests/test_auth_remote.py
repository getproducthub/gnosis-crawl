"""
Remote integration tests for Bearer token authentication

Set these environment variables to run:
- GRUB_API_URL (e.g., https://grub.nuts.services)
- GRUB_AUTH_TOKEN (your Bearer token)

Skip if not set.
"""
import pytest
import requests
import os


@pytest.fixture
def api_config():
    """Get API configuration from environment"""
    url = os.getenv("GRUB_API_URL")
    token = os.getenv("GRUB_AUTH_TOKEN")

    if not url:
        pytest.skip("GRUB_API_URL must be set")

    return {
        "url": url.rstrip("/"),
        "token": token,  # Can be None if auth is disabled
        "auth_enabled": bool(token)  # Track if auth is expected to work
    }


def test_remote_no_auth_returns_401_or_works(api_config):
    """Remote API without Authorization header"""
    response = requests.post(
        f"{api_config['url']}/api/markdown",
        json={"url": "https://example.com"},
        timeout=30
    )

    if api_config['auth_enabled']:
        # If auth token is configured, expect 401 without header
        assert response.status_code == 401
    else:
        # If auth is disabled, request should work
        assert response.status_code in (200, 202)
        data = response.json()
        assert "success" in data or "markdown" in data


def test_remote_wrong_token_returns_401(api_config):
    """Remote API with wrong Bearer token"""
    if not api_config['auth_enabled']:
        pytest.skip("Skipping auth test - no token configured (auth disabled)")

    response = requests.post(
        f"{api_config['url']}/api/markdown",
        json={"url": "https://example.com"},
        headers={"Authorization": "Bearer wrong-token-xyz"},
        timeout=10
    )
    assert response.status_code == 401


def test_remote_correct_token_returns_200(api_config):
    """Remote API with correct Bearer token should succeed"""
    if not api_config['auth_enabled']:
        pytest.skip("Skipping auth test - no token configured (auth disabled)")

    response = requests.post(
        f"{api_config['url']}/api/markdown",
        json={"url": "https://example.com"},
        headers={"Authorization": f"Bearer {api_config['token']}"},
        timeout=30
    )

    # Should not be 401
    assert response.status_code != 401

    # Should be 200 or 202 (accepted for async processing)
    assert response.status_code in (200, 202)

    # Should have JSON response
    data = response.json()
    assert "success" in data or "markdown" in data


def test_remote_malformed_auth_returns_401(api_config):
    """Remote API with malformed Authorization header"""
    if not api_config['auth_enabled']:
        pytest.skip("Skipping auth test - no token configured (auth disabled)")

    # Missing "Bearer " prefix
    response = requests.post(
        f"{api_config['url']}/api/markdown",
        json={"url": "https://example.com"},
        headers={"Authorization": api_config['token']},
        timeout=10
    )
    assert response.status_code == 401


def test_remote_raw_endpoint_with_auth(api_config):
    """Test raw HTML endpoint (works with or without auth)"""
    headers = {}
    if api_config['auth_enabled']:
        headers["Authorization"] = f"Bearer {api_config['token']}"

    response = requests.post(
        f"{api_config['url']}/api/raw",
        json={
            "url": "https://example.com",
            "javascript_enabled": False
        },
        headers=headers,
        timeout=30
    )

    assert response.status_code in (200, 202)
    data = response.json()
    assert "success" in data or "html_content" in data
