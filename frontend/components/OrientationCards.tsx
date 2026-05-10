"use client";

import type { SummaryResponse } from "../lib/types";

// /summary's top_subjects is capped server-side at 5 entries, so a length
// equal to 5 only tells us "at least 5". Show "5+" in that case so the
// number reads truthfully rather than implying a hard count.
const TOP_SUBJECTS_CAP = 5;

function activeActorsLabel(summary: SummaryResponse): string {
  const distinct = summary.top_subjects.length;
  if (distinct >= TOP_SUBJECTS_CAP) return `${TOP_SUBJECTS_CAP}+`;
  return String(distinct);
}

export default function OrientationCards({
  summary,
  loading,
  error,
}: {
  summary: SummaryResponse | null;
  loading: boolean;
  error: string | null;
}) {
  // The summary endpoint can fail (auth, slow query, network). Render the
  // dashes inline rather than blanking out the whole strip so the layout
  // stays stable while the user keeps scanning the rest of the page.
  const failed = error !== null;
  const placeholder = loading ? "…" : "—";

  const actors = !failed && summary ? activeActorsLabel(summary) : placeholder;
  const attention = !failed && summary ? summary.action_required_count.toLocaleString() : placeholder;
  const failuresCount = !failed && summary ? summary.failure_count + summary.denied_count : 0;
  const failures = !failed && summary ? failuresCount.toLocaleString() : placeholder;

  const attentionTone = !failed && summary && summary.action_required_count > 0 ? "alert" : "ok";
  const failuresTone = !failed && summary && failuresCount > 0 ? "warn" : "ok";

  return (
    <section className="orientation-cards" aria-label="Last 24 hours overview">
      <div className="orientation-card neutral">
        <div className="orientation-card-label">Active actors</div>
        <div className="orientation-card-value">{actors}</div>
        <div className="orientation-card-sub">Last 24 hours</div>
      </div>
      <div className={`orientation-card ${attentionTone}`}>
        <div className="orientation-card-label">Need attention</div>
        <div className="orientation-card-value">{attention}</div>
        <div className="orientation-card-sub">Require investigation</div>
      </div>
      <div className={`orientation-card ${failuresTone}`}>
        <div className="orientation-card-label">Failures</div>
        <div className="orientation-card-value">{failures}</div>
        <div className="orientation-card-sub">Denied or failed requests</div>
      </div>
    </section>
  );
}
