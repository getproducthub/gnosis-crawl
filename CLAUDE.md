# CLAUDE.md - Development Context for gnosis-crawl

## Project Overview

**gnosis-crawl** is a pure API web crawling service with markdown generation, following the gnosis service standard. It provides HTML extraction, markdown conversion, and batch processing capabilities with user-partitioned storage.

## Recent Changes (October 16, 2025)

### Customer ID Implementation
Added flexible customer identification system that supports both authenticated and unauthenticated API access:

- **Optional `customer_id` field** in all request models (CrawlRequest, MarkdownRequest, BatchRequest)
- **Priority system**: `customer_id` → authenticated user email → "anonymous@gnosis-crawl.local"
- **Backward compatible**: All existing auth-based flows work unchanged
- **Storage partitioning**: Uses `{hash(customer_id or user_email)}/` for isolation

### Files Modified
1. **app/models.py** - Added `customer_id: Optional[str] = None` to request models
2. **app/auth.py** - Added `get_customer_identifier()` helper function
3. **app/routes.py** - Updated all endpoints to support optional customer_id
4. **app/config.py** - Already had `disable_auth` flag for Porter deployments
5. **.env.porter** - Created minimal config for unauthenticated deployments
6. **Dockerfile** - Added ARG declarations to suppress Porter warnings
7. **README.md** - Comprehensive documentation of customer ID feature
8. **.gitignore** - Added `*_versions/` and `*.backup` patterns

## Architecture

### Core Components

```
app/
├── main.py          # FastAPI application entry point
├── config.py        # Environment-based configuration
├── auth.py          # HMAC JWT authentication + customer ID resolution
├── models.py        # Pydantic request/response models
├── routes.py        # API endpoint handlers
├── storage.py       # User-partitioned storage service (local/GCS)
├── crawler.py       # Playwright-based crawling engine
├── markdown.py      # HTML to markdown conversion
└── browser.py       # Browser automation utilities
```

### Storage Structure

```
storage/
└── {customer_hash}/        # 12-char SHA256 hash of customer_id or email
    └── {session_id}/       # UUID for grouping related crawls
        ├── metadata.json
        └── results/
            ├── {url_hash}.json
            └── screenshots/
```

### Authentication Modes

1. **With Auth (default)**: Uses gnosis-auth HMAC JWT tokens, extracts user email
2. **Without Auth (`DISABLE_AUTH=true`)**: Requires `customer_id` in requests
3. **Hybrid**: Can provide `customer_id` even with auth to override storage partition

## API Endpoints

### Core Crawling
- `POST /api/crawl` - Single URL crawl (HTML + markdown)
- `POST /api/markdown` - Markdown-only crawl (optimized)
- `POST /api/batch` - Batch crawl multiple URLs

### Session Management
- `GET /api/sessions/{session_id}/files` - List stored files
- `GET /api/sessions/{session_id}/file` - Retrieve specific file

### System
- `GET /health` - Health check endpoint

## Key Design Decisions

### Why Optional customer_id?
- **Flexibility**: Support both authenticated SaaS and unauthenticated self-hosted deployments
- **Multi-tenancy**: Allow custom storage partitioning even with auth
- **Porter/Kubernetes**: Enable deployments without gnosis-auth dependency

### Why Hash Customer IDs?
- **Privacy**: Doesn't expose actual email/customer_id in file paths
- **Consistency**: Same hash every time = predictable storage location
- **Safety**: File system safe characters only

### Why Session IDs?
- **Grouping**: Related crawls can be organized together
- **Retrieval**: Easy to list all results from a batch operation
- **Optional**: Auto-generated if not provided

## Configuration

### Environment Variables

**Server:**
- `HOST` - Server host (default: 0.0.0.0)
- `PORT` - Server port (default: 8080)
- `DEBUG` - Debug mode (default: false)

**Storage:**
- `STORAGE_PATH` - Local storage path (default: ./storage)
- `RUNNING_IN_CLOUD` - Use GCS instead of local (default: false)
- `GCS_BUCKET_NAME` - GCS bucket name (cloud mode only)

**Authentication:**
- `DISABLE_AUTH` - Bypass all authentication (default: false) ⚠️
- `GNOSIS_AUTH_URL` - Auth service URL (default: http://gnosis-auth:5000)

**Crawling:**
- `MAX_CONCURRENT_CRAWLS` - Max parallel crawls (default: 5)
- `CRAWL_TIMEOUT` - Timeout in seconds (default: 30)
- `ENABLE_JAVASCRIPT` - JavaScript rendering (default: true)
- `ENABLE_SCREENSHOTS` - Take screenshots (default: false)
- `BROWSER_HEADLESS` - Headless mode (default: true)
- `BROWSER_TIMEOUT` - Browser timeout in ms (default: 30000)

### Deployment Configs

- **.env** - Local development (not in git)
- **.env.porter** - Porter/Kubernetes deployment (no auth)
- **.env.example** - Template for new deployments

## Common Development Tasks

### Running Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Run with uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### Building Docker Image
```bash
docker build -t gnosis-crawl:latest .
```

### Testing Changes
```bash
# Update test script with deployed URL
python test_remote_api.py
```

### Adding New Endpoints
1. Add Pydantic models to `app/models.py`
2. Create route handler in `app/routes.py`
3. Use `get_optional_user_email()` dependency for auth flexibility
4. Call `get_customer_identifier()` to resolve customer ID
5. Update README.md with new endpoint documentation

## Known Issues & Gotchas

### Pydantic V2 Warning
```
Valid config keys have changed in V2: 'fields' has been removed
```
**Status**: Harmless warning from config.py Config class
**Fix**: Update to Pydantic V2 config pattern (low priority)

### Porter Build Args Warning
Porter passes env vars as build args, causing warnings.
**Status**: Fixed by adding ARG declarations in Dockerfile

### Auth Middleware Order
The middleware checks for `disable_auth` flag BEFORE attempting to load auth_client.
**Critical**: Must check `settings.disable_auth` before any auth client operations.

### File Versioning
The `*_versions/` directories are created by file-diff-writer tool for local version tracking.
**Status**: Added to .gitignore, should not be committed

## Dependencies

### Core
- **FastAPI** - Web framework
- **Pydantic** - Data validation
- **Uvicorn** - ASGI server
- **Playwright** - Browser automation

### Storage
- **google-cloud-storage** - GCS support (optional)

### Processing
- **BeautifulSoup4** - HTML parsing
- **html2text** - Markdown conversion
- **httpx** - HTTP client

## Testing

### Remote API Test Script
`test_remote_api.py` - Comprehensive test suite for deployed instances

**Tests:**
- Health check
- Single URL crawl with customer_id
- Markdown-only crawl
- Batch crawl
- Session file listing
- No customer_id fallback

**Usage:**
```python
# Update configuration
API_BASE_URL = "https://your-deployed-url.com"
CUSTOMER_ID = "test-client-123"
BEARER_TOKEN = None  # or "your-token" for auth testing

# Run tests
python test_remote_api.py
```

## Deployment

### Porter/Kubernetes
1. Use `.env.porter` configuration
2. Set `DISABLE_AUTH=true` for public access
3. Build image: `docker build -t gnosis-crawl:latest .`
4. Push to registry
5. Deploy via Porter UI or kubectl

**Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port 8080`

### Google Cloud Run
```powershell
./deploy.ps1 -Target cloudrun -Tag v1.0.0
```

### Local Docker
```powershell
./deploy.ps1 -Target local
```

## Security Considerations

### DISABLE_AUTH Flag
⚠️ **WARNING**: Setting `DISABLE_AUTH=true` makes ALL endpoints publicly accessible.

**Safe Use Cases:**
- Private internal networks
- Behind corporate firewall
- Trusted Kubernetes cluster with network policies
- Development/testing environments

**Unsafe Use Cases:**
- Public internet exposure
- Multi-tenant SaaS without auth
- Untrusted networks

### Customer ID Validation
Currently NO validation on customer_id format. Consider adding:
- Length limits
- Character restrictions
- Rate limiting per customer_id
- Usage quotas

## Future Enhancements

### Potential Improvements
- [ ] Add customer_id validation/sanitization
- [ ] Rate limiting per customer_id
- [ ] Usage metrics and quotas
- [ ] Webhook notifications for batch completion
- [ ] Priority queue for crawl requests
- [ ] Retry logic for failed crawls
- [ ] Browser pool optimization
- [ ] Cost tracking per customer_id

### Phase 3 Roadmap
- [ ] Comprehensive test suite
- [ ] Error handling improvements
- [ ] Monitoring and alerting
- [ ] Performance optimization
- [ ] Documentation improvements

## Contact & References

- **Documentation**: README.md
- **Customer ID Details**: CUSTOMER_ID_IMPLEMENTATION.md
- **Remote Testing**: test_remote_api.py
- **Gnosis Standards**: Follows gnosis deployment patterns

## Tips for AI Assistants

1. **Always check imports** when adding new FastAPI features (Header, Query, etc.)
2. **Use `get_optional_user_email()`** for new endpoints to support both auth modes
3. **Call `get_customer_identifier()`** to resolve customer ID from multiple sources
4. **Test both modes**: with and without DISABLE_AUTH flag
5. **Storage paths**: Always use customer_hash/session_id structure
6. **Backward compatibility**: Never break existing auth-based flows
7. **File versions**: Don't commit *_versions/ directories

## Quick Reference

### Testing Authenticated Request
```bash
curl -H "Authorization: Bearer <token>" \
     -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{"url": "https://example.com"}'
```

### Testing Unauthenticated Request
```bash
curl -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://example.com",
       "customer_id": "test-client-123"
     }'
```

### Getting Session Files
```bash
curl "http://localhost:8080/api/sessions/{session_id}/files?customer_id=test-client-123"
```

---

**Last Updated**: October 16, 2025
**Current Version**: v1.0.0
**Status**: Production Ready ✅
