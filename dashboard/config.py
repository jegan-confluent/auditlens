"""AuditLens dashboard configuration."""

import os
import base64
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.secrets'))

# =============================================================================
# BRANDING CONFIGURATION
# =============================================================================
APP_NAME = "AuditLens"
APP_VERSION = "v11.0"
APP_TAGLINE = "Kafka-native audit intelligence"

# Confluent Logo - loaded from static/logo.png
def get_logo_base64():
    logo_path = Path(__file__).parent / "static" / "logo.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

LOGO_BASE64 = get_logo_base64()

# =============================================================================
# KAFKA CONFIGURATION
# =============================================================================
DEST_BOOTSTRAP = os.getenv('DEST_BOOTSTRAP')
DEST_API_KEY = os.getenv('DEST_API_KEY')
DEST_API_SECRET = os.getenv('DEST_API_SECRET')

# Topic names
TOPIC_ALL = os.getenv('DASHBOARD_SOURCE_TOPIC', os.getenv('AUDIT_ENRICHED_TOPIC', 'audit.enriched.v1'))
TOPIC_DENIALS = os.getenv('DASHBOARD_DENIALS_TOPIC', os.getenv('AUDIT_SIGNALS_DENIALS_TOPIC', 'audit.signals.denials.v1'))
TOPIC_ALERTS = os.getenv('DASHBOARD_ALERTS_TOPIC', os.getenv('AUDIT_ALERTS_TOPIC', 'audit.alerts.v1'))
TOPIC_HIGHRISK = os.getenv('AUDIT_SIGNALS_HIGHRISK_TOPIC', 'audit.signals.highrisk.v1')

# Service endpoints for health checks in containerized deployments
DASHBOARD_FORWARDER_URL = os.getenv('DASHBOARD_FORWARDER_URL', f"http://auditlens-forwarder:{os.getenv('METRICS_PORT', '8003')}")
DASHBOARD_GRAFANA_URL = os.getenv('DASHBOARD_GRAFANA_URL', 'http://grafana:3000')
DASHBOARD_PROMETHEUS_URL = os.getenv('DASHBOARD_PROMETHEUS_URL', 'http://prometheus:9090')

# =============================================================================
# CONFLUENT CLOUD API (for ACL & Identity lookups)
# =============================================================================
# These are Cloud API keys (not Kafka API keys)
# Used for:
# - Identity enrichment (resolving sa-xxxx / u-xxxx to names)
# - ACL lookups (Topic x Identity matrix)
CONFLUENT_CLOUD_API_KEY = os.getenv('CONFLUENT_CLOUD_API_KEY')
CONFLUENT_CLOUD_API_SECRET = os.getenv('CONFLUENT_CLOUD_API_SECRET')

# =============================================================================
# MONITORING CONFIGURATION
# =============================================================================
METRICS_PORT = os.getenv('METRICS_PORT', '8003')
GRAFANA_PORT = '3000'
PROMETHEUS_PORT = '9090'

# =============================================================================
# ANOMALY THRESHOLDS
# =============================================================================
ANOMALY_AUTH_FAILURE_THRESHOLD = int(os.getenv('ANOMALY_AUTH_FAILURE_THRESHOLD', '10'))
ANOMALY_DELETION_THRESHOLD = int(os.getenv('ANOMALY_DELETION_THRESHOLD', '5'))
ANOMALY_API_KEY_THRESHOLD = int(os.getenv('ANOMALY_API_KEY_THRESHOLD', '10'))

# =============================================================================
# CONFLUENT CLOUD API CONFIGURATION
# =============================================================================
CONFLUENT_CLOUD_API_KEY = os.getenv('CONFLUENT_CLOUD_API_KEY')
CONFLUENT_CLOUD_API_SECRET = os.getenv('CONFLUENT_CLOUD_API_SECRET')

# =============================================================================
# FILE PATHS
# =============================================================================
EMAIL_CACHE_FILE = Path(__file__).parent / "email_cache.json"
USER_MAPPING_FILE = Path(__file__).parent / "user_mapping.json"

# =============================================================================
# CLASSIFICATION CONSTANTS
# =============================================================================
CRITICAL_METHODS = frozenset({
    'DeleteKafkaCluster', 'PauseKafkaCluster',
    'DeleteEnvironment', 'DeleteOrganization',
    'kafka.DeleteTopics', 'kafka.DeleteRecords',
    'kafka.DeleteAcls', 'kafka.CreateAcls',
    'DeleteConnector', 'DeleteKsqldbCluster',
    'DeleteFlinkCompute', 'DeleteFlinkStatement',
    'DeleteSchema', 'DeleteSubject',
    'DeleteServiceAccount',
    'DeleteIdentityProvider', 'DeleteIdentityPool',
    'DeleteByokKey',
})

HIGH_METHODS = frozenset({
    'CreateApiKey', 'DeleteApiKey', 'UpdateApiKey', 'RotateApiKey',
    'CreateServiceAccount', 'UpdateServiceAccount',
    'CreateRoleBinding', 'DeleteRoleBinding',
    'kafka.AlterConfigs', 'kafka.AlterReplicaLogDirs',
})

# Quick filter definitions - INCLUDING ALL FAILURES
QUICK_FILTERS = {
    'all_failures': {'label': '🚨 All Failures', 'type': 'failure'},
    'deletions': {'label': '🗑️ Deletions', 'method_contains': 'Delete'},
    'creations': {'label': '🆕 Creations', 'method_contains': 'Create'},
    'api_keys': {'label': '🔑 API Keys', 'method_contains': 'ApiKey'},
    'topics': {'label': '📋 Topics', 'method_contains': 'Topic'},
    'users': {'label': '👤 Users/SA', 'method_contains': ['User', 'ServiceAccount', 'SignIn']},
    'connectors': {'label': '🔌 Connectors', 'method_contains': 'Connector'},
    'flink': {'label': '⚡ Flink', 'method_contains': ['Statement', 'ComputePool', 'Flink']},
    'rbac': {'label': '🛡️ RBAC', 'method_contains': ['Role', 'Acl', 'Bind']},
    'denied': {'label': '🚫 Denied', 'granted': False},
}

# Failure statuses to capture ALL failures
FAILURE_STATUSES = frozenset({
    'ERROR', 'FAILURE', 'FAILED',
    'UNAUTHENTICATED', 'PERMISSION_DENIED',
    'UNAUTHORIZED', 'FORBIDDEN',
    'INVALID', 'REJECTED', 'DENIED'
})

# =============================================================================
# THEME CONFIGURATION
# =============================================================================
THEME = "B"  # Selected: Soft Pastel theme

THEME_CSS = {
    # OPTION A: Clean SaaS Style (Like Notion/Linear)
    "A": """
    <style>
        .stApp { background: #fafafa; }
        .main .block-container { padding: 2rem 3rem; max-width: 1400px; }

        /* Typography */
        h1 { color: #1a1a1a !important; font-weight: 700 !important; }
        h2, h3 { color: #333 !important; font-weight: 600 !important; }
        p, span, label { color: #555 !important; }

        /* Metric Cards - Clean white with subtle shadow */
        .metric-card {
            background: white;
            border-radius: 12px;
            padding: 1.25rem;
            text-align: center;
            border: 1px solid #e5e5e5;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }
        .metric-card .metric-value {
            font-size: 2rem;
            font-weight: 700;
            color: #1a1a1a;
            margin: 0.25rem 0;
        }
        .metric-card .metric-label {
            font-size: 0.75rem;
            font-weight: 500;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .metric-card.purple .metric-value { color: #7c3aed; }
        .metric-card.red .metric-value { color: #dc2626; }
        .metric-card.orange .metric-value { color: #ea580c; }
        .metric-card.green .metric-value { color: #16a34a; }
        .metric-card.blue .metric-value { color: #2563eb; }

        /* Alert Banner */
        .alert-banner {
            background: #fef2f2;
            color: #991b1b;
            padding: 0.875rem 1.25rem;
            border-radius: 8px;
            border-left: 4px solid #dc2626;
            margin-bottom: 1rem;
            font-weight: 500;
        }
        .alert-banner-warning {
            background: #fffbeb;
            color: #92400e;
            border-left-color: #f59e0b;
        }

        /* Buttons - Secondary (default) */
        .stButton > button {
            background: white !important;
            border: 1px solid #e5e5e5 !important;
            border-radius: 8px !important;
            color: #333 !important;
            font-weight: 500 !important;
            padding: 0.5rem 1rem !important;
            transition: all 0.15s ease !important;
        }
        .stButton > button:hover {
            background: #f5f5f5 !important;
            border-color: #d4d4d4 !important;
        }
        /* Primary buttons (active quick filters) */
        .stButton > button[kind="primary"],
        [data-testid="stBaseButton-primary"] {
            background: #7c3aed !important;
            color: white !important;
            border-color: #7c3aed !important;
        }
        .stButton > button[kind="primary"]:hover,
        [data-testid="stBaseButton-primary"]:hover {
            background: #6d28d9 !important;
            border-color: #6d28d9 !important;
        }

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {
            background: white;
            padding: 8px;
            border-radius: 10px;
            border: 1px solid #e5e5e5;
            gap: 4px;
        }
        .stTabs [data-baseweb="tab"] {
            background: transparent;
            border-radius: 6px;
            color: #666 !important;
            font-weight: 500;
            padding: 8px 16px;
        }
        .stTabs [data-baseweb="tab"]:hover { background: #f5f5f5; }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: #1a1a1a !important;
            color: white !important;
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: white;
            border-right: 1px solid #e5e5e5;
        }

        /* Hide default metrics */
        [data-testid="metric-container"] { background: transparent !important; }
    </style>
    """,

    # OPTION B: Soft Pastel Theme
    "B": """
    <style>
        .stApp { background: linear-gradient(135deg, #faf5ff 0%, #f0fdf4 100%); }
        .main .block-container { padding: 2rem; max-width: 1400px; }

        /* Typography */
        h1 { color: #4c1d95 !important; font-weight: 700 !important; }
        h2, h3 { color: #5b21b6 !important; font-weight: 600 !important; }

        /* Metric Cards - Soft pastel backgrounds */
        .metric-card {
            border-radius: 16px;
            padding: 1.5rem;
            text-align: center;
            border: none;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        }
        .metric-card .metric-value {
            font-size: 2.25rem;
            font-weight: 800;
            margin: 0.5rem 0;
        }
        .metric-card .metric-label {
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            opacity: 0.8;
        }
        .metric-card.purple { background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%); color: #5b21b6; }
        .metric-card.purple .metric-value { color: #6d28d9; }
        .metric-card.red { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); color: #991b1b; }
        .metric-card.red .metric-value { color: #dc2626; }
        .metric-card.orange { background: linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%); color: #9a3412; }
        .metric-card.orange .metric-value { color: #ea580c; }
        .metric-card.green { background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%); color: #166534; }
        .metric-card.green .metric-value { color: #16a34a; }
        .metric-card.blue { background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%); color: #1e40af; }
        .metric-card.blue .metric-value { color: #2563eb; }

        /* Alert Banner */
        .alert-banner {
            background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
            color: #991b1b;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            margin-bottom: 1rem;
            font-weight: 600;
            border: 1px solid #fca5a5;
        }
        .alert-banner-warning {
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            color: #92400e;
            border-color: #fcd34d;
        }

        /* Buttons - Secondary (default) */
        .stButton > button {
            background: white !important;
            border: 2px solid #e9d5ff !important;
            border-radius: 12px !important;
            color: #6d28d9 !important;
            font-weight: 600 !important;
            transition: all 0.2s ease !important;
        }
        .stButton > button:hover {
            background: #f5f3ff !important;
            border-color: #c4b5fd !important;
            transform: translateY(-1px) !important;
        }

        /* Primary buttons (active quick filters) - HIGHLIGHTED */
        .stButton > button[kind="primary"],
        [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%) !important;
            color: white !important;
            border: 2px solid #5b21b6 !important;
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.4) !important;
        }
        .stButton > button[kind="primary"]:hover,
        [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(135deg, #6d28d9 0%, #5b21b6 100%) !important;
            border-color: #4c1d95 !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 16px rgba(124, 58, 237, 0.5) !important;
        }

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {
            background: white;
            padding: 10px;
            border-radius: 16px;
            border: 1px solid #e9d5ff;
            gap: 6px;
        }
        .stTabs [data-baseweb="tab"] {
            background: #faf5ff;
            border-radius: 10px;
            color: #7c3aed !important;
            font-weight: 600;
            border: 2px solid transparent;
            transition: all 0.2s ease;
        }
        .stTabs [data-baseweb="tab"]:hover {
            background: #ede9fe;
            border-color: #c4b5fd;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%) !important;
            color: white !important;
            border-color: #5b21b6 !important;
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.4) !important;
            transform: translateY(-1px);
        }
        /* Hide the default underline indicator */
        .stTabs [data-baseweb="tab-highlight"] {
            display: none !important;
        }
        .stTabs [data-baseweb="tab-border"] {
            display: none !important;
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #faf5ff 0%, #f5f3ff 100%);
            border-right: 1px solid #e9d5ff;
        }

        [data-testid="metric-container"] { background: transparent !important; }
    </style>
    """,

    # OPTION C: Professional Blue Theme
    "C": """
    <style>
        .stApp { background: #f8fafc; }
        .main .block-container { padding: 2rem; max-width: 1400px; }

        /* Typography */
        h1 { color: #0f172a !important; font-weight: 700 !important; }
        h2, h3 { color: #1e293b !important; font-weight: 600 !important; }

        /* Metric Cards - Professional with blue accents */
        .metric-card {
            background: white;
            border-radius: 10px;
            padding: 1.25rem;
            text-align: center;
            border: 1px solid #e2e8f0;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            border-top: 3px solid;
        }
        .metric-card .metric-value {
            font-size: 2rem;
            font-weight: 700;
            margin: 0.25rem 0;
        }
        .metric-card .metric-label {
            font-size: 0.75rem;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .metric-card.purple { border-top-color: #7c3aed; }
        .metric-card.purple .metric-value { color: #7c3aed; }
        .metric-card.red { border-top-color: #dc2626; }
        .metric-card.red .metric-value { color: #dc2626; }
        .metric-card.orange { border-top-color: #f59e0b; }
        .metric-card.orange .metric-value { color: #f59e0b; }
        .metric-card.green { border-top-color: #10b981; }
        .metric-card.green .metric-value { color: #10b981; }
        .metric-card.blue { border-top-color: #3b82f6; }
        .metric-card.blue .metric-value { color: #3b82f6; }

        /* Alert Banner */
        .alert-banner {
            background: white;
            color: #dc2626;
            padding: 1rem 1.25rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            font-weight: 600;
            border: 1px solid #fecaca;
            border-left: 4px solid #dc2626;
        }
        .alert-banner-warning {
            color: #d97706;
            border-color: #fde68a;
            border-left-color: #f59e0b;
        }

        /* Buttons */
        .stButton > button {
            background: white !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 6px !important;
            color: #475569 !important;
            font-weight: 500 !important;
        }
        .stButton > button:hover {
            background: #f1f5f9 !important;
            border-color: #3b82f6 !important;
            color: #3b82f6 !important;
        }

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {
            background: white;
            padding: 6px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            gap: 4px;
        }
        .stTabs [data-baseweb="tab"] {
            background: transparent;
            border-radius: 6px;
            color: #64748b !important;
            font-weight: 500;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: #3b82f6 !important;
            color: white !important;
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: white;
            border-right: 1px solid #e2e8f0;
        }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {
            color: #0f172a !important;
        }

        [data-testid="metric-container"] { background: transparent !important; }
    </style>
    """
}

# Additional CSS for data tables
DATA_TABLE_CSS = """
<style>
    /* Data table styling - kept for compatibility */
    .dataframe thead tr th {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
        font-weight: 600 !important;
    }
    .dataframe tbody tr:nth-child(even) {
        background-color: #f8fafc !important;
    }
    .dataframe tbody tr:hover {
        background-color: #e0e7ff !important;
    }

    /* Failure row highlighting */
    .failure-row {
        background-color: #fef2f2 !important;
    }

    /* Success indicator */
    .success-badge {
        background: #dcfce7;
        color: #166534;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
    .failure-badge {
        background: #fef2f2;
        color: #dc2626;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
</style>
"""

# =============================================================================
# TIMEZONE CONFIGURATION
# =============================================================================
TIMEZONES = {
    'UTC': 'UTC',
    'IST': 'Asia/Kolkata',
    'PST': 'America/Los_Angeles',
    'EST': 'America/New_York',
    'CET': 'Europe/Paris',
    'GMT': 'Europe/London',
    'JST': 'Asia/Tokyo',
    'AEST': 'Australia/Sydney'
}
