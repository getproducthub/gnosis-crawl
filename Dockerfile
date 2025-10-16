# Gnosis-Crawl Dockerfile
# Use official Playwright Python image like gnosis-wraith

FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

# Accept Porter build args (to suppress warnings, not actually used)
ARG PORTER_APP_NAME
ARG PORTER_CLUSTER
ARG PORTER_DEPLOYMENT_TARGET_ID
ARG PORTER_HOST
ARG PORTER_PROJECT
ARG PORTER_PR_NUMBER
ARG PORTER_REPO_NAME
ARG PORTER_TAG
ARG PORTER_TOKEN
ARG BUILDKIT_INLINE_CACHE

# Accept runtime config as build args (not used, set at runtime via ENV vars)
ARG DISABLE_AUTH
ARG STORAGE_PATH
ARG RUNNING_IN_CLOUD
ARG HOST
ARG PORT
ARG DEBUG
ARG MAX_CONCURRENT_CRAWLS
ARG CRAWL_TIMEOUT
ARG ENABLE_JAVASCRIPT
ARG ENABLE_SCREENSHOTS
ARG BROWSER_HEADLESS
ARG BROWSER_TIMEOUT

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Install additional dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd --create-home --shell /bin/bash app

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (chromium) to match the installed Python package version
RUN playwright install --with-deps chromium

# Copy application code
COPY app/ ./app/

# Create storage directory
RUN mkdir -p storage && chown -R app:app storage

# Switch to non-root user
USER app

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]