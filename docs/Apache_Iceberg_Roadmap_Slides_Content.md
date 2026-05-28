# Apache Iceberg Expert Roadmap - Slides Content
**For Google Slides Presentation**

**Template:** [Confluent Presentation Template | OFFICIAL [2025]](https://docs.google.com/presentation/d/1VEakn4Dk9MnpvI2fxs9lBwkxnuJukZA54iSLOPROHhs)

**Font:** Inter (as of August 2024)
**Colors:**
- Primary: Midnight #040531, Ocean #0099FF, Mist #F5F7FF, Snow #FBFBFB, White #FFFFFF
- Secondary: Grape #AA2BCE, Han #3A21ED, Yale #14449A, Steel #0074A2, Marlin #01CEDB, Punch #D8365D

---

## SLIDE 1: Title Slide
**Layout:** Title slide with speaker photo

```
Apache Iceberg Expert Roadmap
From Beginner to Production Expert in 8 Weeks

Your Name
Customer Success Technical Architect
Confluent
[Date]
```

---

## SLIDE 2: Disclaimer
**Layout:** Standard disclaimer (from template)

```
As our roadmap may change in the future, the features referred to herein may change, may not be delivered on time or may not be delivered at all.

Last disclaimer slide, what you see today and what we discuss represents our intent but its possible that it could change for any given feature. They may look different when released, the timing could change, or they may not be released at all. So bottom line don't construe anything said as a commitment.
```

---

## SLIDE 3: Agenda
**Layout:** Ten item agenda with objective

```
Agenda

01 Why This Roadmap Matters
02 Learning Journey Overview
03 Week 1-2: Beginner Level
04 Week 3-4: Intermediate Level
05 Week 5-7: Advanced Level
06 Week 8: Expert Level
07 Tools & Resources
08 Success Metrics
09 Final Expert Challenge
10 Next Steps

Objective: Transform you from Iceberg beginner to production expert in 8 weeks
```

---

## SLIDE 4: Section Breaker
**Layout:** Dark background breaker

```
Why This Roadmap Matters
```

---

## SLIDE 5: The Problem
**Layout:** Split view with icons

```
Traditional Data Lake Challenges

LEFT COLUMN:
❌ Hive's Limitations
• Directory-based partitioning
• Expensive file listing operations
• No ACID transactions
• Schema evolution = full rewrites

❌ No Time Travel
• Can't query historical states
• No audit capabilities
• Recovery is manual

RIGHT COLUMN:
❌ Operational Overhead
• Manual schema management
• Complex ETL pipelines
• Brittle data quality
• High maintenance costs

❌ Vendor Lock-in
• Proprietary formats
• Single-engine support
• Migration nightmares
```

---

## SLIDE 6: The Solution
**Layout:** Content with icons

```
Apache Iceberg: The Modern Table Format

✅ ACID Transactions
Snapshot isolation, consistent reads

✅ Schema Evolution
Add/drop/rename columns without rewrites

✅ Partition Evolution
Change partitioning without data movement

✅ Time Travel
Query historical table states

✅ Vendor Neutral
20+ compatible query engines

✅ Tableflow Integration
Kafka → Iceberg in one click
```

---

## SLIDE 7: Why You Need This Expertise
**Layout:** Three column layout

```
COLUMN 1: Business Value
• 30-50% cost savings vs ETL
• Real-time analytics (< 1 min)
• Zero-downtime migrations
• Compliance & audit ready

COLUMN 2: Technical Value
• Production-grade architecture
• Multi-engine compatibility
• Performance optimization
• Troubleshooting mastery

COLUMN 3: Career Value
• High-demand skill set
• Customer enablement
• Thought leadership
• Competitive advantage
```

---

## SLIDE 8: Section Breaker
**Layout:** Dark background breaker

```
Learning Journey Overview
```

---

## SLIDE 9: 8-Week Transformation
**Layout:** Process infographic (4 steps)

```
STEP 1: Beginner (Week 1-2)
Understand "Why"
• Historical context
• Core concepts
• Iceberg vs alternatives

STEP 2: Intermediate (Week 3-4)
Understand "How"
• 3-layer architecture
• Metadata management
• Hands-on labs

STEP 3: Advanced (Week 5-7)
Master Features
• Schema/partition evolution
• Performance tuning
• Integration patterns

STEP 4: Expert (Week 8)
Production Ready
• Architecture design
• Monitoring & alerting
• Stakeholder presentations
```

---

## SLIDE 10: Time Commitment
**Layout:** Content boxes

```
Daily Commitment: 2-3 hours
Total Duration: 8 weeks
Total Investment: 120-180 hours

BREAKDOWN:
• Reading & Videos: 40%
• Hands-on Labs: 40%
• Practice & Review: 20%

OUTCOME:
Production-ready expertise in Apache Iceberg and Confluent Tableflow
```

---

## SLIDE 11: Section Breaker
**Layout:** Dark background breaker

```
Week 1-2: Beginner Level
The "Why" Phase
```

---

## SLIDE 12: Learning Objectives (Beginner)
**Layout:** Five item agenda

```
01 Historical Context
Understand why Iceberg was created and what problems it solves

02 Open Table Formats
Compare Iceberg, Delta Lake, and Apache Hudi

03 Core Concepts
Master fundamental terminology and features

04 Ecosystem Overview
Identify 20+ compatible query engines and catalogs

05 Tableflow Connection
Understand Confluent's Kafka → Iceberg integration
```

---

## SLIDE 13: Historical Context
**Layout:** Timeline infographic

```
BEFORE ICEBERG (2017)

Hive Era:
• Directory-based partitions
• No snapshots
• Manual schema changes
• Expensive queries

THE PROBLEM:
Netflix managing petabyte-scale data lakes

THE NEED:
• ACID on object storage
• Schema evolution
• Concurrent reads/writes
• Query performance

THE SOLUTION:
Apache Iceberg (2017)
Open table format bringing database capabilities to data lakes
```

---

## SLIDE 14: Iceberg vs Delta vs Hudi
**Layout:** Comparison table

```
Feature              | Iceberg        | Delta Lake      | Hudi
---------------------|----------------|-----------------|----------------
Origin               | Netflix (2017) | Databricks (19) | Uber (2016)
Governance           | Apache         | Linux Found.    | Apache
Metadata Design      | 3-layer ⭐     | 2-layer         | Timeline
Partition Evolution  | ✅ Built-in ⭐ | ❌ Rewrites     | ❌ Rewrites
Schema Evolution     | ✅ Excellent   | ✅ Excellent    | ✅ Good
Ecosystem Support    | 20+ engines ⭐ | Databricks      | Spark
Vendor Lock-in       | ✅ Low ⭐      | ⚠️ Medium       | ✅ Low
Best For             | Multi-engine   | Databricks      | Upserts

⭐ = Iceberg Advantage
```

---

## SLIDE 15: Core Concepts
**Layout:** Icon grid (2x3)

```
ACID Transactions
Atomic, Consistent, Isolated, Durable operations

Schema Evolution
Add/drop/rename columns without rewrites

Partition Evolution
Change partitioning strategy without data movement

Time Travel
Query historical table states

Hidden Partitioning
Users don't write partition logic

Snapshot Isolation
Consistent reads during concurrent writes
```

---

## SLIDE 16: Confluent Tableflow
**Layout:** Architecture diagram

```
┌─────────────────────────────────────┐
│     Kafka Topic + Schema Registry   │
└──────────────┬──────────────────────┘
               │ Tableflow
               ↓
┌─────────────────────────────────────┐
│  Kora Storage Layer                 │
│  • Converts segments → Parquet      │
│  • Generates Iceberg metadata       │
└──────────────┬──────────────────────┘
               │
               ↓
┌─────────────────────────────────────┐
│  Iceberg Table (S3/ADLS)            │
└──────────────┬──────────────────────┘
               │
      ┌────────┼────────┬────────┐
      ↓        ↓        ↓        ↓
   Athena  Snowflake  Spark  Databricks

One Click: Kafka → Analytics-Ready Tables
```

---

## SLIDE 17: Week 1-2 Milestones
**Layout:** Checklist style

```
Week 1:
☑ Complete historical context reading
☑ Watch: Apache Iceberg 101 course
☑ Create comparison table (Iceberg vs Delta vs Hudi)
☑ Document 5 use cases where Iceberg is ideal

Week 2:
☑ Read: Introducing Tableflow blog
☑ Understand Tableflow architecture
☑ Identify 3 customer scenarios
☑ Pass beginner quiz (90%+ score)

READY FOR WEEK 3 WHEN YOU CAN:
✅ Explain Iceberg in 5 minutes
✅ Compare alternatives confidently
✅ Describe Tableflow's value proposition
```

---

## SLIDE 18: Section Breaker
**Layout:** Dark background breaker

```
Week 3-4: Intermediate Level
The "How" Phase
```

---

## SLIDE 19: Learning Objectives (Intermediate)
**Layout:** Five item agenda

```
01 Catalog Layer
Understand how query engines find Iceberg tables

02 Metadata Layer
Master JSON metadata files and snapshot structure

03 Manifest Layer
Learn how AVRO manifests enable query optimization

04 Data Layer
Understand Parquet files and storage organization

05 Hands-On Labs
Build, query, and evolve Iceberg tables via Tableflow
```

---

## SLIDE 20: The 3-Layer Architecture
**Layout:** Process infographic (vertical)

```
LAYER 1: CATALOG
Points to current metadata file
• AWS Glue, Polaris, Unity Catalog, IRC

      ↓

LAYER 2: METADATA (JSON)
Table schema, partitions, snapshots
• Metadata File → Manifest List → Manifest

      ↓

LAYER 3: DATA (Parquet)
Actual table data in columnar format
• Optimized for analytics queries

KEY INSIGHT:
Metadata-driven optimization enables
10-100x faster query planning
```

---

## SLIDE 21: How Queries Use Metadata
**Layout:** Step process (numbered)

```
QUERY EXECUTION FLOW

1️⃣ Client requests table from Catalog
   Catalog returns metadata file location

2️⃣ Client reads Metadata File (JSON)
   Gets schema, current snapshot ID

3️⃣ Client reads Manifest List (AVRO)
   Prunes manifests by partition summaries

4️⃣ Client reads Manifests (AVRO)
   Prunes data files by column statistics

5️⃣ Client reads Data Files (Parquet)
   Only necessary files for query

RESULT: Only 1-5% of data scanned!
```

---

## SLIDE 22: Catalog Options
**Layout:** Comparison table

```
Catalog          | Use Case      | Pros               | Cons
-----------------|---------------|--------------------|-----------------
Hadoop           | Dev/test      | Simple             | Not production
Hive Metastore   | Legacy        | Hive compat        | Limited concurrency
AWS Glue         | AWS prod      | Managed, serverless| AWS-only
Polaris          | Multi-engine  | Open, neutral      | Newer project
Unity Catalog    | Databricks    | Unified governance | Databricks-centric
Iceberg REST     | Tableflow     | Standard API       | Requires server

TABLEFLOW RECOMMENDATION: IRC + Glue Sync
Best of both worlds: managed + ecosystem integration
```

---

## SLIDE 23: Hands-On Labs
**Layout:** Content boxes (5 boxes)

```
LAB 1: Create via Tableflow (2 hrs)
Enable Tableflow on Kafka topic → Instant Iceberg table

LAB 2: Inspect Metadata (2 hrs)
Download and analyze metadata JSON files

LAB 3: Query Manifests (2 hrs)
Use avro-tools to inspect manifest files

LAB 4: Schema Evolution (3 hrs)
Add column, verify backward compatibility

LAB 5: Time Travel (2 hrs)
Query historical snapshots, rollback table
```

---

## SLIDE 24: Week 3-4 Milestones
**Layout:** Checklist style

```
Week 3:
☑ Draw 3-layer architecture from memory
☑ Complete Lab 1: Create Iceberg table via Tableflow
☑ Complete Lab 2: Inspect metadata files
☑ Document query execution flow

Week 4:
☑ Complete Lab 3: Query manifest files
☑ Complete Lab 4: Schema evolution
☑ Complete Lab 5: Time travel queries
☑ Pass intermediate quiz (90%+ score)

READY FOR WEEK 5 WHEN YOU CAN:
✅ Explain architecture without notes
✅ Trace query through metadata layers
✅ Perform schema evolution confidently
```

---

## SLIDE 25: Section Breaker
**Layout:** Dark background breaker

```
Week 5-7: Advanced Level
The "Mastery" Phase
```

---

## SLIDE 26: Learning Objectives (Advanced)
**Layout:** Three column layout

```
WEEK 5: Features
• Snapshots & time travel
• Schema evolution
• Partition evolution
• ACID transactions
• Table maintenance

WEEK 6: Performance
• Query optimization
• Write tuning
• Catalog selection
• Storage optimization
• Monitoring setup

WEEK 7: Integrations
• Tableflow → Iceberg
• Flink → Iceberg
• Spark → Iceberg
• Snowflake → Iceberg
• Multi-engine access
```

---

## SLIDE 27: Schema Evolution in Action
**Layout:** Code example with visual

```
BEFORE:                          AFTER:
┌──────────────┐                ┌──────────────┐
│ id (BIGINT)  │                │ id (BIGINT)  │
│ name (STRING)│  ──────►       │ name (STRING)│
│ created (TS) │                │ email (STR)  │ ← NEW
└──────────────┘                │ created (TS) │
                                └──────────────┘

SQL:
ALTER TABLE users ADD COLUMN email STRING;

RESULT:
✅ Zero downtime
✅ No data rewrites
✅ Backward compatible
✅ Old queries still work

Parquet files store data, metadata tracks schema versions
```

---

## SLIDE 28: Partition Evolution Magic
**Layout:** Before/after comparison

```
SCENARIO: Data volume grows 100x

BEFORE (Daily Partitions):
year=2024/month=03/day=10/
  ├─ file-1.parquet (10 GB)
  └─ file-2.parquet (10 GB)

AFTER (Hourly Partitions):
year=2024/month=03/day=10/hour=08/
  ├─ file-3.parquet (512 MB)
  └─ file-4.parquet (512 MB)

TRADITIONAL APPROACH:
1. Create new table with hourly partitions
2. Copy ALL data (expensive!)
3. Switch tables (downtime!)

ICEBERG APPROACH:
ALTER TABLE events ADD PARTITION FIELD hours(timestamp);
✅ No data movement
✅ Zero downtime
✅ Old data keeps daily partitions
✅ New data uses hourly partitions
✅ Queries work seamlessly!
```

---

## SLIDE 29: Performance Optimization
**Layout:** Icon grid (2x3)

```
File Pruning
Compact small files → Target 256-512 MB

Partition Strategy
Match query patterns: daily, hourly, monthly

Statistics Accuracy
Ensure manifests have min/max bounds

Catalog Choice
Use Glue/Polaris, avoid Hadoop

Storage Tiering
Hot (S3 Standard) → Cold (Glacier)

Monitoring
Track file count, size, lag, errors
```

---

## SLIDE 30: Integration Patterns
**Layout:** Architecture diagram

```
┌─────────────────────────────────────────────────┐
│            Kafka Topic (Source)                 │
└───────────────────┬─────────────────────────────┘
                    │ Tableflow
                    ↓
┌─────────────────────────────────────────────────┐
│         Iceberg Table (S3/ADLS)                 │
└───────────────────┬─────────────────────────────┘
                    │ Catalog: Glue + Polaris
    ┌───────────────┼───────────────┬─────────────┐
    │               │               │             │
    ↓               ↓               ↓             ↓
┌────────┐     ┌──────────┐   ┌───────┐    ┌──────────┐
│ Athena │     │Snowflake │   │ Spark │    │Databricks│
│ (SQL)  │     │(Analytics)   │ (ML)  │    │(Lakehouse)
└────────┘     └──────────┘   └───────┘    └──────────┘

ONE TABLE, MULTIPLE ENGINES
No data duplication | Single source of truth
```

---

## SLIDE 31: Week 5-7 Milestones
**Layout:** Checklist style

```
Week 5:
☑ Perform schema evolution on live table
☑ Implement partition evolution scenario
☑ Execute time travel for audit use case
☑ Configure table maintenance schedule

Week 6:
☑ Optimize slow query via compaction
☑ Tune write performance
☑ Select appropriate catalog
☑ Set up monitoring dashboard

Week 7:
☑ Deploy Tableflow → Iceberg pipeline
☑ Configure Flink to write to Iceberg
☑ Access same table from 3+ engines
☑ Implement CDC materialization

READY FOR WEEK 8 WHEN YOU CAN:
✅ Optimize performance independently
✅ Integrate 5+ query engines
✅ Handle production workloads
```

---

## SLIDE 32: Section Breaker
**Layout:** Dark background breaker

```
Week 8: Expert Level
Production Readiness
```

---

## SLIDE 33: Learning Objectives (Expert)
**Layout:** Five item agenda

```
01 Architecture Design
Design production-grade Iceberg infrastructure

02 Monitoring & Alerting
Implement comprehensive observability

03 Failure Handling
Troubleshoot all scenarios independently

04 Cost Optimization
Reduce costs by 30-50% through tuning

05 Stakeholder Presentations
Present to technical and business audiences
```

---

## SLIDE 34: Production Architecture
**Layout:** Architecture diagram (detailed)

```
┌─────────────────────────────────────────────────┐
│              SOURCE SYSTEMS                     │
│  PostgreSQL │ MySQL │ MongoDB │ Apps            │
└──────────────┬──────────────────────────────────┘
               │ CDC (Debezium)
               ↓
┌─────────────────────────────────────────────────┐
│            CONFLUENT CLOUD                      │
│  ┌──────────────────────────────────┐          │
│  │  Kafka Topics (Schema Registry)  │          │
│  └───────────┬──────────────────────┘          │
│              │                                   │
│  ┌───────────▼──────────────────────┐          │
│  │  Flink SQL (Transform, Enrich)   │          │
│  └───────────┬──────────────────────┘          │
│              │                                   │
│  ┌───────────▼──────────────────────┐          │
│  │  Tableflow (Iceberg)             │          │
│  └───────────┬──────────────────────┘          │
└──────────────┼──────────────────────────────────┘
               │
               ↓
     OBJECT STORAGE (S3/ADLS)
     Iceberg Tables (Parquet + Metadata)
               │
      ┌────────┼────────┬─────────┐
      ↓        ↓        ↓         ↓
   Athena  Snowflake  Spark   Databricks
```

---

## SLIDE 35: Monitoring Dashboard
**Layout:** Metrics grid (2x4)

```
KEY METRICS TO MONITOR

Tableflow Throughput        | Tableflow Lag
MB/s, target: > baseline    | Seconds, alert: > 900

DLQ Messages                | File Count
Count, alert: > 0           | Count, alert: > 10,000

Average File Size           | Snapshot Count
MB, alert: < 64 MB          | Count, alert: > 500

Compaction Status           | Error Rate
Success/fail, alert: 3 fails| Errors/min, alert: > 5

DASHBOARD SETUP:
Datadog integration → Real-time visibility
```

---

## SLIDE 36: Failure Scenarios
**Layout:** Table with solutions

```
Scenario                 | Detection              | Resolution
-------------------------|------------------------|---------------------------
Schema Incompatibility   | DLQ messages increase  | Fix schema, replay DLQ
Corrupt Data Files       | Query fails            | Rollback to prev snapshot
Catalog Outage          | Connection errors      | Failover to backup catalog
Snapshot Explosion      | Slow query planning    | Expire old snapshots
Concurrent Write Conflicts| Commit failures       | Retry with backoff

RUNBOOK REQUIRED FOR ALL SCENARIOS
```

---

## SLIDE 37: Cost Optimization
**Layout:** Three column comparison

```
BEFORE (Traditional ETL):
Storage: $200/month
Compute: $300/month
Engineer Time: $500/month
Total: $1,000/month

AFTER (Tableflow):
Tableflow: $300/month
Storage: $100/month
Compute: $150/month
Total: $550/month

SAVINGS: 45% ($450/month)

OPTIMIZATION LEVERS:
• Snapshot retention (7 days)
• Compression (Snappy → Zstd)
• Storage tiering (S3 IA)
• Selective topic enablement
```

---

## SLIDE 38: Stakeholder Presentation
**Layout:** Two column layout

```
TECHNICAL PRESENTATION:
1. Problem Statement (2 min)
2. Solution Architecture (5 min)
3. Technical Benefits (3 min)
4. Live Demo (5 min)
5. Next Steps (2 min)

BUSINESS PRESENTATION:
1. Business Problem (3 min)
2. Tableflow Solution (5 min)
3. ROI Analysis (5 min)
4. Success Stories (2 min)
5. Investment & Timeline (3 min)

KEY SKILL: Translate technical details to business value
```

---

## SLIDE 39: Week 8 Milestones
**Layout:** Checklist style

```
☑ Design production architecture for real use case
☑ Implement monitoring dashboard (10+ metrics)
☑ Create runbook for 5+ failure scenarios
☑ Build cost optimization plan
☑ Present solution to mock stakeholders
☑ Complete final expert challenge

EXPERT CERTIFICATION WHEN YOU CAN:
✅ Design architecture from scratch
✅ Implement monitoring independently
✅ Handle all failures without help
✅ Present to C-level executives
✅ Mentor junior engineers
```

---

## SLIDE 40: Final Expert Challenge
**Layout:** Content box with requirements

```
BUILD END-TO-END PRODUCTION SYSTEM

REQUIREMENTS:
✅ Real-time ingestion: Kafka → Tableflow → Iceberg (< 1 min)
✅ Multi-engine access: Athena, Snowflake, Spark
✅ Schema evolution: Add column without downtime
✅ Time travel: Query yesterday's data
✅ Monitoring: Datadog dashboard with alerts
✅ Cost optimization: Snapshot retention policy
✅ Documentation: Architecture diagram + runbook

SUCCESS CRITERIA:
• 7 days uptime without manual intervention
• Query latency < 5 seconds
• Zero data loss during schema evolution
• All alerts fire correctly
• Total cost under budget estimate
```

---

## SLIDE 41: Section Breaker
**Layout:** Dark background breaker

```
Tools & Resources
```

---

## SLIDE 42: Essential Tools
**Layout:** Icon grid (3x3)

```
☁️ Confluent Cloud          ⚡ Apache Spark
Kafka, Flink, Tableflow     Batch processing

☁️ AWS Services             🌊 Apache Flink
S3, Glue, Athena            Stream processing

❄️ Snowflake                🔍 Trino/Presto
Cloud warehouse             Federated queries

📈 Datadog                  📊 Grafana
Metrics, dashboards         Visualization

🔔 PagerDuty
Incident management
```

---

## SLIDE 43: Learning Resources
**Layout:** Content boxes (4 boxes)

```
OFFICIAL DOCS:
• Apache Iceberg Docs
• Confluent Tableflow Docs
• Iceberg Table Spec
• Confluent Developer

VIDEO COURSES:
• Apache Iceberg 101
• Apache Iceberg + Tableflow
• Flink & Tableflow
• YouTube series

BLOGS:
• Introducing Tableflow
• Tableflow GA: Kafka to Iceberg
• Inside Tableflow Architecture
• Performance tuning guides

INTERNAL:
• Tableflow Main Deck v1.2
• Tableflow L200 Content
• System Architecture Docs
• CSTA Enablement Decks
```

---

## SLIDE 44: Section Breaker
**Layout:** Dark background breaker

```
Success Metrics
```

---

## SLIDE 45: Proficiency Levels
**Layout:** Process infographic (4 steps)

```
BEGINNER (Week 1-2)
Can explain what Iceberg is and why it matters
Score: 60-70%

INTERMEDIATE (Week 3-4)
Understands architecture, performs basic operations
Score: 70-80%

ADVANCED (Week 5-7)
Optimizes performance, integrates multiple engines
Score: 80-90%

EXPERT (Week 8)
Designs production systems, handles all scenarios
Score: 90-100%

YOUR GOAL: Reach Expert level in 8 weeks
```

---

## SLIDE 46: Knowledge Assessment
**Layout:** Table

```
Metric                    | Target      | Validation
--------------------------|-------------|------------------
Architecture Quiz         | 90%+        | Weekly quizzes
Hands-On Labs            | 15+ completed| Lab verification
Production Deployments   | 1+ live     | Production system
Engines Mastered         | 5+          | Multi-engine demo
Troubleshooting Speed    | < 30 min    | Timed exercises
Presentation Confidence  | High        | Stakeholder demo

CERTIFICATION CRITERIA:
All metrics at target level + Final Expert Challenge passed
```

---

## SLIDE 47: Section Breaker
**Layout:** Dark background breaker

```
Top 20 Concepts You Must Master
```

---

## SLIDE 48: Foundation Concepts (Week 1-2)
**Layout:** Five item list

```
01 Open Table Format
Standard for organizing data files as SQL tables

02 Snapshot Isolation
Consistent reads via immutable snapshots

03 Schema Evolution
Add/drop/rename columns without rewrites

04 Partition Evolution
Change partitioning without data movement

05 Time Travel
Query historical table states for audit/debug
```

---

## SLIDE 49: Architecture Concepts (Week 3-4)
**Layout:** Five item list

```
06 Catalog Layer
Entry point storing current metadata location

07 Metadata Files
JSON files with schema, partitions, snapshots

08 Manifest Lists
AVRO files listing manifests per snapshot

09 Manifests
AVRO files listing data files with statistics

10 Data Files
Parquet files containing actual table data
```

---

## SLIDE 50: Advanced Concepts (Week 5-7)
**Layout:** Five item list

```
11 Hidden Partitioning
Users query without partition awareness

12 Column Statistics
Min/max/null counts for query pruning

13 Compaction
Rewriting small files into larger files

14 Snapshot Expiration
Deleting old snapshots to free storage

15 Concurrent Writes
Optimistic concurrency with retry logic
```

---

## SLIDE 51: Production Concepts (Week 8)
**Layout:** Five item list

```
16 Catalog Selection
Choosing Glue vs Polaris vs Unity vs IRC

17 Monitoring Metrics
File count, size, lag, errors, health

18 Dead Letter Queue
Handling schema violations in Tableflow

19 BYOK Encryption
Customer-managed encryption keys

20 Cost Optimization
Retention policies, compression, tiering
```

---

## SLIDE 52: Section Breaker
**Layout:** Dark background breaker

```
Next Steps
```

---

## SLIDE 53: Your Action Plan
**Layout:** Content boxes (4 boxes)

```
WEEK 1-2: START HERE
• Read this deck thoroughly
• Watch Apache Iceberg 101 course
• Set up Confluent Cloud account
• Create first Iceberg table via Tableflow

WEEK 3-4: BUILD SKILLS
• Complete all 5 hands-on labs
• Draw architecture from memory
• Join #iceberg Slack channel
• Ask questions, get help

WEEK 5-7: PRACTICE
• Build real-world use cases
• Optimize performance
• Integrate multiple engines
• Document learnings

WEEK 8: CERTIFY
• Complete final challenge
• Present to peers/stakeholders
• Share knowledge with team
• Celebrate expertise!
```

---

## SLIDE 54: After Certification
**Layout:** Three column layout

```
CONTINUE LEARNING:
• Multi-table transactions
• Branch management
• Advanced transforms
• Custom file formats

COMMUNITY:
• Apache Iceberg mailing list
• Kafka Summit talks
• Blog posts & tutorials
• Open source contributions

CAREER:
• Confluent certifications
• Conference speaking
• Mentoring engineers
• Thought leadership
```

---

## SLIDE 55: Get Support
**Layout:** Content with icons

```
🔗 Official Docs
iceberg.apache.org
docs.confluent.io/tableflow

💬 Slack Channels
#tableflow
#iceberg
#csta-enablement

📧 Contact
Your CSTA: [your-csta@company.com]
Tableflow PM: [pm@company.com]

📚 Resources
Tableflow Main Deck v1.2
Iceberg + Tableflow Course
System Architecture Docs
```

---

## SLIDE 56: Closing Slide
**Layout:** Stream design with logo

```
You're Ready to Become an
Apache Iceberg Expert

8 Weeks | 15+ Labs | Production-Ready

Start Your Journey Today

[Confluent Logo]
```

---

## SLIDE 57: Q&A
**Layout:** Simple text

```
Questions?

Contact:
[Your Name]
[Your Email]
[Your Slack Handle]
```

---

## SLIDE 58: Thank You
**Layout:** Stream design

```
Thank You

Let's Build the Future of
Real-Time Analytics Together

[Confluent Logo]
```

---

## PRESENTATION NOTES

### Slide Transitions
- Use "Fade" for section breakers
- Use "Push" for content slides
- Keep animations minimal and professional

### Color Usage
- Primary content: Midnight (#040531)
- Highlights: Ocean (#0099FF)
- Backgrounds: Mist (#F5F7FF) or Snow (#FBFBFB)
- Accents: Use secondary colors sparingly

### Font Sizes
- Title: 44pt
- Headings: 32pt
- Body: 18-20pt
- Captions: 14pt

### Images & Icons
- Use Confluent icon library from template
- High-quality screenshots for architecture diagrams
- Consistent icon style throughout

### Speaker Notes
Add detailed talking points for each slide in speaker notes section

### Timing
- Total presentation: 45-60 minutes
- Q&A: 15 minutes
- Practice to stay within time

---

## INSTRUCTIONS FOR CREATING SLIDES

1. **Open Template:**
   - Go to: https://docs.google.com/presentation/d/1VEakn4Dk9MnpvI2fxs9lBwkxnuJukZA54iSLOPROHhs
   - File → Make a Copy
   - Rename: "Apache Iceberg Expert Roadmap - [Your Name]"

2. **Use Template Layouts:**
   - Slide 1: "Title Slides" layout
   - Slide 3: "Ten item agenda with objective"
   - Slide 4, 8, 11, etc.: "Breaker Slides - Dark Background"
   - Content slides: Choose from "Layouts" section

3. **Copy Content:**
   - Copy text from this document to corresponding slides
   - Adjust formatting to match template style

4. **Add Visuals:**
   - Use icons from template's "Icons" section
   - Create architecture diagrams using shapes
   - Keep consistent color scheme

5. **Review Checklist:**
   - [ ] All slides use template layouts
   - [ ] Font is Inter (not Montserrat)
   - [ ] Colors match template palette
   - [ ] Icons are consistent
   - [ ] No spelling errors
   - [ ] Speaker notes added
   - [ ] Animations are minimal

6. **Share:**
   - Share with edit access to your team
   - Present to stakeholders
   - Use for customer enablement

---

**Document Version:** 1.0
**Last Updated:** March 12, 2026
**Template Source:** Confluent Presentation Template | OFFICIAL [2025]
