"""Data layer for Audit Dashboard"""

from .email_cache import (
    GLOBAL_EMAIL_CACHE,
    enrich_email_from_cache,
    build_cache_from_dataframe,
    refresh_email_cache,
    initialize_email_cache
)

from .transformations import (
    extract_deep_fields,
    enhance_events_dataframe,
    is_failure_event,
    classify_event,
    detect_anomalies
)

from .kafka_consumer import (
    load_events_from_kafka,
    load_security_alerts
)

__all__ = [
    'GLOBAL_EMAIL_CACHE',
    'enrich_email_from_cache',
    'build_cache_from_dataframe',
    'refresh_email_cache',
    'initialize_email_cache',
    'extract_deep_fields',
    'enhance_events_dataframe',
    'is_failure_event',
    'classify_event',
    'detect_anomalies',
    'load_events_from_kafka',
    'load_security_alerts'
]
