# syntax=docker/dockerfile:1.4
# MCP Server for Audit Forwarder
# Production-ready containerized deployment with security hardening
# Last updated: 2026-03-10

# =============================================================================
# Build Stage - Install dependencies
# =============================================================================
FROM python:3.11-slim AS builder

LABEL org.opencontainers.image.title="MCP Server Builder"
LABEL org.opencontainers.image.description="Build stage for Audit Forwarder MCP Server"
LABEL org.opencontainers.image.vendor="Audit Intelligence Team"
LABEL org.opencontainers.image.version="1.0.0"

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements from src/mcp directory
COPY src/mcp/requirements.txt .

# Install Python dependencies with build cache
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# =============================================================================
# Runtime Stage - Minimal production image
# =============================================================================
FROM python:3.11-slim

# Metadata labels (OCI standard)
LABEL org.opencontainers.image.title="Audit Forwarder MCP Server"
LABEL org.opencontainers.image.description="Model Context Protocol server for audit log intelligence"
LABEL org.opencontainers.image.vendor="Audit Intelligence Team"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/your-org/audit-forwarder"
LABEL org.opencontainers.image.documentation="https://github.com/your-org/audit-forwarder/blob/main/docs/MCP_SERVER.md"

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
RUN groupadd -r -g 1001 mcp && \
    useradd -r -u 1001 -g mcp -m -s /sbin/nologin mcp

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy MCP server code
COPY --chown=mcp:mcp src/mcp/server.py .
COPY --chown=mcp:mcp src/mcp/__init__.py .

# Copy shared modules from src directory
COPY --chown=mcp:mcp src/config/ ./config/
COPY --chown=mcp:mcp src/classification/ ./classification/
COPY --chown=mcp:mcp src/routing/ ./routing/
COPY --chown=mcp:mcp src/anomaly/ ./anomaly/
COPY --chown=mcp:mcp src/metrics/ ./metrics/
COPY --chown=mcp:mcp src/sinks/ ./sinks/
COPY --chown=mcp:mcp src/identity/ ./identity/
COPY --chown=mcp:mcp src/confluent_api/ ./confluent_api/

# Create cache and temp directories with proper permissions
RUN mkdir -p /app/cache /tmp/mcp && \
    chown -R mcp:mcp /app /tmp/mcp && \
    chmod -R 755 /app && \
    chmod -R 700 /app/cache

# Environment variables for Python optimization
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=2 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Application configuration
ENV MCP_PORT=8080 \
    MCP_HOST=0.0.0.0 \
    LOG_LEVEL=INFO \
    TMPDIR=/tmp/mcp

# Expose MCP API port
EXPOSE 8080

# Health check using HTTP endpoint
# Check every 30s, timeout after 5s, start checking after 15s, retry 3 times before unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Switch to non-root user
USER mcp

# Command to run
CMD ["python", "-u", "server.py"]
