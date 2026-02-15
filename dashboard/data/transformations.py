"""DataFrame transformations and event processing"""

import pandas as pd
import numpy as np
import json
import re
from config import CRITICAL_METHODS, HIGH_METHODS, FAILURE_STATUSES
from config import ANOMALY_AUTH_FAILURE_THRESHOLD, ANOMALY_DELETION_THRESHOLD, ANOMALY_API_KEY_THRESHOLD


def extract_deep_fields(event):
    """
    Extract ALL valuable fields from data_json for comprehensive audit trail.
    This serves as fallback for fields not already flattened by the forwarder.
    Returns a dict with extracted fields.
    """
    extracted = {
        'rbac_role': None,
        'rbac_scope': None,
        'acl_permission_type': None,
        'acl_host': None,
        'client_id': None,
        'correlation_id': None,
        'request_id': None,
        'connection_id': None,
        'principal_resource_id': None,
        'identity_email': None,
        'cluster_id': None,
        'environment_id': None,
        'topic_name': None,
        'operation': None,
        'resource_type': None,
        'auth_method': None,
        'client_ip_extracted': None,
    }

    data_json = event.get('data_json')
    if not data_json:
        return extracted

    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json

        # Authentication info
        auth_info = data.get('authenticationInfo', {})
        extracted['principal_resource_id'] = auth_info.get('principalResourceId')

        # Extract email from principal object (new schema location)
        principal_obj = auth_info.get('principal', {})
        if isinstance(principal_obj, dict):
            # Direct email field
            if 'email' in principal_obj:
                extracted['identity_email'] = principal_obj['email']
            # Check nested structures
            for k in ('confluentServiceAccount', 'confluentUser'):
                if k in principal_obj and isinstance(principal_obj[k], dict):
                    if 'email' in principal_obj[k]:
                        extracted['identity_email'] = principal_obj[k]['email']
                        break

        # Fallback: Extract email from identity string
        if not extracted['identity_email']:
            identity = auth_info.get('identity', '')
            if isinstance(identity, str) and '@' in identity:
                extracted['identity_email'] = identity
            elif isinstance(identity, dict):
                extracted['identity_email'] = identity.get('email')

        # Authorization info - RBAC
        authz_info = data.get('authorizationInfo', {})
        rbac_auth = authz_info.get('rbacAuthorization', {})
        if rbac_auth:
            extracted['rbac_role'] = rbac_auth.get('role')
            scope = rbac_auth.get('scope', {})
            if isinstance(scope, dict):
                outer_scope = scope.get('outerScope', [])
                if outer_scope:
                    extracted['rbac_scope'] = ', '.join(outer_scope) if isinstance(outer_scope, list) else str(outer_scope)

        # Authorization info - ACL
        acl_auth = authz_info.get('aclAuthorization', {})
        if acl_auth:
            extracted['acl_permission_type'] = acl_auth.get('permissionType')
            extracted['acl_host'] = acl_auth.get('host')

        extracted['operation'] = authz_info.get('operation')
        extracted['resource_type'] = authz_info.get('resourceType')

        # Request metadata
        request = data.get('request', {})
        extracted['client_id'] = request.get('clientId')
        extracted['correlation_id'] = request.get('correlationId')

        req_metadata = data.get('requestMetadata', {})
        extracted['request_id'] = req_metadata.get('request_id') or req_metadata.get('requestId')
        extracted['connection_id'] = req_metadata.get('connection_id') or req_metadata.get('connectionId')

        # Resource identifiers
        extracted['cluster_id'] = request.get('clusterId') or request.get('kafka_cluster_id')
        extracted['environment_id'] = request.get('environmentId') or request.get('environment_id')

        # Topic name extraction - check multiple sources
        topic_name = request.get('topicName') or request.get('topic_name')

        # If not in request, check authorizationInfo.resourceName when resourceType is Topic
        if not topic_name:
            authz_resource_type = authz_info.get('resourceType', '')
            if authz_resource_type == 'Topic':
                topic_name = authz_info.get('resourceName')

        extracted['topic_name'] = topic_name

        # Auth method
        extracted['auth_method'] = auth_info.get('method') or 'SASL'

        # Extract client IP from multiple locations (fallback for old events)
        client_ip = None
        # Primary: clientAddress array
        addr = data.get('clientAddress', [])
        if addr and isinstance(addr, list) and len(addr) > 0:
            client_ip = addr[0].get('ip')

        # Fallback: requestMetadata.clientAddress
        if not client_ip:
            meta_addr = req_metadata.get('clientAddress', [])
            if meta_addr and isinstance(meta_addr, list) and len(meta_addr) > 0:
                client_ip = meta_addr[0].get('ip')

        # Fallback: authorizationInfo.requestMetadata.clientAddress
        if not client_ip:
            authz_meta = authz_info.get('requestMetadata', {})
            if isinstance(authz_meta, dict):
                authz_addr = authz_meta.get('clientAddress', [])
                if authz_addr and isinstance(authz_addr, list) and len(authz_addr) > 0:
                    client_ip = authz_addr[0].get('ip')

        extracted['client_ip_extracted'] = client_ip

    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    return extracted


def extract_user_display(principal):
    """Extract user-friendly display name from principal."""
    if not principal or pd.isna(principal):
        return 'Unknown'

    principal_str = str(principal)

    # Handle JSON dict strings like '{"externalAccount":{"subject":"Confluent"}}'
    if principal_str.startswith('{') or principal_str.startswith('"{'):
        try:
            clean_str = principal_str.strip('"').replace('""', '"')
            data = json.loads(clean_str)
            if isinstance(data, dict):
                if 'externalAccount' in data:
                    return data['externalAccount'].get('subject', 'External')
                if 'confluentUser' in data:
                    return data['confluentUser'].get('resourceId', 'User')
                if 'confluentServiceAccount' in data:
                    return data['confluentServiceAccount'].get('resourceId', 'SA')
        except:
            pass

    # Handle User:xxx or SA:xxx format
    if ':' in principal_str:
        return principal_str.split(':')[-1]

    return principal_str


def format_resource_for_display(row):
    """Format resource information for clean display."""
    parts = []

    # Try to get meaningful resource info
    resource_name = row.get('resourceName', '')
    topic_name = row.get('topic_name', '')
    cluster_id = row.get('cluster_id', '')
    resource_type = row.get('resourceType', '') or row.get('resource_type', '')

    # Extract topic name from resourceName if not already set
    if not topic_name and resource_name:
        resource_str = str(resource_name)
        # Look for topic in CRN: kafka=lkc-xxx/topic=my-topic
        if '/topic=' in resource_str:
            topic_match = re.search(r'/topic=([^/]+)', resource_str)
            if topic_match:
                topic_name = topic_match.group(1)
        # Look for connector: connector=my-connector
        elif '/connector=' in resource_str:
            conn_match = re.search(r'/connector=([^/]+)', resource_str)
            if conn_match:
                parts.append(f"Connector: {conn_match.group(1)}")

    if topic_name:
        parts.append(f"Topic: {topic_name}")

    if resource_type and resource_type not in ['Topic', 'topic']:
        parts.append(f"Type: {resource_type}")

    if cluster_id:
        parts.append(f"Cluster: {cluster_id}")

    if not parts and resource_name:
        # Fallback: show last part of CRN
        resource_str = str(resource_name)
        if '/' in resource_str:
            last_part = resource_str.split('/')[-1]
            if '=' in last_part:
                parts.append(last_part.replace('=', ': '))
            else:
                parts.append(last_part)
        else:
            parts.append(resource_str[:50] + '...' if len(resource_str) > 50 else resource_str)

    return ' | '.join(parts) if parts else '—'


def is_failure_event(row):
    """Check if event is a failure (comprehensive check)."""
    # Check granted field
    granted = row.get('granted')
    if granted == False:
        return True

    # Check resultStatus
    result_status = str(row.get('resultStatus', '')).upper()
    if result_status in FAILURE_STATUSES:
        return True

    # Check methodName for Deny patterns
    method_name = str(row.get('methodName', ''))
    if 'Deny' in method_name or 'Fail' in method_name:
        return True

    return False


def classify_event(row):
    """Classify event criticality with comprehensive failure detection."""
    method_name = str(row.get('methodName', ''))
    result_status = str(row.get('resultStatus', '')).upper()
    granted = row.get('granted')

    # Use existing criticality if set by forwarder
    existing = row.get('criticality')
    if existing and existing in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        return existing

    # Check for critical methods
    for pattern in CRITICAL_METHODS:
        if pattern.lower() in method_name.lower():
            return 'CRITICAL'

    # Check for high methods
    for pattern in HIGH_METHODS:
        if pattern.lower() in method_name.lower():
            return 'HIGH'

    # Failures are at least HIGH
    if granted == False or result_status in FAILURE_STATUSES:
        return 'HIGH'

    return 'MEDIUM'


def enhance_events_dataframe(df):
    """Add ALL computed columns to events dataframe for comprehensive audit trail."""
    if df is None or df.empty:
        return df

    # Extract user display
    if 'principal' in df.columns:
        def get_user_display(row):
            principal = str(row.get('principal', '') or '')
            # For User:<numeric> format, prefer principalResourceId
            if principal.startswith('User:'):
                user_part = principal.replace('User:', '')
                if user_part.isdigit():
                    prid = row.get('principalResourceId') or row.get('principal_resource_id')
                    if prid and pd.notna(prid):
                        return str(prid)
            return extract_user_display(principal)

        df['user'] = df.apply(get_user_display, axis=1)

    # Create user display with email if available
    if 'user' not in df.columns:
        df['user'] = df.get('principal', 'Unknown')

    df['user_display'] = df.apply(
        lambda row: f"{row.get('user', 'Unknown')}" + (f" ({row['email']})" if pd.notna(row.get('email')) and row.get('email') else ''),
        axis=1
    )

    # Extract service name - VECTORIZED
    if 'serviceName' in df.columns:
        df['service'] = df['serviceName']
    elif 'methodName' in df.columns:
        df['service'] = df['methodName'].astype(str).str.split('.').str[0].replace('nan', 'Other')
    else:
        df['service'] = 'Unknown'

    # Create clean action - VECTORIZED
    if 'methodName' in df.columns:
        df['action'] = df['methodName'].astype(str).str.split('.').str[-1]
    else:
        df['action'] = '—'

    # Format resource for display
    df['resource_display'] = df.apply(format_resource_for_display, axis=1)

    # Add flags
    if 'methodName' in df.columns:
        df['is_deletion'] = df['methodName'].str.contains('Delete', case=False, na=False)
        df['is_creation'] = df['methodName'].str.contains('Create', case=False, na=False)
    else:
        df['is_deletion'] = False
        df['is_creation'] = False

    # Detect internal/system operations (UUID-pattern topic names)
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    df['is_internal'] = False

    if 'topic_name' in df.columns:
        df['is_internal'] = df['topic_name'].astype(str).str.fullmatch(uuid_pattern, case=False, na=False)

    # Also check resource_display for "Topic: <UUID>" pattern
    if 'resource_display' in df.columns:
        topic_uuid_pattern = r'Topic:\s*(' + uuid_pattern + r')'
        resource_has_uuid = df['resource_display'].astype(str).str.contains(topic_uuid_pattern, case=False, na=False, regex=True)
        df['is_internal'] = df['is_internal'] | resource_has_uuid

    # Failure detection
    df['is_failure'] = df.apply(is_failure_event, axis=1)

    # Classify criticality (use existing if set by forwarder)
    if 'criticality' not in df.columns:
        df['criticality'] = df.apply(classify_event, axis=1)

    # Format timestamp
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df['time_display'] = df['time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df['hour_of_day'] = df['time'].dt.hour
        df['day_of_week'] = df['time'].dt.day_name()
    else:
        df['time_display'] = '—'

    # Format granted for display with color coding - VECTORIZED using np.select
    if 'granted' in df.columns:
        conditions = [
            df['granted'] == True,
            df['granted'] == False,
            df.get('is_failure', pd.Series([False] * len(df))).fillna(False)
        ]
        choices = ['✅ Allowed', '❌ DENIED', '⚠️ FAILURE']
        df['access_display'] = np.select(conditions, choices, default='—')
    else:
        df['access_display'] = '—'

    # Result status display - VECTORIZED
    if 'resultStatus' in df.columns:
        result_upper = df['resultStatus'].astype(str).str.upper()
        df['result_display'] = np.where(
            result_upper == 'SUCCESS',
            '✅ ' + df['resultStatus'].astype(str),
            np.where(
                df['resultStatus'].notna() & (df['resultStatus'] != ''),
                '❌ ' + df['resultStatus'].astype(str),
                '—'
            )
        )
    else:
        df['result_display'] = '—'

    # RBAC info display - VECTORIZED
    has_rbac = df.get('rbac_role', pd.Series([None] * len(df))).notna() if 'rbac_role' in df.columns else pd.Series([False] * len(df))
    has_acl = df.get('acl_permission_type', pd.Series([None] * len(df))).notna() if 'acl_permission_type' in df.columns else pd.Series([False] * len(df))

    rbac_role = df.get('rbac_role', pd.Series([''] * len(df))).fillna('')
    acl_perm = df.get('acl_permission_type', pd.Series([''] * len(df))).fillna('')

    df['auth_info'] = np.where(
        has_rbac,
        'Role: ' + rbac_role.astype(str),
        np.where(
            has_acl,
            'ACL: ' + acl_perm.astype(str),
            '—'
        )
    )

    # Fix mixed type columns (list/non-list) that cause Arrow serialization errors
    for col in ['request_id', 'correlation_id', 'connection_id', 'requestId', 'correlationId', 'connectionId']:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: str(x) if x is not None and not isinstance(x, str) else x)

    return df


def detect_anomalies(df):
    """Detect anomalies in the event data and return alerts."""
    anomalies = []

    if df.empty:
        return anomalies

    # Auth failure spike
    if 'is_failure' in df.columns:
        failure_count = df['is_failure'].sum()
        if failure_count > ANOMALY_AUTH_FAILURE_THRESHOLD:
            anomalies.append({
                'type': 'auth_failure_spike',
                'severity': 'HIGH',
                'message': f'{failure_count} authentication/authorization failures detected',
                'count': int(failure_count)
            })

    # Deletion spike
    if 'is_deletion' in df.columns:
        deletion_count = df['is_deletion'].sum()
        if deletion_count > ANOMALY_DELETION_THRESHOLD:
            anomalies.append({
                'type': 'deletion_spike',
                'severity': 'CRITICAL',
                'message': f'{deletion_count} deletion operations detected',
                'count': int(deletion_count)
            })

    # API key operations spike
    if 'methodName' in df.columns:
        api_key_ops = df['methodName'].str.contains('ApiKey', case=False, na=False).sum()
        if api_key_ops > ANOMALY_API_KEY_THRESHOLD:
            anomalies.append({
                'type': 'api_key_spike',
                'severity': 'HIGH',
                'message': f'{api_key_ops} API key operations detected',
                'count': int(api_key_ops)
            })

    return anomalies
