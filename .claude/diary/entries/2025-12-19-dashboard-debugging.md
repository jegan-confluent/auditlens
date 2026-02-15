# Diary Entry: 2025-12-19

## Session Summary
- Started Docker services after downtime
- Investigated and resolved dashboard showing zero events
- Tuned Kafka consumer/producer settings for faster processing
- Fixed multiple bugs in dashboard data pipeline
- Achieved real-time processing (lag=0 on all 12 partitions)

## Key Decisions

- **Increased Kafka timeouts from 3-10s to 10-30s**: Network latency to Confluent Cloud (US West source, AP South dest) requires longer timeouts
- **Changed `hide_internal` default to False**: The UUID regex was matching organization IDs in ALL events, filtering everything out
- **Added cache clear on auto-refresh**: Without this, stale cached data persisted even when auto-refresh triggered
- **Performance tuning trade-offs**: Increased batch sizes and buffers (2x memory) for ~67% faster throughput, no cost/security impact

## Challenges & Solutions

- **Dashboard showing 0 events despite data in Kafka**:
  1. First suspected: Kafka connection timeouts → Fixed by increasing timeout settings
  2. Then found: `enhance_events_dataframe()` was returning `None` (empty function body!) → Added basic implementation
  3. Finally discovered: `hide_internal=True` filter matching ALL events due to org UUID in resourceName → Changed default to False

- **Forwarder lag after Docker restart**:
  - Persistent offsets were already working (file-based at `/app/data/offsets.json`)
  - Lag was from messages accumulated during downtime, not lost offsets
  - Tuned consumer settings to catch up faster

- **Processing speed bottleneck**:
  - Initial: ~900 msg/s
  - After tuning: ~1500 msg/s initially, settled to ~900 msg/s
  - Root cause: Network latency to Confluent Cloud is the real bottleneck, not local resources

## User Preferences Learned

- Prefers tables for status summaries (lag per partition, before/after comparisons)
- Wants direct answers with actionable fixes, not lengthy explanations
- Appreciates cost/security impact analysis before making changes
- Values systematic debugging with logs and evidence

## Code Patterns Used

- **Debug logging pattern**: Add `logger.info()` at key points (before/after data transforms) to trace data flow
- **Streamlit cache debugging**: Check if `@st.cache_data` is returning stale empty results; clear with `st.cache_data.clear()`
- **Docker exec for testing**: `docker exec <container> python3 -c "..."` to test exact same environment as running app

## Potential CLAUDE.md Rules

- When dashboard shows zero data, check: (1) Kafka timeouts, (2) transformation functions returning None, (3) filters removing all data
- Always verify function bodies are complete - Python functions without explicit return statement return None
- Streamlit `@st.cache_data` can cache empty DataFrames; add cache clear on auto-refresh
- UUID regex patterns in "internal event" filters will match org IDs - be careful with default=True
- Network latency to remote Kafka clusters (cross-region) is often the bottleneck, not local CPU/memory
- Test data loading directly with `docker exec python3` before debugging UI layer

---
Created: 2025-12-19T14:30:00+05:30
