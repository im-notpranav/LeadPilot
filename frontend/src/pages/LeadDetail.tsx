import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, EVENT_TYPES, REP_EVENTS, STAGES, type Factor, type LeadDetail as Lead, type Rep, type ScorePoint } from "../lib/api";
import { useLive } from "../lib/live";
import { can, useAuth } from "../lib/auth";
import { ago, dateTime, human, minutes, minutesUntil, money, pct, signed, titleCase } from "../lib/format";
import { AXIS, GRID } from "../components/charts";
import { Button, Card, Chip, Delta, Empty, GradePill, IntentBadge, Loading, Select, StageBadge, StallFlag, Stat, StatusTag } from "../components/ui";

export default function LeadDetail() {
  const { id = "" } = useParams();
  const { me } = useAuth();
  const lead = useQuery({ queryKey: ["lead", id], queryFn: () => api.get<Lead>(`/api/leads/${id}`) });
  const hist = useQuery({ queryKey: ["lead", id, "score"], queryFn: () => api.get<{ points: ScorePoint[] }>(`/api/leads/${id}/score-history`) });
  const tl = useQuery({ queryKey: ["lead", id, "timeline"], queryFn: () => api.get<{ items: any[] }>(`/api/leads/${id}/timeline`) });

  if (lead.isLoading) return <Card><Loading rows={5} /></Card>;
  if (lead.error) return <Empty>Lead not found. <Link className="text-accent-ink underline" to="/queue">Back to queue</Link></Empty>;
  const l = lead.data!;
  if (l.status === "merged") {
    return <Empty>{id} was merged as a duplicate into <Link className="font-medium text-accent-ink underline" to={`/leads/${l.merged_into}`}>{l.merged_into}</Link>.</Empty>;
  }
  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <Header l={l} />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <ScoreChart points={hist.data?.points ?? []} />
          <Waterfall factors={l.factors} score={l.score} />
          <Timeline items={tl.data?.items ?? []} />
        </div>
        <div className="space-y-4">
          <NextAction l={l} />
          <Prediction l={l} />
          <StallPanel l={l} />
          <QualityPanel l={l} />
          <Assignments l={l} />
          <ManualControls l={l} />
          {can.manage(me) && <InjectEvent l={l} />}
        </div>
      </div>
    </div>
  );
}

function Header({ l }: { l: Lead }) {
  return (
    <section className="card relative isolate overflow-hidden rounded-2xl p-5">
      <div className="pointer-events-none absolute -right-16 -top-24 -z-10 h-56 w-56 rounded-full bg-[var(--c-glow-1)] blur-3xl" aria-hidden />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-2xl font-extrabold tracking-tight">{l.name}</h1>
            <GradePill grade={l.grade} score={l.score} />
            <StageBadge stage={l.stage} />
            {l.is_stalled && <StallFlag rules={l.stall.rules} risk={l.stall.risk} />}
            {l.fake_status !== "clean" && <StatusTag status={l.fake_status === "fake" ? "critical" : "serious"}>{l.fake_status === "fake" ? "Quarantined" : "Suspicious"} · fake {l.fake_score}</StatusTag>}
          </div>
          <p className="mt-1 text-sm text-ink-2">
            {l.title ?? "No title"} · {l.company ?? "Unknown company"}{l.employees ? ` (${l.employees.toLocaleString()} employees, ${human(l.industry)})` : ""} · {l.country ?? "-"} / {l.region ?? "-"}
          </p>
          <p className="mt-0.5 text-xs text-ink-3">{l.lead_id} · {l.email} {l.phone ? `· ${l.phone}` : ""} · sources {l.sources.map(human).join(", ")}</p>
        </div>
        <div className="flex items-center gap-2 text-sm"><span className="text-ink-3">Owner</span><span className="font-medium">{l.owner_name ?? "Unassigned"}</span></div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Score" value={l.score.toFixed(1)} sub={`fit ${l.parts.fit.toFixed(0)} · eng ${l.parts.engagement.toFixed(0)} · intent ${l.parts.intent.toFixed(0)} · pen ${l.parts.penalties.toFixed(0)}`} />
        <Stat label="Intent" value={<IntentBadge level={l.intent_level} />} sub={l.active_signals.map(human).join(", ") || "no active signals"} />
        <Stat label="Close probability" value={pct(l.close_prob, 1)} sub={`${l.days_in_stage.toFixed(1)}d in ${human(l.stage)}`} />
        <Stat label="Predicted ACV" value={money(l.predicted_acv)} sub={`${money(l.acv_p10)} – ${money(l.acv_p90)}`} />
        <Stat label="Expected value" value={money(l.expected_value)} sub="ACV × probability" />
        <Stat label="Priority" value={l.priority.toFixed(0)} sub={l.priority_drivers.map((d) => d.label).join(" · ")} />
      </div>
    </section>
  );
}

function ScoreChart({ points }: { points: ScorePoint[] }) {
  const [sel, setSel] = useState<number | null>(null);
  const data = points.map((p, i) => ({ ...p, i, t: new Date(p.ts).getTime() }));
  const chosen = sel != null ? data.find((d) => d.id === sel) : data[data.length - 1];
  const t0 = data[0]?.t ?? 0, t1 = data[data.length - 1]?.t ?? 0;
  const ticks = t1 - t0 > 3600000 ? [0, 1, 2, 3, 4].map((k) => Math.round(t0 + ((t1 - t0) * k) / 4)) : [t0];
  const spanDays = (t1 - t0) / 86400000;
  const fmtTick = (v: number) => new Date(v).toLocaleString(undefined, spanDays > 2 ? { month: "short", day: "numeric", timeZone: "UTC" } : { day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  const shown = chosen?.contributions.filter((c) => Math.abs(c.delta) >= 0.05) ?? [];
  return (
    <Card title="Score over time" subtitle="Every point is a processed event or a time tick. Click a point to see exactly why the score moved.">
      {data.length < 1 ? <Empty>No score history yet.</Empty> : (
        <>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}
                onClick={(e: any) => { const p = e?.activePayload?.[0]?.payload; if (p) setSel(p.id); }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="t" type="number" domain={[t0, t1]} ticks={ticks} {...AXIS} tickFormatter={fmtTick} />
                <YAxis domain={[0, 100]} ticks={[0, 40, 60, 80, 100]} {...AXIS} />
                <ReferenceLine y={80} stroke="var(--grid)" />
                <Tooltip cursor={{ stroke: "var(--c-ink-3)", strokeWidth: 1 }}
                  content={({ active, payload }) => {
                    const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
                    if (!active || !p) return null;
                    return (
                      <div className="max-w-xs rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-pop">
                        <div className="font-medium text-ink">{p.score.toFixed(1)} <span className="text-ink-3">({signed(p.delta)})</span></div>
                        <div className="text-ink-3">{dateTime(p.ts)} · {human(p.event_type)}</div>
                        <div className="mt-1 text-ink-2">{p.summary}</div>
                      </div>
                    );
                  }} />
                <Line type="monotone" dataKey="score" stroke="var(--series-1)" strokeWidth={2} isAnimationActive={false}
                  dot={(props: any) => {
                    const { cx, cy, payload } = props;
                    const big = Math.abs(payload.delta) >= 3 || payload.id === chosen?.id;
                    return <circle key={payload.id} cx={cx} cy={cy} r={payload.id === chosen?.id ? 5 : big ? 4 : 0} fill="var(--series-1)" stroke="var(--c-surface)" strokeWidth={2} />;
                  }}
                  activeDot={{ r: 6, stroke: "var(--c-surface)", strokeWidth: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {chosen && (
            <div className="mt-3 rounded-lg bg-surface-2 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="text-sm font-medium">{chosen.summary}</div>
                <div className="text-xs text-ink-3">{dateTime(chosen.ts)} · {human(chosen.event_type)} · {chosen.event_id}</div>
              </div>
              <ul className="mt-2 space-y-1">
                {shown.length === 0 && <li className="text-xs text-ink-3">No factor changed.</li>}
                {shown.map((c) => (
                  <li key={c.key} className="flex items-baseline gap-2 text-sm">
                    <span className={`w-14 shrink-0 text-right font-medium tabular ${c.delta >= 0 ? "text-good-ink" : "text-critical-ink"}`}>{signed(c.delta)}</span>
                    <span className="w-24 shrink-0 text-xs text-ink-3">{titleCase(c.category)}</span>
                    <span className="text-ink">{c.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

const CAT_ORDER = ["fit", "engagement", "intent", "penalty", "clamp"];
function Waterfall({ factors, score }: { factors: Record<string, Factor>; score: number }) {
  const rows = useMemo(() => {
    const fs = Object.values(factors).filter((f) => Math.abs(f.value) >= 0.05);
    fs.sort((a, b) => CAT_ORDER.indexOf(a.category) - CAT_ORDER.indexOf(b.category) || Math.abs(b.value) - Math.abs(a.value));
    let run = 0;
    return fs.map((f) => { const start = run; run += f.value; return { f, start, end: run }; });
  }, [factors]);
  const scale = (v: number) => `${Math.max(0, Math.min(100, v))}%`;
  return (
    <Card title="Factor breakdown" subtitle={`Fit + engagement + intent − penalties = ${score.toFixed(1)}. Bars show each factor's step on the 0–100 scale.`}>
      <div className="space-y-1.5">
        {rows.map(({ f, start, end }) => (
          <div key={f.key} className="grid grid-cols-[minmax(0,180px)_1fr_56px] items-center gap-3 text-sm" title={f.reason}>
            <div className="min-w-0">
              <div className="truncate text-ink">{titleCase(f.label || f.key.split(".")[1])}</div>
              <div className="truncate text-[11px] text-ink-3">{titleCase(f.category)} · {f.reason}</div>
            </div>
            <div className="relative h-3 rounded bg-surface-2">
              <div className="absolute top-0 h-3 rounded" style={{
                left: scale(Math.min(start, end)), width: `calc(${scale(Math.max(start, end))} - ${scale(Math.min(start, end))})`, minWidth: 2,
                background: f.value >= 0 ? (f.category === "fit" ? "var(--series-1)" : f.category === "engagement" ? "var(--series-3)" : "var(--series-2)") : "var(--c-critical)",
              }} />
            </div>
            <div className={`text-right tabular ${f.value < 0 ? "text-critical-ink" : "text-ink"}`}>{signed(f.value)}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-2">
        {[["Fit", "var(--series-1)"], ["Engagement", "var(--series-3)"], ["Intent", "var(--series-2)"], ["Penalty", "var(--c-critical)"]].map(([l, c]) => (
          <span key={l} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{l}</span>
        ))}
      </div>
    </Card>
  );
}

const KIND_LABEL: Record<string, string> = { event: "Event", score: "Score", stage: "Stage", assignment: "Owner", action: "Action", stall: "Stall", merge: "Merge" };
function Timeline({ items }: { items: any[] }) {
  const [filter, setFilter] = useState<string>("all");
  const shown = items.filter((i) => filter === "all" || i.kind === filter).slice().reverse();
  return (
    <Card title="Unified timeline" subtitle="Events, score changes, stage moves, assignments, actions and flags in one chronological view."
      right={<div className="flex flex-wrap gap-1">{["all", "event", "score", "stage", "assignment", "action", "stall"].map((k) => (
        <button key={k} onClick={() => setFilter(k)} className={`rounded-md px-2 py-0.5 text-xs ${filter === k ? "bg-accent-soft text-accent-ink" : "text-ink-2 hover:bg-surface-2"}`}>{k === "all" ? "All" : KIND_LABEL[k]}</button>
      ))}</div>}>
      <ol className="scroll-thin max-h-[560px] space-y-0 overflow-y-auto">
        {shown.map((i, n) => <TimelineRow key={n} i={i} />)}
        {!shown.length && <Empty>Nothing here.</Empty>}
      </ol>
    </Card>
  );
}

function TimelineRow({ i }: { i: any }) {
  let body: React.ReactNode = null;
  if (i.kind === "event") {
    const pl = i.payload ?? {};
    const detail = pl.page_category ? `${pl.page_category} page` : pl.body ? `“${pl.body}”` : pl.outcome ? pl.outcome : pl.meeting_type ? pl.meeting_type : pl.amount ? money(pl.amount) : pl.status ? `fake score ${pl.fake_score} (${pl.status})` : pl.found ? `${pl.employees} employees, ${pl.industry}` : pl.template ? `template ${pl.template}` : pl.merged_from ? `duplicate ${pl.merged_from} merged` : "";
    body = <><span className="font-medium">{human(i.type)}</span> <span className="text-ink-3">by {i.rep_name ?? i.actor}{i.derived ? " (derived)" : ""}</span>{detail && <div className="text-xs text-ink-2">{detail}</div>}</>;
  } else if (i.kind === "score") {
    body = <><span className="font-medium">Score {i.old.toFixed(0)} → {i.new.toFixed(0)}</span> <Delta value={i.delta} /><div className="text-xs text-ink-2">{i.contributions.filter((c: any) => Math.abs(c.delta) >= 0.05).slice(0, 3).map((c: any) => c.text).join(" · ") || "Time decay only"}</div></>;
  } else if (i.kind === "stage") {
    body = <><span className="font-medium">{human(i.from_stage)} → {human(i.to_stage)}</span> <Chip>{i.rule_id}</Chip> <span className="text-xs text-ink-3">{i.mode}</span><div className="text-xs text-ink-2">{i.reason} · evidence {i.evidence_event_ids?.join(", ")}</div></>;
  } else if (i.kind === "assignment") {
    body = <><span className="font-medium">{i.previous_rep_name ? `${i.previous_rep_name} → ` : ""}{i.rep_name}</span> <Chip>{i.rule_id ?? i.type}</Chip><div className="text-xs text-ink-2">{i.reason}</div></>;
  } else if (i.kind === "action") {
    body = <><span className="font-medium">{i.rule_id} {i.action}</span> <span className="text-xs text-ink-3">{i.status}</span><div className="text-xs text-ink-2">{i.reason}</div></>;
  } else if (i.kind === "stall") {
    body = <><span className="font-medium">Stall detected ({(i.rule_ids ?? []).join(", ")})</span> <span className="text-xs text-ink-3">risk {i.risk}{i.cleared_at ? ` · cleared ${dateTime(i.cleared_at)}` : ""}</span><div className="text-xs text-ink-2">{(i.details ?? []).join(" · ")}</div></>;
  } else if (i.kind === "merge") {
    body = <><span className="font-medium">Merged {i.merged_id}</span> <span className="text-xs text-ink-3">{Math.round(i.confidence * 100)}% · {i.mode} · {(i.match_keys ?? []).join(", ")}</span></>;
  }
  return (
    <li className="grid grid-cols-[92px_64px_1fr] gap-3 border-b border-line py-2 text-sm last:border-0">
      <span className="text-xs tabular text-ink-3">{dateTime(i.ts)}</span>
      <span className="text-xs font-medium text-ink-3">{KIND_LABEL[i.kind]}</span>
      <div className="min-w-0 break-words">{body}</div>
    </li>
  );
}

function NextAction({ l }: { l: Lead }) {
  const { clock } = useLive();
  const qc = useQueryClient();
  const a = l.primary_action;
  const due = minutesUntil(a?.due_at, clock.now);
  return (
    <Card title="Next best action">
      {!a ? <p className="text-sm text-ink-3">No action: {l.stage === "won" || l.stage === "lost" ? "deal is closed" : "nothing recommended"}.</p> : (
        <div>
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="font-semibold">{a.action}</div>
              <div className="mt-0.5 text-sm text-ink-2">{a.reason}</div>
              <div className={`mt-1 text-xs tabular ${due != null && due < 0 ? "text-critical-ink" : "text-ink-3"}`}>{a.rule_id} · {a.channel} · {due == null ? "" : due < 0 ? `overdue ${minutes(-due)}` : `due in ${minutes(due)}`} · {a.urgency}</div>
            </div>
            {a.completion?.type && <Button variant="primary" size="sm" onClick={async () => { await api.post(`/api/actions/${a.id}/done`); qc.invalidateQueries({ queryKey: ["lead"] }); }}>Mark done</Button>}
          </div>
          {!!l.alternates?.length && (
            <div className="mt-3 border-t border-line pt-2">
              <div className="text-xs text-ink-3">Alternates</div>
              {l.alternates.map((x) => <div key={x.rule_id} className="mt-1 text-sm"><span className="text-ink-3">{x.rule_id}</span> {x.action} <span className="text-xs text-ink-3">· {x.reason}</span></div>)}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function Prediction({ l }: { l: Lead }) {
  const maxAbs = Math.max(1, ...l.close_factors.map((f) => Math.abs(f.logit ?? 0)).filter((_, i) => i > 0));
  return (
    <Card title="Deal prediction" subtitle={`${money(l.predicted_acv)} ACV × ${pct(l.close_prob, 1)} = ${money(l.expected_value)} expected`}>
      <div className="space-y-1 text-sm">
        {l.acv_factors.map((f) => (
          <div key={f.key} className="flex justify-between gap-2"><span className="text-ink-2">{f.label}</span><span className="tabular">{f.kind === "multiplier" ? `×${f.value}` : money(f.value)}</span></div>
        ))}
      </div>
      <div className="mt-3 border-t border-line pt-3">
        <div className="mb-1.5 text-xs text-ink-3">Why {pct(l.close_prob)}: log-odds contributions</div>
        {l.close_factors.map((f, i) => (
          <div key={f.key} className="grid grid-cols-[1fr_90px_44px] items-center gap-2 py-0.5 text-xs">
            <span className="truncate text-ink-2">{f.label}</span>
            {i === 0 || f.logit == null ? <span /> : (
              <span className="relative h-2 rounded bg-surface-2">
                <span className="absolute top-0 h-2 rounded" style={{ left: f.logit >= 0 ? "50%" : `${50 - (Math.abs(f.logit) / maxAbs) * 50}%`, width: `${(Math.abs(f.logit) / maxAbs) * 50}%`, background: f.logit >= 0 ? "var(--series-1)" : "var(--series-2)" }} />
              </span>
            )}
            <span className="text-right tabular">{f.logit == null ? "" : signed(f.logit, 2)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function StallPanel({ l }: { l: Lead }) {
  if (!l.stall.sla_days && !l.stall_flags.length) return null;
  return (
    <Card title="Stall watch" subtitle={l.stall.sla_days ? `Stage SLA ${l.stall.sla_days}d · ${l.stall.days_over_sla.toFixed(1)}d over` : undefined}>
      {l.is_stalled ? (
        <div className="space-y-1 text-sm">
          <StallFlag rules={l.stall.rules} risk={l.stall.risk} />
          {l.stall.details.map((d) => <div key={d} className="text-ink-2">• {d}</div>)}
          <div className="text-xs text-ink-3">Risk {l.stall.risk}/100. Clears automatically on the next prospect activity.</div>
        </div>
      ) : <p className="text-sm text-ink-3">Not stalled.</p>}
      {l.stall_flags.length > 0 && <div className="mt-2 text-xs text-ink-3">{l.stall_flags.length} stall flag(s) in history</div>}
    </Card>
  );
}

function QualityPanel({ l }: { l: Lead }) {
  const qc = useQueryClient();
  return (
    <Card title="Quality & identity">
      <div className="space-y-2 text-sm">
        <div className="flex justify-between"><span className="text-ink-2">Fake score</span><span className="tabular">{l.fake_score} · {l.quality?.status ?? l.fake_status}</span></div>
        {l.fake_signals.map((s) => <div key={s.key} className="flex justify-between text-xs"><span className="text-ink-2">{human(s.key)} · {s.detail}</span><span className="tabular">+{s.weight}</span></div>)}
        {l.fake_status !== "clean" && <Button size="sm" onClick={async () => { await api.post(`/api/quality/clear/${l.lead_id}`, { reviewer: "you" }); qc.invalidateQueries(); }}>Mark false positive</Button>}
        {l.disqualifier && <div className="text-xs text-critical-ink">Disqualifier: {human(l.disqualifier)}</div>}
        {l.merged_ids.length > 0 && <div className="text-xs text-ink-2">Merged duplicates: {l.merged_ids.join(", ")}</div>}
        {l.emails.length > 1 && <div className="text-xs text-ink-2">Emails seen: {l.emails.join(", ")}</div>}
        <div className="text-xs text-ink-3">Seniority {human(l.seniority)} · {l.revenue_band ?? "revenue n/a"} · {l.funding_stage ?? "funding n/a"}{l.tech_stack.length ? ` · ${l.tech_stack.join(", ")}` : ""}</div>
      </div>
    </Card>
  );
}

function Assignments({ l }: { l: Lead }) {
  if (!l.assignments.length) return null;
  const last = l.assignments[l.assignments.length - 1];
  const cands = (last.candidate_scores ?? []).filter((c: any) => c.eligible !== undefined).sort((a: any, b: any) => b.total - a.total).slice(0, 4);
  return (
    <Card title="Assignment" subtitle={last.reason}>
      {cands.length > 0 && (
        <table className="w-full text-xs">
          <thead><tr className="text-left text-ink-3"><th className="py-1 font-medium">Candidate</th><th className="font-medium">Skill</th><th className="font-medium">Win</th><th className="font-medium">Free</th><th className="text-right font-medium">Total</th></tr></thead>
          <tbody>{cands.map((c: any) => (
            <tr key={c.rep_id} className={c.chosen ? "font-semibold" : c.eligible ? "" : "text-ink-3"}>
              <td className="py-0.5">{c.name}{!c.eligible && " (filtered)"}</td><td className="tabular">{c.skill}</td><td className="tabular">{pct(c.win_rate)}</td><td className="tabular">{pct(c.headroom)}</td><td className="text-right tabular">{c.total.toFixed(3)}</td>
            </tr>))}</tbody>
        </table>
      )}
      {l.assignments.length > 1 && <div className="mt-2 text-xs text-ink-3">{l.assignments.length} assignments · {l.auto_reassign_count} auto-reassignments</div>}
    </Card>
  );
}

function ManualControls({ l }: { l: Lead }) {
  const { me } = useAuth();
  const manager = can.manage(me);          // reassignment and stage overrides are manager actions
  const qc = useQueryClient();
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const [rep, setRep] = useState(l.owner_rep_id ?? "");
  const [stage, setStage] = useState(l.stage);
  const [msg, setMsg] = useState("");
  const run = async (p: Promise<unknown>, text: string) => { try { await p; setMsg(text); } catch (e) { setMsg(String(e)); } qc.invalidateQueries({ queryKey: ["lead"] }); };
  return (
    <Card title="Manual actions" subtitle="Logged as events with mode=manual">
      <div className="space-y-2">
        {manager && <>
        <div className="flex items-center gap-2">
          <Select value={rep} onChange={setRep}><option value="">Pick rep</option>{reps.data?.items.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name}</option>)}</Select>
          <Button size="sm" disabled={!rep} onClick={() => run(api.post(`/api/leads/${l.lead_id}/assign`, { rep_id: rep }), "Reassigned")}>Assign</Button>
        </div>
        <div className="flex items-center gap-2">
          <Select value={stage} onChange={setStage}>{STAGES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</Select>
          <Button size="sm" onClick={() => run(api.post(`/api/leads/${l.lead_id}/override-stage`, { to_stage: stage, reason: "Manual override from dashboard" }), "Stage overridden")}>Override stage</Button>
        </div>
        </>}
        <Button size="sm" variant="danger" onClick={() => run(api.post(`/api/leads/${l.lead_id}/disqualify`, { reason: "Disqualified from dashboard" }), "Disqualified")}>Disqualify</Button>
        {msg && <div className="text-xs text-ink-3">{msg}</div>}
      </div>
    </Card>
  );
}

function InjectEvent({ l }: { l: Lead }) {
  const qc = useQueryClient();
  const [type, setType] = useState("page_view");
  const [cat, setCat] = useState("pricing");
  const [body, setBody] = useState("Can you send pricing for 50 seats? We want to decide this quarter.");
  const [outcome, setOutcome] = useState("connected");
  const [amount, setAmount] = useState("50000");
  const [res, setRes] = useState<string>("");
  const payload = (): Record<string, unknown> => {
    switch (type) {
      case "page_view": return { url: `/${cat}`, page_category: cat };
      case "email_replied": return { body };
      case "call_logged": return { outcome };
      case "meeting_held": case "meeting_scheduled": return { meeting_type: "demo" };
      case "proposal_sent": case "contract_sent": case "deal_won": return { amount: Number(amount) };
      case "deal_lost": return { lost_reason: "competitor" };
      default: return {};
    }
  };
  const send = async () => {
    const isRep = REP_EVENTS.has(type);
    const r: any = await api.post("/api/events", { type, actor: isRep ? "rep" : "prospect", rep_id: isRep ? l.owner_rep_id : null, lead_ref: { lead_id: l.lead_id }, payload: payload() });
    const x = r.results[0];
    setRes(`${x.status}: ${x.summary || `score ${x.score}`}`);
    qc.invalidateQueries({ queryKey: ["lead"] });
  };
  return (
    <Card title="Inject event" subtitle="Simulate an event for this lead and watch the score, stage and action react">
      <div className="space-y-2">
        <Select value={type} onChange={setType}>{EVENT_TYPES.map((t) => <option key={t} value={t}>{human(t)}</option>)}</Select>
        {type === "page_view" && <Select value={cat} onChange={setCat} label="Page">{["pricing", "demo", "product", "case_study", "roi", "competitor_compare", "docs", "blog", "careers", "enterprise_plan"].map((c) => <option key={c}>{c}</option>)}</Select>}
        {type === "email_replied" && <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} className="w-full rounded-xl border border-line bg-surface p-2 text-sm outline-none focus:ring-2 focus:ring-accent/40" />}
        {type === "call_logged" && <Select value={outcome} onChange={setOutcome} label="Outcome">{["connected", "voicemail", "no_answer"].map((c) => <option key={c}>{c}</option>)}</Select>}
        {["proposal_sent", "contract_sent", "deal_won"].includes(type) && <input value={amount} onChange={(e) => setAmount(e.target.value)} className="w-full rounded-xl border border-line bg-surface px-2 py-1.5 text-sm" />}
        <Button variant="primary" size="sm" onClick={send}>Send event</Button>
        {res && <div className="text-xs text-ink-2">{res}</div>}
        <div className="text-[11px] text-ink-3">Last inbound {ago(l.last_inbound_at, useLive().clock.now)}</div>
      </div>
    </Card>
  );
}
