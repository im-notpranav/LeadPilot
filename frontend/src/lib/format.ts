export const money = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "-";
  const a = Math.abs(v);
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(a >= 1e5 ? 0 : 1)}k`;
  return `$${Math.round(v)}`;
};
export const pct = (v: number | null | undefined, digits = 0) => (v == null ? "-" : `${(v * 100).toFixed(digits)}%`);
export const num = (v: number | null | undefined, digits = 0) => (v == null ? "-" : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }));
export const signed = (v: number, digits = 1) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;

export const minutes = (m: number | null | undefined) => {
  if (m == null) return "-";
  const a = Math.abs(m);
  const s = a < 60 ? `${Math.round(a)}m` : a < 60 * 48 ? `${(a / 60).toFixed(a < 600 ? 1 : 0)}h` : `${Math.round(a / 1440)}d`;
  return m < 0 ? `-${s}` : s;
};

const dtf = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const tf = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const df = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
export const dateTime = (iso: string | null | undefined) => (iso ? dtf.format(new Date(iso)) : "-");
export const time = (iso: string | null | undefined) => (iso ? tf.format(new Date(iso)) : "-");
export const day = (iso: string | number | null | undefined) => (iso == null ? "-" : df.format(new Date(iso)));

export const ago = (iso: string | null | undefined, nowIso: string | null | undefined) => {
  if (!iso || !nowIso) return "-";
  const m = (new Date(nowIso).getTime() - new Date(iso).getTime()) / 60000;
  return m < 0 ? `in ${minutes(-m)}` : `${minutes(m)} ago`;
};
export const minutesUntil = (iso: string | null | undefined, nowIso: string | null | undefined) =>
  !iso || !nowIso ? null : (new Date(iso).getTime() - new Date(nowIso).getTime()) / 60000;

export const titleCase = (s: string | null | undefined) => (s ? s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "-");
export const human = (s: string | null | undefined) => (s ? s.replace(/_/g, " ") : "-");
