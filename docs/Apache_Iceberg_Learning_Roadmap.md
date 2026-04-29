# Apache Iceberg Expert Learning Roadmap
**From Beginner to Production Expert in 8 Weeks**

---

## Document Information

**Author:** Jegan K
**Date:** March 12, 2026
**Version:** 1.0
**Purpose:** Comprehensive learning roadmap for Apache Iceberg and Confluent Tableflow expertise

---

## Executive Summary

This roadmap provides a structured 8-week learning path to become an Apache Iceberg expert, with focus on Confluent Tableflow integration. The program covers fundamental concepts, architectural deep-dives, hands-on practice, and production deployment scenarios.

**Time Commitment:** 2-3 hours per day, 5 days per week
**Total Duration:** 8 weeks
**Outcome:** Production-ready expertise in Apache Iceberg and Tableflow

---

## Learning Journey Overview

### Phase Distribution

| Phase | Duration | Focus | Proficiency Level |
|-------|----------|-------|------------------|
| **Beginner** | Week 1-2 | Concepts & Context | Understanding "Why" |
| **Intermediate** | Week 3-4 | Architecture & Labs | Understanding "How" |
| **Advanced** | Week 5-7 | Features & Optimization | Mastery |
| **Expert** | Week 8 | Production & Design | Expertise |

### Learning Progression

```
BEGINNER (Week 1-2)
├─ Historical context
├─ Core concepts
├─ Iceberg vs alternatives
└─ Ecosystem overview
      ↓
INTERMEDIATE (Week 3-4)
├─ 3-layer architecture
├─ Metadata management
├─ Query execution flow
└─ Hands-on labs
      ↓
ADVANCED (Week 5-7)
├─ Schema & partition evolution
├─ Performance tuning
├─ Integration patterns
└─ Table maintenance
      ↓
EXPERT (Week 8)
├─ Production architecture design
├─ Multi-catalog integration
├─ Performance troubleshooting
└─ Cost optimization
```

---

## Week 1-2: Beginner Level
**The "Why" Phase**

### Learning Objectives

By the end of Week 2, you will be able to:
- ✅ Explain why Apache Iceberg was created
- ✅ Articulate the problems it solves vs traditional Hive
- ✅ Compare Iceberg with Delta Lake and Apache Hudi
- ✅ Identify when to use Iceberg in real-world scenarios
- ✅ Understand Tableflow's role in the Iceberg ecosystem

### Topics to Master

#### 1. Historical Context (4 hours)

**The Problem Era (Pre-Iceberg):**
- Traditional data lakes used Hive metastore
- Directory-based partitioning (fragile, error-prone)
- Expensive file listing operations for queries
- No consistent snapshots or ACID transactions
- Schema evolution required full table rewrites
- No time travel or audit capabilities

**Why Netflix Created Iceberg:**
- Managing petabyte-scale data lakes
- Need for ACID guarantees on object storage
- Support for schema and partition evolution
- Enable concurrent reads and writes
- Improve query performance through metadata optimization

**The Solution:**
Apache Iceberg emerged as an open table format that brings database-like capabilities (ACID, schema evolution, time travel) to object storage (S3, ADLS, GCS).

#### 2. Open Table Formats Comparison (3 hours)

**Iceberg vs Delta Lake vs Hudi:**

| Criteria | Apache Iceberg | Delta Lake | Apache Hudi |
|----------|---------------|------------|-------------|
| **Origin** | Netflix (2017) | Databricks (2019) | Uber (2016) |
| **Governance** | Apache Foundation | Linux Foundation | Apache Foundation |
| **Metadata Design** | 3-layer (efficient) | 2-layer (transaction log) | Timeline-based |
| **Partition Evolution** | ✅ Built-in | ❌ Requires rewrites | ❌ Requires rewrites |
| **Schema Evolution** | ✅ Excellent | ✅ Excellent | ✅ Good |
| **Time Travel** | ✅ Snapshots | ✅ Versions | ✅ Timeline |
| **Ecosystem Support** | 20+ engines | Strong (Databricks-focused) | Good (Spark-focused) |
| **Upsert/Merge** | ✅ Supported | ✅ Optimized | ✅ Best-in-class |
| **Vendor Lock-in** | ✅ Low | ⚠️ Databricks-centric | ✅ Low |
| **Best For** | Broad ecosystem, vendor neutrality | Databricks users | Upsert-heavy workloads |

**Decision Framework:**
- **Choose Iceberg:** Multi-engine compatibility, partition evolution, vendor independence
- **Choose Delta Lake:** Deep Databricks integration, strong streaming support
- **Choose Hudi:** Upsert-heavy CDC workloads, incremental processing

#### 3. Core Concepts (4 hours)

**Table Format Fundamentals:**
- **Table:** Logical collection of data with schema
- **Schema:** Column names, types, and metadata
- **Snapshot:** Point-in-time state of the table
- **Partition:** Logical division of data for query optimization
- **Manifest:** Metadata file listing data files

**Key Features:**
1. **ACID Transactions** - Atomic, Consistent, Isolated, Durable operations
2. **Schema Evolution** - Add/drop/rename columns without rewrites
3. **Partition Evolution** - Change partitioning strategy on existing tables
4. **Time Travel** - Query historical table states
5. **Hidden Partitioning** - Users don't write partition logic in queries
6. **Snapshot Isolation** - Consistent reads even during writes

#### 4. Ecosystem Overview (2 hours)

**Compatible Query Engines (20+):**
- **Batch:** Apache Spark, Apache Hive, Trino, Presto, Athena
- **Streaming:** Apache Flink, Kafka (via Tableflow)
- **Warehouses:** Snowflake, Databricks, Google BigQuery
- **Analytics:** Dremio, Starburst, AWS Athena, Azure Synapse

**Catalog Integrations:**
- AWS Glue Catalog
- Databricks Unity Catalog
- Apache Polaris (Snowflake)
- Confluent Iceberg REST Catalog (IRC)
- Nessie (Project Nessie)

#### 5. Confluent Tableflow Connection (3 hours)

**What is Tableflow?**
Confluent's fully managed service that materializes Kafka topics as Apache Iceberg or Delta Lake tables with a single click.

**How Tableflow Uses Iceberg:**
1. Reads Kafka topic data and Schema Registry schemas
2. Converts Kafka segments to Parquet files (via Kora Storage Layer)
3. Generates Iceberg metadata (manifest lists, manifests, metadata files)
4. Publishes to Iceberg REST Catalog or external catalogs
5. Handles schema evolution, type conversions, and table maintenance

**Benefits:**
- Zero-code Kafka → Iceberg pipeline
- Real-time data availability for analytics
- 30-50% cost savings vs traditional ETL
- Automatic schema mapping and evolution
- Built-in table maintenance (compaction, cleanup)

### Weekly Milestones

**Week 1:**
- [ ] Complete historical context reading
- [ ] Watch: Apache Iceberg 101 course (Confluent Developer)
- [ ] Create comparison table of Iceberg vs Delta vs Hudi
- [ ] Document 5 use cases where Iceberg is ideal

**Week 2:**
- [ ] Read: Introducing Tableflow blog post
- [ ] Understand Tableflow architecture
- [ ] Identify 3 customer scenarios for Tableflow
- [ ] Pass beginner quiz (90%+ score)

### Resources

**Official Documentation:**
- [Apache Iceberg Official Docs](https://iceberg.apache.org/)
- [Confluent Tableflow Documentation](https://docs.confluent.io/cloud/current/tableflow/)

**Courses:**
- [Confluent Developer: Apache Iceberg Course](https://developer.confluent.io/courses/)
- [Apache Iceberg + Tableflow Course Outline](https://confluentinc.atlassian.net/wiki/spaces/DEVX/pages/4281860372)

**Blogs:**
- [Introducing Tableflow: Unifying Streaming and Analytics](https://www.confluent.io/blog/introducing-tableflow/)
- [Tableflow is Now Generally Available](https://www.confluent.io/blog/tableflow-is-now-generally-available/)

### Assessment Criteria

You're ready for Week 3 when you can:
- ✅ Explain Iceberg's origin and purpose in 5 minutes
- ✅ Identify when to use Iceberg vs Delta Lake vs Hudi
- ✅ Describe Tableflow's value proposition
- ✅ List 5+ query engines compatible with Iceberg
- ✅ Score 90%+ on beginner quiz

---

## Week 3-4: Intermediate Level
**The "How" Phase**

### Learning Objectives

By the end of Week 4, you will be able to:
- ✅ Explain the 3-layer Iceberg architecture in detail
- ✅ Trace how a query uses metadata to prune files
- ✅ Understand snapshot lifecycle and time travel mechanics
- ✅ Perform schema evolution operations
- ✅ Set up and query Iceberg tables via Tableflow

### Topics to Master

#### 1. Catalog Layer (4 hours)

**What is a Catalog?**
The catalog is the entry point for accessing Iceberg tables. It stores the location of the current metadata file for each table.

**Catalog Types:**

| Catalog Type | Use Case | Pros | Cons |
|-------------|----------|------|------|
| **Hadoop Catalog** | Development/testing | Simple, file-based | Not recommended for production |
| **Hive Metastore** | Legacy integration | Existing Hive compatibility | Limited concurrency |
| **AWS Glue** | AWS production | Managed, serverless | AWS-only |
| **Polaris (Snowflake)** | Multi-engine | Open, vendor-neutral | Newer project |
| **Unity Catalog** | Databricks | Unified governance | Databricks-centric |
| **Iceberg REST Catalog** | Tableflow, modern apps | Standard API, portable | Requires REST server |

**How Catalog Works:**
1. Client requests table location from catalog
2. Catalog returns path to current metadata file
3. Client reads metadata file from object storage
4. Client follows metadata → manifest list → manifest → data files

**Tableflow's Iceberg REST Catalog (IRC):**
- Built-in catalog provided by Confluent
- Supports standard Iceberg REST API
- Automatically managed for Tableflow-enabled topics
- Compatible with any Iceberg REST client

#### 2. Metadata Layer (6 hours)

**Metadata File Structure (JSON):**

```json
{
  "format-version": 2,
  "table-uuid": "unique-uuid",
  "location": "s3://bucket/warehouse/db/table",
  "last-updated-ms": 1678900000000,
  "schema": {
    "type": "struct",
    "schema-id": 0,
    "fields": [
      {"id": 1, "name": "id", "required": true, "type": "long"},
      {"id": 2, "name": "data", "required": false, "type": "string"}
    ]
  },
  "partition-spec": [...],
  "default-spec-id": 0,
  "current-snapshot-id": 3051729675574597004,
  "snapshots": [...],
  "snapshot-log": [...],
  "metadata-log": [...]
}
```

**Key Metadata Components:**
- **Schema:** Column definitions with IDs (immutable)
- **Partition Spec:** How data is partitioned
- **Current Snapshot ID:** Points to latest snapshot
- **Snapshots:** List of all table snapshots
- **Snapshot Log:** History of snapshot changes

**Metadata Evolution:**
- New metadata file created for every table change
- Old metadata files retained for time travel
- Metadata files are immutable (append-only)

**Snapshot Structure:**

```json
{
  "snapshot-id": 3051729675574597004,
  "timestamp-ms": 1678900000000,
  "manifest-list": "s3://bucket/.../snap-123-1-manifest-list.avro",
  "summary": {
    "operation": "append",
    "added-files-count": "5",
    "total-records": "1000000"
  }
}
```

#### 3. Manifest Layer (5 hours)

**Manifest List (AVRO):**
Lists all manifest files for a snapshot, with partition summaries.

**Manifest List Fields:**
- `manifest_path`: Location of manifest file
- `partition_spec_id`: Which partition spec is used
- `added_files_count`: Files added in this manifest
- `existing_files_count`: Existing files referenced
- `deleted_files_count`: Files marked as deleted
- `partition_summaries`: Min/max values per partition

**Manifest (AVRO):**
Lists individual data files with detailed statistics.

**Manifest Entry Fields:**
- `status`: ADDED, EXISTING, or DELETED
- `data_file`:
  - `file_path`: S3 path to Parquet file
  - `file_format`: PARQUET, ORC, AVRO
  - `partition`: Partition values
  - `record_count`: Number of records
  - `file_size_in_bytes`: File size
  - `column_sizes`: Size per column
  - `value_counts`: Count per column
  - `null_value_counts`: Nulls per column
  - `lower_bounds`: Min values per column
  - `upper_bounds`: Max values per column

**How Manifests Enable Query Optimization:**
1. Query planner reads metadata file
2. Identifies relevant snapshots
3. Reads manifest list for snapshot
4. Prunes manifests based on partition summaries
5. Reads remaining manifests
6. Prunes data files based on column statistics
7. Only reads necessary Parquet files

#### 4. Data Layer (3 hours)

**Data Files (Parquet):**
- Columnar storage format
- Optimized for analytics queries
- Support compression (Snappy, GZIP, LZ4)
- Self-describing with embedded schema

**File Organization:**
```
s3://bucket/warehouse/db/table/
  data/
    year=2024/
      month=01/
        00000-0-data-file-1.parquet
        00001-0-data-file-2.parquet
    year=2024/
      month=02/
        00002-0-data-file-3.parquet
```

**File Sizing Best Practices:**
- Target: 128 MB - 512 MB per file
- Too small: Metadata overhead, slow queries
- Too large: Less parallelism, memory issues

**Tableflow Data Files:**
- Automatically converted from Kafka segments
- Uses Kora Storage Layer for transformation
- Parquet files stored in S3 or ADLS
- Automatic file sizing and compaction

### Hands-On Labs

#### Lab 1: Create Iceberg Table via Tableflow (2 hours)

**Prerequisites:**
- Confluent Cloud account
- Kafka topic with schema in Schema Registry
- AWS or Azure account (for BYOS option)

**Steps:**
1. Navigate to Confluent Cloud → Topics
2. Select topic → Tableflow tab
3. Click "Enable Tableflow"
4. Choose storage: Confluent Managed or BYOS
5. Select table format: Iceberg or Delta Lake
6. Configure settings (freshness, retention, DLQ)
7. Enable and wait for materialization

**Validation:**
```sql
-- Query via Athena, Snowflake, or Spark
SELECT * FROM iceberg_table LIMIT 10;
```

#### Lab 2: Inspect Metadata Files (2 hours)

**Download metadata file:**
```bash
aws s3 cp s3://bucket/warehouse/db/table/metadata/v1.metadata.json .
jq . v1.metadata.json
```

**Analyze structure:**
- Identify current snapshot ID
- Count total snapshots
- Review schema fields
- Check partition spec

#### Lab 3: Query Manifest Files (2 hours)

**Install avro-tools:**
```bash
brew install avro-tools  # Mac
apt-get install avro-tools  # Linux
```

**Read manifest list:**
```bash
avro-tools tojson manifest-list.avro | jq .
```

**Read manifest:**
```bash
avro-tools tojson manifest.avro | jq .
```

#### Lab 4: Schema Evolution (3 hours)

**Add column:**
```sql
-- Spark SQL
ALTER TABLE iceberg_table ADD COLUMN new_column STRING;
```

**Verify:**
```bash
# Check metadata file shows new schema version
jq '.schemas' metadata.json
```

**Query old vs new snapshots:**
```sql
-- Query current state
SELECT * FROM iceberg_table;

-- Query before schema change (time travel)
SELECT * FROM iceberg_table
TIMESTAMP AS OF '2024-03-10 10:00:00';
```

#### Lab 5: Time Travel Queries (2 hours)

**Query by timestamp:**
```sql
SELECT * FROM iceberg_table
TIMESTAMP AS OF '2024-03-10 00:00:00';
```

**Query by snapshot ID:**
```sql
SELECT * FROM iceberg_table
VERSION AS OF 3051729675574597004;
```

**List all snapshots:**
```sql
SELECT * FROM iceberg_table.snapshots;
```

### Weekly Milestones

**Week 3:**
- [ ] Draw 3-layer architecture from memory
- [ ] Complete Lab 1: Create Iceberg table via Tableflow
- [ ] Complete Lab 2: Inspect metadata files
- [ ] Document query execution flow

**Week 4:**
- [ ] Complete Lab 3: Query manifest files
- [ ] Complete Lab 4: Schema evolution
- [ ] Complete Lab 5: Time travel queries
- [ ] Pass intermediate quiz (90%+ score)

### Resources

**Architecture Documentation:**
- [Iceberg Table Spec](https://iceberg.apache.org/spec/)
- [Tableflow System Architecture](https://confluentinc.atlassian.net/wiki/spaces/KORAGE/pages/4544528407)

**Video Tutorials:**
- YouTube: "Architecture & Concepts | Apache Iceberg + Tableflow"
- YouTube: "Catalog | Apache Iceberg + Tableflow"
- YouTube: "Metadata Tables | Apache Iceberg + Tableflow"

### Assessment Criteria

You're ready for Week 5 when you can:
- ✅ Draw and explain 3-layer architecture without notes
- ✅ Trace query execution through metadata layers
- ✅ Perform schema evolution on live table
- ✅ Execute time travel queries successfully
- ✅ Inspect and interpret manifest files

---

## Week 5-7: Advanced Level
**The "Mastery" Phase**

### Week 5: Advanced Features (20 hours)

#### 1. Snapshots & Time Travel (5 hours)

**Snapshot Lifecycle:**
1. Write operation begins (INSERT, UPDATE, DELETE)
2. New data files written to object storage
3. New manifest files created referencing data files
4. New manifest list created
5. New metadata file created pointing to manifest list
6. Catalog updated to point to new metadata file
7. Previous snapshot remains accessible

**Time Travel Use Cases:**
- **Audit:** "What did this table look like yesterday?"
- **Debugging:** "What changed between these two versions?"
- **Recovery:** "Restore table to state before bad write"
- **Reproducibility:** "Re-run ML training with exact same data"

**Time Travel Syntax:**

```sql
-- Spark SQL
SELECT * FROM iceberg_table
TIMESTAMP AS OF '2024-03-10 10:00:00';

SELECT * FROM iceberg_table
VERSION AS OF 3051729675574597004;

-- List snapshots
SELECT * FROM iceberg_table.snapshots;

-- Rollback to previous snapshot
CALL catalog.system.rollback_to_snapshot('db.table', 3051729675574597004);
```

**Snapshot Expiration:**
```sql
-- Set retention to 7 days
ALTER TABLE iceberg_table
SET TBLPROPERTIES (
  'history.expire.max-snapshot-age-ms'='604800000'
);

-- Manual expiration
CALL catalog.system.expire_snapshots('db.table',
  TIMESTAMP '2024-03-01 00:00:00');
```

#### 2. Schema Evolution (5 hours)

**Supported Operations:**
- ✅ Add columns (nullable or with defaults)
- ✅ Drop columns (data remains in files)
- ✅ Rename columns (logical only)
- ✅ Update column types (widening only)
- ✅ Reorder columns (logical only)

**Schema Evolution Examples:**

```sql
-- Add column
ALTER TABLE iceberg_table ADD COLUMN email STRING;

-- Drop column
ALTER TABLE iceberg_table DROP COLUMN old_field;

-- Rename column
ALTER TABLE iceberg_table RENAME COLUMN name TO full_name;

-- Widen type (INT → LONG)
ALTER TABLE iceberg_table
ALTER COLUMN user_id TYPE BIGINT;

-- Reorder columns
ALTER TABLE iceberg_table
ALTER COLUMN email FIRST;
```

**Schema ID Tracking:**
- Each schema version gets unique ID
- Column IDs are immutable (never reused)
- Enables backward compatibility

**Tableflow Schema Evolution:**
- Automatically detects Schema Registry changes
- Maps Avro/Protobuf/JSON Schema to Parquet
- Handles type conversions safely
- No manual intervention required

#### 3. Partition Evolution (5 hours)

**What is Partition Evolution?**
Change partitioning strategy on existing table without rewriting data.

**Example Scenario:**
```
Initial: Partitioned by day (year/month/day)
Later: Data grows, switch to hour (year/month/day/hour)
```

**Traditional Approach (Hive):**
1. Create new table with new partition scheme
2. Copy all data to new table (expensive!)
3. Drop old table
4. Rename new table

**Iceberg Approach:**
```sql
-- Original partition spec (ID 0)
CREATE TABLE events (
  id BIGINT,
  timestamp TIMESTAMP,
  data STRING
) PARTITIONED BY (days(timestamp));

-- Add hourly partition spec (ID 1)
ALTER TABLE events
ADD PARTITION FIELD hours(timestamp);

-- New data uses hourly partitions
-- Old data keeps daily partitions
-- Queries work seamlessly across both!
```

**Hidden Partitioning:**
Users don't write partition logic in queries:

```sql
-- Traditional Hive (partition aware)
SELECT * FROM events
WHERE year=2024 AND month=3 AND day=10;

-- Iceberg (partition hidden)
SELECT * FROM events
WHERE timestamp BETWEEN '2024-03-10' AND '2024-03-11';
-- Iceberg automatically prunes partitions!
```

#### 4. ACID Transactions (3 hours)

**Atomicity:**
All changes committed as single unit or none at all.

**Consistency:**
Table always in valid state (schema constraints enforced).

**Isolation:**
Snapshot isolation prevents dirty reads.

**Durability:**
Committed changes persisted to object storage.

**Optimistic Concurrency:**
```
Writer 1: Read metadata v10 → Write → Commit v11
Writer 2: Read metadata v10 → Write → Commit fails (conflict!)
Writer 2: Retry from v11 → Write → Commit v12
```

**Tableflow ACID Guarantees:**
- `acks=all` on Kafka producer
- Idempotent writes
- Atomic snapshot commits
- No data loss or duplication

#### 5. Table Maintenance (2 hours)

**Why Maintenance Needed:**
- Small files accumulate (slow queries)
- Delete files not physically removed
- Old snapshots consume storage
- Orphan files from failed writes

**Maintenance Operations:**

**1. Compaction (File Rewriting):**
```sql
CALL catalog.system.rewrite_data_files(
  table => 'db.table',
  options => map(
    'target-file-size-bytes', '536870912',  -- 512 MB
    'min-input-files', '5'
  )
);
```

**2. Orphan File Deletion:**
```sql
CALL catalog.system.remove_orphan_files(
  table => 'db.table',
  older_than => TIMESTAMP '2024-03-01 00:00:00'
);
```

**3. Snapshot Expiration:**
```sql
CALL catalog.system.expire_snapshots(
  table => 'db.table',
  older_than => TIMESTAMP '2024-03-01 00:00:00',
  retain_last => 100
);
```

**4. Metadata Cleanup:**
```sql
CALL catalog.system.remove_old_metadata(
  table => 'db.table',
  older_than => TIMESTAMP '2024-02-01 00:00:00'
);
```

**Tableflow Automatic Maintenance:**
- Compaction: Configurable (default: daily)
- Snapshot expiration: Configurable (default: infinite)
- Orphan cleanup: Automatic
- Metadata cleanup: Automatic

### Week 6: Performance Optimization (20 hours)

#### 1. Query Performance Tuning (6 hours)

**File Pruning Optimization:**

**Problem:** Too many small files
**Solution:** Compaction
```sql
-- Target 256 MB files
CALL rewrite_data_files(
  'db.table',
  map('target-file-size-bytes', '268435456')
);
```

**Problem:** Poor partition pruning
**Solution:** Partition evolution or hidden partitioning
```sql
-- Use appropriate partition granularity
-- Daily for moderate volume
-- Hourly for high volume
-- Monthly for low volume
```

**Statistics-Based Optimization:**
- Ensure manifests have accurate min/max bounds
- Use bloom filters for high-cardinality columns
- Enable column-level metrics

#### 2. Write Performance Tuning (5 hours)

**Batch vs Streaming Writes:**

**Batch (Spark):**
```python
df.write \
  .format("iceberg") \
  .mode("append") \
  .option("write.parquet.compression-codec", "snappy") \
  .option("write.target-file-size-bytes", 536870912) \
  .save("db.table")
```

**Streaming (Flink/Tableflow):**
- Micro-batches (Tableflow: 15 min default)
- Automatic file sizing
- Concurrent writes supported

**Concurrent Write Handling:**
- Use REST Catalog or Glue (not Hadoop)
- Enable optimistic concurrency
- Implement retry logic for conflicts

#### 3. Catalog Performance (4 hours)

**Catalog Selection Impact:**

| Catalog | Latency | Concurrency | Best For |
|---------|---------|-------------|----------|
| Hadoop | High | Poor | Development only |
| Hive Metastore | Medium | Medium | Legacy systems |
| AWS Glue | Low | High | AWS production |
| REST Catalog | Low | High | Modern apps |
| Polaris | Low | High | Multi-cloud |

**Metadata Caching:**
- Client-side metadata caching reduces catalog calls
- TTL-based invalidation
- Shared metadata cache for query engines

#### 4. Storage Optimization (3 hours)

**File Format Tuning:**

```python
# Parquet compression
spark.conf.set("spark.sql.parquet.compression.codec", "snappy")

# Row group size
spark.conf.set("spark.sql.parquet.block.size", 134217728)  # 128 MB

# Column index
spark.conf.set("spark.sql.parquet.enableVectorizedReader", "true")
```

**Storage Tiering:**
- Hot data: Standard S3
- Warm data: S3 Infrequent Access
- Cold data: S3 Glacier (with expiration)

#### 5. Monitoring & Metrics (2 hours)

**Key Metrics to Track:**

**Table Health:**
- Number of data files
- Average file size
- Number of snapshots
- Metadata file count
- Manifest file count

**Query Performance:**
- Files scanned per query
- Bytes scanned per query
- Partition pruning effectiveness
- Query planning time

**Write Performance:**
- Write throughput (records/sec)
- File creation rate
- Compaction frequency
- Snapshot creation rate

**Tableflow Metrics (Datadog Integration):**
- Throughput (MB/s)
- Lag (freshness)
- Storage utilization
- Compaction status
- Health status

### Week 7: Integration Patterns (20 hours)

#### 1. Tableflow → Iceberg (4 hours)

**Setup:**
```yaml
Topic: orders
Schema: Avro in Schema Registry
Tableflow: Enabled with Iceberg format
Storage: AWS S3 (BYOS)
Catalog: Confluent IRC + AWS Glue sync
```

**Configuration:**
- Data freshness: 15 minutes
- Snapshot retention: 7 days
- DLQ: Enabled for schema violations
- Compaction: Daily

**Access Pattern:**
```sql
-- Athena
SELECT * FROM glue_catalog.db.orders
WHERE order_date = '2024-03-10';

-- Snowflake
SELECT * FROM external_iceberg.orders
WHERE order_date = CURRENT_DATE;
```

#### 2. Flink → Iceberg (4 hours)

**Flink SQL DDL:**
```sql
CREATE CATALOG iceberg_catalog WITH (
  'type' = 'iceberg',
  'catalog-type' = 'rest',
  'uri' = 'https://rest-catalog:8181',
  'warehouse' = 's3://bucket/warehouse'
);

CREATE TABLE iceberg_catalog.db.processed_events (
  event_id BIGINT,
  event_type STRING,
  event_time TIMESTAMP(3),
  payload STRING
) WITH (
  'write.format.default' = 'parquet',
  'write.target-file-size-bytes' = '134217728'
);
```

**Flink Stream to Iceberg:**
```sql
INSERT INTO iceberg_catalog.db.processed_events
SELECT
  event_id,
  event_type,
  event_time,
  payload
FROM kafka_source_table
WHERE event_type != 'HEARTBEAT';
```

#### 3. Spark → Iceberg (3 hours)

**Batch Write:**
```python
from pyspark.sql import SparkSession

spark = SparkSession.builder \
  .appName("IcebergWrite") \
  .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions") \
  .config("spark.sql.catalog.my_catalog", "org.apache.iceberg.spark.SparkCatalog") \
  .config("spark.sql.catalog.my_catalog.type", "rest") \
  .config("spark.sql.catalog.my_catalog.uri", "https://rest-catalog:8181") \
  .getOrCreate()

# Read from Kafka
df = spark.readStream \
  .format("kafka") \
  .option("kafka.bootstrap.servers", "broker:9092") \
  .option("subscribe", "events") \
  .load()

# Write to Iceberg
query = df.writeStream \
  .format("iceberg") \
  .outputMode("append") \
  .option("checkpointLocation", "s3://bucket/checkpoints") \
  .toTable("my_catalog.db.events")
```

#### 4. Snowflake → Iceberg (3 hours)

**External Tables:**
```sql
-- Create external volume
CREATE OR REPLACE EXTERNAL VOLUME iceberg_volume
  STORAGE_LOCATIONS = (
    (
      NAME = 's3_location'
      STORAGE_PROVIDER = 'S3'
      STORAGE_BASE_URL = 's3://bucket/warehouse/'
      STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::123456789:role/snowflake-role'
    )
  );

-- Create Iceberg table reference
CREATE OR REPLACE ICEBERG TABLE orders
  EXTERNAL_VOLUME = 'iceberg_volume'
  CATALOG = 'POLARIS'
  CATALOG_TABLE_NAME = 'db.orders';

-- Query
SELECT * FROM orders WHERE order_date = CURRENT_DATE;
```

#### 5. Multi-Engine Access (3 hours)

**Unified Access Pattern:**

```
Kafka Topic (Source)
     ↓ (Tableflow)
Iceberg Table (S3)
     ↓ (Catalog: Glue + Polaris)
├─ Athena (Ad-hoc SQL)
├─ Snowflake (Analytics)
├─ Spark (Batch ML)
├─ Flink (Real-time aggregation)
└─ Trino (Federated queries)
```

**Each engine sees the same data:**
- No data duplication
- Single source of truth
- Consistent schema
- ACID guarantees

#### 6. CDC with Iceberg (3 hours)

**Debezium → Kafka → Tableflow:**

```yaml
Source: PostgreSQL
Connector: Debezium PostgreSQL CDC
Kafka Topic: postgres.public.customers
Tableflow: Iceberg with upsert mode
Result: Live replica of customers table
```

**Materialized View Pattern:**
```sql
-- Original CDC events (append-only)
CREATE TABLE cdc_events (
  op STRING,  -- c=create, u=update, d=delete
  before STRUCT<...>,
  after STRUCT<...>,
  ts_ms BIGINT
);

-- Materialized current state (via Tableflow)
CREATE TABLE customers_current (
  customer_id BIGINT,
  name STRING,
  email STRING,
  updated_at TIMESTAMP
);
```

### Weekly Milestones

**Week 5:**
- [ ] Perform schema evolution on production-like table
- [ ] Implement partition evolution scenario
- [ ] Execute time travel for audit use case
- [ ] Configure table maintenance schedule

**Week 6:**
- [ ] Optimize slow query through file compaction
- [ ] Tune write performance for streaming workload
- [ ] Select appropriate catalog for use case
- [ ] Set up monitoring dashboard

**Week 7:**
- [ ] Deploy Tableflow → Iceberg pipeline
- [ ] Configure Flink to write to Iceberg
- [ ] Access same table from 3+ query engines
- [ ] Implement CDC materialization pattern

### Resources

**Advanced Guides:**
- [Iceberg Performance Tuning](https://iceberg.apache.org/docs/latest/performance/)
- [Tableflow Best Practices](https://docs.confluent.io/cloud/current/tableflow/best-practices.html)

**Video Series:**
- "Partitioning and Partition Evolution | Apache Iceberg + Tableflow"
- "Table Maintenance | Apache Iceberg + Tableflow"
- "Time Travel and Rollback | Apache Iceberg + Tableflow"

### Assessment Criteria

You're ready for Week 8 when you can:
- ✅ Perform schema and partition evolution confidently
- ✅ Optimize query performance through tuning
- ✅ Configure and monitor Tableflow pipelines
- ✅ Integrate Iceberg with 5+ query engines
- ✅ Implement CDC materialization pattern

---

## Week 8: Expert Level
**Production Readiness**

### Learning Objectives

By the end of Week 8, you will be able to:
- ✅ Design production-grade Iceberg architecture
- ✅ Implement comprehensive monitoring and alerting
- ✅ Handle failure scenarios and edge cases
- ✅ Estimate and optimize costs
- ✅ Present solutions to technical and business stakeholders

### Topics to Master

#### 1. Production Architecture Design (8 hours)

**Design Checklist:**

**1. Catalog Selection:**
- [ ] Evaluate catalog options (Glue, Polaris, Unity, IRC)
- [ ] Consider multi-cloud requirements
- [ ] Plan for disaster recovery
- [ ] Design access control model

**2. Storage Strategy:**
- [ ] Choose storage tier (S3, ADLS, GCS)
- [ ] Plan data retention policy
- [ ] Configure encryption (SSE-S3, SSE-KMS, BYOK)
- [ ] Design bucket structure

**3. Partition Strategy:**
- [ ] Analyze query patterns
- [ ] Choose partition granularity (hourly, daily, monthly)
- [ ] Plan for partition evolution
- [ ] Implement hidden partitioning

**4. Table Properties:**
```sql
CREATE TABLE production_table (...)
WITH (
  'write.format.default' = 'parquet',
  'write.parquet.compression-codec' = 'snappy',
  'write.target-file-size-bytes' = '536870912',  -- 512 MB
  'write.metadata.delete-after-commit.enabled' = 'true',
  'write.metadata.previous-versions-max' = '100',
  'history.expire.max-snapshot-age-ms' = '604800000',  -- 7 days
  'commit.retry.num-retries' = '4',
  'commit.retry.min-wait-ms' = '100'
);
```

**5. Tableflow Configuration:**
- [ ] Data freshness: 15 min (default) or custom
- [ ] Snapshot retention: 7-30 days based on compliance
- [ ] DLQ: Always enabled for production
- [ ] Compaction: Daily or on-demand
- [ ] Storage: BYOS for control, Managed for simplicity

**Reference Architecture:**

```
┌─────────────────────────────────────────────────────┐
│              SOURCE SYSTEMS                         │
│  PostgreSQL  │  MySQL  │  MongoDB  │  Apps          │
└──────────────┬──────────────────────────────────────┘
               │ CDC (Debezium)
               ↓
┌─────────────────────────────────────────────────────┐
│            CONFLUENT CLOUD                          │
│  ┌──────────────────────────────────────────┐      │
│  │  Kafka Topics (Schema Registry)          │      │
│  └──────────────┬───────────────────────────┘      │
│                 │                                    │
│  ┌──────────────▼───────────────────────────┐      │
│  │  Flink SQL (Transform, Enrich, Filter)   │      │
│  └──────────────┬───────────────────────────┘      │
│                 │                                    │
│  ┌──────────────▼───────────────────────────┐      │
│  │  Tableflow (Iceberg Materialization)     │      │
│  └──────────────┬───────────────────────────┘      │
└─────────────────┼───────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────┐
│         OBJECT STORAGE (S3/ADLS)                    │
│  Iceberg Tables (Parquet + Metadata)                │
└──────────────┬──────────────────────────────────────┘
               │
      ┌────────┼────────┬─────────┬──────────┐
      ↓        ↓        ↓         ↓          ↓
   Athena  Snowflake  Spark    Databricks  Trino
   (SQL)   (Analytics) (ML)    (Lakehouse) (Federated)
```

#### 2. Monitoring & Alerting (5 hours)

**Metrics to Monitor:**

**Table Health Metrics:**
```yaml
Metric: iceberg_table_files_count
Alert: > 10,000 files
Action: Run compaction

Metric: iceberg_table_avg_file_size_mb
Alert: < 64 MB
Action: Increase target file size

Metric: iceberg_table_snapshots_count
Alert: > 500
Action: Expire old snapshots

Metric: iceberg_table_metadata_files_count
Alert: > 1,000
Action: Cleanup old metadata
```

**Tableflow Metrics (via Datadog):**
```yaml
Metric: tableflow_throughput_mbps
Alert: < expected throughput
Action: Check Kafka lag, investigate

Metric: tableflow_lag_seconds
Alert: > 900 (15 min)
Action: Scale up, check failures

Metric: tableflow_dlq_messages_count
Alert: > 0
Action: Investigate schema violations

Metric: tableflow_compaction_failures
Alert: > 3 consecutive failures
Action: Check storage permissions, quotas

Metric: tableflow_health_status
Alert: != "HEALTHY"
Action: Check logs, contact support
```

**Dashboard Setup (Datadog/Grafana):**

```yaml
Panels:
  - Tableflow Throughput (time series)
  - Tableflow Lag (gauge)
  - DLQ Messages (counter)
  - Table File Count (gauge)
  - Average File Size (gauge)
  - Snapshot Count (gauge)
  - Query Performance (histogram)
  - Error Rate (time series)
```

**Alert Escalation:**
```
Level 1 (Warning): Team notification
Level 2 (Critical): On-call page
Level 3 (Emergency): Incident response
```

#### 3. Failure Handling (4 hours)

**Scenario 1: Schema Incompatibility**

**Problem:**
Producer sends data with schema change that breaks consumers.

**Detection:**
- DLQ messages increase
- Tableflow shows schema violation errors

**Resolution:**
1. Check DLQ topic for rejected records
2. Identify schema incompatibility
3. Options:
   - Fix producer schema (backward compatible)
   - Update table schema (forward compatible)
   - Replay DLQ records after fix

**Scenario 2: Corrupt Data Files**

**Problem:**
Parquet file corrupted in object storage.

**Detection:**
- Query fails with "Unable to read file" error

**Resolution:**
1. Identify corrupt file from error message
2. Find snapshot containing corrupt file
3. Rollback to previous snapshot:
```sql
CALL rollback_to_snapshot('db.table', previous_snapshot_id);
```
4. Re-process data from Kafka (if available)

**Scenario 3: Catalog Outage**

**Problem:**
AWS Glue unavailable, queries fail.

**Detection:**
- "Unable to connect to catalog" errors
- High latency on metadata requests

**Resolution:**
1. Check AWS Glue service health
2. If outage: queries wait or fail
3. Mitigation: Multi-catalog setup
   - Primary: AWS Glue
   - Failover: Polaris or IRC
   - Keep catalogs in sync

**Scenario 4: Snapshot Explosion**

**Problem:**
Too many snapshots (slow query planning, high costs).

**Detection:**
- Query planning takes > 10 seconds
- Metadata file count > 1,000

**Resolution:**
1. Immediate: Expire old snapshots
```sql
CALL expire_snapshots('db.table',
  TIMESTAMP '2024-03-01 00:00:00',
  retain_last => 100
);
```
2. Long-term: Set retention policy
```sql
ALTER TABLE db.table SET TBLPROPERTIES (
  'history.expire.max-snapshot-age-ms' = '604800000'
);
```

**Scenario 5: Concurrent Write Conflicts**

**Problem:**
Multiple writers conflict, commits fail.

**Detection:**
- "Commit conflict" errors in logs
- High retry rate on writes

**Resolution:**
1. Use REST Catalog or Glue (better concurrency)
2. Implement exponential backoff retry:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60)
)
def write_to_iceberg(data):
    df.write.format("iceberg").mode("append").save("db.table")
```
3. Batch smaller writes to reduce conflicts

#### 4. Cost Optimization (3 hours)

**Cost Components:**

| Component | Cost Driver | Optimization |
|-----------|-------------|--------------|
| **Storage** | Data volume, retention | Expire snapshots, compress, tier |
| **Catalog** | API calls, metadata storage | Cache, batch operations |
| **Compute** | Query execution | Partition pruning, compaction |
| **Tableflow** | Topics enabled, data processed | Selective enablement, batching |
| **Egress** | Data transfer out | Co-locate storage & compute |

**Optimization Strategies:**

**1. Storage Costs:**
```sql
-- Expire old snapshots (free up storage)
CALL expire_snapshots('db.table',
  TIMESTAMP '2024-02-01 00:00:00');

-- Remove orphan files
CALL remove_orphan_files('db.table',
  TIMESTAMP '2024-02-01 00:00:00');

-- Use better compression
ALTER TABLE db.table SET TBLPROPERTIES (
  'write.parquet.compression-codec' = 'zstd'
);
```

**2. Compute Costs:**
```sql
-- Optimize partition strategy (reduce scanned data)
-- Daily partitions for moderate volume
CREATE TABLE events (...)
PARTITIONED BY (days(event_time));

-- Use Athena workgroups with query limits
-- Use Snowflake warehouses with auto-suspend
```

**3. Tableflow Costs:**
- Enable only for analytics-critical topics
- Use longer freshness intervals (e.g., 1 hour vs 15 min)
- Leverage Confluent Managed Storage (no egress fees)

**Cost Comparison: Tableflow vs Alternatives:**

| Solution | Monthly Cost (100 GB/day) | Notes |
|----------|--------------------------|-------|
| **Tableflow** | ~$300 | Includes processing, storage, compaction |
| **S3 Sink Connector** | ~$220 | Manual compaction, no table format |
| **Snowflake Sink** | ~$425 | Snowflake storage + compute |
| **Custom Pipeline** | ~$500+ | EC2, EMR, engineer time |

**Winner:** Tableflow (best TCO for managed experience)

#### 5. Stakeholder Presentations (4 hours)

**Technical Presentation:**

**Agenda:**
1. Problem Statement (2 min)
   - Current ETL pain points
   - Data latency issues
   - Maintenance overhead
2. Solution Architecture (5 min)
   - Kafka → Tableflow → Iceberg flow
   - Multi-engine access pattern
   - ACID guarantees
3. Technical Benefits (3 min)
   - Zero-downtime schema evolution
   - Time travel for audit/debug
   - Cost savings: 30-50%
4. Demo (5 min)
   - Enable Tableflow on topic
   - Query from Athena/Snowflake
   - Show time travel query
5. Next Steps (2 min)
   - POC timeline
   - Resource requirements
   - Success metrics

**Business Presentation:**

**Agenda:**
1. Business Problem (3 min)
   - Slow time-to-insight
   - High ETL maintenance costs
   - Data quality issues
2. Tableflow Solution (5 min)
   - Real-time data in lakehouse
   - Single click to enable
   - No custom code
3. ROI (5 min)
   - Cost savings: 30-50% vs custom ETL
   - Time savings: Weeks → Hours
   - Risk reduction: No data loss, ACID
4. Success Stories (2 min)
   - Customer case studies
   - Industry examples
5. Investment & Timeline (3 min)
   - Licensing costs
   - Implementation effort
   - Time to value: 2-4 weeks

**Objection Handling:**

**"Why not Delta Lake?"**
> "Delta Lake is excellent for Databricks-centric environments. We chose Iceberg for its vendor neutrality—we can use Athena, Snowflake, Trino, and Spark with the same tables. Iceberg's partition evolution also gives us flexibility as data volumes change."

**"What about data lock-in?"**
> "Iceberg is Apache-licensed open source. Data files are standard Parquet in your S3 bucket. You can switch query engines or even table formats without vendor lock-in. Confluent's Tableflow uses the standard Iceberg REST API."

**"How does this compare to our current ETL?"**
> "Your current ETL requires custom code, manual schema management, and batch processing. Tableflow provides real-time materialization, automatic schema evolution, and zero operational overhead. We estimate 30-50% cost savings and 10x faster time-to-insight."

### Final Expert Challenge

**Build End-to-End Production System:**

**Requirements:**
1. ✅ **Real-time ingestion:** Kafka → Tableflow → Iceberg (< 1 min latency)
2. ✅ **Multi-engine access:** Query from Athena, Snowflake, and Spark
3. ✅ **Schema evolution:** Add column without downtime
4. ✅ **Time travel:** Query yesterday's data
5. ✅ **Monitoring:** Datadog dashboard with alerts
6. ✅ **Cost optimization:** Snapshot retention policy
7. ✅ **Documentation:** Architecture diagram + runbook

**Success Criteria:**
- System runs for 7 days without manual intervention
- Query latency < 5 seconds for typical queries
- Zero data loss during schema evolution
- Alerts fire correctly for failures
- Total cost under budget estimate

### Weekly Milestones

**Week 8:**
- [ ] Design production architecture for real use case
- [ ] Implement monitoring dashboard with 10+ metrics
- [ ] Create runbook for 5+ failure scenarios
- [ ] Build cost optimization plan
- [ ] Present solution to mock stakeholders
- [ ] Complete final expert challenge

### Resources

**Production Guides:**
- [Tableflow Best Practices](https://docs.confluent.io/cloud/current/tableflow/best-practices.html)
- [Iceberg Production Checklist](https://iceberg.apache.org/docs/latest/reliability/)

**Enablement Decks:**
- [Tableflow Main Deck v1.2](https://docs.google.com/presentation/d/189kHEEAjgW6VRkTOaJZEA9pW-JHzG8rFSjGItvn416Q)
- [Tableflow Product Overview](https://docs.google.com/presentation/d/1Li8lylvPf9jVos74GESSN-GNMp6k-JmQQDn7oQeNh20)

### Assessment Criteria

You're an EXPERT when you can:
- ✅ Design production architecture from scratch
- ✅ Implement comprehensive monitoring
- ✅ Handle all failure scenarios independently
- ✅ Present to both technical and business audiences
- ✅ Deploy and operate production Iceberg system
- ✅ Mentor others on Iceberg best practices

---

## Expert Certification Checklist

### Technical Mastery
- [ ] Draw Iceberg architecture from memory (< 2 min)
- [ ] Explain query execution using metadata layers
- [ ] Debug slow queries by inspecting manifest files
- [ ] Design partition strategy for any use case
- [ ] Implement zero-downtime schema migration
- [ ] Configure table maintenance schedule
- [ ] Set up multi-catalog architecture

### Hands-On Skills
- [ ] Set up Tableflow in Confluent Cloud (production-grade)
- [ ] Configure external catalogs (Glue, Polaris, Unity)
- [ ] Write Flink SQL to populate Iceberg tables
- [ ] Query Iceberg with 5+ engines simultaneously
- [ ] Perform compaction, expiration, and cleanup
- [ ] Implement CDC materialization pipeline
- [ ] Deploy monitoring dashboard with alerts

### Production Experience
- [ ] Designed architecture for real customer use case
- [ ] Migrated existing data lake to Iceberg
- [ ] Troubleshot production performance issue
- [ ] Implemented monitoring and alerting system
- [ ] Presented solution to stakeholders (technical & business)
- [ ] Created runbook for operations team
- [ ] Optimized costs by 30%+

### Business Impact
- [ ] Explain ROI vs traditional ETL (with numbers)
- [ ] Articulate cost savings clearly
- [ ] Position Iceberg in competitive scenarios
- [ ] Address "Why not Delta Lake?" objections
- [ ] Demo real-time analytics use case
- [ ] Estimate implementation timeline and costs

---

## Key Concepts Reference

### Top 20 Concepts You Must Master

#### Foundation (Week 1-2)
1. **Open Table Format** - Standard for organizing data files as SQL tables
2. **Snapshot Isolation** - Consistent reads via immutable snapshots
3. **Schema Evolution** - Add/drop/rename columns without rewrites
4. **Partition Evolution** - Change partitioning without data movement
5. **Time Travel** - Query historical table states

#### Architecture (Week 3-4)
6. **Catalog Layer** - Entry point, stores current metadata location
7. **Metadata Files** - JSON files with schema, partitions, snapshots
8. **Manifest Lists** - AVRO files listing manifests per snapshot
9. **Manifests** - AVRO files listing data files with statistics
10. **Data Files** - Parquet files containing actual table data

#### Advanced (Week 5-7)
11. **Hidden Partitioning** - Users query without partition awareness
12. **Column Statistics** - Min/max/null counts for query pruning
13. **Compaction** - Rewriting small files into larger files
14. **Snapshot Expiration** - Deleting old snapshots to free storage
15. **Concurrent Writes** - Optimistic concurrency with retry

#### Production (Week 8)
16. **Catalog Selection** - Choosing Glue vs Polaris vs Unity vs IRC
17. **Monitoring Metrics** - File count, size, lag, errors
18. **Dead Letter Queue** - Handling schema violations in Tableflow
19. **BYOK Encryption** - Customer-managed encryption keys
20. **Cost Optimization** - Retention, compression, tiering

---

## Tools & Technologies

### Essential Tools

**Cloud Platforms:**
- ☁️ Confluent Cloud (Kafka, Flink, Tableflow)
- ☁️ AWS (S3, Glue, Athena)
- ☁️ Azure (ADLS, Databricks)

**Query Engines:**
- ⚡ Apache Spark (batch processing)
- 🌊 Apache Flink (stream processing)
- ❄️ Snowflake (cloud data warehouse)
- 🔍 Trino/Presto (federated queries)
- 📊 AWS Athena (serverless SQL)

**Development Tools:**
- `spark-shell` - Interactive Spark queries
- `aws-cli` - S3 and Glue operations
- `jq` - JSON metadata inspection
- `avro-tools` - Manifest file inspection
- `confluent-cli` - Confluent Cloud operations

**Monitoring:**
- 📈 Datadog (metrics, dashboards, alerts)
- 📊 Grafana (visualization)
- 🔔 PagerDuty (incident management)

---

## Success Metrics

### Knowledge Assessment

| Metric | Target | Validation |
|--------|--------|------------|
| Architecture Quiz | 90%+ | Weekly quizzes |
| Hands-On Labs | 15+ completed | Lab verification |
| Production Deployments | 1+ live | Production system |
| Engines Mastered | 5+ | Multi-engine demo |
| Troubleshooting | < 30 min | Timed exercises |
| Presentation | Confident | Stakeholder demo |

### Proficiency Levels

**Beginner (Week 1-2):**
- Can explain what Iceberg is and why it matters
- Understands basic concepts and terminology
- Compares Iceberg with alternatives

**Intermediate (Week 3-4):**
- Understands architecture in detail
- Can perform basic operations (create, query, evolve)
- Traces query execution through metadata

**Advanced (Week 5-7):**
- Performs schema and partition evolution
- Optimizes performance through tuning
- Integrates with multiple query engines

**Expert (Week 8):**
- Designs production architectures
- Implements monitoring and alerting
- Handles all failure scenarios
- Presents to stakeholders confidently

---

## Next Steps After Certification

### Continue Learning
1. **Advanced Topics:**
   - Multi-table transactions (when available)
   - Branch and tag management
   - Advanced partition transforms
   - Custom file formats

2. **Community Involvement:**
   - Join Apache Iceberg mailing list
   - Attend Kafka Summit sessions on Tableflow
   - Contribute to Iceberg documentation
   - Share knowledge via blog posts

3. **Specializations:**
   - Machine Learning with Iceberg (feature stores)
   - Real-time analytics architectures
   - Multi-cloud data platforms
   - Data mesh implementations

### Career Development
- **Certifications:** Confluent Certified Developer/Administrator
- **Speaking:** Present at meetups, conferences
- **Mentoring:** Train junior engineers
- **Thought Leadership:** Write technical blogs, create tutorials

---

## Additional Resources

### Official Documentation
- [Apache Iceberg Docs](https://iceberg.apache.org/)
- [Iceberg Table Spec](https://iceberg.apache.org/spec/)
- [Confluent Tableflow Docs](https://docs.confluent.io/cloud/current/tableflow/)
- [Confluent Developer](https://developer.confluent.io/)

### Internal Resources
- [Tableflow Main Deck v1.2](https://docs.google.com/presentation/d/189kHEEAjgW6VRkTOaJZEA9pW-JHzG8rFSjGItvn416Q)
- [Tableflow L200 Content](https://docs.google.com/presentation/d/11e6L7gav0-h9MqBzYLrFeKCZzLmB-gCUTZ_W-GLV9Jw)
- [Tableflow System Architecture](https://confluentinc.atlassian.net/wiki/spaces/KORAGE/pages/4544528407)
- [Iceberg + Tableflow Course](https://confluentinc.atlassian.net/wiki/spaces/DEVX/pages/4281860372)

### Blogs & Articles
- [Introducing Tableflow](https://www.confluent.io/blog/introducing-tableflow/)
- [Tableflow GA: Kafka to Iceberg](https://www.confluent.io/blog/tableflow-ga-kafka-snowflake-iceberg/)
- [Tableflow is Generally Available](https://www.confluent.io/blog/tableflow-is-now-generally-available/)

### Video Resources
- YouTube: Search "Apache Iceberg + Tableflow"
- Confluent Developer Podcast
- Kafka Summit talks on Tableflow

---

## Appendix

### Glossary

**ACID** - Atomicity, Consistency, Isolation, Durability
**AVRO** - Binary serialization format for metadata
**BYOK** - Bring Your Own Key (encryption)
**BYOS** - Bring Your Own Storage
**CDC** - Change Data Capture
**DLQ** - Dead Letter Queue
**IRC** - Iceberg REST Catalog (Confluent)
**Manifest** - File listing data files with statistics
**Manifest List** - File listing manifest files
**Metadata File** - JSON file with schema, partitions, snapshots
**Parquet** - Columnar storage format
**Snapshot** - Point-in-time state of table
**Tableflow** - Confluent's Kafka → Iceberg service
**Time Travel** - Querying historical table states

### FAQ

**Q: Can I use Iceberg with GCP?**
A: Yes, Iceberg works with GCS. However, Confluent Tableflow is currently AWS and Azure only (GCP support planned).

**Q: What's the difference between Iceberg and Hudi?**
A: Both are open table formats. Iceberg excels at metadata management and broad ecosystem support. Hudi excels at upserts and incremental processing.

**Q: Do I need to choose between Iceberg and Delta Lake?**
A: It depends on your ecosystem. If you're Databricks-centric, Delta Lake integrates better. If you need vendor neutrality and multi-engine support, Iceberg is ideal.

**Q: Can I migrate from Hive to Iceberg?**
A: Yes, Iceberg provides migration tools to convert Hive tables to Iceberg format.

**Q: What happens to Parquet files when I drop an Iceberg table?**
A: Metadata is deleted, but Parquet files remain in S3/ADLS unless you manually delete them.

**Q: How does Tableflow handle schema changes?**
A: Automatically detects changes in Schema Registry and evolves Iceberg schema accordingly. Incompatible changes go to DLQ.

---

## Conclusion

Congratulations on completing the Apache Iceberg Expert Learning Roadmap!

You now have a comprehensive understanding of:
- ✅ Iceberg architecture and design principles
- ✅ Confluent Tableflow integration
- ✅ Production deployment patterns
- ✅ Performance optimization techniques
- ✅ Cost management strategies
- ✅ Monitoring and troubleshooting

You're ready to:
- 🚀 Deploy Tableflow in production
- 💼 Consult on customer implementations
- 🎤 Present at conferences
- 📝 Write technical content
- 🏆 Mentor junior engineers

**Your next steps:**
1. Complete the final expert challenge
2. Deploy your first production Iceberg system
3. Share your knowledge with the community
4. Continue learning advanced topics

**Remember:** Expertise is built through continuous practice and real-world experience. Keep experimenting, keep learning, and keep pushing boundaries.

**Good luck on your Apache Iceberg journey!**

---

**Document Version:** 1.0
**Last Updated:** March 12, 2026
**Author:** Jegan K
**Feedback:** Please submit suggestions to improve this roadmap
