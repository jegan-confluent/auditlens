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
