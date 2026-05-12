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
