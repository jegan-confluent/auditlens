import Link from "next/link";
import type { SummaryResponse } from "../lib/types";
import { looksLikeJsonActor, stripPrincipalPrefix } from "../lib/principal";
import { isConfluentInternalActor } from "../lib/utils";

function formatAge(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "recently";
  const ageMin = Math.max(0, (Date.now() - ts) / 60000);
  if (ageMin < 1) return "just now";
  if (ageMin < 60) return `${Math.round(ageMin)}m ago`;
  const ageH = ageMin / 60;
  if (ageH < 24) return `${Math.round(ageH * 10) / 10}h ago`;
  return `${Math.round(ageH / 24)}d ago`;
}

function formatSubject(subject: string, displayName?: string | null): string | null {
  if (!subject || looksLikeJsonActor(subject)) return null;
  if (displayName) return displayName;
  return stripPrincipalPrefix(subject);
}

export default function ActionAlertBanner({ summary }: { summary: SummaryResponse }) {
  const count = summary.action_required_count;
  if (count === 0) return null;

  const topActionFlow = summary.flow_groups
    .filter((g) => g.signal_type === "action_required")
    .filter((g) => !isConfluentInternalActor(g.subject, g.subject_display_name || g.subject || ""))
    .sort((a, b) => b.event_count - a.event_count)[0] ?? null;

  const actorLabel = topActionFlow
    ? formatSubject(topActionFlow.subject, topActionFlow.subject_display_name)
    : null;

  const ageLabel = topActionFlow ? formatAge(topActionFlow.last_seen) : null;

  return (
    <div className="action-alert-banner" role="alert">
      <span className="action-alert-dot" aria-hidden />
      <span className="action-alert-text">
        <strong>{count.toLocaleString()}</strong>
        {" event"}
        {count === 1 ? "" : "s"}
        {" need"}
        {count === 1 ? "s" : ""}
        {" action"}
        {actorLabel ? (
          <>
            {" — "}
            <span className="action-alert-actor">{actorLabel}</span>
            {" activity"}
            {ageLabel ? <> {ageLabel}</> : null}
          </>
        ) : null}
      </span>
      <Link
        href={`/events?signal=action_required&mode=decision&hide_noise=true`}
        className="action-alert-link"
      >
        Investigate →
      </Link>
    </div>
  );
}
