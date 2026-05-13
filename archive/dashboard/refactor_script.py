#!/usr/bin/env python3
"""
Script to refactor app.py into modular structure
"""

import re
import os
from pathlib import Path

def extract_function(content, func_name):
    """Extract a complete function from content"""
    pattern = rf'(^def {func_name}\(.*?\n(?:.*?\n)*?)(?=^def\s|^@st|^# =+|^if __name__|^\S|$)'
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        return match.group(1).rstrip() + '\n'
    return None

def extract_decorated_function(content, decorator, func_name):
    """Extract a function with its decorator"""
    pattern = rf'({decorator}.*?\ndef {func_name}\(.*?\n(?:.*?\n)*?)(?=^def\s|^@|^# =+|^if __name__|^\S|$)'
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        return match.group(1).rstrip() + '\n'
    return None

def main():
    # Read original app.py
    with open('app.py.backup', 'r') as f:
        original_content = f.read()

    print("Extracting functions from app.py...")

    # Extract transformations.py functions
    transformation_funcs = [
        'extract_deep_fields',
        'extract_email_from_principal',
        'extract_user_display',
        'format_resource_for_display',
        'is_failure_event',
        'classify_event',
        'enhance_events_dataframe',
        'detect_anomalies'
    ]

    # Extract kafka_consumer.py functions (with decorators)
    kafka_funcs = [
        ('load_events_from_kafka', '@st.cache_data'),
        ('load_security_alerts', None)
    ]

    # Extract components functions
    component_funcs = [
        'render_metric_card',
        'render_alert_banner',
        'render_quick_filters',
        'apply_quick_filter'
    ]

    # Extract export functions
    export_funcs = [
        'export_to_csv',
        'export_to_json'
    ]

    print(f"Functions to extract: {len(transformation_funcs) + len(kafka_funcs) + len(component_funcs) + len(export_funcs)}")

    # Build data/transformations.py
    trans_code = []
    trans_code.append('"""DataFrame transformations and event processing"""')
    trans_code.append('')
    trans_code.append('import pandas as pd')
    trans_code.append('import numpy as np')
    trans_code.append('import json')
    trans_code.append('from config import CRITICAL_METHODS, HIGH_METHODS, FAILURE_STATUSES')
    trans_code.append('from config import ANOMALY_AUTH_FAILURE_THRESHOLD, ANOMALY_DELETION_THRESHOLD, ANOMALY_API_KEY_THRESHOLD')
    trans_code.append('')

    for func in transformation_funcs:
        code = extract_function(original_content, func)
        if code:
            trans_code.append(code)
            trans_code.append('')
            print(f"✓ Extracted {func}")
        else:
            print(f"✗ Could not extract {func}")

    with open('data/transformations.py', 'w') as f:
        f.write('\n'.join(trans_code))
    print("Created data/transformations.py")

    # Build data/kafka_consumer.py
    kafka_code = []
    kafka_code.append('"""Kafka consumer functions"""')
    kafka_code.append('')
    kafka_code.append('import streamlit as st')
    kafka_code.append('import pandas as pd')
    kafka_code.append('import json')
    kafka_code.append('import time')
    kafka_code.append('from datetime import datetime, timedelta, timezone')
    kafka_code.append('from confluent_kafka import Consumer, KafkaError, TopicPartition')
    kafka_code.append('from config import (')
    kafka_code.append('    DEST_BOOTSTRAP, DEST_API_KEY, DEST_API_SECRET,')
    kafka_code.append('    TOPIC_CRITICAL, TOPIC_HIGH, TOPIC_MEDIUM, TOPIC_ALERTS')
    kafka_code.append(')')
    kafka_code.append('from .transformations import enhance_events_dataframe')
    kafka_code.append('from .email_cache import GLOBAL_EMAIL_CACHE, build_cache_from_dataframe, enrich_email_from_cache')
    kafka_code.append('')

    for func, decorator in kafka_funcs:
        if decorator:
            code = extract_decorated_function(original_content, decorator, func)
        else:
            code = extract_function(original_content, func)
        if code:
            kafka_code.append(code)
            kafka_code.append('')
            print(f"✓ Extracted {func}")
        else:
            print(f"✗ Could not extract {func}")

    with open('data/kafka_consumer.py', 'w') as f:
        f.write('\n'.join(kafka_code))
    print("Created data/kafka_consumer.py")

    # Build components/metrics.py
    metrics_code = []
    metrics_code.append('"""Metric card components"""')
    metrics_code.append('')

    code = extract_function(original_content, 'render_metric_card')
    if code:
        metrics_code.append(code)
        print("✓ Extracted render_metric_card")

    with open('components/metrics.py', 'w') as f:
        f.write('\n'.join(metrics_code))
    print("Created components/metrics.py")

    # Build components/filters.py
    filters_code = []
    filters_code.append('"""Filter components"""')
    filters_code.append('')
    filters_code.append('import streamlit as st')
    filters_code.append('import pandas as pd')
    filters_code.append('from config import QUICK_FILTERS')
    filters_code.append('')

    for func in ['render_alert_banner', 'render_quick_filters', 'apply_quick_filter']:
        code = extract_function(original_content, func)
        if code:
            filters_code.append(code)
            filters_code.append('')
            print(f"✓ Extracted {func}")

    with open('components/filters.py', 'w') as f:
        f.write('\n'.join(filters_code))
    print("Created components/filters.py")

    print("\nRefactoring complete! Check the created files.")

if __name__ == '__main__':
    main()
