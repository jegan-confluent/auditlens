#!/usr/bin/env python3
"""
Confluent Audit Log Schema Watcher

Monitors Confluent documentation for audit log schema changes, detects new event types,
methods, and fields, and automatically updates classification rules.

Features:
- Scrapes Confluent audit log documentation
- Detects schema changes (new event types, methods, fields)
- Classifies new methods using heuristics (Delete=CRITICAL, Create=MEDIUM, etc.)
- Updates src/classification/methods.py with new methods
- Sends Slack alerts on changes
- Tracks version history in schema_versions.json
"""

import asyncio
import hashlib
import hmac
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import httpx
import orjson
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConfluentSchemaWatcher:
    """Monitors Confluent audit log schema for changes."""

    # Confluent audit log documentation URLs
    AUDIT_LOG_DOCS_URL = "https://docs.confluent.io/cloud/current/monitoring/audit-logging/audit-log-events.html"
    CLOUDEVENTS_SPEC_URL = "https://github.com/cloudevents/spec/blob/v1.0/spec.md"

    def __init__(
        self,
        data_file: Path,
        versions_file: Path,
        slack_webhook_url: Optional[str] = None,
        dry_run: bool = False
    ):
        """
        Initialize the schema watcher.

        Args:
            data_file: Path to schema_methods.json (the data file methods.py
                reads at startup). The watcher MUST NOT write to any .py
                source file at runtime — that is a code-injection vector if
                the upstream Schema Registry / docs page is ever compromised.
            versions_file: Path to schema_versions.json
            slack_webhook_url: Slack webhook URL for alerts
            dry_run: If True, don't update files or send alerts
        """
        # Defence-in-depth: refuse to operate on a .py path even if the
        # caller wires one up by mistake.
        if data_file.suffix == ".py":
            raise ValueError(
                f"schema-watcher data_file must not be a Python source file: {data_file}. "
                "Use schema_methods.json instead."
            )
        self.data_file = data_file
        self.versions_file = versions_file
        self.slack_webhook_url = slack_webhook_url
        self.dry_run = dry_run
        self.http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.http_client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def fetch_confluent_schema(self) -> Dict:
        """
        Fetch Confluent audit log schema from documentation.

        Returns:
            Dict containing event_types, methods, and fields
        """
        logger.info(f"Fetching Confluent audit log documentation from {self.AUDIT_LOG_DOCS_URL}")

        try:
            response = await self.http_client.get(self.AUDIT_LOG_DOCS_URL)
            response.raise_for_status()
            html_content = response.text

            soup = BeautifulSoup(html_content, 'lxml')

            # Extract schema information from documentation
            schema = {
                'event_types': self._extract_event_types(soup),
                'methods': self._extract_methods(soup),
                'fields': self._extract_fields(soup),
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'source_url': self.AUDIT_LOG_DOCS_URL,
                'checksum': hashlib.sha256(html_content.encode('utf-8')).hexdigest()
            }

            logger.info(f"Extracted {len(schema['methods'])} methods, "
                       f"{len(schema['event_types'])} event types, "
                       f"{len(schema['fields'])} fields")

            return schema

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching schema: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching schema: {e}")
            raise

    def _extract_event_types(self, soup: BeautifulSoup) -> Set[str]:
        """Extract event types from documentation."""
        event_types = set()

        # Look for event type patterns in documentation
        # CloudEvents 1.0 uses "type" field like "io.confluent.kafka.cluster.created"
        type_pattern = re.compile(r'io\.confluent\.[a-z0-9.-]+')

        for text in soup.stripped_strings:
            matches = type_pattern.findall(text)
            event_types.update(matches)

        # Also look for explicit event type sections
        for heading in soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().lower()
            if 'event type' in heading_text or 'event format' in heading_text:
                next_elem = heading.find_next_sibling()
                if next_elem:
                    text = next_elem.get_text()
                    matches = type_pattern.findall(text)
                    event_types.update(matches)

        return event_types

    def _extract_methods(self, soup: BeautifulSoup) -> Set[str]:
        """Extract method names from documentation."""
        methods = set()

        # Look for method patterns in code blocks, tables, and text
        # Method patterns: CamelCase or dot.notation
        method_pattern = re.compile(r'\b([A-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+|[a-z]+\.[A-Z][a-zA-Z0-9]*)\b')

        # Check code blocks
        for code_block in soup.find_all(['code', 'pre']):
            text = code_block.get_text()
            matches = method_pattern.findall(text)
            methods.update(matches)

        # Check tables (often list methods)
        for table in soup.find_all('table'):
            for cell in table.find_all(['td', 'th']):
                text = cell.get_text()
                matches = method_pattern.findall(text)
                methods.update(matches)

        # Filter out false positives (common words, type names, etc.)
        filtered_methods = self._filter_methods(methods)

        return filtered_methods

    def _filter_methods(self, methods: Set[str]) -> Set[str]:
        """Filter out false positive method names."""
        # Common false positives
        blacklist = {
            'CloudEvents', 'IoConfluent', 'KafkaCluster', 'ServiceAccount',
            'ApiKey', 'RoleBinding', 'PrivateLink', 'TransitGateway',
            'Boolean', 'String', 'Integer', 'Object', 'Array', 'Null',
            'True', 'False', 'None', 'Json', 'Yaml', 'Http', 'Https',
            'Utf', 'Aws', 'Gcp', 'Azure', 'VpcPeering'
        }

        # Must contain a verb or be namespaced (e.g., kafka.DeleteTopics)
        verb_keywords = {
            'Create', 'Delete', 'Update', 'Get', 'List', 'Describe',
            'Alter', 'Pause', 'Resume', 'Suspend', 'Restart', 'Rotate',
            'Revoke', 'Grant', 'Bind', 'Unbind', 'Encrypt', 'Decrypt',
            'Activate', 'Deactivate', 'Refresh', 'Reset', 'Restore',
            'Patch', 'Authenticate', 'Authorize', 'Produce', 'Fetch',
            'Join', 'Leave', 'Sync', 'Heartbeat', 'Offset', 'Commit',
            'Metadata'
        }

        filtered = set()
        for method in methods:
            # Skip blacklisted
            if method in blacklist:
                continue

            # Keep if namespaced (contains dot)
            if '.' in method:
                filtered.add(method)
                continue

            # Keep if contains a verb
            if any(verb in method for verb in verb_keywords):
                filtered.add(method)

        return filtered

    def _extract_fields(self, soup: BeautifulSoup) -> Set[str]:
        """Extract field names from schema documentation."""
        fields = set()

        # CloudEvents standard fields
        cloudevents_fields = {
            'id', 'source', 'specversion', 'type', 'datacontenttype',
            'dataschema', 'subject', 'time'
        }
        fields.update(cloudevents_fields)

        # Confluent-specific fields in data payload
        # Look for field references in documentation
        field_pattern = re.compile(r'`([a-z_][a-z0-9_]*)`')

        for code in soup.find_all(['code', 'pre']):
            text = code.get_text()
            matches = field_pattern.findall(text)
            fields.update(matches)

        return fields

    def compare_schemas(self, old_schema: Dict, new_schema: Dict) -> Dict:
        """
        Compare old and new schemas to detect changes.

        Args:
            old_schema: Previously recorded schema
            new_schema: Newly fetched schema

        Returns:
            Dict with added/removed items
        """
        changes = {
            'has_changes': False,
            'event_types': {
                'added': [],
                'removed': []
            },
            'methods': {
                'added': [],
                'removed': []
            },
            'fields': {
                'added': [],
                'removed': []
            }
        }

        # Compare event types
        old_event_types = set(old_schema.get('event_types', []))
        new_event_types = set(new_schema.get('event_types', []))
        changes['event_types']['added'] = sorted(new_event_types - old_event_types)
        changes['event_types']['removed'] = sorted(old_event_types - new_event_types)

        # Compare methods
        old_methods = set(old_schema.get('methods', []))
        new_methods = set(new_schema.get('methods', []))
        changes['methods']['added'] = sorted(new_methods - old_methods)
        changes['methods']['removed'] = sorted(old_methods - new_methods)

        # Compare fields
        old_fields = set(old_schema.get('fields', []))
        new_fields = set(new_schema.get('fields', []))
        changes['fields']['added'] = sorted(new_fields - old_fields)
        changes['fields']['removed'] = sorted(old_fields - new_fields)

        # Determine if there are any changes
        changes['has_changes'] = (
            len(changes['event_types']['added']) > 0 or
            len(changes['event_types']['removed']) > 0 or
            len(changes['methods']['added']) > 0 or
            len(changes['methods']['removed']) > 0 or
            len(changes['fields']['added']) > 0 or
            len(changes['fields']['removed']) > 0
        )

        return changes

    def classify_new_methods(self, methods: List[str]) -> Dict[str, List[str]]:
        """
        Classify new methods into criticality levels using heuristics.

        Heuristics:
        - Delete/Remove/Purge → CRITICAL
        - CreateAcls/DeleteAcls → CRITICAL
        - Create*ApiKey/Delete*ApiKey → HIGH
        - Create*ServiceAccount → HIGH
        - *RoleBinding → HIGH
        - Update*Audit* → CRITICAL
        - Create/Update (other) → MEDIUM
        - Get/List/Describe → LOW (READ_ONLY)

        Args:
            methods: List of new method names

        Returns:
            Dict mapping criticality level to list of methods
        """
        classification = {
            'CRITICAL': [],
            'HIGH': [],
            'MEDIUM': [],
            'LOW': []
        }

        for method in methods:
            method_upper = method.upper()
            method_lower = method.lower()
            method_upper_nopunct = method_upper.replace('_', '').replace('-', '').replace('.', '')

            # Specific HIGH-entity checks come FIRST so that Delete-prefixed entity
            # methods (DeleteApiKey, DeleteRoleBinding, DeleteUser …) land in HIGH,
            # not in the generic CRITICAL deletion bucket below.

            # HIGH: API Key operations (DeleteApiKey / CreateApiKey / UpdateApiKey …)
            if 'APIKEY' in method_upper_nopunct or 'API_KEY' in method_upper:
                classification['HIGH'].append(method)
                continue

            # HIGH/CRITICAL: Service Account operations
            if 'SERVICEACCOUNT' in method_upper_nopunct or 'SERVICE_ACCOUNT' in method_upper:
                if 'DELETE' in method_upper:
                    classification['CRITICAL'].append(method)  # DeleteServiceAccount is irreversible
                else:
                    classification['HIGH'].append(method)
                continue

            # HIGH: Role Binding operations (DeleteRoleBinding → HIGH, not CRITICAL)
            if 'ROLEBINDING' in method_upper_nopunct or 'ROLE_BINDING' in method_upper:
                classification['HIGH'].append(method)
                continue

            # HIGH: User / Invitation management (DeleteUser → HIGH)
            if any(kw in method_upper_nopunct for kw in ['DELETEUSER', 'CREATEUSER', 'UPDATEUSER',
                                                          'DELETEINVITATION', 'CREATEINVITATION', 'INVITEUSER']):
                classification['HIGH'].append(method)
                continue

            # HIGH/CRITICAL: Identity operations
            if any(kw in method_upper for kw in ['IDENTITYPROVIDER', 'IDENTITYPOOL',
                                                  'IDENTITY_PROVIDER', 'IDENTITY_POOL']):
                if 'DELETE' in method_upper:
                    classification['CRITICAL'].append(method)
                else:
                    classification['HIGH'].append(method)
                continue

            # HIGH: Private Link Attachment / Connection — sub-resources, not top-level.
            # Top-level PrivateLinkAccess deletion falls through to CRITICAL below.
            if any(kw in method_upper for kw in ['PRIVATELINKATTACHMENT', 'PRIVATELINKATTACHMENTCONNECTION']):
                classification['HIGH'].append(method)
                continue

            # HIGH/CRITICAL: Other network constructs (Peering, TransitGateway, NetworkLink,
            # top-level PrivateLinkAccess).
            if any(kw in method_upper for kw in ['PRIVATELINK', 'PEERING', 'TRANSITGATEWAY', 'NETWORKLINK']):
                if 'DELETE' in method_upper:
                    classification['CRITICAL'].append(method)
                else:
                    classification['HIGH'].append(method)
                continue

            # HIGH: Cluster Link operations (DeleteClusterLink / kafka.DeleteClusterLinks → HIGH)
            if any(kw in method_upper_nopunct for kw in ['CLUSTERLINK', 'CLUSTERLINKS', 'MIRRORTOPIC']):
                classification['HIGH'].append(method)
                continue

            # HIGH: BYOK/Encryption
            if any(kw in method_upper for kw in ['BYOK', 'ENCRYPT', 'DECRYPT']):
                classification['HIGH'].append(method)
                continue

            # HIGH: ACL operations (kafka.CreateAcls / kafka.DeleteAcls).
            # Use 'ACLS' (plural) — 'ACL' alone is a substring of 'KAFKACLUSTER'
            # which would incorrectly match DeleteKafkaCluster.
            if 'ACLS' in method_upper and any(kw in method_upper for kw in ['CREATE', 'DELETE']):
                classification['HIGH'].append(method)
                continue

            # HIGH: Consumer group management — kafka.DeleteGroups is deliberate
            # HIGH (not CRITICAL), analogous to kafka.AlterConfigs promotion.
            if 'DELETEGROUPS' in method_upper_nopunct:
                classification['HIGH'].append(method)
                continue

            # HIGH: Schema Registry subject/version deletions — soft-delete, not CRITICAL.
            if any(kw in method_upper_nopunct for kw in ['DELETESUBJECT', 'DELETESCHEMAVERSION']):
                classification['HIGH'].append(method)
                continue

            # HIGH: IP filtering / DNS / Integrations / SSO group mappings / alerts —
            # individually scoped, not cluster-level blast radius.
            if any(kw in method_upper_nopunct for kw in [
                'IPFILTER', 'IPGROUP', 'DNSFORWARDER', 'INTEGRATION',
                'SSOGROUPMAPPING', 'GROUPMAPPING',
            ]):
                classification['HIGH'].append(method)
                continue

            # CRITICAL: Audit log configuration changes
            if 'AUDIT' in method_upper and any(kw in method_upper for kw in ['UPDATE', 'DELETE']):
                classification['CRITICAL'].append(method)
                continue

            # CRITICAL: Pause cluster operations
            if 'PAUSE' in method_upper and 'CLUSTER' in method_upper:
                classification['CRITICAL'].append(method)
                continue

            # CRITICAL: Generic deletions — only reached after all HIGH-entity checks above
            if any(keyword in method_upper for keyword in ['DELETE', 'REMOVE', 'PURGE', 'DROP']):
                # Exception: OffsetDelete is routine consumer group management (MEDIUM)
                if 'OFFSETDELETE' in method_upper_nopunct:
                    classification['MEDIUM'].append(method)
                else:
                    classification['CRITICAL'].append(method)
                continue

            # MEDIUM: Create operations (not covered above)
            if 'CREATE' in method_upper:
                classification['MEDIUM'].append(method)
                continue

            # MEDIUM: Update/Alter operations
            if any(kw in method_upper for kw in ['UPDATE', 'ALTER', 'MODIFY', 'PATCH']):
                classification['MEDIUM'].append(method)
                continue

            # MEDIUM: Pause/Resume operations
            if any(kw in method_upper for kw in ['PAUSE', 'RESUME', 'SUSPEND', 'RESTART']):
                classification['MEDIUM'].append(method)
                continue

            # LOW: Read operations
            if any(kw in method_upper for kw in ['GET', 'LIST', 'DESCRIBE', 'FETCH', 'READ', 'FIND', 'SHOW']):
                classification['LOW'].append(method)
                continue

            # LOW: Authentication/Authorization (high volume but need to track)
            if any(kw in method_lower for kw in ['authenticate', 'authorize', 'authentication', 'authorization']):
                classification['LOW'].append(method)
                continue

            # LOW: Produce/Consume operations
            if any(kw in method_upper for kw in ['PRODUCE', 'FETCH', 'OFFSET', 'HEARTBEAT', 'METADATA']):
                classification['LOW'].append(method)
                continue

            # Default: MEDIUM (unknown operations should be reviewed)
            logger.warning(f"Method '{method}' did not match any heuristic, defaulting to MEDIUM")
            classification['MEDIUM'].append(method)

        return classification

    def update_methods_data_file(self, new_methods: Dict[str, List[str]]) -> bool:
        """
        Merge newly-detected methods into the schema_methods.json data file.

        ``methods.py`` reads this JSON at startup and unions the entries with
        the hard-coded defaults. Writing data — never source — keeps the
        schema-watcher off the supply-chain compromise path.

        Args:
            new_methods: Dict mapping criticality level to list of methods.

        Returns:
            True if the data file was updated, False otherwise.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would update schema_methods.json with new methods")
            return False

        if not any(new_methods.values()):
            logger.info("No new methods to add")
            return False

        # Belt-and-braces: re-check the destination is not a .py file.
        if self.data_file.suffix == ".py":
            raise ValueError(
                f"refusing to write methods to a .py file: {self.data_file}"
            )

        try:
            existing: Dict = {}
            if self.data_file.exists():
                with open(self.data_file, 'rb') as f:
                    raw = f.read()
                if raw.strip():
                    existing = orjson.loads(raw)

            timestamp = datetime.now(timezone.utc).isoformat()
            buckets = existing.setdefault("methods_by_level", {})
            audit_trail = existing.setdefault("change_log", [])
            additions_summary: Dict[str, List[str]] = {}

            for level in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
                methods = new_methods.get(level, [])
                if not methods:
                    continue
                bucket = set(buckets.get(level, []))
                added_this_run = sorted(set(methods) - bucket)
                bucket.update(methods)
                buckets[level] = sorted(bucket)
                if added_this_run:
                    additions_summary[level] = added_this_run

            existing["last_updated"] = timestamp
            if additions_summary:
                audit_trail.append({"timestamp": timestamp, "added": additions_summary})
                # Keep only the last 100 entries to bound the file size.
                existing["change_log"] = audit_trail[-100:]

            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.data_file.with_suffix(self.data_file.suffix + ".tmp")
            with open(tmp_path, 'wb') as f:
                f.write(orjson.dumps(existing, option=orjson.OPT_INDENT_2))
            os.replace(tmp_path, self.data_file)

            logger.info(
                "Updated %s with %d new methods",
                self.data_file,
                sum(len(m) for m in additions_summary.values()),
            )
            return True

        except Exception as e:
            logger.error(f"Error updating methods data file: {e}")
            raise

    async def send_slack_alert(self, changes: Dict, new_methods_classified: Dict[str, List[str]]) -> None:
        """
        Send Slack alert about schema changes.

        Args:
            changes: Schema changes from compare_schemas()
            new_methods_classified: Classified new methods
        """
        if not self.slack_webhook_url:
            logger.info("No Slack webhook URL configured, skipping alert")
            return

        if self.dry_run:
            logger.info("[DRY RUN] Would send Slack alert")
            return

        try:
            # Build Slack message
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🔔 Confluent Audit Log Schema Change Detected"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Detected at:* {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n*Source:* {self.AUDIT_LOG_DOCS_URL}"
                    }
                }
            ]

            # Add methods changes
            if changes['methods']['added']:
                methods_text = "*New Methods Detected:*\n"
                for level in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
                    methods = new_methods_classified.get(level, [])
                    if methods:
                        emoji = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢'}[level]
                        methods_text += f"\n{emoji} *{level}*:\n"
                        methods_text += "\n".join(f"  • `{m}`" for m in methods)

                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": methods_text
                    }
                })

            # Add event types changes
            if changes['event_types']['added']:
                event_types_text = "*New Event Types:*\n" + "\n".join(f"  • `{e}`" for e in changes['event_types']['added'])
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": event_types_text
                    }
                })

            # Add fields changes
            if changes['fields']['added']:
                fields_text = "*New Fields:*\n" + "\n".join(f"  • `{f}`" for f in changes['fields']['added'])
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": fields_text
                    }
                })

            # Add action recommendation
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Action Required:*\n  • Review new methods in `src/classification/methods.py`\n  • Verify auto-classification is correct\n  • Update dashboard filters if needed\n  • Test forwarder routing with new event types"
                }
            })

            await self._post_slack_blocks(blocks)
            logger.info("Sent Slack alert successfully")

        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=False,
    )
    async def _post_slack_blocks(self, blocks: list) -> None:
        """POST a pre-built Slack blocks payload with tenacity retry."""
        response = await self.http_client.post(
            self.slack_webhook_url,
            json={"blocks": blocks},
        )
        response.raise_for_status()

    def load_version_history(self) -> List[Dict]:
        """Load version history from schema_versions.json."""
        if not self.versions_file.exists():
            return []

        try:
            with open(self.versions_file, 'rb') as f:
                return orjson.loads(f.read())
        except Exception as e:
            logger.error(f"Error loading version history: {e}")
            return []

    def save_version_history(self, schema: Dict, changes: Optional[Dict] = None) -> None:
        """Save schema version to history."""
        if self.dry_run:
            logger.info("[DRY RUN] Would save version history")
            return

        history = self.load_version_history()

        version_entry = {
            'version': len(history) + 1,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checksum': schema['checksum'],
            'source_url': schema['source_url'],
            'event_types_count': len(schema['event_types']),
            'methods_count': len(schema['methods']),
            'fields_count': len(schema['fields']),
        }

        if changes:
            version_entry['changes'] = changes

        # Keep only schema metadata, not full content (to save space)
        history.append(version_entry)

        # Save atomically — a SIGKILL mid-write must not corrupt the file.
        # Corrupted versions.json causes load_version_history() to return []
        # which treats all current methods as "new" → mass CRITICAL escalation.
        try:
            tmp_path = self.versions_file.with_suffix(self.versions_file.suffix + ".tmp")
            with open(tmp_path, 'wb') as f:
                f.write(orjson.dumps(history, option=orjson.OPT_INDENT_2))
            os.replace(tmp_path, self.versions_file)
            logger.info(f"Saved version {version_entry['version']} to history")
        except Exception as e:
            logger.error(f"Error saving version history: {e}")

    async def run_check(self) -> None:
        """Run a single schema check cycle."""
        logger.info("Starting schema check cycle")

        try:
            # Fetch current schema
            new_schema = await self.fetch_confluent_schema()

            # Load version history
            history = self.load_version_history()

            # Compare with last version
            if history:
                last_version = history[-1]
                # Reconstruct old schema from last version (we only store metadata)
                # For now, fetch previous schema from saved full snapshot if available
                old_schema_file = self.versions_file.parent / f"schema_snapshot_{last_version['version']}.json"
                if old_schema_file.exists():
                    with open(old_schema_file, 'rb') as f:
                        old_schema = orjson.loads(f.read())
                else:
                    # First run or snapshot not found, use empty schema
                    old_schema = {'event_types': [], 'methods': [], 'fields': []}
            else:
                # First run
                old_schema = {'event_types': [], 'methods': [], 'fields': []}

            # Compare schemas
            changes = self.compare_schemas(old_schema, new_schema)

            if changes['has_changes']:
                logger.info("Schema changes detected!")

                # Classify new methods
                new_methods_classified = self.classify_new_methods(changes['methods']['added'])

                # Update methods data file (JSON, NOT a .py source file).
                if changes['methods']['added']:
                    self.update_methods_data_file(new_methods_classified)

                # Send Slack alert
                await self.send_slack_alert(changes, new_methods_classified)

                # Save version history
                self.save_version_history(new_schema, changes)

                # Save full schema snapshot
                snapshot_file = self.versions_file.parent / f"schema_snapshot_{len(history) + 1}.json"
                if not self.dry_run:
                    with open(snapshot_file, 'wb') as f:
                        f.write(orjson.dumps(new_schema, option=orjson.OPT_INDENT_2))
            else:
                logger.info("No schema changes detected")

                # Still update last check timestamp
                self.save_version_history(new_schema)

        except Exception as e:
            logger.error(f"Error during schema check: {e}", exc_info=True)
            raise


async def main():
    """Main entry point."""
    # Configuration from environment variables. The data_file MUST be a JSON
    # file under the writeable schema_watcher_data volume — never a path under
    # the read-only application source tree.
    data_file = Path(os.getenv('SCHEMA_METHODS_DATA_FILE', '/app/data/schema_methods.json'))
    versions_file = Path(os.getenv('VERSIONS_FILE', '/app/data/schema_versions.json'))
    slack_webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    check_interval_hours = max(1, int(os.getenv('CHECK_INTERVAL_HOURS', '24')))
    dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'

    logger.info(f"Starting Confluent Schema Watcher")
    logger.info(f"Data file: {data_file}")
    logger.info(f"Versions file: {versions_file}")
    logger.info(f"Check interval: {check_interval_hours} hours")
    logger.info(f"Dry run: {dry_run}")

    # Ensure versions file directory exists
    versions_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    async with ConfluentSchemaWatcher(
        data_file=data_file,
        versions_file=versions_file,
        slack_webhook_url=slack_webhook_url,
        dry_run=dry_run
    ) as watcher:
        while True:
            try:
                await watcher.run_check()
            except Exception as e:
                logger.error(f"Check cycle failed: {e}", exc_info=True)

            # Wait until next check
            logger.info(f"Next check in {check_interval_hours} hours")
            await asyncio.sleep(check_interval_hours * 3600)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully")
        sys.exit(0)
