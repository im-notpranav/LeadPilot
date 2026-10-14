import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { human } from "../lib/format";
import { useTheme, type ThemePref } from "../lib/theme";
import { Icon, type IconName } from "./icons";

export function Card({ title, subtitle, right, children, className = "", pad = true, id }: { title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean; id?: string }) {
  return (
    <section id={id} className={`card rounded-2xl ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 className="font-display text-[15px] font-bold tracking-tight text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, right, eyebrow }: { title: string; subtitle?: ReactNode; right?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-ink">{eyebrow}</div>}
        <h1 className="font-display text-[28px] font-extrabold leading-tight tracking-tight text-ink sm:text-[32px]">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

const GRADE_STYLE: Record<string, string> = {
  A: "bg-[var(--ramp-550)] text-white",
  B: "bg-[var(--ramp-450)] text-white",
  C: "bg-[var(--ramp-250)] text-[#0b0b0b]",
  D: "bg-surface-2 text-ink-2 border border-line",
};
export function GradePill({ grade, score }: { grade: string; score?: number }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-semibold tabular ${GRADE_STYLE[grade] ?? GRADE_STYLE.D}`} title={`Grade ${grade}`}>
      {grade}{score != null && <span className="font-medium opacity-90">{Math.round(score)}</span>}
    </span>
  );
}

const INTENT_LEVEL: Record<string, number> = { none: 0, low: 1, medium: 2, high: 3, hot: 4 };
export function IntentBadge({ level }: { level: string }) {
  const n = INTENT_LEVEL[level] ?? 0;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2" title={`Intent: ${level}`}>
      <span className="flex gap-0.5" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className="h-2.5 w-1 rounded-sm" style={{ background: i <= n ? "var(--series-2)" : "var(--c-line)" }} />
        ))}
      </span>
      <span className={n >= 4 ? "font-semibold text-ink" : ""}>{level}</span>
    </span>
  );
}

export function Chip({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "accent"; title?: string }) {
  const cls = tone === "accent" ? "bg-accent-soft text-accent-ink" : "bg-surface-2 text-ink-2";
  return <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

export function StageBadge({ stage }: { stage: string }) {
  return <span className="inline-flex items-center rounded-full border border-accent/30 bg-accent-soft/60 px-2 py-0.5 text-xs font-medium capitalize text-accent-ink">{human(stage)}</span>;
}

export function StatusTag({ status, children, title }: { status: "good" | "warn" | "serious" | "critical"; children: ReactNode; title?: string }) {
  const icon = { good: "✓", warn: "!", serious: "▲", critical: "■" }[status];
  return (
    <span title={title} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium text-ink" style={{ borderColor: `color-mix(in srgb, var(--c-${status}) 45%, transparent)`, background: `color-mix(in srgb, var(--c-${status}) 9%, transparent)` }}>
      <span aria-hidden className="text-[10px] leading-none" style={{ color: `var(--c-${status})` }}>{icon}</span>
      {children}
    </span>
  );
}

export function StallFlag({ rules, risk }: { rules: string[]; risk?: number }) {
  return <StatusTag status="critical" title={`Stall rules ${rules.join(", ")}${risk != null ? ` · risk ${risk}` : ""}`}>Stalled {rules.join("+")}</StatusTag>;
}

export function Button({ children, onClick, variant = "secondary", size = "md", disabled, title, type = "button" }: { children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; disabled?: boolean; title?: string; type?: "button" | "submit" }) {
  const v = {
    primary: "btn-brand border border-transparent",
    secondary: "bg-surface text-ink border border-line shadow-sm hover:bg-surface-2",
    ghost: "text-ink-2 hover:bg-surface-2 border border-transparent",
    danger: "bg-surface text-critical-ink border border-line hover:bg-surface-2",
  }[variant];
  const s = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm";
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-xl font-medium transition active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 ${v} ${s}`}>
      {children}
    </button>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label?: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-xl border border-line bg-surface-2 p-0.5">
      {options.map((o) => (
        <button key={String(o.value)} onClick={() => onChange(o.value)} aria-pressed={o.value === value}
          className={`rounded-[10px] px-2.5 py-1 text-xs font-medium transition ${o.value === value ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-ink-2 hover:text-ink"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Select({ value, onChange, children, label }: { value: string; onChange: (v: string) => void; children: ReactNode; label?: string }) {
  return (
    <label className="inline-flex items-center gap-2 text-xs text-ink-2">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-xl border border-line bg-surface px-2.5 py-2 text-sm text-ink shadow-sm outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/15">
        {children}
      </select>
    </label>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-0.5 truncate text-lg font-semibold tabular text-ink">{value}</div>
      {sub && <div className="truncate text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Sparkline({ values, width = 64, height = 20 }: { values: number[]; width?: number; height?: number }) {
  if (!values || values.length < 2) return <span className="inline-block" style={{ width, height }} />;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = Math.max(hi - lo, 4);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (width - 4) + 2, height - 2 - ((v - lo) / span) * (height - 4)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} aria-hidden className="overflow-visible">
      <path d={d} fill="none" stroke="var(--c-ink-3)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill="var(--series-1)" stroke="var(--c-surface)" strokeWidth={1.5} />
    </svg>
  );
}

export function Meter({ value, max = 1 }: { value: number; max?: number }) {
  const w = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="h-1.5 w-full rounded-full bg-[var(--ramp-250)]/40" aria-hidden>
      <div className="h-1.5 rounded-full bg-accent" style={{ width: `${w}%` }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-ink-3">
      <span className="grid h-10 w-10 place-items-center rounded-2xl bg-accent-soft text-accent-ink"><Icon name="inbox" size={18} /></span>
      {children}
    </div>
  );
}

/** Shimmering placeholder rows: reads as "content is coming" rather than a bare spinner. */
export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton h-4 rounded-md" style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

/** KPI tile: label, headline number, optional icon and footnote. */
export function StatTile({ label, value, icon, sub, tone = "accent", to }: { label: string; value: ReactNode; icon?: IconName; sub?: ReactNode; tone?: "accent" | "critical" | "good"; to?: string }) {
  const toneCls = { accent: "bg-accent-soft text-accent-ink", critical: "bg-[color-mix(in_srgb,var(--c-critical)_14%,transparent)] text-critical-ink", good: "bg-[color-mix(in_srgb,var(--c-good)_14%,transparent)] text-good-ink" }[tone];
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <div className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">{label}</div>
        {icon && <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg transition group-hover:scale-110 ${toneCls}`}><Icon name={icon} size={14} /></span>}
      </div>
      <div className="mt-1.5 truncate font-display text-2xl font-bold tabular tracking-tight text-ink">{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-ink-3">{sub}</div>}
    </>
  );
  const cls = "card group block rounded-2xl px-4 py-3.5 transition duration-300";
  return to
    ? <Link to={to} className={`${cls} hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-pop`}>{body}</Link>
    : <div className={cls}>{body}</div>;
}

const THEME_OPTS: { value: ThemePref; icon: IconName; label: string }[] = [
  { value: "light", icon: "sun", label: "Light" },
  { value: "dark", icon: "moon", label: "Dark" },
  { value: "system", icon: "monitor", label: "System" },
];

/** Light / dark / system. `compact` renders a single icon button that flips light and dark. */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { pref, resolved, setPref, toggle } = useTheme();
  if (compact) {
    return (
      <button onClick={toggle} aria-label={`Switch to ${resolved === "dark" ? "light" : "dark"} mode`} title={`Switch to ${resolved === "dark" ? "light" : "dark"} mode`}
        className="relative grid h-9 w-9 place-items-center overflow-hidden rounded-xl border border-line bg-surface text-ink-2 shadow-sm transition hover:text-ink">
        <span className={`absolute transition duration-500 ${resolved === "dark" ? "rotate-0 opacity-100" : "-rotate-90 scale-50 opacity-0"}`}><Icon name="moon" /></span>
        <span className={`absolute transition duration-500 ${resolved === "light" ? "rotate-0 opacity-100" : "rotate-90 scale-50 opacity-0"}`}><Icon name="sun" /></span>
      </button>
    );
  }
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-xl border border-line bg-surface-2 p-0.5">
      {THEME_OPTS.map((o) => (
        <button key={o.value} role="radio" aria-checked={pref === o.value} title={o.label} onClick={() => setPref(o.value)}
          className={`grid h-7 w-8 place-items-center rounded-[10px] transition ${pref === o.value ? "bg-surface text-accent-ink shadow-sm ring-1 ring-line" : "text-ink-3 hover:text-ink"}`}>
          <Icon name={o.icon} size={14} />
        </button>
      ))}
    </div>
  );
}

export function Delta({ value }: { value: number }) {
  if (Math.abs(value) < 0.05) return <span className="tabular text-ink-3">±0</span>;
  const up = value > 0;
  return <span className={`tabular font-medium ${up ? "text-good-ink" : "text-critical-ink"}`}>{up ? "▲" : "▼"} {Math.abs(value).toFixed(1)}</span>;
}
