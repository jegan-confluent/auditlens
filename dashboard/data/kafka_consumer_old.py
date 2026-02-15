"""Kafka consumer functions"""

import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime, timedelta, timezone
from confluent_kafka import Consumer, KafkaError, TopicPartition
from config import (
    DEST_BOOTSTRAP, DEST_API_KEY, DEST_API_SECRET,
    TOPIC_CRITICAL, TOPIC_HIGH, TOPIC_MEDIUM, TOPIC_ALERTS
)
from .transformations import enhance_events_dataframe
from .email_cache import GLOBAL_EMAIL_CACHE, build_cache_from_dataframe, enrich_email_from_cache

@st.cache_data(ttl=60)  # Increased TTL from 30s to 60s for better performance
def load_events_from_kafka(criticality_filter='All', time_minutes=60, max_events=1500):
    """Load LATEST events from Kafka topics using PARALLEL partition reading."""
    if not DEST_BOOTSTRAP or not DEST_API_KEY:
        st.error("⚠️ Kafka connection not configured. Check .env file.")
        return pd.DataFrame()


def load_security_alerts(time_minutes=60, max_alerts=500):
    """Load security alerts from the aggregated alerts topic."""
    if not DEST_BOOTSTRAP or not DEST_API_KEY:
        return pd.DataFrame()

