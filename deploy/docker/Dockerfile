# Confluent Audit Log Forwarder v2
# Multi-stage build for minimal production image

# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.11-slim

# Labels
LABEL maintainer="Audit Forwarder Team"
LABEL version="2.0.0"
LABEL description="Confluent Audit Log Forwarder with multi-sink support"

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    librdkafka1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 -g root forwarder

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ ./src/

# Create data directory
RUN mkdir -p /app/data && \
    chown -R forwarder:root /app && \
    chmod -R 755 /app

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OFFSET_FILE=/app/data/offsets.json \
    METRICS_PORT=8000 \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json

# Expose ports
EXPOSE 8000 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run as non-root user
USER forwarder

# Entry point
ENTRYPOINT ["python", "-m", "src.main"]
