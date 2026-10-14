import { useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type DealBoard, type Rep } from "../lib/api";
import { dateTime, human, money, pct } from "../lib/format";
import { DealCard } from "../components/deals";
import { Empty, GradePill, Loading, PageHeader, Segmented, Select, StallFlag } from "../components/ui";
import { to } from "../lib/links";

type Card = { lead_id: string; name: string; company: string | null; score: number; grade: string; intent_level: string; owner_rep_id: string | null; owner_name: string | null; acv: number; close_prob: number; expected_value: number; is_stalled: boolean; stall_rules: string[]; stall_risk: number; days_in_stage: number; source: string; history: { ts: string; from: string; to: string; rule_id: string; reason: string; mode: string }[] };
type Column = { stage: string; count: number; acv_total: number; ev_total: number; stalled: number; cards: Card[] };

const SOURCES = ["website", "google_ads", "referral", "trade_show", "partner", "webinar", "cold_outreach", "list_vendor_x"];

type View = "deals" | "leads";

// Deals is the default: one card per deal, however many contacts it has. Leads is the per-person board.
export default function Pipeline() {
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "leads" ? "leads" : "deals";
  const switcher = <Segmented label="Board" value={view} onChange={(v) => setParams(v === "leads" ? { view: "leads" } : {}, { replace: true })}
    options={[{ value: "deals", label: "Deals" }, { value: "leads", label: "Leads" }]} />;
  return view === "leads" ? <LeadBoard switcher={switcher} /> : <DealBoardView switcher={switcher} />;
}

function DealBoardView({ switcher }: { switcher: JSX.Element }) {
  const [params, setParams] = useSearchParams();
  const owner = params.get("owner") ?? "", stalledOnly = !!params.get("stalled"), focus = params.get("stage") ?? "";
  const showClosed = params.get("closed") !== "0";
  const set = (k: string, v: string | null) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };
  const board = useRef<HTMLDivElement>(null);
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const q = useQuery({ queryKey: ["opportunities", owner], queryFn: () => api.get<DealBoard>(`/api/opportunities${owner ? `?owner=${owner}` : ""}`) });
  const columns = (q.data?.columns ?? [])
    .filter((c) => showClosed || !["won", "lost"].includes(c.stage))
    .map((c) => (stalledOnly ? { ...c, cards: c.cards.filter((x) => x.is_stalled) } : c));
  const stalledTotal = (q.data?.columns ?? []).reduce((n, c) => n + c.stalled, 0);
  useEffect(() => {
    if (!focus || !q.data) return;
    board.current?.querySelector(`[data-stage="${focus}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [focus, !!q.data]);

  return (
    <div>
      <PageHeader title="Pipeline" subtitle={q.data ? <>{q.data.open_deals} open deals worth <span className="font-medium text-ink">{money(q.data.pipeline_ev)}</span> expected ({money(q.data.pipeline_acv)} if all win) · <button onClick={() => set("stalled", stalledOnly ? null : "1")} className="drill font-medium text-ink">{stalledTotal} stalled</button></> : "Deals move on evidence from any contact at the company."}
        right={<div className="flex flex-wrap items-center gap-2">
          {switcher}
          <label className={`inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-sm shadow-sm transition ${stalledOnly ? "border-critical/50 bg-[color-mix(in_srgb,var(--c-critical)_8%,transparent)] text-critical-ink" : "border-line bg-surface text-ink-2"}`}><input type="checkbox" checked={stalledOnly} onChange={(e) => set("stalled", e.target.checked ? "1" : null)} /> Stalled only</label>
          <label className="inline-flex h-9 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm text-ink-2 shadow-sm"><input type="checkbox" checked={showClosed} onChange={(e) => set("closed", e.target.checked ? null : "0")} /> Won & lost</label>
          <Select label="Owner" value={owner} onChange={(v) => set("owner", v || null)}><option value="">All</option>{reps.data?.items.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name}</option>)}</Select>
        </div>} />
      {q.isLoading ? <Loading /> : q.isError ? <Empty>Could not load deals. <button onClick={() => q.refetch()} className="font-medium text-accent-ink hover:underline">Try again</button></Empty> : (
        <div ref={board} className="stagger scroll-thin flex gap-3 overflow-x-auto pb-4">
          {columns.map((col) => (
            <div key={col.stage} data-stage={col.stage} className={`glass flex w-64 shrink-0 flex-col rounded-2xl shadow-card ${focus === col.stage ? "target-flash ring-2 ring-brand/50" : ""}`}>
              <div className="border-b border-line px-3 py-2.5">
                <div className="flex items-baseline justify-between">
                  <span className="font-display text-sm font-bold capitalize">{human(col.stage)}</span>
                  <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold tabular text-accent-ink">{stalledOnly ? `${col.cards.length} / ${col.count}` : col.count}</span>
                </div>
                <div className="mt-0.5 text-xs tabular text-ink-3">
                  {["won", "lost"].includes(col.stage) ? `${money(col.acv_total)} value${col.count > col.cards.length ? ` · latest ${col.cards.length}` : ""}` : <>{money(col.ev_total)} EV · {money(col.acv_total)} ACV{col.stalled ? <> · <button onClick={() => set("stalled", "1")} className="drill text-critical-ink">{col.stalled} stalled</button></> : ""}</>}
                </div>
              </div>
              <div className="scroll-thin flex max-h-[calc(100vh-240px)] flex-col gap-2 overflow-y-auto p-2">
                {col.cards.map((d) => <DealCard key={d.opp_id} d={d} />)}
                {!col.cards.length && <div className="py-6 text-center text-xs text-ink-3">{stalledOnly ? "No stalled deals" : "Empty"}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LeadBoard({ switcher }: { switcher: JSX.Element }) {
  const [params, setParams] = useSearchParams();
  const rep = params.get("rep") ?? "", source = params.get("source") ?? "", stalledOnly = !!params.get("stalled"), focus = params.get("stage") ?? "";
  const set = (k: string, v: string | null) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };
  const setRep = (v: string) => set("rep", v), setSource = (v: string) => set("source", v);
  const board = useRef<HTMLDivElement>(null);
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const qs = new URLSearchParams({ ...(rep && { rep_id: rep }), ...(source && { source }) }).toString();
  const q = useQuery({ queryKey: ["pipeline", rep, source], queryFn: () => api.get<{ columns: Column[] }>(`/api/pipeline?${qs}`) });
  const columns = (q.data?.columns ?? []).map((c) => (stalledOnly ? { ...c, cards: c.cards.filter((x) => x.is_stalled) } : c));
  const open = q.data?.columns.filter((c) => !["won", "lost", "nurture"].includes(c.stage)) ?? [];
  const totalEv = open.reduce((s, c) => s + c.ev_total, 0);
  const stalledTotal = open.reduce((s, c) => s + c.stalled, 0);
  // ?stage= scrolls that column into view once the board has loaded.
  useEffect(() => {
    if (!focus || !q.data) return;
    board.current?.querySelector(`[data-stage="${focus}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [focus, !!q.data]);

  return (
    <div>
      <PageHeader title="Pipeline" subtitle={<>Lead stages move automatically on evidence. Open pipeline: <Link to={to.leads({ open: true, rep_id: rep || undefined, source: source || undefined, sort: "ev" })} className="drill font-medium text-ink">{money(totalEv)} expected value</Link> · <button onClick={() => set("stalled", stalledOnly ? null : "1")} className="drill font-medium text-ink">{stalledTotal} stalled</button></>}
        right={<div className="flex flex-wrap items-center gap-2">
          {switcher}
          <label className={`inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-sm shadow-sm transition ${stalledOnly ? "border-critical/50 bg-[color-mix(in_srgb,var(--c-critical)_8%,transparent)] text-critical-ink" : "border-line bg-surface text-ink-2"}`}><input type="checkbox" checked={stalledOnly} onChange={(e) => set("stalled", e.target.checked ? "1" : null)} /> Stalled only</label>
          <Select label="Rep" value={rep} onChange={setRep}><option value="">All</option>{reps.data?.items.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name}</option>)}</Select>
          <Select label="Source" value={source} onChange={setSource}><option value="">All</option>{SOURCES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</Select>
        </div>} />
      {q.isLoading ? <Loading /> : (
        <div ref={board} className="scroll-thin flex gap-3 overflow-x-auto pb-4">
          {columns.map((col) => (
            <div key={col.stage} data-stage={col.stage} className={`glass flex w-64 shrink-0 flex-col rounded-2xl shadow-card ${focus === col.stage ? "target-flash ring-2 ring-brand/50" : ""}`}>
              <div className="border-b border-line px-3 py-2.5">
                <div className="flex items-baseline justify-between">
                  <Link to={to.leads({ stage: col.stage, rep_id: rep || undefined, source: source || undefined })} className="drill font-display text-sm font-bold capitalize" title={`All leads in ${human(col.stage)}`}>{human(col.stage)}</Link>
                  <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold tabular text-accent-ink">{stalledOnly ? `${col.cards.length} / ${col.count}` : col.count}</span>
                </div>
                <div className="mt-0.5 text-xs tabular text-ink-3">{money(col.ev_total)} EV · {money(col.acv_total)} ACV{col.stalled ? <> · <button onClick={() => set("stalled", "1")} className="drill text-critical-ink">{col.stalled} stalled</button></> : ""}</div>
              </div>
              <div className="scroll-thin flex max-h-[calc(100vh-240px)] flex-col gap-2 overflow-y-auto p-2">
                {col.cards.map((c) => <PipelineCard key={c.lead_id} c={c} />)}
                {!col.cards.length && <div className="py-6 text-center text-xs text-ink-3">{stalledOnly ? "No stalled deals" : "Empty"}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PipelineCard({ c }: { c: Card }) {
  const nav = useNavigate();
  return (
    <div className="group relative">
      <Link to={`/leads/${c.lead_id}`} className={`cv-auto block rounded-xl border bg-surface p-3 text-sm shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-card ${c.is_stalled ? "border-[var(--c-critical)]" : "border-line hover:border-brand/40"}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate font-medium">{c.name}</div>
            <div className="truncate text-xs text-ink-3">{c.company ?? "-"}</div>
          </div>
          <GradePill grade={c.grade} score={c.score} />
        </div>
        <div className="mt-2 flex items-center justify-between text-xs tabular text-ink-2">
          <span>{money(c.expected_value)} · {pct(c.close_prob)}</span>
          <span className="text-ink-3">{c.days_in_stage.toFixed(1)}d</span>
        </div>
        <div className="mt-1 flex items-center justify-between gap-2 text-xs text-ink-3">
          {c.owner_name ? <span role="link" tabIndex={0} title={`${c.owner_name}'s queue`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); nav(to.queue(c.owner_rep_id)); }} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); nav(to.queue(c.owner_rep_id)); } }} className="drill truncate">{c.owner_name}</span> : <span className="truncate">Unassigned</span>}
          {c.is_stalled && <StallFlag rules={c.stall_rules} risk={c.stall_risk} />}
        </div>
      </Link>
      {c.history.length > 0 && (
        <div className="pop pointer-events-none absolute left-full top-0 z-20 ml-2 hidden w-72 rounded-xl border border-line bg-surface p-3 text-xs shadow-pop group-hover:block">
          <div className="mb-1 font-medium text-ink">Stage history</div>
          {c.history.slice().reverse().map((h, i) => (
            <div key={i} className="border-t border-line py-1 first:border-0">
              <div className="text-ink"><span className="capitalize">{human(h.from)}</span> → <span className="capitalize">{human(h.to)}</span> <span className="text-ink-3">{h.rule_id}</span></div>
              <div className="text-ink-3">{dateTime(h.ts)} · {h.reason}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
