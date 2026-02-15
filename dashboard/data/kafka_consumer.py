"""Kafka consumer functions"""

import streamlit as st
import pandas as pd
import orjson
import time
import logging
from datetime import datetime, timedelta, timezone
from confluent_kafka import Consumer, KafkaError, TopicPartition
from config import (
    DEST_BOOTSTRAP, DEST_API_KEY, DEST_API_SECRET,
    TOPIC_CRITICAL, TOPIC_HIGH, TOPIC_MEDIUM, TOPIC_ALERTS
)
from .transformations import enhance_events_dataframe
from .email_cache import GLOBAL_EMAIL_CACHE, build_cache_from_dataframe, enrich_email_from_cache

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@st.cache_data(ttl=15, show_spinner=False)  # 15s cache for responsive data
def load_events_from_kafka(criticality_filter='All', time_minutes=60, max_events=1500):
    """Load LATEST events from Kafka topics using PARALLEL partition reading.

    Cached for 30 seconds. Filter clicks don't re-fetch data.
    """
    logger.info(f"[KafkaConsumer] Loading events: filter={criticality_filter}, time_mins={time_minutes}, max={max_events}")

    if not DEST_BOOTSTRAP or not DEST_API_KEY:
        logger.error("[KafkaConsumer] Missing DEST_BOOTSTRAP or DEST_API_KEY")
        st.error("⚠️ Kafka connection not configured. Check .env file.")
        return pd.DataFrame()

    # Select topics based on filter
    if criticality_filter == 'CRITICAL':
        topics = [TOPIC_CRITICAL]
    elif criticality_filter == 'HIGH':
        topics = [TOPIC_HIGH]
    elif criticality_filter == 'MEDIUM':
        topics = [TOPIC_MEDIUM]
    else:  # 'All'
        topics = [TOPIC_CRITICAL, TOPIC_HIGH, TOPIC_MEDIUM]

    if not topics:
        return pd.DataFrame()

    consumer_config = {
        'bootstrap.servers': DEST_BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': DEST_API_KEY,
        'sasl.password': DEST_API_SECRET,
        'group.id': 'auditlens-dashboard-viewer',  # Static group - no more group explosion
        'enable.auto.commit': False,
        'fetch.max.bytes': 52428800,  # 50MB
        'max.partition.fetch.bytes': 10485760,  # 10MB
        'fetch.min.bytes': 1,
        'fetch.wait.max.ms': 100,
        'socket.timeout.ms': 30000,  # 30s socket timeout
        'session.timeout.ms': 45000,  # 45s session timeout
    }

    consumer = Consumer(consumer_config)
    events = []

    try:
        progress_bar = st.progress(0, text="📡 Connecting to Kafka...")
        all_partitions = []

        for topic in topics:
            try:
                md = consumer.list_topics(topic, timeout=30)  # Increased from 10s
                if topic not in md.topics:
                    continue

                partitions = md.topics[topic].partitions
                msgs_per_partition = max(50, max_events // (len(topics) * len(partitions)))

                for p in partitions.keys():
                    tp = TopicPartition(topic, p)
                    try:
                        low, high = consumer.get_watermark_offsets(tp, timeout=10)  # Increased from 3s
                        if high > low:
                            start_offset = max(low, high - msgs_per_partition)
                            tp.offset = start_offset
                            all_partitions.append(tp)
                    except:
                        continue
            except Exception as e:
                continue

        if not all_partitions:
            logger.warning("[KafkaConsumer] No partitions assigned!")
            progress_bar.empty()
            return pd.DataFrame()

        logger.info(f"[KafkaConsumer] Assigned {len(all_partitions)} partitions")
        consumer.assign(all_partitions)
        progress_bar.progress(0.1, text=f"📡 Reading from {len(all_partitions)} partitions...")

        empty_polls = 0
        max_empty_polls = 10  # Increased from 5
        poll_timeout = 1.0  # Increased from 0.2s

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
                event_data = orjson.loads(msg.value())  # orjson is 2-3x faster, no decode needed
                events.append(event_data)

                if len(events) % 100 == 0:
                    progress = min(len(events) / max_events, 0.95)
                    progress_bar.progress(progress, text=f"📡 Loaded {len(events):,} events...")
            except orjson.JSONDecodeError:
                continue

        progress_bar.empty()

    finally:
        consumer.close()

    if not events:
        logger.warning("[KafkaConsumer] No events loaded from Kafka!")
        return pd.DataFrame()

    logger.info(f"[KafkaConsumer] Loaded {len(events)} raw events from Kafka")
    df = pd.DataFrame(events)

    # EARLY DEDUPLICATION
    dedup_cols = ['time', 'principal', 'methodName', 'resourceName']
    existing_dedup_cols = [c for c in dedup_cols if c in df.columns]
    if len(existing_dedup_cols) >= 2:
        df = df.drop_duplicates(subset=existing_dedup_cols, keep='first')

    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.sort_values('time', ascending=False)

        if time_minutes > 0:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=time_minutes)
            if df['time'].dt.tz is None:
                df['time'] = df['time'].dt.tz_localize('UTC')
            before_filter = len(df)
            df = df[df['time'] >= cutoff_time]
            logger.info(f"[KafkaConsumer] Time filter: {before_filter} -> {len(df)} events (cutoff={cutoff_time})")

    # Enhance dataframe
    df = enhance_events_dataframe(df)

    # Handle case where df becomes empty or None
    if df is None or df.empty:
        return pd.DataFrame()

    # Enrich emails
    from .email_cache import GLOBAL_EMAIL_CACHE
    build_cache_from_dataframe(df, GLOBAL_EMAIL_CACHE)
    df = enrich_email_from_cache(df, GLOBAL_EMAIL_CACHE)

    # Rebuild user_display
    if 'user' in df.columns:
        df['user_display'] = df.apply(
            lambda row: f"{row.get('user', 'Unknown')}" + (f" ({row['email']})" if pd.notna(row.get('email')) and row.get('email') else ''),
            axis=1
        )

    return df


def load_security_alerts(time_minutes=60, max_alerts=500):
    """Load security alerts from the aggregated alerts topic."""
    if not DEST_BOOTSTRAP or not DEST_API_KEY:
        return pd.DataFrame()

    consumer_config = {
        'bootstrap.servers': DEST_BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': DEST_API_KEY,
        'sasl.password': DEST_API_SECRET,
        'group.id': 'auditlens-dashboard-alerts',  # Static group - no more group explosion
        'enable.auto.commit': False,
    }

    consumer = Consumer(consumer_config)
    alerts = []

    try:
        md = consumer.list_topics(TOPIC_ALERTS, timeout=10)
        if TOPIC_ALERTS not in md.topics:
            return pd.DataFrame()

        partitions = md.topics[TOPIC_ALERTS].partitions
        msgs_per_partition = max(50, max_alerts // max(len(partitions), 1))

        for p in partitions.keys():
            tp = TopicPartition(TOPIC_ALERTS, p)
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
                        alert_data = orjson.loads(msg.value())  # orjson is 2-3x faster
                        alerts.append(alert_data)
                        partition_alerts += 1
                    except orjson.JSONDecodeError:
                        continue

                if len(alerts) >= max_alerts:
                    break

    finally:
        consumer.close()

    if not alerts:
        return pd.DataFrame()

    df = pd.DataFrame(alerts)

    if 'window_start' in df.columns:
        df['window_start'] = pd.to_datetime(df['window_start'], errors='coerce')
    if 'window_end' in df.columns:
        df['window_end'] = pd.to_datetime(df['window_end'], errors='coerce')

    if time_minutes > 0 and 'window_end' in df.columns:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=time_minutes)
        if df['window_end'].dt.tz is None:
            df['window_end'] = df['window_end'].dt.tz_localize('UTC')
        df = df[df['window_end'] >= cutoff_time]

    if 'window_end' in df.columns:
        df = df.sort_values('window_end', ascending=False)
        df['time_display'] = df['window_end'].dt.strftime('%H:%M:%S')

    # Format list columns
    for col in ['operations', 'resources', 'source_ips', 'environment_ids', 'cluster_ids', 'organization_ids']:
        if col in df.columns:
            df[f'{col}_display'] = df[col].apply(
                lambda x: ', '.join(x[:3]) + (f' (+{len(x)-3})' if len(x) > 3 else '') if isinstance(x, list) and x else ''
            )

    return df
