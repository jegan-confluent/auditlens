"use client";

import { useEffect, useRef, useState } from "react";

export const BREAKDOWN_TIERS = [
  { name: "noise",            label: "Noise",  color: "#888780", description: "routine, expected activity", subtitle: "all clear" },
  { name: "informational",    label: "Info",   color: "#0F6E56", description: "informational events",       subtitle: "informational" },
  { name: "attention",        label: "Review", color: "#BA7517", description: "events needing monitoring",  subtitle: "monitored" },
  { name: "action_required",  label: "Action", color: "#E24B4A", description: "needs immediate action",     subtitle: "needs review" },
] as const;

export type BreakdownTierName = (typeof BREAKDOWN_TIERS)[number]["name"];

type Tier = (typeof BREAKDOWN_TIERS)[number];

function BarSegment({
  tier,
  count,
  total,
  active,
  onSelect,
}: {
  tier: Tier;
  count: number;
  total: number;
  active: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [isNarrow, setIsNarrow] = useState(false);
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipId = `tier-tt-${tier.name}`;
  const pct = total > 0 ? (count / total) * 100 : 0;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setIsNarrow(el.offsetWidth < 60);
    check();
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(check);
      ro.observe(el);
      return () => ro.disconnect();
    }
  }, []);

  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      aria-label={`${count.toLocaleString()} ${tier.label} events, ${pct.toFixed(1)}%`}
      aria-describedby={showTooltip ? tooltipId : undefined}
      aria-pressed={active}
      className={`signal-bar-segment${active ? " active" : ""}`}
      style={{ flex: Math.max(count, 0.001), backgroundColor: tier.color, position: "relative" }}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      onFocus={() => setShowTooltip(true)}
      onBlur={() => setShowTooltip(false)}
    >
      {/* Floating badge above for narrow action segments */}
      {isNarrow && count > 0 ? (
        <div className="signal-bar-badge" style={{ background: tier.color }}>
          {count.toLocaleString()}
        </div>
      ) : !isNarrow && count > 0 ? (
        <span className="signal-bar-inline-count">{count.toLocaleString()}</span>
      ) : null}

      {showTooltip ? (
        <div role="tooltip" id={tooltipId} className="signal-bar-tooltip">
          <strong>{tier.label}</strong>
          {" · "}
          {count.toLocaleString()}
          {" ("}
          {pct.toFixed(1)}
          {"%)"}
          <span>{tier.description}</span>
        </div>
      ) : null}
    </div>
  );
}

export default function SignalBreakdown({
  noise,
  informational,
  attention,
  action_required,
  activeTier,
  onTierSelect,
}: {
  noise: number;
  informational: number;
  attention: number;
  action_required: number;
  activeTier?: string | null;
  onTierSelect?: (tier: string | null) => void;
}) {
  const counts: Record<BreakdownTierName, number> = {
    noise,
    informational,
    attention,
    action_required,
  };
  const total = noise + informational + attention + action_required;

  function handleSelect(name: string) {
    const next = activeTier === name ? null : name;
    if (onTierSelect) {
      onTierSelect(next);
    } else {
      console.log("[SignalBreakdown] tier selected:", next);
    }
  }

  return (
    <div className="signal-breakdown">
      {/* Segmented bar */}
      <div className="signal-bar" role="group" aria-label="Signal breakdown">
        {BREAKDOWN_TIERS.map((tier) => (
          <BarSegment
            key={tier.name}
            tier={tier}
            count={counts[tier.name]}
            total={total}
            active={activeTier === tier.name}
            onSelect={() => handleSelect(tier.name)}
          />
        ))}
      </div>

      {/* Pill legend */}
      <div className="signal-breakdown-pills" role="group" aria-label="Signal tier legend">
        {BREAKDOWN_TIERS.map((tier) => {
          const count = counts[tier.name];
          const isActive = activeTier === tier.name;
          return (
            <button
              key={tier.name}
              type="button"
              role="checkbox"
              aria-checked={isActive}
              className={`signal-breakdown-pill${isActive ? " active" : ""}`}
              style={{ "--tier-color": tier.color } as React.CSSProperties}
              onClick={() => handleSelect(tier.name)}
            >
              <span className="pill-dot" style={{ background: tier.color }} />
              <span className="pill-label">{tier.label}</span>
              <span className="pill-count">{count.toLocaleString()}</span>
              <span className="pill-subtitle">{tier.subtitle}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
