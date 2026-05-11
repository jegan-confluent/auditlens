import type { AuditEvent, EventListResponse, FilterOptions, ForwarderHealth, PatternListResponse, SummaryResponse, SystemStatus, VacuumResult } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8080";

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

export type ReadinessSnapshot = {
  ok: boolean;
  status: number;
  newest_event?: string | null;
  oldest_event?: string | null;
};

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
