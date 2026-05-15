"use client";

export function NotificationsTab() {
  return (
    <div className="settings-section">
      <p className="muted">
        Notification destinations are configured in <code>notifications.yml</code> at the repo root.
        Copy <code>notifications.example.yml</code> and restart the forwarder to pick up changes.
      </p>
      <p className="settings-info">
        Supported: Slack, Microsoft Teams, generic webhooks. Supports per-destination signal filters, min risk level, and dedup.
      </p>
    </div>
  );
}
