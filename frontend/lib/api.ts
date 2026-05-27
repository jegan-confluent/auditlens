import type { ActorIpBaseline, ActorNarrative, AuditEvent, EventListResponse, FilterHierarchy, FilterOptions, ForwarderHealth, PatternListResponse, SummaryResponse, SystemStatus, VacuumResult } from "./types";

// Relative default: works on every platform (macOS, Linux EC2, Windows
// WSL2) without baking a host into the production bundle. Caddy on :80
// reverse-proxies /api/* → api:8080. NEXT_PUBLIC_API_BASE_URL is honoured
// when a deployment runs without Caddy or behind a non-default proxy —
// e.g. tunnel users who hit `http://localhost:8080/api`.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

export function getSummary(params?: URLSearchParams, signal?: AbortSignal) {
  const query = params?.toString();
  return request<SummaryResponse>(`/summary${query ? `?${query}` : ""}`, signal);
}

export function getEvents(params: URLSearchParams, signal?: AbortSignal) {
  const query = params.toString();
  return request<EventListResponse>(`/events${query ? `?${query}` : ""}`, signal);
}

export function getFailures(signal?: AbortSignal) {
  return request<EventListResponse>("/failures?limit=5", signal);
}

export function getDeletions(signal?: AbortSignal) {
  return request<EventListResponse>("/deletions?limit=5", signal);
}

export function getEvent(id: number, signal?: AbortSignal) {
  return request<AuditEvent>(`/events/${id}`, signal);
}

export async function updateEventTriage(id: number, triage_status: string, triage_note?: string) {
  const response = await fetch(`${API_BASE}/events/${id}/triage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ triage_status, triage_note: triage_note || null })
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<AuditEvent>;
}

export function getFilters(signal?: AbortSignal) {
  return request<FilterOptions>("/filters/options", signal);
}

export function getFilterHierarchy(signal?: AbortSignal) {
  return request<FilterHierarchy>("/filters/hierarchy", signal);
}

export function getSystemStatus(signal?: AbortSignal) {
  return request<SystemStatus>("/system/status", signal);
}

export function getForwarderHealth(signal?: AbortSignal) {
  return request<ForwarderHealth>("/system/forwarder-health", signal);
}

export async function runForwarderVacuum(signal?: AbortSignal): Promise<VacuumResult> {
  const response = await fetch(`${API_BASE}/system/vacuum`, {
    method: "POST",
    cache: "no-store",
    signal,
  });
  const body = (await response.json()) as VacuumResult;
  if (!response.ok && !body.status) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return body;
}

export function getActorIpBaseline(actorId: string, signal?: AbortSignal) {
  return request<ActorIpBaseline>(`/actors/${encodeURIComponent(actorId)}/ip-baseline`, signal);
}

export function getActorNarrative(actorId: string, timeWindow: string = "24h", signal?: AbortSignal) {
  return request<ActorNarrative>(
    `/actors/${encodeURIComponent(actorId)}/narrative?time_window=${encodeURIComponent(timeWindow)}`,
    signal,
  );
}

export function getPatterns(status?: string, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const query = params.toString();
  return request<PatternListResponse>(`/patterns${query ? `?${query}` : ""}`, signal);
}

export async function suppressPattern(id: number, durationHours: number = 24, reason: string = ""): Promise<{ status: string; id: number }> {
  const response = await fetch(`${API_BASE}/patterns/${id}/suppress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_hours: durationHours, reason }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<{ status: string; id: number }>;
}

export async function markPatternExpected(id: number, reason: string = ""): Promise<{ status: string; id: number }> {
  const response = await fetch(`${API_BASE}/patterns/${id}/mark-expected`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<{ status: string; id: number }>;
}

export async function exportEvents(
  params: URLSearchParams,
  format: "csv" | "json"
): Promise<string> {
  const exportParams = new URLSearchParams(params);
  exportParams.set("format", format);
  exportParams.set("limit", "10000");
  // remove pagination params not relevant to export
  exportParams.delete("offset");
  const response = await fetch(`${API_BASE}/events/export?${exportParams.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}

export type FeedbackType = "bug" | "feature" | "general";

export type FeedbackPayload = {
  type: FeedbackType;
  title: string;
  description: string;
  email?: string;
  page_context?: string;
};

export type FeedbackResponse = {
  id: string;
  type: FeedbackType;
  title: string;
  created_at: string;
};

export async function submitFeedback(payload: FeedbackPayload): Promise<FeedbackResponse> {
  const response = await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<FeedbackResponse>;
}

export type ActorMapping = {
  raw_id: string;
  display_name: string;
  team: string | null;
  notes: string | null;
};

export type ActorMappingIn = {
  raw_id: string;
  display_name: string;
  team?: string | null;
  notes?: string | null;
};

export async function getActorMappings(): Promise<ActorMapping[]> {
  const r = await fetch(`${API_BASE}/actor-mappings`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<ActorMapping[]>;
}

export async function createActorMapping(payload: ActorMappingIn): Promise<ActorMapping> {
  const r = await fetch(`${API_BASE}/actor-mappings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(body || `${r.status} ${r.statusText}`);
  }
  return r.json() as Promise<ActorMapping>;
}

export async function updateActorMapping(rawId: string, payload: ActorMappingIn): Promise<ActorMapping> {
  const r = await fetch(`${API_BASE}/actor-mappings/${encodeURIComponent(rawId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(body || `${r.status} ${r.statusText}`);
  }
  return r.json() as Promise<ActorMapping>;
}

export async function deleteActorMapping(rawId: string): Promise<void> {
  const r = await fetch(`${API_BASE}/actor-mappings/${encodeURIComponent(rawId)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export type ResourceCatalogItem = {
  resource_id: string;
  resource_type: string;
  resource_name: string;
  display_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  cluster_id: string | null;
  first_seen: string;
  last_seen: string;
  event_count: number;
};

export type ResourceCatalogResponse = {
  items: ResourceCatalogItem[];
  total: number;
};

export async function getResourceCatalog(params?: { resource_type?: string; search?: string; limit?: number }): Promise<ResourceCatalogItem[]> {
  const q = new URLSearchParams();
  if (params?.resource_type) q.set("resource_type", params.resource_type);
  if (params?.search) q.set("search", params.search);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  const r = await fetch(`${API_BASE}/resources${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<ResourceCatalogItem[]>;
}

export async function getResourceCatalogPage(params?: { resource_type?: string; q?: string; limit?: number }, signal?: AbortSignal): Promise<ResourceCatalogResponse> {
  const query = new URLSearchParams();
  if (params?.resource_type) query.set("resource_type", params.resource_type);
  if (params?.q) query.set("q", params.q);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return request<ResourceCatalogResponse>(`/resources/catalog${qs ? `?${qs}` : ""}`, signal);
}

export type NotificationTestResult = {
  destination: string;
  type?: string;
  status: "sent" | "skipped" | "error";
  error: string | null;
  reason?: string;
};

export type NotificationTestResponse = {
  success: boolean;
  results: NotificationTestResult[];
  sent_count: number;
  error_count: number;
  warning?: string;
  message?: string;
};

export async function testNotification(destinationName?: string): Promise<NotificationTestResponse> {
  const response = await fetch(`${API_BASE}/settings/notifications/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ destination_name: destinationName ?? "" }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<NotificationTestResponse>;
}

export type NotificationDestinationView = {
  name: string;
  type: string;
  enabled: boolean;
  mode: string;
  digest_schedule: string;
  rate_limit_per_minute: number;
  filters: {
    signal_type: string[];
    min_risk_level: string | null;
    action_category: string[];
    exclude_actions: string[];
  };
};

export type NotificationDestinationsResponse = {
  status: "ok" | "no_config" | "no_destinations" | "parse_error";
  config_path: string;
  destinations: NotificationDestinationView[];
};

export async function getNotificationDestinations(signal?: AbortSignal): Promise<NotificationDestinationsResponse> {
  const response = await fetch(`${API_BASE}/notifications/destinations`, { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<NotificationDestinationsResponse>;
}

export async function toggleNotificationDestination(name: string): Promise<{ name: string; enabled: boolean; config_path: string }> {
  const response = await fetch(`${API_BASE}/notifications/destinations/${encodeURIComponent(name)}/toggle`, {
    method: "PATCH",
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<{ name: string; enabled: boolean; config_path: string }>;
}

export type ReadinessSnapshot = {
  ok: boolean;
  status: number;
  newest_event?: string | null;
  oldest_event?: string | null;
};

export type AuthAnalyticsActor = {
  actor: string;
  actor_display_name: string;
  auth_count: number;
  unique_ips: number;
  pct_of_total: number;
  trend: "up" | "down" | "stable";
};

export type AuthAnalyticsSourceIp = {
  source_ip: string;
  auth_count: number;
  unique_actors: number;
  cloud_provider: string;
};

export type AuthAnalyticsResponse = {
  total_auth_events: number;
  time_window: "1d" | "7d";
  top_actors: AuthAnalyticsActor[];
  top_source_ips: AuthAnalyticsSourceIp[];
  concentration: { top3_pct: number };
};

export function getAuthAnalytics(timeWindow: "1d" | "7d" = "1d", signal?: AbortSignal) {
  return request<AuthAnalyticsResponse>(`/auth/analytics?time_window=${timeWindow}`, signal);
}

export async function getReadinessStatus(signal?: AbortSignal): Promise<ReadinessSnapshot> {
  try {
    const response = await fetch(`${API_BASE}/ready`, { cache: "no-store", signal });
    if (!response.ok) {
      return { ok: false, status: response.status };
    }
    const body = (await response.json()) as { db?: { newest_event?: string | null; oldest_event?: string | null } };
    return {
      ok: true,
      status: response.status,
      newest_event: body.db?.newest_event ?? null,
      oldest_event: body.db?.oldest_event ?? null
    };
  } catch (err) {
    if (isAbortError(err)) throw err;
    return { ok: false, status: 0 };
  }
}
