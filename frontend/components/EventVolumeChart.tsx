"use client";

import React from "react";
import {
  Bar,
  BarChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// recharts 2.x class components have type incompatibilities with React 19 JSX types.
// The runtime behaviour is correct; `as unknown as ComponentType<T>` is the
// standard TypeScript workaround — avoids `any` while narrowing each component
// to the specific props we actually pass.
interface _ChartProps { data: DataPoint[]; onClick?: (e: unknown) => void; margin?: { top?: number; right?: number; left?: number; bottom?: number }; children?: React.ReactNode; }
interface _BarProps { dataKey: string; name?: string; stackId?: string; fill?: string; }
interface _AxisProps { dataKey?: string; tick?: Record<string, unknown>; allowDecimals?: boolean; }
interface _ContainerProps { width?: string | number; height?: string | number; children?: React.ReactNode; }
interface _TooltipProps { formatter?: (value: number, name: string) => [string, string]; }
interface _LegendProps { wrapperStyle?: Record<string, unknown>; }

const Chart = BarChart as unknown as React.ComponentType<_ChartProps>;
const BarEl = Bar as unknown as React.ComponentType<_BarProps>;
const XAxisEl = XAxis as unknown as React.ComponentType<_AxisProps>;
const YAxisEl = YAxis as unknown as React.ComponentType<_AxisProps>;
const TooltipEl = Tooltip as unknown as React.ComponentType<_TooltipProps>;
const LegendEl = Legend as unknown as React.ComponentType<_LegendProps>;
const Container = ResponsiveContainer as unknown as React.ComponentType<_ContainerProps>;

type DataPoint = {
  label: string;
  action_required: number;
  attention: number;
  informational: number;
  noise?: number;
};

const SEGMENT_DEFS = [
  { key: "noise" as const, label: "Noise", color: "#9ca3af" },
  { key: "informational" as const, label: "Info", color: "#116466" },
  { key: "attention" as const, label: "Review", color: "#b54708" },
  { key: "action_required" as const, label: "Critical", color: "#b42318" },
] as const;

export default function EventVolumeChart({
  data,
  onBarClick,
  height = 180,
}: {
  data: DataPoint[];
  onBarClick?: (label: string) => void;
  height?: number;
}) {
  if (!data.length) return null;

  // Single bucket: horizontal stacked bar with per-segment count labels
  if (data.length === 1) {
    const d = data[0];
    const total = (d.noise ?? 0) + d.informational + d.attention + d.action_required;
    if (total === 0) return null;

    const segments = SEGMENT_DEFS
      .map((def) => ({ ...def, value: def.key === "noise" ? (d.noise ?? 0) : d[def.key] }))
      .filter((s) => s.value > 0);

    return (
      <div
        style={{ marginBottom: 16, padding: "12px 16px", background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }}
        onClick={() => onBarClick?.(d.label)}
      >
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", marginBottom: 8 }}>
          Signal Breakdown
          <span style={{ fontWeight: 400, marginLeft: 8, textTransform: "none" }}>{d.label} · {total.toLocaleString()} events</span>
        </div>
        <div style={{ display: "flex", height: 28, borderRadius: 4, overflow: "hidden", gap: 1, cursor: onBarClick ? "pointer" : undefined }}>
          {segments.map((seg) => {
            const pct = total > 0 ? seg.value / total : 0;
            const showLabel = pct >= 0.08;
            return (
              <div
                key={seg.key}
                title={`${seg.label}: ${seg.value.toLocaleString()}`}
                style={{
                  flex: seg.value,
                  background: seg.color,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  color: "white",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  padding: "0 6px",
                  minWidth: 0,
                }}
              >
                {showLabel ? `${seg.value.toLocaleString()} ${seg.label}` : ""}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const handleClick = (e: unknown) => {
    const event = e as { activeLabel?: string } | null;
    if (event?.activeLabel && onBarClick) onBarClick(event.activeLabel);
  };

  return (
    <div style={{ marginBottom: 16, padding: "12px 16px", background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", marginBottom: 8 }}>Signal Breakdown</div>
      <Container width="100%" height={height}>
        <Chart
          data={data}
          onClick={handleClick}
          margin={{ top: 4, right: 8, left: -16, bottom: 0 }}
        >
          <XAxisEl dataKey="label" tick={{ fontSize: 11 }} />
          <YAxisEl tick={{ fontSize: 11 }} allowDecimals={false} />
          <TooltipEl formatter={(value: number, name: string) => [value.toLocaleString(), name]} />
          <LegendEl wrapperStyle={{ fontSize: 11 }} />
          <BarEl dataKey="noise" name="Noise" stackId="a" fill="#9ca3af" />
          <BarEl dataKey="informational" name="Info" stackId="a" fill="#116466" />
          <BarEl dataKey="attention" name="Review" stackId="a" fill="#b54708" />
          <BarEl dataKey="action_required" name="Critical" stackId="a" fill="#b42318" />
        </Chart>
      </Container>
    </div>
  );
}
