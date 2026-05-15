"use client";

import { useEffect, useState } from "react";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost/api";

export type SettingEntry = {
  is_secret: boolean;
  is_set: boolean;
  masked: string | null;
  updated_at: string | null;
  updated_by: string | null;
};

export type SettingsCategory = Record<string, SettingEntry>;

export async function apiGet(path: string): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function apiPut(path: string, body: object): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function apiPost(path: string, body: object = {}): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function apiDelete(path: string): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export function useSetting(category: string): { data: SettingsCategory | null; loading: boolean; error: string | null; reload: () => void } {
  const [data, setData] = useState<SettingsCategory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = () => setTick((t) => t + 1);
  useEffect(() => {
    setLoading(true);
    apiGet(`/settings/${category}`)
      .then((d) => { setData(d as SettingsCategory); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [category, tick]);
  return { data, loading, error, reload };
}

export function SaveStatus({ status, message }: { status: "idle" | "saving" | "ok" | "error"; message?: string }) {
  if (status === "idle") return null;
  if (status === "saving") return <span className="settings-save-status saving">Saving…</span>;
  if (status === "ok") return <span className="settings-save-status ok">Saved ✓</span>;
  return <span className="settings-save-status error">Error: {message}</span>;
}
