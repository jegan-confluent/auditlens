"use client";

import { useEffect, useState } from "react";
import { apiPut, SaveStatus, useSetting } from "./shared";

export function RetentionTab() {
  const { data, loading, error, reload } = useSetting("retention");
  const [eventDays, setEventDays] = useState("7");
  const [rawDays, setRawDays] = useState("7");
  const [noiseDays, setNoiseDays] = useState("3");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "ok" | "error">("idle");

  useEffect(() => {
    if (!data) return;
    if (data.event_retention_days?.masked) setEventDays(data.event_retention_days.masked);
    if (data.raw_payload_retention_days?.masked) setRawDays(data.raw_payload_retention_days.masked);
    if (data.noise_retention_days?.masked) setNoiseDays(data.noise_retention_days.masked);
  }, [data]);

  async function onSave() {
    setSaveStatus("saving");
    try {
      await apiPut("/settings/retention/event_retention_days", { value: eventDays });
      await apiPut("/settings/retention/raw_payload_retention_days", { value: rawDays });
      await apiPut("/settings/retention/noise_retention_days", { value: noiseDays });
      setSaveStatus("ok");
      reload();
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch {
      setSaveStatus("error");
    }
  }

  if (loading) return <div className="muted">Loading…</div>;
  if (error) return <div className="settings-access-denied">Unavailable: {error}</div>;

  return (
    <div className="settings-section">
      <div className="settings-field">
        <label className="settings-label">Event retention</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={eventDays} onChange={(e) => setEventDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label">Raw payload retention</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={rawDays} onChange={(e) => setRawDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label">Noise retention</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={noiseDays} onChange={(e) => setNoiseDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      <p className="settings-info">
        Raw payload retention removes original Confluent event JSON. Enriched fields are always kept for the full event retention period.
      </p>
      <div className="settings-actions">
        <button className="settings-save-btn" onClick={onSave} disabled={saveStatus === "saving"}>Save</button>
        <SaveStatus status={saveStatus} />
      </div>
    </div>
  );
}
