"""
Method Classification Constants for Confluent Audit Log Intelligence System.

This module defines comprehensive classification of Confluent Cloud audit log
method names into criticality levels for intelligent routing and alerting.

Criticality Levels:
- CRITICAL: Immediate attention required (destructive operations, security breaches)
- HIGH: Attention within hours (credential operations, permission changes)
- MEDIUM: Daily review (configuration changes, resource modifications)
- LOW: Archive/audit trail (read operations, routine activity)

Rules can be loaded from config/classification_rules.yaml for easy updates
without code changes. Falls back to hardcoded values if YAML not found.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import FrozenSet, Tuple, Set

logger = logging.getLogger(__name__)

# =============================================================================
# YAML CONFIGURATION LOADER
# =============================================================================

def _load_rules_from_yaml() -> dict:
    """Load classification rules from YAML config file."""
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "classification_rules.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                rules = yaml.safe_load(f)
                logger.info(f"Loaded classification rules from {config_path}")
                return rules
    except ImportError:
        logger.debug("PyYAML not installed, using hardcoded rules")
    except Exception as e:
        logger.warning(f"Failed to load classification rules from YAML: {e}")
    return {}


def _load_extras_from_data_file() -> dict[str, Set[str]]:
    """Load schema-watcher additions from a read-only JSON data file.

    Phase 3 hardening: the schema-watcher container no longer rewrites
    ``methods.py`` at runtime. Instead it appends to a JSON data file under
    its writeable volume (``/app/data/schema_methods.json`` by default), and
    we *read* that file here at startup. If the file is missing or malformed
    we fall back to the YAML/hardcoded defaults silently — never failing
    open by re-running source code from disk.
    """
    candidates: list[Path] = []
    env_path = os.getenv("SCHEMA_METHODS_DATA_FILE")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("/app/data/schema_methods.json"))
    candidates.append(Path(__file__).parent.parent.parent / "schema-watcher" / "data" / "schema_methods.json")

    for path in candidates:
        try:
            if not path.exists():
                continue
            with open(path, "rb") as f:
                payload = json.loads(f.read() or b"{}")
        except Exception as exc:
            logger.warning("schema-watcher data file %s could not be read: %s", path, exc)
            continue
        buckets = payload.get("methods_by_level", {}) or {}
        return {
            level: set(values or []) for level, values in buckets.items()
            if isinstance(values, list)
        }
    return {}


_YAML_RULES = _load_rules_from_yaml()
_SCHEMA_WATCHER_EXTRAS = _load_extras_from_data_file()


_SCHEMA_WATCHER_KEY_BY_LEVEL = {
    "critical_methods": "CRITICAL",
    "high_methods": "HIGH",
    "medium_methods": "MEDIUM",
    "read_only_methods": "LOW",
}


def _get_methods(key: str, default: Set[str]) -> FrozenSet[str]:
    """Return the resolved method set for ``key``.

    Resolution order:
      1. ``classification_rules.yaml`` if it defines ``key`` (full override).
      2. The hardcoded ``default`` baked into this module.
    Either is then *unioned* with any schema-watcher-detected additions for
    the same criticality level (read-only JSON data file).
    """
    if _YAML_RULES and key in _YAML_RULES:
        base = set(_YAML_RULES[key])
    else:
        base = set(default)
    extras = _SCHEMA_WATCHER_EXTRAS.get(_SCHEMA_WATCHER_KEY_BY_LEVEL.get(key, ""), set())
    return frozenset(base | extras)

# =============================================================================
# CRITICAL METHODS - Require immediate attention
# =============================================================================
# Destructive operations that cannot be easily undone, or security breaches

_CRITICAL_METHODS_DEFAULT = {
    # Kafka Cluster Operations
    'DeleteKafkaCluster',
    'PauseKafkaCluster',

    # Environment & Organization
    'DeleteEnvironment',
    'DeleteOrganization',
    'DeleteOrg',  # Alternative name for DeleteOrganization

    # Kafka Topic Operations (destructive)
    'kafka.DeleteTopics',
    'kafka.DeleteRecords',

    # Connector Operations
    'DeleteConnector',

    # ksqlDB Operations
    'DeleteKsqldbCluster',

    # Flink Operations
    'DeleteFlinkCompute',
    'DeleteFlinkStatement',
    'DeleteStatement',  # General statement deletion

    # Schema Registry (destructive)
    'DeleteSchema',
    'DeleteSubject',

    # Network Operations
    'DeletePrivateLinkAccess',
    'DeleteNetworkLinkEndpoint',
    'DeleteNetworkLinkService',
    'DeletePeering',
    'DeleteTransitGatewayAttachment',
    'DeleteTransitGateway',

    # Service Account Operations (security-critical)
    'DeleteServiceAccount',

    # Identity Provider
    'DeleteIdentityProvider',
    'DeleteIdentityPool',

    # Audit Log Configuration (meta-security)
    'DeleteAuditLogConfig',
    'UpdateAuditLogConfig',  # Changing audit settings is critical

    # BYOK/Encryption
    'DeleteByokKey',

    # TableFlow
    'DeleteTableflow',

    # Pipeline Operations
    'DeletePipeline',

    # Workspace Operations
    'DeleteWorkspace',

    # Stream Processing / Exporter
    'DeleteExporter',  # Stream processing exporters

    # Domain & Access Point
    'DeleteDomain',
    'DeleteAccessPoint',

    # RBAC — Confluent emits the *ById variant; pattern-match would catch the
    # Delete prefix but the explicit set documents intent.
    'DeleteRoleBindingById',
    # Promoted from HIGH: revoking all role-resource bindings for a principal
    # is irreversible and operationally equivalent to a destructive change.
    'RevokeRoleResourcesForPrincipal',
    # Schema Registry cluster deletion is irreversible (loses subjects + schemas).
    'DeleteSchemaRegistryCluster',
    # Promoted from MEDIUM: tearing down a network removes connectivity for
    # every cluster scoped to it.
    'DeleteNetwork',
    # KSQL cluster delete (capital-K naming variant).
    'DeleteKSQLCluster',
    # SSO connection delete cuts off federation for the org.
    'DeleteSSOConnection',
    # Identity provider / pool delete (already enumerated above; harmless dup,
    # but kept to make audit-trail of this revision explicit).
    'DeleteIdentityProvider',
    'DeleteIdentityPool',
}

CRITICAL_METHODS = _get_methods('critical_methods', _CRITICAL_METHODS_DEFAULT)

# =============================================================================
# HIGH METHODS - Require attention within hours
# =============================================================================
# Credential operations, permission changes, and significant modifications

_HIGH_METHODS_DEFAULT = {
    # API Key Operations
    'CreateApiKey',
    'DeleteApiKey',
    'UpdateApiKey',
    'RotateApiKey',

    # ACL Operations (security-changing, but not destructive)
    'kafka.CreateAcls',
    'kafka.DeleteAcls',

    # Service Account Operations
    'CreateServiceAccount',
    'UpdateServiceAccount',

    # Role Binding Operations (RBAC)
    'CreateRoleBinding',
    'DeleteRoleBinding',
    'UpdateRoleBinding',
    'UnbindAllRolesForPrincipal',  # Removes all role bindings for a principal
    # Note: RevokeRoleResourcesForPrincipal was promoted to CRITICAL.
    'GrantRoleResourcesForPrincipal',
    'BindRoleForPrincipal',

    # User Management
    'CreateInvitation',
    'DeleteInvitation',
    'CreateUser',
    'DeleteUser',
    'UpdateUser',
    'InviteUser',

    # Identity Provider Configuration
    'CreateIdentityProvider',
    'UpdateIdentityProvider',
    'CreateIdentityPool',
    'UpdateIdentityPool',

    # Network Configuration - Private Link
    'CreatePrivateLinkAccess',
    'UpdatePrivateLinkAccess',
    'CreatePrivateLinkAttachment',
    'DeletePrivateLinkAttachment',
    'UpdatePrivateLinkAttachment',
    'CreatePrivateLinkAttachmentConnection',
    'DeletePrivateLinkAttachmentConnection',

    # Network Configuration - Network Link
    'CreateNetworkLinkEndpoint',
    'UpdateNetworkLinkEndpoint',
    'CreateNetworkLinkService',
    'UpdateNetworkLinkService',

    # Network Configuration - Peering & Transit Gateway
    'CreatePeering',
    'UpdatePeering',
    'CreateTransitGatewayAttachment',
    'UpdateTransitGatewayAttachment',
    'CreateTransitGateway',
    'UpdateTransitGateway',

    # Cluster Linking (cross-cluster replication)
    'CreateClusterLink',
    'DeleteClusterLink',
    'UpdateClusterLink',
    'CreateMirrorTopic',
    'DeleteMirrorTopic',

    # Connect Operations
    'CreateConnector',
    'UpdateConnector',
    'PauseConnector',
    'ResumeConnector',

    # Schema Registry Configuration
    'UpdateMode',  # Schema compatibility mode changes
    'UpdateConfig',

    # Kafka ACL Read (indicates reconnaissance)
    'kafka.DescribeAcls',

    # BYOK/Encryption
    'CreateByokKey',
    'UpdateByokKey',
    'EncryptTopic',  # Topic encryption operations
    'DecryptTopic',

    # Audit Log Configuration
    'CreateAuditLogConfig',

    # SSO/SCIM/Group Mapping
    'CreateSSOGroupMapping',
    'DeleteSSOGroupMapping',
    'UpdateSSOGroupMapping',
    'CreateGroupMapping',
    'DeleteGroupMapping',

    # IP Filtering & Security
    'CreateIPFilter',
    'DeleteIPFilter',
    'CreateIPGroup',
    'DeleteIPGroup',
    'UpdateIPGroup',

    # Organization Management
    'SuspendOrg',
    'UnsuspendOrg',

    # DNS & Networking
    'CreateDnsForwarder',
    'DeleteDnsForwarder',

    # Integrations
    'CreateIntegration',
    'DeleteIntegration',

    # Stream Processing / Exporter
    'CreateExporter',

    # Alerting
    'CreateAlert',

    # Domain & Access Point
    'CreateDomain',
    'CreateAccessPoint',

    # Confluent caps the API in API Key — distinct strings from CreateApiKey,
    # explicit set must enumerate both spellings (pattern fallback works but
    # this documents intent and protects routing if patterns are tightened).
    'CreateAPIKey',
    'DeleteAPIKey',
    'UpdateAPIKey',

    # SSO connection mutations.
    'CreateSSOConnection',
    'UpdateSSOConnection',

    # Promoted up from MEDIUM: ACL/config and consumer-group changes that
    # were materially under-prioritised when bucketed as MEDIUM.
    'kafka.AlterConfigs',
    'kafka.IncrementalAlterConfigs',
    'kafka.DeleteGroups',

    # Cluster linking — kafka. prefixed variants Confluent actually emits.
    'kafka.CreateClusterLinks',
    'kafka.DeleteClusterLinks',

    # Schema Registry KEK / DEK lifecycle (security-sensitive encryption keys).
    'schema-registry.RegisterDek',
    'schema-registry.RegisterKek',
    'schema-registry.DeregisterDek',
    'schema-registry.DeregisterKek',
    'schema-registry.DeleteSubject',
    'schema-registry.DeleteSchemaVersion',
}

HIGH_METHODS = _get_methods('high_methods', _HIGH_METHODS_DEFAULT)

# =============================================================================
# MEDIUM METHODS - Daily review
# =============================================================================
# Configuration changes and resource modifications

_MEDIUM_METHODS_DEFAULT = {
    # Kafka Configuration
    # Note: kafka.AlterConfigs, kafka.IncrementalAlterConfigs, and
    # kafka.DeleteGroups were promoted to HIGH.
    'kafka.DescribeConfigs',

    # Cluster Updates
    'UpdateKafkaCluster',
    'CreateKafkaCluster',
    'ResumeKafkaCluster',

    # Environment Updates
    'CreateEnvironment',
    'UpdateEnvironment',

    # Topic Operations
    'kafka.CreateTopics',
    'kafka.CreatePartitions',

    # Consumer Group Management
    'kafka.OffsetDelete',

    # ksqlDB Operations
    'CreateKsqldbCluster',
    'UpdateKsqldbCluster',
    'PauseKsqldbCluster',
    'RestoreKsqldbCluster',

    # Flink Operations
    'CreateFlinkCompute',
    'UpdateFlinkCompute',
    'CreateFlinkStatement',
    'UpdateFlinkStatement',

    # Schema Registry
    'CreateSchema',
    'UpdateSchema',
    'CreateSubject',

    # Network — DeleteNetwork was promoted to CRITICAL.
    'CreateNetwork',
    'UpdateNetwork',

    # TableFlow
    'CreateTableflow',
    'UpdateTableflow',

    # Connector Task Management
    'RestartConnector',
    'RestartConnectorTask',

    # Pipeline Operations
    'ActivatePipeline',
    'DeactivatePipeline',
    'ActivatePipelineConnector',
    'DeactivatePipelineConnector',

    # Stream Processing / Exporter Operations
    'PauseExporter',
    'ResumeExporter',
    'ResetExporter',

    # Workspace Operations
    'PatchWorkspace',

    # Integration Updates
    'UpdateIntegration',

    # Alert Operations
    'UpdateAlert',

    # Subscription & Opt-in
    'UpdateSubscription',
    'UpdateOptIn',

    # Identity Provider Maintenance
    'RefreshIdentityProviderKeys',
}

MEDIUM_METHODS = _get_methods('medium_methods', _MEDIUM_METHODS_DEFAULT)

# =============================================================================
# SECURITY FAILURE STATUSES - Indicate potential security issues
# =============================================================================
# Any event with these statuses should be elevated to CRITICAL

_SECURITY_FAILURE_STATUSES_DEFAULT = {
    'UNAUTHENTICATED',
    'PERMISSION_DENIED',
    'UNAUTHORIZED',
    'FORBIDDEN',
    'INVALID_CREDENTIALS',
}

SECURITY_FAILURE_STATUSES = _get_methods('security_failure_statuses', _SECURITY_FAILURE_STATUSES_DEFAULT)

# =============================================================================
# AUTHENTICATION METHODS - Track auth events specially
# =============================================================================
# These are high-volume but important for security monitoring

_AUTHENTICATION_METHODS_DEFAULT = {
    'kafka.Authentication',
    'Authentication',
    'Authenticate',
    'flink.Authenticate',
    'ksql.Authenticate',
    'schema-registry.Authentication',
}

AUTHENTICATION_METHODS = _get_methods('authentication_methods', _AUTHENTICATION_METHODS_DEFAULT)

# =============================================================================
# AUTHORIZATION CHECK METHODS - Routine RBAC checks
# =============================================================================
# These are very high-volume authorization checks that happen constantly.
# They should NOT be elevated to CRITICAL even when granted=False, as denials
# are normal part of the authorization system (e.g., checking permissions
# before granting access).

_AUTHORIZATION_CHECK_METHODS_DEFAULT = {
    'mds.Authorize',
    'flink.Authorize',
    'ksql.Authorize',
    'schema-registry.Authorize',
    'ip-filter.Authorize',
}

AUTHORIZATION_CHECK_METHODS = _get_methods('authorization_check_methods', _AUTHORIZATION_CHECK_METHODS_DEFAULT)

# =============================================================================
# READ-ONLY METHODS - Typically LOW criticality
# =============================================================================
# These are informational/read operations

_READ_ONLY_METHODS_DEFAULT = {
    # Kafka Metadata
    'kafka.Metadata',
    'kafka.DescribeCluster',
    'kafka.ListGroups',
    'kafka.DescribeGroups',
    'kafka.ListOffsets',
    'kafka.OffsetFetch',
    'kafka.FindCoordinator',

    # List Operations
    'ListKafkaClusters',
    'ListEnvironments',
    'ListServiceAccounts',
    'ListApiKeys',
    'ListUsers',
    'ListRoleBindings',
    'ListConnectors',
    'ListSchemas',
    'ListSubjects',

    # Get/Describe Operations
    'GetKafkaCluster',
    'GetKafkaClusters',
    'GetEnvironment',
    'GetEnvironments',
    'GetServiceAccount',
    'GetServiceAccounts',
    'GetApiKey',
    'GetApiKeys',
    'GetUser',
    'GetUsers',
    'GetConnector',
    'GetConnectors',
    'GetSchema',
    'DescribeConnector',
    'GetKSQLClusters',
    'GetKSQLCluster',
    'ListWorkspaces',
    'ListComputePools',
    'ListSchemaRegistryClusters',
    'GetPrivateLinkAttachments',
    'GetPrivateLinkAttachmentConnections',
    'GetNetworks',
    'schema-registry.GetAllTagDefs',
    'schema-registry.GetEntityByTypeAndName',
    'schema-registry.GetDek',
    'SignIn',

    # Caps-API variants Confluent emits — explicit set must enumerate both
    # forms because pattern-matching collides with the API Key bucket.
    'GetAPIKey',
    'GetAPIKeys',

    # Flink / statement / workspace reads.
    'GetStatement',
    'ListStatements',
    'ListFlinkRegions',
    'GetWorkspace',

    # Custom connector / endpoint / identity-pool list reads.
    'ListCustomConnectorPlugins',
    'ListEndpoints',
    'ListIdentityPool',

    # Networking reads.
    'GetTransitGateways',

    # ksqlDB authentication / authorization (very high volume; READ_ONLY by
    # the criticality model). Already present in AUTHENTICATION_METHODS /
    # AUTHORIZATION_CHECK_METHODS — listing here documents read-only intent
    # for the criticality cascade.
    'ksql.Authenticate',
    'ksql.Authorize',

    # Produce/Consume (routine operations)
    'kafka.Produce',
    'kafka.Fetch',
    'kafka.JoinGroup',
    'kafka.LeaveGroup',
    'kafka.SyncGroup',
    'kafka.Heartbeat',
    'kafka.OffsetCommit',

    # API/UI Access
    'ApiAccess',
    'UIAccess',

    # Tableflow OAuth token fetches — read-only, high-volume Flink/Tableflow
    # internals; previously hit the unclassified-method catch-all.
    'TableflowOAuthTokens',
}

READ_ONLY_METHODS = _get_methods('read_only_methods', _READ_ONLY_METHODS_DEFAULT)

# =============================================================================
# METHOD PATTERNS - Regex patterns for classification
# =============================================================================
# Used when exact method name matching isn't sufficient

def _get_patterns(key: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    """Get patterns from YAML or fall back to default."""
    if _YAML_RULES and 'patterns' in _YAML_RULES and key in _YAML_RULES['patterns']:
        return tuple(_YAML_RULES['patterns'][key])
    return default

# Pattern: Methods containing these substrings are deletions
DELETION_PATTERNS = _get_patterns('deletion', ('Delete', 'Remove', 'Purge', 'Drop'))

# Pattern: Methods containing these substrings are creations
CREATION_PATTERNS = _get_patterns('creation', ('Create', 'Add', 'New', 'Register'))

# Pattern: Methods containing these substrings are modifications
MODIFICATION_PATTERNS = _get_patterns('modification', ('Update', 'Alter', 'Modify', 'Change', 'Set'))

# Pattern: Methods containing these substrings are reads
READ_PATTERNS = _get_patterns('read', ('Get', 'List', 'Describe', 'Fetch', 'Read', 'Find', 'Show'))

# Sensitive keywords for method detection
_SENSITIVE_KEYWORDS_DEFAULT = (
    'apikey', 'api_key', 'serviceaccount', 'service_account',
    'acl', 'rolebinding', 'role_binding', 'identity', 'credential',
    'secret', 'password', 'token', 'permission'
)

def _get_sensitive_keywords() -> Tuple[str, ...]:
    """Get sensitive keywords from YAML or fall back to default."""
    if _YAML_RULES and 'sensitive_keywords' in _YAML_RULES:
        return tuple(_YAML_RULES['sensitive_keywords'])
    return _SENSITIVE_KEYWORDS_DEFAULT

SENSITIVE_KEYWORDS = _get_sensitive_keywords()


def get_method_category(method_name: str) -> str:
    """
    Determine the category of a method based on its name.

    Args:
        method_name: The audit log method name

    Returns:
        Category string: 'deletion', 'creation', 'modification', 'read', or 'other'
    """
    if not method_name:
        return 'other'

    method_upper = method_name.upper()

    # Check patterns in order of precedence
    for pattern in DELETION_PATTERNS:
        if pattern.upper() in method_upper:
            return 'deletion'

    for pattern in CREATION_PATTERNS:
        if pattern.upper() in method_upper:
            return 'creation'

    for pattern in MODIFICATION_PATTERNS:
        if pattern.upper() in method_upper:
            return 'modification'

    for pattern in READ_PATTERNS:
        if pattern.upper() in method_upper:
            return 'read'

    return 'other'


def is_sensitive_method(method_name: str) -> bool:
    """
    Check if a method is considered sensitive (API key, service account, ACL related).

    Args:
        method_name: The audit log method name

    Returns:
        True if the method involves sensitive operations

    Note: 'auth' was removed from keywords because it matches mds.Authorize,
    flink.Authorize etc. which are high-volume routine RBAC checks, not sensitive operations
    """
    if not method_name:
        return False

    method_lower = method_name.lower()
    tokenized = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', method_name).lower()
    tokenized = re.sub(r'[^a-z0-9]+', ' ', tokenized)
    tokens = set(tokenized.split())

    for keyword in SENSITIVE_KEYWORDS:
        normalized_keyword = keyword.replace('_', ' ').lower()
        keyword_tokens = tuple(normalized_keyword.split())
        if len(keyword_tokens) == 1:
            if keyword_tokens[0] in tokens:
                return True
        elif all(token in tokens for token in keyword_tokens):
            return True

    return False
