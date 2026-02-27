# Grub Crawler Dockerfile
# Use official Playwright Python image like grub

FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Install additional dependencies (xvfb required for camoufox headless="virtual")
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    iputils-ping \
    xvfb \
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

# Fetch Camoufox browser binary
RUN python -m camoufox fetch

# Copy application code
COPY app/ ./app/

# Copy embedded landing page (grub-site)
COPY site/ ./site/

# Create storage directory
RUN mkdir -p storage && chown -R app:app storage

# Switch to non-root user
USER app

# Expose port
EXPOSE 6792

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-6792}/health || exit 1

# Run application — respect PORT env var (Cloud Run sets PORT=8080)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-6792}