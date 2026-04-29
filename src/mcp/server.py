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
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import orjson
import pandas as pd
from confluent_kafka import Consumer, KafkaError, TopicPartition
from cachetools import TTLCache

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
        version: str = "3.0.0",
    ):
        self.name = name
        self.version = version
        self._export_jobs = {}

        # Kafka configuration from environment
        self.kafka_bootstrap = os.getenv('DEST_BOOTSTRAP')
        self.kafka_api_key = os.getenv('DEST_API_KEY')
        self.kafka_api_secret = os.getenv('DEST_API_SECRET')
        self.topic_critical = os.getenv('AUDIT_TOPIC_CRITICAL', 'audit_events_critical')
        self.topic_high = os.getenv('AUDIT_TOPIC_HIGH', 'audit_events_high')
        self.topic_medium = os.getenv('AUDIT_TOPIC_MEDIUM', 'audit_events_medium')
        self.topic_alerts = os.getenv('AUDIT_TOPIC_ALERTS', 'audit_events_alerts')

        # Thread-safe cache with 15-second TTL (same as dashboard)
        self._cache_lock = threading.Lock()
        self._events_cache = TTLCache(maxsize=10, ttl=15)
        self._alerts_cache = TTLCache(maxsize=5, ttl=15)

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
        # Determine which topics to query based on filters
        topics = [self.topic_critical, self.topic_high, self.topic_medium]

        # Calculate time window
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        time_minutes = 60  # Default to last hour

        if start_time and end_time:
            try:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                time_minutes = int((end - start).total_seconds() / 60)
            except:
                pass

        # Load events from Kafka (uses cache)
        limit = args.get("limit", 100)
        events = await asyncio.get_event_loop().run_in_executor(
            None, self._load_events_from_kafka, topics, limit, time_minutes
        )

        # Apply filters
        filtered_events = events
        if args.get("principal"):
            principal_filter = args["principal"].lower()
            filtered_events = [e for e in filtered_events if principal_filter in str(e.get("principal", "")).lower()]

        if args.get("granted") is not None:
            granted_filter = args["granted"]
            filtered_events = [e for e in filtered_events if e.get("granted") == granted_filter]

        if args.get("cluster_id"):
            cluster_filter = args["cluster_id"]
            filtered_events = [e for e in filtered_events if cluster_filter in str(e.get("cluster_id", ""))]

        if args.get("service"):
            service_filter = args["service"].lower()
            filtered_events = [e for e in filtered_events if service_filter in str(e.get("serviceName", "")).lower()]

        # Apply offset and limit
        offset = args.get("offset", 0)
        filtered_events = filtered_events[offset:offset + limit]

        return {
            "events": filtered_events,
            "total_count": len(filtered_events),
            "has_more": len(events) > offset + limit,
            "filters_applied": {
                "start_time": args.get("start_time"),
                "end_time": args.get("end_time"),
                "event_type": args.get("event_type"),
                "service": args.get("service"),
                "principal": args.get("principal"),
                "granted": args.get("granted"),
                "cluster_id": args.get("cluster_id"),
            },
        }

    async def _handle_search_audit_events(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle search_audit_events tool call."""
        query = args.get("query", "").lower()
        fields = args.get("fields", [])

        # Calculate time window
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        time_minutes = 60

        if start_time and end_time:
            try:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                time_minutes = int((end - start).total_seconds() / 60)
            except:
                pass

        # Load events from Kafka
        topics = [self.topic_critical, self.topic_high, self.topic_medium]
        limit = args.get("limit", 50)
        events = await asyncio.get_event_loop().run_in_executor(
            None, self._load_events_from_kafka, topics, limit * 2, time_minutes
        )

        # Search across specified fields or all text fields
        search_fields = fields if fields else [
            "principal", "methodName", "resourceName", "serviceName",
            "cluster_id", "environment_id", "client_id", "clientIp"
        ]

        matches = []
        for event in events:
            for field in search_fields:
                field_value = str(event.get(field, "")).lower()
                if query in field_value:
                    matches.append(event)
                    break  # Don't add same event multiple times

        matches = matches[:limit]

        return {
            "events": matches,
            "query": query,
            "fields_searched": search_fields,
            "total_matches": len(matches),
        }

    async def _handle_get_security_events(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_security_events tool call."""
        # Calculate time window
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        time_minutes = 60

        if start_time and end_time:
            try:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                time_minutes = int((end - start).total_seconds() / 60)
            except:
                pass

        # Load from CRITICAL and HIGH topics (security-relevant)
        severity = args.get("severity", "all")
        topics = [self.topic_critical, self.topic_high] if severity != "critical" else [self.topic_critical]

        events = await asyncio.get_event_loop().run_in_executor(
            None, self._load_events_from_kafka, topics, 500, time_minutes
        )

        # Filter for security events (auth failures, denials, access transparency)
        security_events = []
        auth_failures = 0
        authz_denials = 0
        access_transparency_events = 0
        principals = set()

        for event in events:
            is_security_event = False

            # Authentication failures
            method_name = event.get("methodName", "")
            if "Authentication" in method_name and event.get("granted") == False:
                auth_failures += 1
                is_security_event = True

            # Authorization denials
            if event.get("granted") == False and "Authorize" in method_name:
                authz_denials += 1
                is_security_event = True

            # Access transparency
            event_type = event.get("type", "")
            if "access-transparency" in event_type:
                access_transparency_events += 1
                is_security_event = True

            if is_security_event:
                security_events.append(event)
                principal = event.get("principal")
                if principal:
                    principals.add(principal)

        # Filter out access transparency if not requested
        if not args.get("include_access_transparency", True):
            security_events = [e for e in security_events if "access-transparency" not in e.get("type", "")]

        return {
            "events": security_events,
            "summary": {
                "total_failures": len(security_events),
                "auth_failures": auth_failures,
                "authz_denials": authz_denials,
                "access_transparency_events": access_transparency_events,
                "unique_principals": len(principals),
            },
            "time_range": {
                "start": start_time,
                "end": end_time,
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
        # Calculate time window
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        time_minutes = 60

        if start_time and end_time:
            try:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                time_minutes = int((end - start).total_seconds() / 60)
            except:
                pass

        # Load security alerts
        alerts = await asyncio.get_event_loop().run_in_executor(
            None, self._load_alerts_from_kafka, 500, time_minutes
        )

        # Also load recent auth failure events
        topics = [self.topic_critical, self.topic_high]
        events = await asyncio.get_event_loop().run_in_executor(
            None, self._load_events_from_kafka, topics, 500, time_minutes
        )

        # Filter for auth/authz failures
        failures = [e for e in events if e.get("granted") == False]

        # Group by specified dimension
        group_by = args.get("group_by", "principal")
        min_failures = args.get("min_failures", 1)

        grouped = {}
        for event in failures:
            key = event.get(group_by, "Unknown")
            if key not in grouped:
                grouped[key] = {
                    "group_key": key,
                    "count": 0,
                    "events": [],
                }
            grouped[key]["count"] += 1
            grouped[key]["events"].append(event)

        # Filter by minimum failures and sort
        by_group = [v for v in grouped.values() if v["count"] >= min_failures]
        by_group.sort(key=lambda x: x["count"], reverse=True)

        # Identify anomalies (groups with unusually high failure rates)
        anomalies = []
        avg_failures = sum(g["count"] for g in by_group) / max(len(by_group), 1)
        for group in by_group:
            if group["count"] > avg_failures * 2:  # More than 2x average
                anomalies.append({
                    "group": group["group_key"],
                    "count": group["count"],
                    "severity": "high" if group["count"] > avg_failures * 3 else "medium",
                })

        # Generate recommendations
        recommendations = []
        if len(by_group) > 10:
            recommendations.append("High number of failing principals - review ACL configuration")
        if anomalies:
            recommendations.append(f"{len(anomalies)} principals showing anomalous failure patterns - investigate for potential security issues")

        return {
            "summary": {
                "total_failures": len(failures),
                "unique_principals": len(set(e.get("principal") for e in failures)),
                "time_range": {
                    "start": start_time,
                    "end": end_time,
                },
            },
            "by_group": by_group[:20],  # Top 20
            "anomalies": anomalies,
            "recommendations": recommendations,
        }

    async def _handle_get_access_transparency(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_access_transparency tool call."""
        # Calculate time window
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        time_minutes = 60

        if start_time and end_time:
            try:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                time_minutes = int((end - start).total_seconds() / 60)
            except:
                pass

        # Load from all topics
        topics = [self.topic_critical, self.topic_high, self.topic_medium]
        events = await asyncio.get_event_loop().run_in_executor(
            None, self._load_events_from_kafka, topics, 500, time_minutes
        )

        # Filter for access transparency events
        at_events = [e for e in events if "access-transparency" in e.get("type", "")]

        # Apply resource type filter if specified
        resource_type = args.get("resource_type")
        if resource_type:
            at_events = [e for e in at_events if resource_type in str(e.get("resourceName", ""))]

        # Apply environment filter if specified
        environment_id = args.get("environment_id")
        if environment_id:
            at_events = [e for e in at_events if environment_id in str(e.get("environment_id", ""))]

        # Aggregate by resource type
        by_resource_type = {}
        by_reason = {}
        for event in at_events:
            resource_name = event.get("resourceName", "Unknown")
            # Extract resource type from CRN (e.g., crn://confluent.cloud/kafka=...)
            if "kafka=" in resource_name:
                res_type = "KAFKA_CLUSTER"
            elif "environment=" in resource_name:
                res_type = "ENVIRONMENT"
            elif "organization=" in resource_name:
                res_type = "ORGANIZATION"
            else:
                res_type = "OTHER"

            by_resource_type[res_type] = by_resource_type.get(res_type, 0) + 1

            # Extract reason from event data
            reason = event.get("reason", "Not specified")
            by_reason[reason] = by_reason.get(reason, 0) + 1

        return {
            "events": at_events,
            "summary": {
                "total_accesses": len(at_events),
                "by_resource_type": by_resource_type,
                "by_reason": by_reason,
            },
            "message": "Access transparency events show when Confluent personnel accessed customer resources.",
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

    # Kafka Data Fetching Methods
    def _load_events_from_kafka(
        self,
        topics: List[str],
        max_events: int = 1000,
        time_minutes: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Load events from Kafka topics.
        Returns list of event dictionaries.
        """
        if not self.kafka_bootstrap or not self.kafka_api_key:
            logger.error("Kafka configuration missing")
            return []

        # Create cache key based on topics and time window
        cache_key = f"{','.join(sorted(topics))}:{max_events}:{time_minutes}"

        # Check cache first (thread-safe)
        with self._cache_lock:
            if cache_key in self._events_cache:
                logger.info(f"Cache hit for key: {cache_key}")
                return self._events_cache[cache_key]

        consumer_config = {
            'bootstrap.servers': self.kafka_bootstrap,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanism': 'PLAIN',
            'sasl.username': self.kafka_api_key,
            'sasl.password': self.kafka_api_secret,
            'group.id': 'auditlens-mcp-server',
            'auto.offset.reset': 'latest',
            'enable.auto.commit': False,
            'fetch.max.bytes': 52428800,
            'max.partition.fetch.bytes': 10485760,
            'socket.timeout.ms': 30000,
            'session.timeout.ms': 45000,
        }

        consumer = Consumer(consumer_config)
        events = []

        try:
            all_partitions = []

            for topic in topics:
                try:
                    md = consumer.list_topics(topic, timeout=30)
                    if topic not in md.topics:
                        continue

                    partitions = md.topics[topic].partitions
                    msgs_per_partition = max(50, max_events // (len(topics) * len(partitions)))

                    for p in partitions.keys():
                        tp = TopicPartition(topic, p)
                        try:
                            low, high = consumer.get_watermark_offsets(tp, timeout=10)
                            if high > low:
                                start_offset = max(low, high - msgs_per_partition)
                                tp.offset = start_offset
                                all_partitions.append(tp)
                        except Exception as e:
                            logger.debug(f"Could not get watermarks for {topic} partition {p}: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"Could not access topic {topic}: {e}")
                    continue

            if not all_partitions:
                logger.warning("No partitions assigned")
                return []

            consumer.assign(all_partitions)
            logger.info(f"Assigned {len(all_partitions)} partitions from {len(topics)} topics")

            empty_polls = 0
            max_empty_polls = 10
            poll_timeout = 1.0

            while len(events) < max_events and empty_polls < max_empty_polls:
                msg = consumer.poll(timeout=poll_timeout)
                if msg is None:
                    empty_polls += 1
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        empty_polls += 1
                    continue
                empty_polls = 0
                try:
                    event_data = orjson.loads(msg.value())
                    events.append(event_data)
                except orjson.JSONDecodeError:
                    logger.warning("Failed to decode message")
                    continue

        except Exception as e:
            logger.error(f"Error loading events from Kafka: {e}")
        finally:
            consumer.close()

        # Filter by time if specified
        if time_minutes > 0 and events:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=time_minutes)
            filtered_events = []
            for event in events:
                event_time_str = event.get('time')
                if event_time_str:
                    try:
                        event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
                        if event_time >= cutoff_time:
                            filtered_events.append(event)
                    except:
                        filtered_events.append(event)  # Include if can't parse time
                else:
                    filtered_events.append(event)
            events = filtered_events

        logger.info(f"Loaded {len(events)} events from Kafka")

        # Cache the results (thread-safe)
        with self._cache_lock:
            self._events_cache[cache_key] = events

        return events

    def _load_alerts_from_kafka(
        self,
        max_alerts: int = 500,
        time_minutes: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Load security alerts from the alerts topic.
        Returns list of alert dictionaries.
        """
        if not self.kafka_bootstrap or not self.kafka_api_key:
            logger.error("Kafka configuration missing")
            return []

        # Check cache first (thread-safe)
        cache_key = f"alerts:{max_alerts}:{time_minutes}"
        with self._cache_lock:
            if cache_key in self._alerts_cache:
                logger.info(f"Cache hit for alerts: {cache_key}")
                return self._alerts_cache[cache_key]

        consumer_config = {
            'bootstrap.servers': self.kafka_bootstrap,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanism': 'PLAIN',
            'sasl.username': self.kafka_api_key,
            'sasl.password': self.kafka_api_secret,
            'group.id': 'auditlens-mcp-alerts',
            'auto.offset.reset': 'latest',
            'enable.auto.commit': False,
        }

        consumer = Consumer(consumer_config)
        alerts = []

        try:
            md = consumer.list_topics(self.topic_alerts, timeout=10)
            if self.topic_alerts not in md.topics:
                return []

            partitions = md.topics[self.topic_alerts].partitions
            msgs_per_partition = max(50, max_alerts // max(len(partitions), 1))

            for p in partitions.keys():
                tp = TopicPartition(self.topic_alerts, p)
                low, high = consumer.get_watermark_offsets(tp, timeout=5)

                if high > low:
                    start_offset = max(low, high - msgs_per_partition)
                    tp.offset = start_offset
                    consumer.assign([tp])

                    partition_alerts = 0
                    empty_polls = 0
                    while partition_alerts < msgs_per_partition and empty_polls < 3:
                        msg = consumer.poll(timeout=0.5)
                        if msg is None:
                            empty_polls += 1
                            continue
                        if msg.error():
                            if msg.error().code() == KafkaError._PARTITION_EOF:
                                break
                            continue
                        empty_polls = 0
                        try:
                            alert_data = orjson.loads(msg.value())
                            alerts.append(alert_data)
                            partition_alerts += 1
                        except orjson.JSONDecodeError:
                            continue

                    if len(alerts) >= max_alerts:
                        break

        except Exception as e:
            logger.error(f"Error loading alerts from Kafka: {e}")
        finally:
            consumer.close()

        # Filter by time if specified
        if time_minutes > 0 and alerts:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=time_minutes)
            filtered_alerts = []
            for alert in alerts:
                window_end_str = alert.get('window_end')
                if window_end_str:
                    try:
                        window_end = datetime.fromisoformat(window_end_str.replace('Z', '+00:00'))
                        if window_end >= cutoff_time:
                            filtered_alerts.append(alert)
                    except:
                        filtered_alerts.append(alert)
                else:
                    filtered_alerts.append(alert)
            alerts = filtered_alerts

        logger.info(f"Loaded {len(alerts)} alerts from Kafka")

        # Cache the results (thread-safe)
        with self._cache_lock:
            self._alerts_cache[cache_key] = alerts

        return alerts
