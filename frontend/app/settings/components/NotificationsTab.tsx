"use client";

import { useState } from "react";
import { testNotification } from "../../../lib/api";

export function NotificationsTab() {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testNotification();
      setTestResult(result);
    } catch (e) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="settings-section">
      <p className="settings-info">
        Notification destinations are configured in <code>notifications.yml</code> at the repo root.
        Copy <code>notifications.example.yml</code> and restart the forwarder to pick up changes.
      </p>
      <p className="muted">
        Supported: Slack, Microsoft Teams, generic webhooks. Supports per-destination signal filters,
        minimum risk level, and deduplication.
      </p>
      <div style={{ marginTop: 16 }}>
        <button
          className="settings-test-btn"
          onClick={() => { void handleTest(); }}
          disabled={testing}
        >
          {testing ? "Testing…" : "Send test notification"}
        </button>
      </div>
      {testResult !== null && (
        <p
          className={testResult.success ? "settings-info" : "settings-access-denied"}
          style={{ marginTop: 8 }}
        >
          {testResult.success ? "✓ " : "✗ "}{testResult.message}
        </p>
      )}
    </div>
  );
}
