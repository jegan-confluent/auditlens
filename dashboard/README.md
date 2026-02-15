# Audit Log Intelligence Dashboard

A Streamlit dashboard for monitoring Confluent Cloud audit events in real-time.

## Features

- **Overview Panel**: Event counts by criticality level with distribution charts
- **Critical Events Feed**: Real-time list of CRITICAL and HIGH priority events
- **Anomaly Alerts**: Detected anomalies and security failures
- **Activity Analysis**: Top principals and methods by event count
- **Event Table**: Searchable, filterable event details with CSV export

## Prerequisites

- Python 3.9+
- Access to Confluent Cloud Kafka cluster
- Environment variables configured (see below)

## Installation

```bash
cd dashboard
pip install -r requirements.txt
```

## Configuration

Create `.env` and `.secrets` files in the parent directory with:

```bash
# .env
DEST_BOOTSTRAP=your-kafka-bootstrap-server:9092

# .secrets
DEST_API_KEY=your-api-key
DEST_API_SECRET=your-api-secret
```

## Running the Dashboard

```bash
cd dashboard
streamlit run app.py --server.port 8503
```

Then open http://localhost:8503 in your browser.

## Features

### Filters (Sidebar)

- **Time Range**: Last Hour, 6 Hours, 24 Hours, 7 Days
- **Criticality Level**: All, CRITICAL, HIGH, MEDIUM, LOW
- **Principal Filter**: Search by principal name
- **Method Filter**: Search by method name
- **Auto-refresh**: Enable 30-second automatic refresh

### Tabs

1. **Overview**: Metrics and distribution charts
2. **Critical Events**: Expandable cards for CRITICAL/HIGH events
3. **Anomalies**: Detected anomalies and security failures
4. **Activity**: Top principals and methods charts
5. **Event Table**: Full event details with export

## Metrics Integration

The dashboard can connect to the forwarder's metrics endpoint (default: http://localhost:8003/metrics) to display:

- Events processed/forwarded counts
- Error counts
- Anomaly detection statistics
- Forwarder health status

## Troubleshooting

### No events displayed

1. Check that the Kafka credentials are correct
2. Verify the `audit_events_flattened` topic exists
3. Ensure the forwarder is running and producing events

### Slow loading

1. Reduce the time range filter
2. Add more specific filters (criticality, principal, method)
3. Check network connectivity to Kafka cluster

### Forwarder status shows "Unreachable"

1. Ensure the forwarder is running with metrics enabled
2. Check the metrics port (default 8003)
3. Verify firewall/network allows localhost connections
