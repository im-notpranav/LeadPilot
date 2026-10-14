// LeadPilot brand: a paper plane taking off over a rising bar chart.
// One geometry, drawn in a few tones, so every size (favicon to splash) stays consistent.
import { useId, type CSSProperties } from "react";

export const PLANE = {
  wing: "M62 4 L2 27 L22 35 Z",       // upper wing
  fold: "M62 4 L22 35 L27 56 Z",      // lit fold
  keel: "M62 4 L33 41 L27 56 Z",      // shaded keel
};
export const BARS = [
  { x: 36, y: 49, h: 11 },
  { x: 45, y: 42, h: 18 },
  { x: 54, y: 33, h: 27 },
];

type MarkProps = { size?: number; tone?: "color" | "mono" | "white"; className?: string; animateBars?: boolean; style?: CSSProperties; title?: string };

export function LogoMark({ size = 32, tone = "color", className, animateBars, style, title }: MarkProps) {
  const id = useId().replace(/:/g, "");
  const fill = (part: "wing" | "fold" | "keel" | "bar") => {
    if (tone === "white") return { wing: "#ffffff", fold: "#dbeafe", keel: "#bfdbfe", bar: "#ffffff" }[part];
    if (tone === "mono") return { wing: "currentColor", fold: "currentColor", keel: "currentColor", bar: "currentColor" }[part];
    return `url(#${id}-${part})`;
  };
  const monoOpacity = tone === "mono" ? { wing: 1, fold: 0.72, keel: 0.5 } : { wing: 1, fold: 1, keel: 1 };
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} style={style} role={title ? "img" : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      {tone === "color" && (
        <defs>
          <linearGradient id={`${id}-wing`} x1="2" y1="27" x2="62" y2="4" gradientUnits="userSpaceOnUse"><stop stopColor="#2563eb" /><stop offset="1" stopColor="#60a5fa" /></linearGradient>
          <linearGradient id={`${id}-fold`} x1="22" y1="35" x2="58" y2="8" gradientUnits="userSpaceOnUse"><stop stopColor="#93c5fd" /><stop offset="1" stopColor="#3b82f6" /></linearGradient>
          <linearGradient id={`${id}-keel`} x1="27" y1="56" x2="62" y2="4" gradientUnits="userSpaceOnUse"><stop stopColor="#1e40af" /><stop offset="1" stopColor="#2563eb" /></linearGradient>
          <linearGradient id={`${id}-bar`} x1="0" y1="60" x2="0" y2="33" gradientUnits="userSpaceOnUse"><stop stopColor="#1d4ed8" /><stop offset="1" stopColor="#3b82f6" /></linearGradient>
        </defs>
      )}
      <g>
        <path d={PLANE.wing} fill={fill("wing")} opacity={monoOpacity.wing} />
        <path d={PLANE.fold} fill={fill("fold")} opacity={monoOpacity.fold} />
        <path d={PLANE.keel} fill={fill("keel")} opacity={monoOpacity.keel} />
      </g>
      {BARS.map((b, i) => (
        <rect key={b.x} x={b.x} y={b.y} width={6.5} height={b.h} rx={1.6} fill={fill("bar")}
          className={animateBars ? "splash-bar" : undefined} style={animateBars ? { animationDelay: `${240 + i * 60}ms` } : undefined} />
      ))}
    </svg>
  );
}

/** "Lead" in ink (navy / white by theme), "Pilot" in brand blue. */
export function Wordmark({ className = "", animate }: { className?: string; animate?: boolean }) {
  if (animate) {
    return (
      <span className={`splash-word font-display font-extrabold tracking-tight ${className}`}>
        <span className="text-ink">Lead</span><span style={{ color: "var(--c-wordmark)" }}>Pilot</span>
      </span>
    );
  }
  return (
    <span className={`font-display font-extrabold tracking-tight ${className}`}>
      <span className="text-ink">Lead</span><span style={{ color: "var(--c-wordmark)" }}>Pilot</span>
    </span>
  );
}

export function Tagline({ className = "" }: { className?: string }) {
  return <span className={`whitespace-nowrap text-ink-3 ${className}`}>Smarter Leads. <span className="text-ink-2">Bigger Deals.</span></span>;
}

/** Primary horizontal lockup. */
export function Logo({ size = 32, tagline = false, className = "" }: { size?: number; tagline?: boolean; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <LogoMark size={size} />
      <span className="flex flex-col leading-none">
        <Wordmark className="text-[1.15rem]" />
        {tagline && <Tagline className="logo-tagline mt-1 text-[11px] font-medium" />}
      </span>
    </span>
  );
}

/** App-icon style tile (blue in light mode, navy in dark) used where a compact badge reads better. */
export function LogoTile({ size = 36, className = "" }: { size?: number; className?: string }) {
  return (
    <span className={`inline-grid place-items-center rounded-[28%] bg-gradient-to-br from-[#60a5fa] to-[#2563eb] shadow-[0_6px_16px_-6px_rgb(37_99_235/.7)] dark:from-[#1e293b] dark:to-[#0f172a] dark:ring-1 dark:ring-white/10 ${className}`} style={{ width: size, height: size }}>
      <span className="dark:hidden"><LogoMark size={size * 0.68} tone="white" /></span>
      <span className="hidden dark:inline"><LogoMark size={size * 0.68} /></span>
    </span>
  );
}
