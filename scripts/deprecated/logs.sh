#!/bin/bash
# Confluent AuditLens - View Logs
# Usage: ./scripts/logs.sh [service]

SERVICE=${1:-audit-forwarder}

echo "Showing logs for $SERVICE (Ctrl+C to exit)..."
echo ""

docker logs -f "$SERVICE" --tail 50
