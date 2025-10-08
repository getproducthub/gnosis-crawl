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

## Configuration

Environment variables (see `.env.example`):

### Server
- `HOST` - Server host (default: 0.0.0.0)
- `PORT` - Server port (default: 8080)  
- `DEBUG` - Debug mode (default: false)

### Storage
- `STORAGE_PATH` - Local storage path (default: ./storage)
- `RUNNING_IN_CLOUD` - Cloud mode flag (default: false)
- `GCS_BUCKET_NAME` - GCS bucket for cloud storage

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

All API endpoints require authentication:

```bash
curl -H "Authorization: Bearer <token>" \
     -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{"url": "https://example.com"}'
```

### Without authentication (DISABLE_AUTH=true)

When auth is disabled (Porter/Kubernetes deployments), no token required:

```bash
curl -X POST http://localhost:8080/api/crawl \
     -H "Content-Type: application/json" \
     -d '{"url": "https://example.com"}'
```

⚠️ **Warning:** Only use `DISABLE_AUTH=true` in trusted, internal environments.

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
└── {user_hash}/        # User partition
    └── {session_id}/   # Session partition
        ├── metadata.json
        └── results/
            ├── {url_hash}.json
            └── ...
```

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
- [x] Storage service
- [x] API routes (mock responses)
- [x] Docker configuration
- [x] Deployment scripts

### Phase 2: Crawling (Next)
- [ ] Browser automation (Playwright)
- [ ] HTML extraction
- [ ] Markdown generation  
- [ ] Batch processing
- [ ] Job management

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