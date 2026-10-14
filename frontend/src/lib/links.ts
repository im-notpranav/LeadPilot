// One place for drill-down URLs, so every number, chip and bar in the app lands on the same filtered views.
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

export type LeadFilter = {
  q?: string; stage?: string; grade?: string; source?: string; rep_id?: string; stalled?: boolean; open?: boolean;
  status?: string; intent?: string; signal?: string; min?: number; max?: number; sort?: string;
};

const qs = (o: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const to = {
  lead: (id: string) => `/leads/${id}`,
  leads: (f: LeadFilter = {}) => `/leads${qs(f)}`,
  queue: (rep?: string | null) => `/queue${qs({ rep: rep ?? undefined })}`,
  pipeline: (o: { rep?: string | null; source?: string; stalled?: boolean; stage?: string } = {}) => `/pipeline${qs({ rep: o.rep ?? undefined, source: o.source, stalled: o.stalled, stage: o.stage })}`,
  feed: (o: { type?: string; lead?: string } = {}) => `/feed${qs(o)}`,
  analytics: (section?: "funnel" | "response" | "scores" | "grades" | "stages" | "reps") => `/analytics${section ? `#${section}` : ""}`,
  quality: (section?: "sources" | "review" | "quarantine" | "merges") => `/quality${section ? `#${section}` : ""}`,
};

/** Signals carry their count and window ("pricing_page_x2_7d"); the base name is what you filter on. */
export const signalBase = (s: string) => s.replace(/_x\d+_\d+d$/, "");

/** Scroll to #section after navigation and briefly highlight it. */
export function useHashScroll(ready = true) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash || !ready) return;
    const el = document.getElementById(hash.slice(1));
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.remove("target-flash"); void el.offsetWidth; el.classList.add("target-flash");
  }, [hash, ready]);
}

/** In-page jump to a section by id, with the same highlight as a #hash link. */
export function jumpTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  el.classList.remove("target-flash"); void el.offsetWidth; el.classList.add("target-flash");
}
