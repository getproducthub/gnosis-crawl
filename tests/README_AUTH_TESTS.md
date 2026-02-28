# Authentication Tests

Tests work **with or without** auth tokens configured. If no token is set, auth is disabled and requests pass through.

## Quick Start

### Run Local Tests (no setup needed)
```bash
cd grub-crawl
pytest tests/test_auth_local.py -v
```

### Run Remote Tests (optional credentials)
```bash
# Option 1: With auth token (tests full auth flow)
export GRUB_API_URL="https://grub.nuts.services"
export GRUB_AUTH_TOKEN="your-token-here"
pytest tests/test_auth_remote.py -v

# Option 2: Without auth token (tests pass through when auth disabled)
export GRUB_API_URL="https://grub.nuts.services"
pytest tests/test_auth_remote.py -v
```

## Test Files

### `test_auth_local.py` - Unit Tests
Tests the Bearer token authentication logic locally without hitting any API.

**Tests:**
- ✅ No auth header → 401 (when API key set)
- ✅ Wrong token → 401 (when API key set)
- ✅ Correct token → 200 (when API key set)
- ✅ Malformed auth header → 401 (when API key set)
- ✅ Empty API key → 200 (auth disabled, all requests pass)

**Run:**
```bash
pytest tests/test_auth_local.py -v
```

### `test_auth_remote.py` - Integration Tests
Tests against actual remote API endpoint (works with or without credentials).

**Tests:**
- ✅ No auth header → 401 (if auth enabled) or 200 (if auth disabled)
- ✅ Wrong token → 401 (if auth enabled)
- ✅ Correct token → 200/202 (if auth enabled)
- ✅ Malformed auth header → 401 (if auth enabled)
- ✅ Raw endpoint with auth

**Setup:**
```bash
# Option 1: Test with auth enabled (requires token)
export GRUB_API_URL="https://grub.nuts.services"
export GRUB_AUTH_TOKEN="your-token-here"

# Option 2: Test with auth disabled (no token needed)
export GRUB_API_URL="https://grub.nuts.services"
# Don't set GRUB_AUTH_TOKEN - tests will pass assuming auth is disabled
```

**Run:**
```bash
pytest tests/test_auth_remote.py -v
```

**Auto-skip behavior:**
Tests will automatically skip if `GRUB_API_URL` is not set. If URL is set but token is not, tests assume auth is disabled on the server.

## Run All Tests
```bash
# Local only (no credentials needed)
pytest tests/test_auth_local.py -v

# All tests (skips remote if no credentials)
pytest tests/ -v

# Verbose with output
pytest tests/ -vv -s
```

## CI/CD

For CI/CD pipelines:
- Always run `test_auth_local.py`
- Only run `test_auth_remote.py` if credentials are available in secrets

```yaml
# Example GitHub Actions
- name: Run local auth tests
  run: pytest tests/test_auth_local.py -v

- name: Run remote auth tests
  if: env.GRUB_AUTH_TOKEN != ''
  env:
    GRUB_API_URL: https://grub.nuts.services
    GRUB_AUTH_TOKEN: ${{ secrets.GRUB_AUTH_TOKEN }}
  run: pytest tests/test_auth_remote.py -v
```
