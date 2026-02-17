"""
Email Cache Module
Handles user email resolution with LRU cache for performance
"""

import json
import logging
import pandas as pd
import requests
from cachetools import LRUCache
from pathlib import Path

logger = logging.getLogger(__name__)
from config import (
    EMAIL_CACHE_FILE,
    USER_MAPPING_FILE,
    CONFLUENT_CLOUD_API_KEY,
    CONFLUENT_CLOUD_API_SECRET
)

# LRU Cache for email lookups (maxsize=10000 as per requirements)
email_lru_cache = LRUCache(maxsize=10000)


def load_email_cache():
    """Load email cache from file."""
    if EMAIL_CACHE_FILE.exists():
        try:
            with open(EMAIL_CACHE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load email cache: {e}")
    return {}


def save_email_cache(cache):
    """Save email cache to file."""
    try:
        with open(EMAIL_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Failed to save email cache: {e}")


def fetch_users_from_confluent_api():
    """Fetch all users from Confluent Cloud IAM API."""
    if not CONFLUENT_CLOUD_API_KEY or not CONFLUENT_CLOUD_API_SECRET:
        return {}

    users = {}
    url = "https://api.confluent.cloud/iam/v2/users"

    try:
        while url:
            response = requests.get(
                url,
                auth=(CONFLUENT_CLOUD_API_KEY, CONFLUENT_CLOUD_API_SECRET),
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                for user in data.get('data', []):
                    user_id = user.get('id')  # e.g., "u-mvw1k5w"
                    email = user.get('email')
                    if user_id and email:
                        users[user_id] = email
                # Handle pagination
                url = data.get('metadata', {}).get('next')
            else:
                print(f"Confluent API error: {response.status_code}")
                break
    except Exception as e:
        print(f"Failed to fetch users from Confluent API: {e}")

    return users


def refresh_email_cache():
    """Refresh email cache from Confluent API."""
    cache = load_email_cache()
    api_users = fetch_users_from_confluent_api()
    if api_users:
        cache.update(api_users)
        save_email_cache(cache)
    return cache


def extract_user_id(principal):
    """Extract user ID (u-xxxxx) from various principal formats."""
    if not principal or pd.isna(principal):
        return None

    principal_str = str(principal)

    # Direct u-xxxxx format
    if principal_str.startswith('u-'):
        return principal_str.split()[0].split('(')[0].strip()

    # JSON format with confluentUser
    if '{' in principal_str:
        try:
            clean = principal_str.strip('"').replace('""', '"')
            data = json.loads(clean)
            if isinstance(data, dict):
                if 'confluentUser' in data:
                    return data['confluentUser'].get('resourceId')
                if 'confluentServiceAccount' in data:
                    return data['confluentServiceAccount'].get('resourceId')
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Return None if parsing fails

    # User:NNNNN format - can't directly map but store for reference
    if principal_str.startswith('User:'):
        return principal_str

    return None


def enrich_email_from_cache(df, cache):
    """Fill in missing emails using the cache - handles user IDs from data plane events.

    IMPORTANT: For User:<numeric> principals, we MUST use principalResourceId (u-xxxxx)
    to resolve the email, as numeric IDs don't map directly to IAM users.
    """
    if 'principal' not in df.columns:
        return df

    def get_email(row):
        # If email already exists, keep it
        existing_email = row.get('email')
        if pd.notna(existing_email) and existing_email and '@' in str(existing_email):
            return existing_email

        principal = str(row.get('principal', '') or '')

        # Check LRU cache first for performance
        if principal in email_lru_cache:
            return email_lru_cache[principal]

        # CRITICAL FIX: For User:<numeric> format, use principalResourceId instead
        # The numeric ID (e.g., User:1389855) cannot be directly mapped to email
        # We must use the principalResourceId (e.g., u-75rw9o) which links to IAM
        if principal.startswith('User:'):
            # Check if it's a numeric ID (not u-xxx or sa-xxx format)
            user_part = principal.replace('User:', '')
            if user_part.isdigit():
                # Use principalResourceId for email resolution
                principal_resource_id = row.get('principalResourceId') or row.get('principal_resource_id')
                if principal_resource_id and pd.notna(principal_resource_id):
                    prid = str(principal_resource_id)
                    if prid in cache:
                        email = cache[prid]
                        email_lru_cache[principal] = email
                        return email
                    # Try without prefix
                    clean_prid = prid.replace('User:', '').strip()
                    if clean_prid in cache:
                        email = cache[clean_prid]
                        email_lru_cache[principal] = email
                        return email

        # Try exact match first
        if principal and principal in cache:
            email = cache[principal]
            email_lru_cache[principal] = email
            return email

        # Extract user ID and try that
        user_id = extract_user_id(principal)
        if user_id and user_id in cache:
            email = cache[user_id]
            email_lru_cache[principal] = email
            return email

        return existing_email

    df['email'] = df.apply(get_email, axis=1)
    return df


def build_cache_from_dataframe(df, cache):
    """Extract user→email mappings from dataframe and update cache.

    IMPORTANT: Do NOT cache User:<numeric> → email mappings directly.
    Numeric IDs like User:1389855 should be resolved via principalResourceId.
    Caching them directly causes wrong email associations.
    """
    if 'principal' not in df.columns or 'email' not in df.columns:
        return cache

    updated = False
    for _, row in df.iterrows():
        principal = str(row.get('principal', '') or '')
        email = str(row.get('email', '') or '')

        if not email or pd.isna(row.get('email')) or '@' not in email:
            continue

        # CRITICAL: Skip User:<numeric> principals - they should NOT be cached
        # These must be resolved via principalResourceId, not direct mapping
        if principal.startswith('User:'):
            user_part = principal.replace('User:', '')
            if user_part.isdigit():
                # For numeric IDs, cache the principalResourceId instead
                prid = row.get('principalResourceId') or row.get('principal_resource_id')
                if prid and pd.notna(prid) and str(prid) not in cache:
                    cache[str(prid)] = email
                    email_lru_cache[str(prid)] = email
                    updated = True
                continue  # Don't cache the numeric ID directly

        # Cache full principal (only for non-numeric IDs like u-xxxxx, sa-xxxxx)
        if principal and principal not in cache:
            cache[principal] = email
            email_lru_cache[principal] = email
            updated = True

        # Also cache user ID separately for data plane event lookups
        user_id = extract_user_id(principal)
        if user_id and user_id not in cache:
            # Double-check it's not a numeric ID
            if not (user_id.startswith('User:') and user_id.replace('User:', '').isdigit()):
                cache[user_id] = email
                email_lru_cache[user_id] = email
                updated = True

    if updated:
        save_email_cache(cache)
    return cache


def load_user_mapping():
    """Load pre-built user mapping from file.

    Supports both flat format (legacy) and nested format with 'users' and 'service_accounts'.
    """
    if USER_MAPPING_FILE.exists():
        try:
            with open(USER_MAPPING_FILE, 'r') as f:
                data = json.load(f)

            # Check if new nested format with 'users' and 'service_accounts' keys
            if 'users' in data or 'service_accounts' in data:
                mapping = {}
                # Load user mappings
                if 'users' in data and isinstance(data['users'], dict):
                    mapping.update(data['users'])
                # Load service account mappings (sa-xxxxx -> friendly name)
                if 'service_accounts' in data and isinstance(data['service_accounts'], dict):
                    for sa_id, friendly_name in data['service_accounts'].items():
                        if not sa_id.startswith('_'):  # Skip example entries
                            mapping[sa_id] = friendly_name
                return mapping
            else:
                # Legacy flat format - filter out comment keys
                return {k: v for k, v in data.items() if not k.startswith('_')}
        except (json.JSONDecodeError, IOError, KeyError) as e:
            logger.warning(f"Failed to load user mapping: {e}")
    return {}


def initialize_email_cache():
    """Initialize email cache from Confluent Cloud IAM API on startup."""
    cache = load_email_cache()

    # Try to fetch from Confluent Cloud API
    if CONFLUENT_CLOUD_API_KEY and CONFLUENT_CLOUD_API_SECRET:
        try:
            api_users = fetch_users_from_confluent_api()
            if api_users:
                cache.update(api_users)
                # Populate LRU cache
                email_lru_cache.update(api_users)
                save_email_cache(cache)
                print(f"[AuditLens] Loaded {len(api_users)} users from Confluent Cloud IAM API")
        except Exception as e:
            print(f"[AuditLens] Warning: Could not fetch users from API: {e}")

    # Merge with static user_mapping.json as fallback
    user_mapping = load_user_mapping()
    if user_mapping:
        cache.update(user_mapping)
        email_lru_cache.update(user_mapping)
        print(f"[AuditLens] Merged {len(user_mapping)} users from static mapping (fallback)")

    return cache


# Initialize cache at startup (runs once when module loads)
GLOBAL_EMAIL_CACHE = initialize_email_cache()
