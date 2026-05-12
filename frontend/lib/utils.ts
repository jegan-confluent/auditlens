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
  if (value.startsWith("User:")) {
    const stripped = value.slice(5);
    if (/^\d+$/.test(stripped)) return `User #${stripped}`;
    return stripped;
  }
  if (value.startsWith("ServiceAccount:")) return value.slice(15);
  return value;
}

/**
 * Strip a Confluent CRN to its meaningful terminal ID component.
 * crn://confluent.cloud/.../environment=env-mkr6ww  →  env-mkr6ww
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
