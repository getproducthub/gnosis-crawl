# Porter Deployment Guide for gnosis-crawl

## Prerequisites

1. **GCS Bucket Created**
   ```bash
   gsutil mb gs://gnosis-crawl-storage
   ```

2. **Service Account Permissions**
   Porter's GKE cluster should have a service account with:
   - `roles/storage.objectAdmin` on the bucket
   
   Or grant explicitly:
   ```bash
   gsutil iam ch serviceAccount:YOUR-PORTER-SA@PROJECT.iam.gserviceaccount.com:objectAdmin gs://gnosis-crawl-storage
   ```

## Porter Configuration

### 1. Environment Variables to Set in Porter UI

```bash
# Authentication
DISABLE_AUTH=true

# Storage - CLOUD MODE
RUNNING_IN_CLOUD=true
GCS_BUCKET_NAME=gnosis-crawl-storage

# Server
HOST=0.0.0.0
PORT=8080
DEBUG=false

# Crawling
MAX_CONCURRENT_CRAWLS=5
CRAWL_TIMEOUT=30
ENABLE_JAVASCRIPT=true
ENABLE_SCREENSHOTS=false

# Browser
BROWSER_HEADLESS=true
BROWSER_TIMEOUT=30000
```

### 2. Application Settings in Porter

- **Port**: `8080`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port 8080`
- **Health Check Path**: `/health`
- **Container Image**: Your built image from registry

## Build & Deploy Steps

### 1. Build with Latest Code
```bash
# Make sure you have the latest changes
git pull

# Build Docker image
docker build -t your-registry/gnosis-crawl:latest .

# Push to your registry
docker push your-registry/gnosis-crawl:latest
```

### 2. Deploy in Porter
1. Go to Porter dashboard
2. Select your application
3. Update environment variables (above)
4. Trigger new deployment

### 3. Verify Deployment
```bash
# Check health
curl https://your-porter-url.com/health

# Test with customer_id (since auth is disabled)
curl -X POST https://your-porter-url.com/api/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "customer_id": "test-client-123"
  }'

# Check where files are stored
curl "https://your-porter-url.com/api/debug/storage?customer_id=test-client-123"
```

## Storage Behavior

### With Cloud Mode Enabled:
- Files stored in: `gs://gnosis-crawl-storage/{customer_hash}/{session_id}/results/`
- No persistent volume needed in Porter
- Files persist across container restarts
- Shared across all pod replicas

### Without Cloud Mode (Previous):
- Files stored in: `/app/storage/` inside container
- Lost on container restart
- Not shared between replicas
- Not recommended for production

## Troubleshooting

### Error: "Google Cloud Storage client not installed"
**Solution**: The Docker image should have `google-cloud-storage` in requirements.txt
```bash
# Verify it's in requirements.txt
grep "google-cloud-storage" requirements.txt
```

### Error: "403 Forbidden" accessing GCS
**Solution**: Service account needs permissions
```bash
# Check service account
gcloud projects get-iam-policy YOUR-PROJECT

# Grant permission
gsutil iam ch serviceAccount:SA-EMAIL:objectAdmin gs://gnosis-crawl-storage
```

### Files Still Going to /app/storage
**Solution**: Check environment variables are actually set
```bash
# In Porter logs, look for:
# "GCS client initialized for bucket: gnosis-crawl-storage"

# If you see "Local storage initialized at /app/storage" instead,
# then RUNNING_IN_CLOUD=true is not being set
```

### How to Verify Cloud Storage is Working
```bash
# Make a crawl request
curl -X POST https://your-url.com/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "customer_id": "test"}'

# Check in GCS bucket
gsutil ls -r gs://gnosis-crawl-storage/

# Should see files like:
# gs://gnosis-crawl-storage/abc123def456/uuid-here/results/xyz789.json
```

## Quick Checklist

Before deploying, ensure:
- [ ] GCS bucket created
- [ ] Service account has permissions
- [ ] `RUNNING_IN_CLOUD=true` set in Porter
- [ ] `GCS_BUCKET_NAME` set to your bucket name
- [ ] Latest code with batch crawl fix deployed
- [ ] Health check passes
- [ ] Test crawl works and files appear in GCS

## Important Notes

1. **Authentication Disabled**: With `DISABLE_AUTH=true`, all endpoints are public. Only use in trusted environments.

2. **Customer ID Required**: Without auth, you MUST provide `customer_id` in requests for proper storage partitioning.

3. **Storage Costs**: GCS storage has costs. Monitor usage and set lifecycle policies if needed.

4. **No Migration Tool**: Existing files in `/app/storage` won't automatically move to GCS. They're separate storage systems.

## Next Steps After Deployment

1. Run the test script with his Porter URL
2. Verify files appear in GCS bucket
3. Check that batch crawls work (the bug fix)
4. Monitor logs for any GCS errors

---

**Need Help?**
- Check Porter logs for startup errors
- Use `/api/debug/storage` endpoint to verify configuration
- Check GCS bucket contents with `gsutil ls`
