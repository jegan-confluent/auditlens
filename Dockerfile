# syntax=docker/dockerfile:1.4
# Confluent Audit Log Intelligence Forwarder
# Production-ready containerized deployment with security hardening and performance optimizations
# Last updated: 2025-12-08

# =============================================================================
# Build Stage - Install dependencies
# =============================================================================
FROM python:3.11-slim AS builder

LABEL org.opencontainers.image.title="Audit Forwarder Builder"
LABEL org.opencontainers.image.description="Build stage for Confluent Audit Log Forwarder"
LABEL org.opencontainers.image.vendor="Audit Intelligence Team"
LABEL org.opencontainers.image.version="2.1.0"

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy and install Python dependencies with build cache
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# =============================================================================
# Runtime Stage - Minimal production image
# =============================================================================
FROM python:3.11-slim

# Metadata labels (OCI standard)
LABEL org.opencontainers.image.title="Confluent Audit Log Forwarder"
LABEL org.opencontainers.image.description="Intelligent forwarding and routing for Confluent Cloud audit logs"
LABEL org.opencontainers.image.vendor="Audit Intelligence Team"
LABEL org.opencontainers.image.version="2.1.0"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/your-org/audit-forwarder"
LABEL org.opencontainers.image.documentation="https://github.com/your-org/audit-forwarder/blob/main/README.md"

# Install ONLY runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        librdkafka1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && apt-get autoremove -y

# Create non-root user
RUN groupadd -r -g 1000 forwarder && \
    useradd -r -u 1000 -g forwarder -m -s /sbin/nologin forwarder

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=forwarder:forwarder audit_forwarder.py .
COPY --chown=forwarder:forwarder src/ ./src/
COPY --chown=forwarder:forwarder backend/ ./backend/

# Create data directory with proper permissions
RUN mkdir -p /app/data /tmp/forwarder && \
    chown -R forwarder:forwarder /app /tmp/forwarder && \
    chmod -R 755 /app && \
    chmod -R 700 /app/data

# Environment variables for Python optimization
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=2 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Application configuration
# NOTE: Offsets are managed by Kafka consumer groups (not file-based)
ENV METRICS_PORT=8003 \
    LOG_LEVEL=INFO \
    TMPDIR=/tmp/forwarder

# Expose metrics/health port
EXPOSE 8003

# Health check using the /health endpoint
# Check every 30s, timeout after 5s, start checking after 30s, retry 3 times before unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

# Switch to non-root user
USER forwarder

# Command to run
CMD ["python", "-u", "audit_forwarder.py"]
