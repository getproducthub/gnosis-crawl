# Gnosis-Crawl

Pure API web crawling service with markdown generation, following the gnosis service standard.

## Overview

Gnosis-Crawl is a focused, API-only crawling service that provides:

- **Single URL crawling** - Synchronous HTML + markdown extraction
- **Markdown-only crawling** - Optimized markdown extraction  
- **Batch processing** - Asynchronous multi-URL crawling with job tracking
- **User partitioned storage** - Secure, isolated data storage
- **Gnosis-auth integration** - Standardized authentication

## API Endpoints

### Core Crawling
- `POST /api/crawl` - Crawl single URL (returns HTML + markdown)
- `POST /api/markdown` - Crawl single URL (markdown only)
- `POST /api/batch` - Start batch crawl job

### Job Management  
- `GET /api/jobs/{job_id}` - Get job status and results
- `GET /api/jobs` - List user jobs

### Session Management
- `GET /api/sessions/{session_id}/files` - List files for a session
- `GET /api/sessions/{session_id}/file` - Get specific file from session

### System
- `GET /health` - Health check

## Quick Start

### Local Development

1. **Clone and setup:**
   ```bash
   git clone <repo>
   cd gnosis-crawl
   cp .env.example .env
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run locally:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
   ```

4. **Access service:**
   - API: http://localhost:8080
   - Docs: http://localhost:8080/docs
   - Health: http://localhost:8080/health

### Docker Deployment

1. **Local Docker:**
   ```powershell
   ./deploy.ps1 -Target local
   ```

2. **Google Cloud Run:**
   ```powershell
   ./deploy.ps1 -Target cloudrun -Tag v1.0.0
   ```

### Porter/Kubernetes Deployment (No Auth)

For standalone deployments without gnosis-auth:

1. **Copy Porter config:**
   ```bash
   cp .env.porter .env
   ```

2. **Deploy to your cluster:**
   - The `DISABLE_AUTH=true` flag bypasses all authentication
   - All endpoints become publicly accessible
   - Recommended for internal/private clusters only

3. **Build and deploy:**
   ```bash
   docker build -t gnosis-crawl:latest .
   # Push to your registry and deploy via Porter/kubectl
   ```

### Cloud Storage (GCS) Setup

For production deployments using Google Cloud Storage:

1. **Create GCS bucket:**
   ```bash
   gsutil mb gs://gnosis-crawl-storage
   ```

2. **Set permissions:**
   ```bash
   # Grant service account write access
   gsutil iam ch serviceAccount:YOUR-SA@PROJECT.iam.gserviceaccount.com:objectAdmin gs://gnosis-crawl-storage
   ```

3. **Use cloud config:**
   ```bash
   cp .env.cloud .env
   ```

4. **Update environment variables:**
   ```bash
   RUNNING_IN_CLOUD=true
   GCS_BUCKET_NAME=gnosis-crawl-storage
   GOOGLE_CLOUD_PROJECT=your-project-id  # Optional if running in GCP
   ```

5. **Install GCS client:**
   ```bash
   pip install google-cloud-storage
   ```

**Note:** When running in GCP (Cloud Run, GKE), authentication is automatic via service accounts. For local development, set `GOOGLE_APPLICATION_CREDENTIALS` to your service account key file.

## Configuration

Environment variables (see `.env.example`):

### Server
- `HOST` - Server host (default: 0.0.0.0)
- `PORT` - Server port (default: 8080)  
- `DEBUG` - Debug mode (default: false)

### Storage
- `STORAGE_PATH` - Local storage path (default: ./storage)
- `RUNNING_IN_CLOUD` - Enable GCS cloud storage (default: false)
- `GCS_BUCKET_NAME` - GCS bucket name (required if RUNNING_IN_CLOUD=true)
- `GOOGLE_CLOUD_PROJECT` - GCP project ID (optional, auto-detected in GCP)

### Authentication
- `DISABLE_AUTH` - Disable all authentication (default: false) ⚠️
- `GNOSIS_AUTH_URL` - Gnosis-auth service URL

### Crawling
- `MAX_CONCURRENT_CRAWLS` - Max concurrent crawls (default: 5)
- `CRAWL_TIMEOUT` - Crawl timeout in seconds (default: 30)
- `ENABLE_JAVASCRIPT` - Enable JS rendering (default: true)
- `ENABLE_SCREENSHOTS` - Enable screenshots (default: false)

## Authentication

### With gnosis-auth (default)

All API endpoints require authentication via Bearer token. User email from the token is used for storage partitioning:

```bash
curl -H "Authorization: Bearer <token>" \
     -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{"url": "https://example.com"}'
```

### Without authentication (DISABLE_AUTH=true)

When auth is disabled (Porter/Kubernetes deployments), use `customer_id` for storage partitioning:

```bash
curl -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://example.com",
       "customer_id": "client-xyz-123"
     }'
```

⚠️ **Warning:** Only use `DISABLE_AUTH=true` in trusted, internal environments.

### Customer ID Support

All crawl endpoints support an optional `customer_id` field for flexible storage partitioning:

- **Priority**: `customer_id` (if provided) → authenticated user email → "anonymous"
- **Use cases**:
  - Unauthenticated API access (with `DISABLE_AUTH=true`)
  - Multi-tenant storage partitioning even with auth
  - Custom storage organization
- **Storage path**: `storage/{hash(customer_id or user_email)}/{session_id}/`

**Example with customer_id override:**
```bash
curl -H "Authorization: Bearer <token>" \
     -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://example.com",
       "customer_id": "custom-partition-id",
       "session_id": "my-session"
     }'
```

**Session file access with customer_id:**
```bash
# List session files
curl "http://localhost:8080/api/sessions/my-session/files?customer_id=client-xyz-123"

# Get specific file
curl "http://localhost:8080/api/sessions/my-session/file?path=results/abc123.json&customer_id=client-xyz-123"
```

## Architecture

### Directory Structure
```
gnosis-crawl/
├── app/                 # Application code
│   ├── main.py         # FastAPI app
│   ├── config.py       # Configuration  
│   ├── auth.py         # Authentication
│   ├── models.py       # Data models
│   ├── routes.py       # API routes
│   ├── storage.py      # Storage service
│   └── crawler.py      # Crawling logic
├── tests/              # Test suite
├── storage/            # Local storage
├── Dockerfile          # Container config
├── docker-compose.yml  # Local deployment
├── deploy.ps1          # Deployment script
└── requirements.txt    # Dependencies
```

### Storage Organization
```
storage/
└── {customer_hash}/        # Customer partition (hash of customer_id or user_email)
    └── {session_id}/       # Session partition
        ├── metadata.json
        └── results/
            ├── {url_hash}.json
            └── ...
```

**Customer Hash:** 12-character SHA256 hash provides:
- Privacy (doesn't expose actual customer_id or email)
- Consistent bucketing per customer
- File system safety

### Job System
- **Local**: ThreadPoolExecutor for development
- **Cloud**: Google Cloud Tasks for production  
- **Status**: Derived from actual storage files
- **Sessions**: User-scoped job grouping

## Development Status

### Phase 1: Core Infrastructure ✅
- [x] Directory structure  
- [x] FastAPI application
- [x] Authentication integration
- [x] Customer ID support (optional auth bypass)
- [x] Storage service with customer partitioning
- [x] API routes
- [x] Docker configuration
- [x] Deployment scripts

### Phase 2: Crawling ✅
- [x] Browser automation (Playwright)
- [x] HTML extraction
- [x] Markdown generation  
- [x] Batch processing
- [x] Session management

### Phase 3: Testing & Production
- [ ] Test suite
- [ ] Error handling
- [ ] Monitoring
- [ ] Documentation

## Contributing

This service follows the gnosis deployment standard:
1. **Flat app structure** - All code in `/app` directory
2. **Environment-based config** - `.env` pattern
3. **PowerShell deployment** - `deploy.ps1` script
4. **Docker-first** - Containerized deployment
5. **Gnosis-auth integration** - Standard authentication

## License

Gnosis Project License