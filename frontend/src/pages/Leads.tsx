// Every lead, filterable. Most drill-downs in the app land here with filters already set in the URL.
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, STAGES, type LeadView, type Rep } from "../lib/api";
import { human, money, pct } from "../lib/format";
import { signalBase, to } from "../lib/links";
import { Card, Chip, Empty, GradePill, IntentBadge, Loading, PageHeader, Select, Sparkline, StageBadge, StallFlag } from "../components/ui";
import { Icon } from "../components/icons";

const SOURCES = ["website", "google_ads", "referral", "trade_show", "partner", "webinar", "cold_outreach", "list_vendor_x"];
const GRADES = ["A", "B", "C", "D"];
const INTENTS = ["hot", "high", "medium", "low", "none"];
const SORTS = [{ v: "priority", l: "Priority" }, { v: "score", l: "Score" }, { v: "ev", l: "Expected value" }, { v: "created", l: "Newest first" }];
const LIMIT = 500;
const PAGE = 100; // rows rendered at a time; more mount as you scroll, so the page stays light

export default function Leads() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };
  const [q, setQ] = useState(get("q"));
  // A link elsewhere may change ?q= while this page is open; ignore our own (trimmed) writes.
  useEffect(() => { if (get("q") !== q.trim()) setQ(get("q")); }, [params]);
  useEffect(() => { const t = setTimeout(() => { if (q !== get("q")) set("q", q.trim() || null); }, 250); return () => clearTimeout(t); }, [q]);

  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const repName = (id: string) => reps.data?.items.find((r) => r.rep_id === id)?.name ?? id;

  // Server-side filters go to /api/leads; intent, signal and score range are applied here.
  const server = new URLSearchParams({ limit: String(LIMIT), sort: get("sort") || "priority" });
  for (const k of ["q", "stage", "grade", "source", "rep_id", "status"]) if (get(k)) server.set(k, get(k));
  if (get("stalled")) server.set("stalled", "true");
  if (get("open")) { server.set("include_closed", "false"); server.set("status", "active"); }
  const res = useQuery({ queryKey: ["leads", server.toString()], queryFn: () => api.get<{ items: LeadView[]; total: number }>(`/api/leads?${server}`) });

  const rows = useMemo(() => {
    const min = get("min") ? Number(get("min")) : -Infinity, max = get("max") ? Number(get("max")) : Infinity;
    return (res.data?.items ?? []).filter((l) =>
      (!get("intent") || l.intent_level === get("intent")) &&
      (!get("signal") || l.active_signals.some((s) => signalBase(s) === get("signal"))) &&
      l.score >= min && l.score <= max);
  }, [res.data, params]);

  const active: [string, string][] = [];
  if (get("q")) active.push(["q", `Search “${get("q")}”`]);
  if (get("stage")) active.push(["stage", `Stage: ${get("stage").split(",").map(human).join(", ")}`]);
  if (get("grade")) active.push(["grade", `Grade ${get("grade")}`]);
  if (get("source")) active.push(["source", `Source: ${human(get("source"))}`]);
  if (get("rep_id")) active.push(["rep_id", `Owner: ${repName(get("rep_id"))}`]);
  if (get("stalled")) active.push(["stalled", "Stalled only"]);
  if (get("open")) active.push(["open", "Open only"]);
  if (get("status")) active.push(["status", `Status: ${get("status")}`]);
  if (get("intent")) active.push(["intent", `Intent: ${get("intent")}`]);
  if (get("signal")) active.push(["signal", `Signal: ${human(get("signal"))}`]);
  if (get("min") || get("max")) active.push(["min", `Score ${get("min") || 0}–${get("max") || 100}`]);
  const clear = (k: string) => { const n = new URLSearchParams(params); n.delete(k); if (k === "min") n.delete("max"); setParams(n, { replace: true }); };

  const truncated = (res.data?.total ?? 0) > LIMIT;
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Leads" subtitle={res.data ? `${rows.length.toLocaleString()} of ${res.data.total.toLocaleString()} leads${truncated ? ` (first ${LIMIT} by ${get("sort") || "priority"})` : ""}` : "All leads in the workspace"}
        right={<Select label="Sort" value={get("sort") || "priority"} onChange={(v) => set("sort", v === "priority" ? null : v)}>{SORTS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}</Select>} />

      <div className="card mb-4 rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-xl border border-line bg-surface px-3 shadow-sm focus-within:border-brand focus-within:ring-4 focus-within:ring-brand/15">
            <Icon name="search" className="text-ink-3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, company, email or lead ID" aria-label="Search leads" className="field-input" />
          </label>
          <Select value={get("stage")} onChange={(v) => set("stage", v)}><option value="">All stages</option>{STAGES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</Select>
          <Select value={get("grade")} onChange={(v) => set("grade", v)}><option value="">All grades</option>{GRADES.map((g) => <option key={g} value={g}>Grade {g}</option>)}</Select>
          <Select value={get("intent")} onChange={(v) => set("intent", v)}><option value="">Any intent</option>{INTENTS.map((g) => <option key={g} value={g}>{g}</option>)}</Select>
          <Select value={get("source")} onChange={(v) => set("source", v)}><option value="">All sources</option>{SOURCES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</Select>
          <Select value={get("rep_id")} onChange={(v) => set("rep_id", v)}><option value="">All owners</option>{reps.data?.items.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name}</option>)}</Select>
          <label className="inline-flex h-9 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm text-ink-2 shadow-sm"><input type="checkbox" checked={!!get("stalled")} onChange={(e) => set("stalled", e.target.checked ? "1" : null)} /> Stalled</label>
          <label className="inline-flex h-9 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm text-ink-2 shadow-sm"><input type="checkbox" checked={!!get("open")} onChange={(e) => set("open", e.target.checked ? "1" : null)} /> Open only</label>
        </div>
        {active.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
            {active.map(([k, label]) => (
              <button key={k} onClick={() => clear(k)} className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent-ink transition hover:brightness-95" aria-label={`Remove filter ${label}`}>
                {label}<Icon name="close" size={12} />
              </button>
            ))}
            <button onClick={() => setParams(new URLSearchParams(get("sort") ? { sort: get("sort") } : {}), { replace: true })} className="ml-1 text-xs font-medium text-ink-3 hover:text-ink">Clear all</button>
          </div>
        )}
      </div>

      <Card pad={false}>
        {res.isLoading ? <Loading rows={6} /> : res.isError ? <Empty>Could not load leads. <button onClick={() => res.refetch()} className="font-medium text-accent-ink hover:underline">Try again</button></Empty> : !rows.length ? <Empty>No leads match these filters.</Empty> : <LeadsTable rows={rows} />}
      </Card>
    </div>
  );
}

function LeadsTable({ rows }: { rows: LeadView[] }) {
  const nav = useNavigate();
  const stop = (e: MouseEvent) => e.stopPropagation();
  const [shown, setShown] = useState(PAGE);
  const more = useRef<HTMLDivElement>(null);
  useEffect(() => setShown(PAGE), [rows]);
  useEffect(() => {
    const el = more.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) setShown((n) => n + PAGE); }, { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, [shown, rows]);
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[1080px] text-sm">
        <thead><tr className="border-b border-line bg-surface-2/60 text-left text-[11px] uppercase tracking-[0.06em] text-ink-3">
          {["Lead", "Score", "Intent", "Stage", "Owner", "Source", "Deal", "Created"].map((h) => <th key={h} className="px-3 py-2.5 font-semibold first:pl-4">{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.slice(0, shown).map((l) => (
            <tr key={l.lead_id} onClick={() => nav(to.lead(l.lead_id))} className="cursor-pointer border-b border-line align-top transition-colors last:border-0 hover:bg-accent-soft/40">
              <td className="max-w-[240px] py-3 pl-4 pr-3">
                <Link to={to.lead(l.lead_id)} onClick={stop} className="font-medium text-ink hover:underline">{l.name}</Link>
                <div className="truncate text-xs text-ink-3">
                  {l.company ? <Link to={to.leads({ q: l.company })} onClick={stop} className="drill">{l.company}</Link> : "-"} · {l.lead_id}
                </div>
              </td>
              <td className="px-3 py-3">
                <div className="flex items-center gap-2"><Link to={to.leads({ grade: l.grade })} onClick={stop} title={`All grade ${l.grade} leads`}><GradePill grade={l.grade} score={l.score} /></Link><Sparkline values={l.sparkline} /></div>
              </td>
              <td className="max-w-[200px] px-3 py-3">
                <Link to={to.leads({ intent: l.intent_level })} onClick={stop} title={`All ${l.intent_level}-intent leads`}><IntentBadge level={l.intent_level} /></Link>
                <div className="mt-1 flex flex-wrap gap-1">{l.active_signals.slice(0, 2).map((s) => <Link key={s} to={to.leads({ signal: signalBase(s) })} onClick={stop}><Chip>{human(s)}</Chip></Link>)}</div>
              </td>
              <td className="px-3 py-3">
                <div className="flex flex-col items-start gap-1">
                  <Link to={to.pipeline({ stage: l.stage })} onClick={stop} title="Show in pipeline"><StageBadge stage={l.stage} /></Link>
                  {l.is_stalled && <Link to={to.leads({ stalled: true })} onClick={stop}><StallFlag rules={l.stall.rules} risk={l.stall.risk} /></Link>}
                  {l.status !== "active" && <Chip>{l.status}</Chip>}
                </div>
              </td>
              <td className="px-3 py-3 text-sm">{l.owner_rep_id ? <Link to={to.queue(l.owner_rep_id)} onClick={stop} className="drill text-ink-2">{l.owner_name}</Link> : <span className="text-ink-3">Unassigned</span>}</td>
              <td className="px-3 py-3 text-sm"><Link to={to.leads({ source: l.source })} onClick={stop} className="drill text-ink-2">{human(l.source)}</Link></td>
              <td className="px-3 py-3 text-xs tabular text-ink-2">{money(l.expected_value)} EV<div className="text-ink-3">{money(l.predicted_acv)} · {pct(l.close_prob)}</div></td>
              <td className="px-3 py-3 text-xs tabular text-ink-3">{l.created_at?.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown < rows.length && <div ref={more} className="px-4 py-3 text-center text-xs text-ink-3">Loading more rows…</div>}
    </div>
  );
}
