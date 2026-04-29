import fs from "node:fs";

const required = [
  "app/dashboard/page.tsx",
  "app/events/page.tsx",
  "app/system/page.tsx",
  "components/FilterBar.tsx",
  "components/AuditEventTable.tsx",
  "components/EventDetailDrawer.tsx",
  "components/EmptyState.tsx",
  "components/ErrorState.tsx"
];

for (const file of required) {
  if (!fs.existsSync(new URL(`../${file}`, import.meta.url))) {
    throw new Error(`Missing frontend file: ${file}`);
  }
}

console.log("frontend smoke checks passed");
