# Changelog

All notable changes to AuditLens are documented in this file.

## [2.2.0] - 2025-12-14

### Added

#### Forwarder
- **Dead Letter Queue (DLQ)**: Failed events are now sent to `audit_events_dlq` topic for later reprocessing
  - Includes original event, error message, source topic/partition/offset, timestamp
  - Configurable via `ENABLE_DLQ` and `DLQ_TOPIC` environment variables
- **DLQ metrics in heartbeat**: Logs now show `DLQ: X sent/Y failed` every 30 seconds
- **Bounded LRU offset cache**: Prevents memory leaks with `LRUCache(maxsize=500)`

#### Dashboard
- **Non-blocking auto-refresh**: Uses `streamlit-autorefresh` instead of blocking `time.sleep()`
- **orjson parsing**: 2-3x faster JSON parsing in Kafka consumer

#### Infrastructure
- **Complete AWS Fargate Terraform**: Production-ready deployment configuration
  - VPC with public/private subnets
  - ECR repositories with lifecycle policies
  - ECS cluster with Fargate/Fargate Spot support
  - Application Load Balancer
  - AWS Secrets Manager integration
  - CloudWatch logs, alarms, and dashboard
  - IAM roles with least-privilege policies

### Changed

#### Forwarder
- **Producer reliability**: Changed `acks="1"` to `acks="all"` for zero data loss
- **Idempotence enabled**: `enable.idempotence=True` for exactly-once semantics
- **Heartbeat logging**: Now includes DLQ statistics

#### Dashboard
- **Static consumer groups**: Changed from `dashboard-viewer-{timestamp}` to `auditlens-dashboard-viewer`
  - Prevents consumer group explosion in Confluent Cloud
  - Reduces API calls and improves monitoring clarity
- **Version bump**: v10.18 → v10.19

### Fixed
- Dashboard UI freeze during 60-second auto-refresh countdown
- Potential memory leak from unbounded offset cache dictionary
- Consumer group proliferation causing Confluent Cloud clutter

### Security
- Producer now uses `acks=all` + idempotence for audit data integrity
- Failed events preserved in DLQ instead of being lost
- Secrets stored in AWS Secrets Manager (Terraform)

---

## [2.1.0] - 2025-12-13

### Added
- Multi-topic routing (CRITICAL/HIGH/MEDIUM/LOW)
- Security alerts aggregation with denial pattern detection
- Webhook retry with tenacity
- Non-root container support
- Secrets management with 6 backend support

### Dashboard v10.18
- Theme toggle (Pastel/Clean/Professional)
- Filter presets (save/load)
- PDF compliance report export
- Clickable metric cards
- Activity heatmap in Time Insights
- Keyboard shortcuts

---

## [2.0.0] - 2025-12-08

### Added
- Initial multi-topic routing architecture
- Criticality-based event classification
- Prometheus metrics endpoint
- Docker Compose deployment
- Grafana dashboards

---

## Version Numbering

- **Major (X.0.0)**: Breaking changes, architecture changes
- **Minor (0.X.0)**: New features, non-breaking
- **Patch (0.0.X)**: Bug fixes, performance improvements
