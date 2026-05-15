export type AuditEvent = {
  id: number;
  event_fingerprint: string;
  timestamp: string;
  result: string;
  actor: string;
  action: string;
  normalized_action: string;
  action_category: string;
  resource_type: string;
  resource_name: string;
  resource_display: string;
  resource_display_name: string;
  cluster_id?: string | null;
  cluster_name?: string | null;
  source_ip?: string | null;
  summary: string;
  is_failure: boolean;
  is_denied: boolean;
  is_routine_noise: boolean;
  impact_type: string;
  risk_level: string;
  change_type: string;
  resource_family: string;
  event_title: string;
  event_summary: string;
  subject: string;
  subject_type: string;
  actor_display_name: string;
  actor_email?: string | null;
  actor_type: string;
  actor_raw_id?: string | null;
  actor_source?: string;
  actor_confidence?: string;
  actor_enriched_at?: string | null;
  resource_display_short: string;
  source_context: string;
  environment_name?: string | null;
  parent_resource?: string | null;
  resource_scope: string;
  resource_criticality: string;
  blast_radius_hint: string;
  production_hint: string;
  source_display?: string;
  source_reason?: string;
  client_id?: string | null;
  client_tool?: string | null;
  connection_id?: string | null;
  request_id?: string | null;
  environment_id?: string | null;
  flink_region?: string | null;
  network_id?: string | null;
  signal_type: string;
  signal_reason: string;
  decision_reason: string;
  decision_label: string;
  recommended_action: string;
  triage_status: string;
  triage_actor?: string | null;
  triage_timestamp?: string | null;
  triage_note?: string | null;
  raw_payload_json?: string;
  rbac_role?: string | null;
  rbac_scope?: string | null;
  plane_type: string;
  suppressed?: boolean;
};

export type EventListResponse = {
  items: AuditEvent[];
  limit: number;
  offset: number;
  total: number;
  scanned_events: number;
  signal_filter_applied: boolean;
  hide_noise_applied: boolean;
  result_limit_reached: boolean;
  next_cursor?: string | null;
  debug?: Record<string, unknown> | null;
};

export type SummaryResponse = {
  total_events: number;
  scanned_events: number;
  failures: number;
  denials: number;
  noise_count: number;
  informational_count: number;
  attention_count: number;
  action_required_count: number;
  failure_count: number;
  denied_count: number;
  destructive_count: number;
  configuration_change_count: number;
  access_change_count: number;
  top_subjects: Array<{ value: string; count: number; display_name?: string }>;
  top_resources: Array<{ value: string; count: number }>;
  top_actions: Array<{ value: string; count: number }>;
  top_signal_reasons: Array<{ value: string; count: number }>;
  flow_groups: Array<{
    group_title: string;
    group_summary: string;
    event_count: number;
    first_seen: string;
    last_seen: string;
    subject: string;
    subject_display_name?: string | null;
    signal_type: string;
    decision_label: string;
    risk_level: string;
    impact_type: string;
    resource_family: string;
    resource_display_short: string;
    recommended_action: string;
    blast_radius_hint?: string;
    production_hint?: string;
    representative_event_ids?: number[];
  }>;
  overall_status: string;
  summary_scope: string;
  sample_limit: number;
  sample_warning?: string | null;
  headline: string;
  short_digest: string;
  by_action_category: Record<string, number>;
  by_resource_type: Record<string, number>;
  by_result: Record<string, number>;
};

export type FilterOptions = {
  resource_types: string[];
  action_categories: string[];
  results: string[];
  actors: string[];
  environments: string[];
};

export type PipelineStatus = "healthy" | "degraded" | "stalled" | "unknown";

export type PipelineLag = {
  kafka_consumer_lag_messages: number | null;
  db_latest_event_at: string | null;
  forwarder_last_write_at: string | null;
  db_behind_seconds: number | null;
  replay_recommended: boolean;
  status: PipelineStatus;
};

export type SystemStatus = {
  consumer_state: string;
  last_successful_poll?: string | null;
  retry_count: number;
  consecutive_error_count: number;
  last_error?: string | null;
  consumer_lag?: number | null;
  records_consumed_total: number;
  db_writer_enabled: boolean;
  db_writer_state: string;
  db_write_success_total: number;
  db_write_error_total: number;
  db_write_batch_size: number;
  db_last_successful_write?: string | null;
  db_last_error?: string | null;
  db_last_cleanup_at?: string | null;
  db_last_cleanup_deleted_count: number;
  storage_usage: Record<string, unknown>;
  database_mode: string;
  db_health?: Record<string, unknown>;
  pipeline_lag?: PipelineLag | null;
  pipeline_status?: PipelineStatus;
  storage_health?: {
    status: "healthy" | "warning" | "critical" | "error";
    db_size_bytes?: number;
    db_size_pretty?: string;
    audit_events_size_pretty?: string;
    noise_table_size_pretty?: string;
    oldest_event_at?: string | null;
    newest_event_at?: string | null;
    events_with_raw_payload?: number;
    retention_days?: number;
    error?: string;
  } | null;
  auth_enabled?: boolean;
};

// Shape of GET /system/forwarder-health (proxies the forwarder's /health).
// Most fields are optional because the proxy returns
// {"status": "unknown", "error": "..."} on failure to fetch.
export type ForwarderHealth = {
  status?: string;
  state?: string;
  error?: string;
  processed_total?: number;
  consumer_lag?: number;
  processing_rate?: number;
  freshness?: {
    last_enriched_event_time?: string | null;
    last_enriched_ingest_at?: string | null;
    last_committed_at?: string | null;
  };
  observability?: {
    consumer_runtime?: {
      consumer_state?: string;
      last_successful_poll?: string | null;
      poll_count?: number;
      empty_poll_count?: number;
      records_consumed_total?: number;
      consecutive_error_count?: number;
      last_error?: string | null;
    };
    db_writer?: {
      enabled?: boolean;
      db_writer_state?: string;
      db_write_success_total?: number;
      db_write_error_total?: number;
      db_write_batch_size?: number;
      db_last_successful_write?: string | null;
      db_last_error?: string | null;
      db_last_cleanup_at?: string | null;
      db_last_cleanup_deleted_count?: number;
      retention_days?: number;
    };
    persistence_storage?: {
      enabled?: boolean;
      healthy?: boolean;
      backend?: string;
      db_path?: string;
      db_file_bytes?: number;
      max_db_size?: number;
      db_max_bytes?: number;
      storage_mode?: string;
      storage_status?: string;
      sqlite_reclaimable_bytes?: number;
      last_vacuum_at?: string | null;
      last_vacuum_status?: string;
      hot_cache_retention_hours?: number;
      data_loss_possible?: boolean;
    };
    data_quality?: {
      missing_principal_total?: number;
      missing_resource_total?: number;
      unknown_method_total?: number;
      classification_fallback_total?: number;
      suppressed_authz_noise_total?: number;
    };
  };
};

export type EventPattern = {
  id: number;
  actor: string;
  actor_display_name?: string | null;
  actor_type?: string | null;
  action: string;
  resource_name: string | null;
  occurrence_count: number;
  window_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
  status: string;
  suppressed_until: string | null;
  suppressed_by: string | null;
  suppression_reason: string | null;
};

export type PatternListResponse = {
  patterns: EventPattern[];
  total: number;
};

export type VacuumResult = {
  status: "success" | "failure" | string;
  trigger?: string;
  before_bytes?: number;
  after_bytes?: number;
  reclaimed_bytes?: number;
  duration_ms?: number;
  error?: string;
  at?: string;
};

export type ActorIpEntry = {
  source_ip: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  occurrence_count: number;
  cloud_provider: string | null;
  region: string | null;
  is_trusted: boolean;
  is_new: boolean;
};

export type ActorIpBaseline = {
  actor: string;
  actor_display_name: string | null;
  ips: ActorIpEntry[];
  total_ips: number;
  new_ips_last_24h: number;
  trusted_ips_configured: boolean;
};

export type NarrativeChapter = {
  category: string;
  event_count: number;
  peak_signal: string;
  actions: string[];
  resources: string[];
};

export type NarrativeAnomaly = {
  type: string;
  description: string;
  severity: string;
};

export type ActorNarrative = {
  actor: string;
  actor_display_name: string | null;
  time_window: string;
  total_events: number;
  non_noise_count: number;
  headline: string;
  chapters: NarrativeChapter[];
  anomalies: NarrativeAnomaly[];
  generated_at: string;
};
