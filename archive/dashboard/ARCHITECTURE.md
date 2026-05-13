# AuditLens Dashboard Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         app.py (229 lines)                   │
│                    Main Entry Point                          │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   config.py   │  │  components/  │  │     data/     │
│ Configuration │  │  UI Components│  │  Data Layer   │
└───────────────┘  └───────────────┘  └───────────────┘
                            │               │
                            │               │
                            ▼               ▼
                    ┌───────────────┐  ┌───────────────┐
                    │     tabs/     │  │    Kafka      │
                    │   Tab Modules │  │   Confluent   │
                    └───────────────┘  │     Cloud     │
                                       └───────────────┘
```

## Module Dependency Graph

```
app.py
├── config.py
│   ├── Environment Variables
│   ├── Theme CSS (A/B/C)
│   ├── Constants (CRITICAL_METHODS, HIGH_METHODS, etc.)
│   └── Timezones
│
├── components/
│   ├── metrics.py → config.py
│   ├── filters.py → config.py
│   └── charts.py → pandas, plotly
│
├── data/
│   ├── email_cache.py
│   │   ├── config.py
│   │   ├── cachetools.LRUCache
│   │   └── Confluent Cloud IAM API
│   │
│   ├── transformations.py
│   │   ├── config.py
│   │   ├── pandas, numpy
│   │   └── data/email_cache.py
│   │
│   ├── kafka_consumer.py
│   │   ├── config.py
│   │   ├── confluent_kafka
│   │   ├── data/transformations.py
│   │   └── data/email_cache.py
│   │
│   └── export.py
│       └── pandas
│
└── tabs/
    ├── audit_trail.py → streamlit, pandas
    ├── failures.py → streamlit, pandas
    ├── deletions.py → streamlit, pandas
    ├── api_keys.py → streamlit, pandas
    ├── security.py → streamlit, pandas, plotly
    ├── details.py → streamlit, pandas
    ├── analytics.py → streamlit, pandas, plotly
    ├── time_insights.py → streamlit, pandas, plotly
    ├── export.py → streamlit, data/export.py
    └── security_alerts.py → streamlit, data/kafka_consumer.py
```

## Data Flow

```
┌──────────────┐
│ Kafka Topics │
│  - CRITICAL  │
│  - HIGH      │
│  - MEDIUM    │
│  - ALERTS    │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────┐
│ data/kafka_consumer.py          │
│ - load_events_from_kafka()      │
│ - load_security_alerts()        │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│ data/transformations.py         │
│ - extract_deep_fields()         │
│ - enhance_events_dataframe()    │
│ - classify_event()              │
│ - detect_anomalies()            │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│ data/email_cache.py             │
│ - enrich_email_from_cache()     │
│ - LRU Cache (10,000 items)      │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│ app.py                          │
│ - Apply filters                 │
│ - Detect anomalies              │
│ - Render metrics                │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│ tabs/*.py                       │
│ - render_tab(df, config)        │
│ - Display data in Streamlit     │
└─────────────────────────────────┘
```

## Component Responsibilities

### config.py
**Purpose**: Centralized configuration
**Responsibilities**:
- Load environment variables
- Define Kafka connection parameters
- Store classification constants
- Define theme CSS
- Configure timezone mappings

### data/email_cache.py
**Purpose**: User email resolution and caching
**Responsibilities**:
- Fetch users from Confluent Cloud IAM API
- Maintain LRU cache (10,000 items) for performance
- Persist cache to email_cache.json
- Extract user IDs from various principal formats
- Enrich DataFrames with email addresses

**Key Classes**:
- `LRUCache` from cachetools (maxsize=10000)

**Key Functions**:
- `initialize_email_cache()` - Load/fetch users on startup
- `enrich_email_from_cache(df, cache)` - Add emails to DataFrame
- `build_cache_from_dataframe(df, cache)` - Extract new mappings

### data/transformations.py
**Purpose**: DataFrame transformations and event processing
**Responsibilities**:
- Extract fields from nested data_json
- Classify event criticality
- Detect failure events
- Add computed columns (user_display, resource_display, etc.)
- Mark internal operations
- Detect anomalies

**Key Functions**:
- `extract_deep_fields(event)` - Parse data_json
- `enhance_events_dataframe(df)` - Add all computed columns
- `classify_event(event)` - CRITICAL/HIGH/MEDIUM
- `is_failure_event(event)` - Boolean failure detection
- `detect_anomalies(df)` - Find unusual patterns

### data/kafka_consumer.py
**Purpose**: Kafka data loading
**Responsibilities**:
- Connect to Confluent Cloud Kafka
- Read from multiple topics in parallel
- Apply time-based filtering
- Deduplicate events
- Enrich data using transformations and email cache

**Key Functions**:
- `load_events_from_kafka()` - Main event loader (cached @st.cache_data)
- `load_security_alerts()` - Load aggregated alerts

**Performance Optimizations**:
- Parallel partition reading
- Early deduplication
- Progress tracking
- Configurable TTL caching (60s)

### data/export.py
**Purpose**: Data export functionality
**Responsibilities**:
- Format DataFrames for export
- Column renaming and selection
- CSV generation
- JSON generation

**Key Functions**:
- `export_to_csv(df)` - CSV with renamed columns
- `export_to_json(df)` - JSON with timestamp conversion

### components/metrics.py
**Purpose**: Metric card rendering
**Responsibilities**:
- Render HTML metric cards
- Color-coded values

**Key Functions**:
- `render_metric_card(label, value, color)` - HTML metric card

### components/filters.py
**Purpose**: Filter UI components
**Responsibilities**:
- Render alert banners
- Render quick filter buttons
- Apply filter logic to DataFrames

**Key Functions**:
- `render_alert_banner(anomalies)` - Display alerts
- `render_quick_filters(current_filter)` - Button grid
- `apply_quick_filter(df, filter_key)` - Filter logic

### components/charts.py
**Purpose**: Plotly chart generation
**Responsibilities**:
- Create all visualizations
- Consistent styling
- Handle empty data gracefully

**Key Functions**:
- `create_timeline_chart(df)` - Events over time
- `create_method_distribution_chart(df)` - Pie chart
- `create_user_activity_chart(df)` - Bar chart
- `create_failure_distribution_chart(df)` - Success vs failures
- `create_hour_of_day_chart(df)` - Hourly activity
- `create_day_of_week_chart(df)` - Daily activity
- And 4 more chart types...

### tabs/*.py
**Purpose**: Individual tab rendering
**Responsibilities**:
- Render tab-specific UI
- Filter data for tab context
- Display tables with appropriate columns
- Show relevant visualizations

**Standard Interface**:
```python
def render_tab(df, config=None):
    """Render the tab"""
    # Tab-specific logic
    pass
```

**Available Tabs**:
1. audit_trail - Complete audit trail
2. failures - All failures
3. deletions - Deletion events
4. api_keys - API key operations
5. security - RBAC/ACL details
6. details - Event inspector
7. analytics - Charts and visualizations
8. time_insights - Time-based analysis
9. export - CSV/JSON download
10. security_alerts - Aggregated alerts

## Performance Considerations

### Caching Strategy
```
┌─────────────────────────────────────────────────────┐
│ Streamlit @st.cache_data (TTL: 60s)                 │
│ - load_events_from_kafka() result cached            │
│ - Reduces Kafka consumption frequency                │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│ LRU Cache (10,000 items)                            │
│ - Email lookups cached in memory                     │
│ - Automatic eviction of old entries                  │
│ - Persistent to email_cache.json                     │
└─────────────────────────────────────────────────────┘
```

### Data Processing Pipeline
```
Kafka → DataFrame Creation → Early Deduplication →
  ↓
Time Filtering → enhance_events_dataframe() →
  ↓
Email Enrichment (LRU Cache) → Display
```

## Error Handling

### Graceful Degradation
- Missing columns handled with `.get()` and existence checks
- Empty DataFrames return early with info messages
- Missing config falls back to defaults
- API failures logged but don't crash app

### User Feedback
- Progress bars during Kafka loading
- Clear error messages for missing config
- Info boxes when no data available
- Suggestions for troubleshooting

## Security Considerations

### Secrets Management
- All sensitive data in `.env` and `.secrets`
- No hardcoded credentials
- Docker secrets via `--env-file`

### Data Privacy
- Email cache persists locally only
- No data sent to external services except Confluent Cloud IAM API
- User data stays within Kafka and dashboard

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│             Docker Container                        │
│  ┌───────────────────────────────────────────────┐ │
│  │  Streamlit App (Port 8501)                    │ │
│  │  ├── app.py                                   │ │
│  │  ├── config.py                                │ │
│  │  ├── components/                              │ │
│  │  ├── data/                                    │ │
│  │  └── tabs/                                    │ │
│  └───────────────────────────────────────────────┘ │
│         │                                           │
│         │ Reads from                                │
│         ▼                                           │
│  ┌───────────────────────────────────────────────┐ │
│  │  Volume Mounts                                 │ │
│  │  ├── .env (Kafka config)                      │ │
│  │  ├── .secrets (API keys)                      │ │
│  │  ├── email_cache.json (persistent)            │ │
│  │  └── user_mapping.json (fallback)             │ │
│  └───────────────────────────────────────────────┘ │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ Connects to
                   ▼
┌─────────────────────────────────────────────────────┐
│         Confluent Cloud Kafka                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐   │
│  │  CRITICAL  │  │    HIGH    │  │   MEDIUM   │   │
│  │   Topic    │  │   Topic    │  │   Topic    │   │
│  └────────────┘  └────────────┘  └────────────┘   │
│  ┌────────────┐                                    │
│  │   ALERTS   │  Confluent Cloud IAM API           │
│  │   Topic    │  (User lookups)                    │
│  └────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

## File Size Comparison

| File | Before | After | Change |
|------|--------|-------|--------|
| app.py | 2,667 lines | 229 lines | -91% |
| config.py | - | 431 lines | +431 |
| data/ modules | - | ~800 lines | +800 |
| components/ modules | - | ~200 lines | +200 |
| tabs/ modules | - | ~1,000 lines | +1,000 |
| **Total** | **2,667** | **~2,660** | Reorganized |

**Key Insight**: Same amount of code, but now organized into 20+ focused modules instead of one giant file.

## Benefits Summary

✅ **Maintainability**: Easy to find and modify features
✅ **Testability**: Modules can be tested independently
✅ **Reusability**: Functions easily imported
✅ **Scalability**: Simple to add new features
✅ **Readability**: Clear separation of concerns
✅ **Performance**: LRU caching for email lookups
✅ **Collaboration**: Multiple developers can work in parallel

## Future Enhancements

1. **Testing**: Add pytest unit tests for each module
2. **Type Hints**: Add type annotations for better IDE support
3. **Documentation**: Auto-generate docs from docstrings
4. **Utilities**: Extract common utilities to utils/ module
5. **Monitoring**: Add structured logging
6. **Configuration**: Move more hardcoded values to config
