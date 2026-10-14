// Shared chart tokens + tooltip so every chart reads as one system.
import type { ReactNode } from "react";

export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
export const AXIS = { stroke: "var(--grid)", tick: { fill: "var(--c-ink-3)", fontSize: 11 }, tickLine: false, axisLine: false } as const;
export const GRID = { stroke: "var(--grid)", vertical: false } as const;

export function ChartTooltip({ active, payload, label, format, labelFormat }: { active?: boolean; payload?: any[]; label?: any; format?: (v: number, name: string) => string; labelFormat?: (l: any) => ReactNode }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      {label != null && <div className="mb-1 font-medium text-ink">{labelFormat ? labelFormat(label) : label}</div>}
      {payload.map((p) => (
        <div key={p.dataKey ?? p.name} className="flex items-center gap-2 text-ink-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color ?? p.fill }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 font-medium tabular text-ink">{format ? format(p.value, p.name) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
