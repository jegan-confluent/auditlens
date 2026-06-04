/**
 * Normalize an actor principal string for display.
 *
 * - Confluent internal service account JSON → "Confluent (internal)"
 * - "User:<numeric>" → "User #<numeric>"  (numeric IDs have no IAM entry)
 * - "User:<id>"     → "<id>"              (strip prefix; u-rrk8nmp is acceptable)
 * - "ServiceAccount:<id>" → "<id>"
 * - Anything else → unchanged
 */
export function normalizeActorDisplay(value: string): string {
  if (value.includes('"externalAccount"') && value.includes('"Confluent"')) return "Confluent (internal)";
  if (/^\d+$/.test(value)) return `User #${value}`;
  if (value.startsWith("User:")) {
    const stripped = value.slice(5);
    if (/^\d+$/.test(stripped)) return `User #${stripped}`;
    return stripped;
  }
  if (value.startsWith("ServiceAccount:")) return value.slice(15);
  return value;
}

/**
 * Identify Confluent's own platform-automation service account.
 *
 * These events (e.g. ScheduledJwksRefresh) are system-internal, not human or
 * customer-service-account activity. UI surfaces that highlight "most active"
 * or "most recent" actors should skip them — they're noise as actor attribution,
 * even when the underlying signal classification is action_required.
 *
 * Triggers on:
 *   - raw subject containing "externalAccount" (JSON-blob form pre-parse)
 *   - display name exactly "Confluent" (parsed externalAccount.subject)
 *   - display name exactly "Confluent (internal)" (normalized form)
 */
export function isConfluentInternalActor(subject: string, display: string): boolean {
  if (subject.includes("externalAccount")) return true;
  if (display === "Confluent" || display === "Confluent (internal)") return true;
  return false;
}

/**
 * Strip a Confluent CRN to its meaningful terminal ID component.
 * crn://confluent.cloud/.../environment=env-abc123  →  env-abc123
 * crn://confluent.cloud/.../cloud-cluster=lkc-abc   →  lkc-abc
 * Non-CRN strings are returned unchanged; null/undefined returns "—".
 */
export function formatResourceName(resource: string | null | undefined): string {
  if (!resource) return "—";
  if (resource.startsWith("crn://")) {
    const parts = resource.replace(/\/$/, "").split("/");
    const last = parts[parts.length - 1] ?? "";
    if (last.includes("=")) {
      return last.split("=").slice(1).join("=") || resource;
    }
    return last || resource;
  }
  return resource;
}
