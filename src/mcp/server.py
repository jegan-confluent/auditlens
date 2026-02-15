"""
MCP Server for Audit Forwarder.

Provides tools for:
- Querying audit logs
- Exporting to S3/GCS
- Security analysis
- Forwarder status
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditForwarderMCP:
    """
    MCP Server implementation for audit log management.

    Exposes tools for AI agents to:
    - Query and search audit logs
    - Export logs to cloud storage
    - Analyze security events
    - Monitor forwarder health
    """

    def __init__(
        self,
        name: str = "audit-forwarder",
        version: str = "2.0.0",
    ):
        self.name = name
        self.version = version
        self._query_cache = {}
        self._export_jobs = {}

        # Tool definitions
        self.tools = self._define_tools()
        self.resources = self._define_resources()

    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define MCP tools."""
        return [
            {
                "name": "list_audit_events",
                "description": "Retrieve audit log events with pagination and filtering",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Start of time window (ISO8601)",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                            "description": "End of time window (ISO8601)",
                        },
                        "event_type": {
                            "type": "string",
                            "enum": ["authentication", "authorization", "request", "access-transparency"],
                            "description": "Filter by event category",
                        },
                        "service": {
                            "type": "string",
                            "enum": ["kafka", "schema-registry", "ksqldb", "flink", "organization"],
                            "description": "Filter by service",
                        },
                        "principal": {
                            "type": "string",
                            "description": "Filter by principal (User:ID or service account)",
                        },
                        "granted": {
                            "type": "boolean",
                            "description": "Filter by authorization result",
                        },
                        "cluster_id": {
                            "type": "string",
                            "description": "Filter by Kafka cluster ID",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 100,
                            "maximum": 1000,
                            "description": "Maximum records to return",
                        },
                        "offset": {
                            "type": "integer",
                            "default": 0,
                            "description": "Pagination offset",
                        },
                    },
                },
            },
            {
                "name": "search_audit_events",
                "description": "Full-text search across audit log fields",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Fields to search (default: all text fields)",
                        },
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_security_events",
                "description": "Retrieve security-relevant events (auth failures, denied access, access transparency)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["all", "high", "critical"],
                            "default": "all",
                        },
                        "include_access_transparency": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include Confluent personnel access events",
                        },
                    },
                },
            },
            {
                "name": "export_to_s3",
                "description": "Export audit logs to Amazon S3",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "bucket": {
                            "type": "string",
                            "description": "S3 bucket name",
                        },
                        "prefix": {
                            "type": "string",
                            "default": "confluent-audit-logs/",
                            "description": "Object key prefix",
                        },
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Export window start",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Export window end",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["parquet", "json", "csv"],
                            "default": "parquet",
                        },
                        "compression": {
                            "type": "string",
                            "enum": ["snappy", "gzip", "none"],
                            "default": "snappy",
                        },
                        "partition_by": {
                            "type": "string",
                            "enum": ["hour", "day", "event_type", "service"],
                            "default": "hour",
                        },
                    },
                    "required": ["bucket", "start_time", "end_time"],
                },
            },
            {
                "name": "export_to_gcs",
                "description": "Export audit logs to Google Cloud Storage",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "bucket": {
                            "type": "string",
                            "description": "GCS bucket name",
                        },
                        "prefix": {
                            "type": "string",
                            "default": "confluent-audit-logs/",
                        },
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["parquet", "json", "csv"],
                            "default": "parquet",
                        },
                        "compression": {
                            "type": "string",
                            "enum": ["snappy", "gzip", "none"],
                            "default": "snappy",
                        },
                        "project_id": {
                            "type": "string",
                            "description": "GCP project ID",
                        },
                    },
                    "required": ["bucket", "start_time", "end_time"],
                },
            },
            {
                "name": "analyze_auth_failures",
                "description": "Analyze authentication and authorization failures",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["principal", "cluster", "client_ip", "api_key", "hour"],
                            "default": "principal",
                        },
                        "min_failures": {
                            "type": "integer",
                            "default": 1,
                            "description": "Minimum failure count to include",
                        },
                    },
                },
            },
            {
                "name": "get_access_transparency",
                "description": "Retrieve Access Transparency events (Confluent personnel access)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "resource_type": {
                            "type": "string",
                            "enum": ["KAFKA_CLUSTER", "ENVIRONMENT", "ORGANIZATION"],
                        },
                        "environment_id": {
                            "type": "string",
                        },
                    },
                },
            },
            {
                "name": "get_forwarder_status",
                "description": "Get current status and metrics of the audit forwarder",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_export_job_status",
                "description": "Get status of an export job",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Export job ID",
                        },
                    },
                    "required": ["job_id"],
                },
            },
        ]

    def _define_resources(self) -> List[Dict[str, Any]]:
        """Define MCP resources."""
        return [
            {
                "uri": "audit://schema/v1",
                "name": "audit_event_schema",
                "description": "JSON Schema for audit log events",
                "mimeType": "application/schema+json",
            },
            {
                "uri": "audit://categories",
                "name": "event_categories",
                "description": "List of all audit event types and categories",
                "mimeType": "application/json",
            },
            {
                "uri": "audit://methods",
                "name": "method_names",
                "description": "List of all method names by service",
                "mimeType": "application/json",
            },
            {
                "uri": "metrics://forwarder",
                "name": "forwarder_metrics",
                "description": "Current forwarder metrics",
                "mimeType": "application/json",
            },
        ]

    def get_server_info(self) -> Dict[str, Any]:
        """Get MCP server information."""
        return {
            "name": self.name,
            "version": self.version,
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": True},
            },
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools."""
        return self.tools

    def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources."""
        return self.resources

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call."""
        tool_handlers = {
            "list_audit_events": self._handle_list_audit_events,
            "search_audit_events": self._handle_search_audit_events,
            "get_security_events": self._handle_get_security_events,
            "export_to_s3": self._handle_export_to_s3,
            "export_to_gcs": self._handle_export_to_gcs,
            "analyze_auth_failures": self._handle_analyze_auth_failures,
            "get_access_transparency": self._handle_get_access_transparency,
            "get_forwarder_status": self._handle_get_forwarder_status,
            "get_export_job_status": self._handle_get_export_job_status,
        }

        handler = tool_handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}

        try:
            result = await handler(arguments)
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"error": str(e)}

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource."""
        resource_handlers = {
            "audit://schema/v1": self._get_audit_schema,
            "audit://categories": self._get_event_categories,
            "audit://methods": self._get_method_names,
            "metrics://forwarder": self._get_forwarder_metrics,
        }

        handler = resource_handlers.get(uri)
        if not handler:
            return {"error": f"Unknown resource: {uri}"}

        try:
            content = await handler()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(content, indent=2),
                    }
                ]
            }
        except Exception as e:
            return {"error": str(e)}

    # Tool handlers
    async def _handle_list_audit_events(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle list_audit_events tool call."""
        # This would query from the cache/database
        # For now, return a placeholder structure
        return {
            "events": [],
            "total_count": 0,
            "has_more": False,
            "filters_applied": {
                "start_time": args.get("start_time"),
                "end_time": args.get("end_time"),
                "event_type": args.get("event_type"),
                "service": args.get("service"),
                "principal": args.get("principal"),
            },
            "message": "Query cache not yet initialized. Events will be available after forwarder processes data.",
        }

    async def _handle_search_audit_events(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle search_audit_events tool call."""
        return {
            "events": [],
            "query": args.get("query"),
            "fields_searched": args.get("fields", ["all"]),
            "total_matches": 0,
            "message": "Search functionality requires query cache to be populated.",
        }

    async def _handle_get_security_events(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_security_events tool call."""
        return {
            "events": [],
            "summary": {
                "total_failures": 0,
                "auth_failures": 0,
                "authz_denials": 0,
                "access_transparency_events": 0,
                "unique_principals": 0,
            },
            "time_range": {
                "start": args.get("start_time"),
                "end": args.get("end_time"),
            },
        }

    async def _handle_export_to_s3(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle export_to_s3 tool call."""
        import uuid

        job_id = str(uuid.uuid4())[:8]

        # Store job info
        self._export_jobs[job_id] = {
            "id": job_id,
            "type": "s3",
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "config": args,
        }

        return {
            "job_id": job_id,
            "status": "pending",
            "message": f"Export job created. Use get_export_job_status to check progress.",
            "destination": f"s3://{args['bucket']}/{args.get('prefix', '')}",
        }

    async def _handle_export_to_gcs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle export_to_gcs tool call."""
        import uuid

        job_id = str(uuid.uuid4())[:8]

        self._export_jobs[job_id] = {
            "id": job_id,
            "type": "gcs",
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "config": args,
        }

        return {
            "job_id": job_id,
            "status": "pending",
            "message": f"Export job created. Use get_export_job_status to check progress.",
            "destination": f"gs://{args['bucket']}/{args.get('prefix', '')}",
        }

    async def _handle_analyze_auth_failures(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle analyze_auth_failures tool call."""
        return {
            "summary": {
                "total_failures": 0,
                "unique_principals": 0,
                "time_range": {
                    "start": args.get("start_time"),
                    "end": args.get("end_time"),
                },
            },
            "by_group": [],
            "anomalies": [],
            "recommendations": [],
        }

    async def _handle_get_access_transparency(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_access_transparency tool call."""
        return {
            "events": [],
            "summary": {
                "total_accesses": 0,
                "by_resource_type": {},
                "by_reason": {},
            },
            "message": "Access transparency events are captured when Confluent personnel access customer resources.",
        }

    async def _handle_get_forwarder_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_forwarder_status tool call."""
        return {
            "status": "healthy",
            "uptime_seconds": 0,
            "version": self.version,
            "metrics": {
                "processed_total": 0,
                "processing_rate": 0.0,
                "error_count": 0,
                "consumer_lag": {},
            },
            "sinks": {
                "kafka": {"status": "unknown", "last_write": None},
                "s3": {"status": "unknown", "last_write": None},
                "gcs": {"status": "unknown", "last_write": None},
            },
        }

    async def _handle_get_export_job_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_export_job_status tool call."""
        job_id = args.get("job_id")

        if job_id not in self._export_jobs:
            return {"error": f"Job {job_id} not found"}

        return self._export_jobs[job_id]

    # Resource handlers
    async def _get_audit_schema(self) -> Dict[str, Any]:
        """Get audit event schema."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Confluent Audit Log Event",
            "type": "object",
            "required": ["id", "specversion", "source", "type"],
            "properties": {
                "id": {"type": "string", "description": "Unique event identifier"},
                "specversion": {"type": "string", "const": "1.0"},
                "source": {"type": "string", "format": "uri", "description": "Event source CRN"},
                "subject": {"type": "string", "description": "Affected resource CRN"},
                "type": {"type": "string", "description": "Event type"},
                "time": {"type": "string", "format": "date-time"},
                "data": {"type": "object", "description": "Event payload"},
            },
        }

    async def _get_event_categories(self) -> Dict[str, Any]:
        """Get event categories."""
        return {
            "categories": {
                "authentication": {
                    "description": "User/service account authentication attempts",
                    "types": [
                        "io.confluent.kafka.server/authentication",
                        "io.confluent.sg.server/authentication",
                        "io.confluent.ksql.server/authentication",
                        "io.confluent.flink.server/authentication",
                    ],
                },
                "authorization": {
                    "description": "Permission checks for operations",
                    "types": [
                        "io.confluent.kafka.server/authorization",
                        "io.confluent.sg.server/authorization",
                        "io.confluent.ksql.server/authorization",
                        "io.confluent.flink.server/authorization",
                        "io.confluent.cloud/authorization",
                    ],
                },
                "request": {
                    "description": "Administrative and management operations",
                    "types": [
                        "io.confluent.kafka.server/request",
                        "io.confluent.sg.server/request",
                        "io.confluent.cloud/request",
                    ],
                },
                "access-transparency": {
                    "description": "Confluent personnel access to customer resources",
                    "types": ["io.confluent.cloud/access-transparency"],
                },
            },
        }

    async def _get_method_names(self) -> Dict[str, Any]:
        """Get method names by service."""
        return {
            "kafka": [
                "kafka.Authentication",
                "kafka.Produce",
                "kafka.Fetch",
                "kafka.CreateTopics",
                "kafka.DeleteTopics",
                "kafka.DescribeConfigs",
                "kafka.AlterConfigs",
                "kafka.CreateAcls",
                "kafka.DeleteAcls",
                "kafka.DescribeAcls",
            ],
            "schema-registry": [
                "GetSchemas",
                "GetSubjects",
                "RegisterSchema",
                "DeleteSubject",
                "GetCompatibility",
                "UpdateCompatibility",
            ],
            "ksqldb": [
                "ExecuteStatement",
                "RunQuery",
                "TerminateQuery",
                "DescribeStreams",
            ],
            "flink": [
                "CreateStatement",
                "GetStatement",
                "DeleteStatement",
                "GetComputePool",
            ],
            "organization": [
                "CreateServiceAccount",
                "DeleteServiceAccount",
                "CreateApiKey",
                "DeleteApiKey",
                "CreateRoleBinding",
                "DeleteRoleBinding",
                "CreateEnvironment",
                "DeleteEnvironment",
            ],
        }

    async def _get_forwarder_metrics(self) -> Dict[str, Any]:
        """Get forwarder metrics."""
        return {
            "uptime_seconds": 0,
            "processed_messages_total": 0,
            "processing_rate_per_second": 0.0,
            "error_count_total": 0,
            "consumer_lag_total": 0,
            "sinks": {},
        }
