# Grub Crawler Tests

Comprehensive test suite for grub-crawl API.

## Test Organization

```
tests/
├── test_auth_local.py          # Local auth unit tests
├── test_remote_integration.py  # Remote API integration tests
├── test_simple.py              # Simple health checks
├── test_batch_crawl.py         # Batch crawling tests
├── test_screenshot_api.py      # Screenshot functionality
└── test_simple_crawl.py        # Basic crawl tests
```

## Running Tests

### Local Unit Tests Only

Fast tests that don't require external services:

```bash
pytest -v -m "not remote"
```

Or specifically:

```bash
pytest -v tests/test_auth_local.py
```

### Remote Integration Tests

Tests that require a deployed grub-crawl service:

```bash
# Set environment variables first
export GRUB_CRAWL_API_URL="https://your-deployed-url.com"
export GRUB_CRAWL_CUSTOMER_ID="test-customer-123"
export GRUB_CRAWL_BEARER_TOKEN="your-token-here"  # Optional

# Run remote tests
pytest -v -m remote
```

Or specifically:

```bash
pytest -v tests/test_remote_integration.py
```

### All Tests

```bash
pytest -v
```

### Specific Test Classes

```bash
pytest -v tests/test_auth_local.py::TestBearerAuth
pytest -v tests/test_remote_integration.py::TestHealthEndpoint
```

### Specific Test Methods

```bash
pytest -v tests/test_auth_local.py::TestBearerAuth::test_protected_endpoint_correct_token
```

## Test Markers

Tests are organized with pytest markers:

- `@pytest.mark.remote` - Requires deployed service (skipped by default)
- `@pytest.mark.slow` - Takes significant time to run
- `@pytest.mark.auth` - Authentication-related tests
- `@pytest.mark.unit` - Fast unit tests
- `@pytest.mark.integration` - Integration tests

### Running by Marker

```bash
pytest -v -m remote      # Only remote tests
pytest -v -m "not remote"  # Skip remote tests
pytest -v -m slow        # Only slow tests
pytest -v -m auth        # Only auth tests
```

## Environment Variables

### For Local Tests

```bash
# API key for testing ProductBot endpoints
export TEST_API_KEY="test-secret-key-123"

# HMAC secret for token validation (must match gnosis-ahp)
export AHP_SECRET_KEY="your-secret-key"
export SECRET_KEY="your-secret-key"
```

### For Remote Integration Tests

```bash
# Required: Deployed service URL
export GRUB_CRAWL_API_URL="https://your-service.com"

# Optional: Customer ID for testing
export GRUB_CRAWL_CUSTOMER_ID="test-customer"

# Optional: Bearer token for authenticated tests
export GRUB_CRAWL_BEARER_TOKEN="your-jwt-token"
```

## Test Configuration

### pytest.ini

Configuration for test discovery, markers, and output formatting.

```ini
[pytest]
markers =
    remote: Remote integration tests (require deployed API)
    slow: Slow tests
    auth: Authentication tests
```

### .env.example

Template showing all available environment variables for testing.

## Writing New Tests

### Local Unit Tests

Place in appropriate test file or create new `test_*.py`:

```python
import pytest

class TestMyFeature:
    def test_something(self):
        assert True
```

### Remote Integration Tests

Add to `test_remote_integration.py` with `remote` marker:

```python
import pytest

@pytest.mark.remote
class TestMyAPIFeature:
    def test_api_endpoint(self, api_client, check_api_configured):
        response = api_client["session"].get(
            f"{api_client['base_url']}/my-endpoint"
        )
        assert response.status_code == 200
```

## Common Test Patterns

### Using API Client Fixture

```python
def test_with_auth(self, api_client):
    """api_client fixture provides session with auth"""
    response = api_client["session"].post(
        f"{api_client['base_url']}/api/crawl",
        json={"url": "https://example.com"}
    )
    assert response.status_code == 200
```

### Testing Auth Decorator

```python
def test_protected_endpoint(self, monkeypatch):
    """Test Bearer token protection"""
    monkeypatch.setenv("TEST_API_KEY", "secret")

    response = client.post(
        "/protected",
        headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 200
```

### Skipping Tests Conditionally

```python
def test_optional_feature(self):
    if not os.getenv("FEATURE_ENABLED"):
        pytest.skip("Feature not enabled")
    # ... test code
```

## CI/CD Integration

### GitHub Actions Example

```yaml
- name: Run Tests
  env:
    GRUB_CRAWL_API_URL: ${{ secrets.API_URL }}
    GRUB_CRAWL_BEARER_TOKEN: ${{ secrets.BEARER_TOKEN }}
  run: |
    pytest -v -m "not slow"
```

### Skip Remote Tests in CI

```bash
# In CI, only run local tests
pytest -v -m "not remote"
```

## Troubleshooting

### Remote Tests Fail to Connect

Check environment variables:
```bash
echo $GRUB_CRAWL_API_URL
echo $GRUB_CRAWL_CUSTOMER_ID
```

### Auth Tests Fail

Verify token is valid:
```bash
curl -H "Authorization: Bearer $GRUB_CRAWL_BEARER_TOKEN" \
     $GRUB_CRAWL_API_URL/health
```

### Import Errors

Ensure you're in the project root:
```bash
cd /path/to/grub-crawl
pytest -v
```

## Test Coverage

To generate coverage report:

```bash
pytest --cov=app --cov-report=html
```

View report:
```bash
open htmlcov/index.html
```

## Quick Reference

```bash
# All local tests (fast)
pytest -v -m "not remote"

# All remote tests (requires deployed service)
pytest -v -m remote

# Auth tests only
pytest -v tests/test_auth_local.py

# Integration tests only
pytest -v tests/test_remote_integration.py

# With verbose output and show print statements
pytest -v -s

# Stop on first failure
pytest -x

# Run last failed tests
pytest --lf

# Show test durations
pytest --durations=10
```
