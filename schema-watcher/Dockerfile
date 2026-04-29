# Schema Watcher - Confluent Audit Log Schema Monitoring
# Security hardened: non-root user, minimal base image, no unnecessary packages

FROM python:3.9-slim

# Security: Create non-root user
RUN groupadd -r watcher && useradd -r -g watcher -u 1000 watcher

# Install system dependencies (minimal)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY watcher.py .

# Create data directory for version tracking
RUN mkdir -p /app/data && \
    chown -R watcher:watcher /app

# Security: Switch to non-root user
USER watcher

# Environment variables (can be overridden in docker-compose)
ENV METHODS_FILE=/app/src/classification/methods.py \
    VERSIONS_FILE=/app/data/schema_versions.json \
    CHECK_INTERVAL_HOURS=24 \
    DRY_RUN=false \
    PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=6h --timeout=30s --start-period=10s --retries=3 \
    CMD python -c "import sys; from pathlib import Path; sys.exit(0 if Path('/app/data/schema_versions.json').exists() else 1)"

# Run watcher
CMD ["python", "-u", "watcher.py"]
