"""
Confluent Audit Log Forwarder v2

A production-grade audit log forwarding system with:
- Multi-sink support (Kafka, S3, GCS)
- MCP server for agentic AI integration
- Enhanced CloudEvents parsing
- Resilience patterns (circuit breaker, DLQ, retry)
"""

from pathlib import Path as _VersionPath
_version_file = _VersionPath(__file__).parent.parent / "VERSION"
__version__ = _version_file.read_text().strip() if _version_file.exists() else "2.1.0"
__author__ = "Audit Forwarder Team"
