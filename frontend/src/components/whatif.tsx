// What-if results: the whole event log re-run under draft rules and under the rules in force, side by side.
// The run happens in the background on the server; this polls it until it is done.
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, STAGES, type WhatIfDeal, type WhatIfLead, type WhatIfResult, type WhatIfRun } from "../lib/api";
import { dateTime, human, money, num } from "../lib/format";
import { to } from "../lib/links";
import { errText } from "./deals";
import { Button, Card, Empty, GradePill, Loading, Segmented, Stat } from "./ui";

const GRADES = ["A", "B", "C", "D"];
const SHOWN = 200;   // the server lists at most this many changes per kind; the counts are always complete

type Kind = "grade" | "stage" | "owner" | "action" | "quality" | "deals";
const KINDS: { value: Kind; label: string }[] = [
  { value: "grade", label: "Grades" }, { value: "stage", label: "Stages" }, { value: "owner", label: "Owners" },
  { value: "action", label: "Next actions" }, { value: "quality", label: "Quality" }, { value: "deals", label: "Deals" },
];

export function WhatIfPanel({ runId, onClose }: { runId: number; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["config", "whatif", runId],
    queryFn: () => api.get<WhatIfRun>(`/api/config/whatif/${runId}`),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 700 : false),
  });
  const run = q.data;
  return (
    <Card id="whatif" title="What if"
      subtitle={run ? `${run.label} compared with version ${run.against.id} (in force). Every event is re-run in a scratch copy under both sets of rules; nothing is switched.` : "Loading the run…"}
      right={<Button size="sm" variant="ghost" onClick={onClose}>Close</Button>}>
      {q.error ? <Empty>Could not load this run. {errText(q.error)}</Empty>
        : !run ? <Loading rows={3} />
        : run.status === "running" ? <Running run={run} />
        : run.status === "failed" ? (
          <div role="alert" className="rounded-xl border px-3 py-2.5 text-sm text-critical-ink" style={{ borderColor: "color-mix(in srgb, var(--c-critical) 40%, transparent)", background: "color-mix(in srgb, var(--c-critical) 8%, transparent)" }}>
            These rules cannot be used: {run.error}
          </div>
        ) : run.result ? <Result run={run} r={run.result} /> : null}
    </Card>
  );
}

function Running({ run }: { run: WhatIfRun }) {
  const p = Math.round(run.progress * 100);
  return (
    <div role="status" className="space-y-2">
      <div className="flex items-center justify-between text-sm text-ink-2">
        <span>Re-running {num(run.events)} events twice: under the rules in force, then under {run.label.toLowerCase()}.</span>
        <span className="tabular text-ink-3">{p}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--ramp-250)]/40" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100} aria-label="What-if progress">
        <div className="h-2 rounded-full bg-accent transition-[width] duration-300" style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

const delta = (b: number, a: number, fmt: (v: number) => string = (v) => num(v)) => {
  const d = a - b;
  if (Math.abs(d) < 0.005) return <span className="text-ink-3">±0</span>;
  return <span className={d > 0 ? "text-good-ink" : "text-critical-ink"}>{d > 0 ? "+" : "−"}{fmt(Math.abs(d))}</span>;
};

function Result({ run, r }: { run: WhatIfRun; r: WhatIfResult }) {
  const c = r.counts;
  const deals = c.deals_opened + c.deals_closed + c.deals_stage;
  const first = KINDS.find((k) => (k.value === "deals" ? deals : c[k.value]) > 0)?.value ?? "grade";
  const [kind, setKind] = useState<Kind>(first);
  return (
    <div className="space-y-4">
      {run.stale && <p role="status" className="rounded-xl border border-line bg-surface-2/50 px-3 py-2 text-sm text-ink-2">The rules in force have changed since this run (it compared with version {run.against.id}). Run it again for an up-to-date picture.</p>}
      <p className="text-sm text-ink-2">
        Re-ran {num(run.events)} events as of {dateTime(run.as_of)} in {run.seconds}s.{" "}
        {r.unchanged ? <strong className="font-semibold text-ink">Nothing would change: every grade, stage, owner, next action and deal stays the same.</strong>
          : <>If these rules were in force, <strong className="font-semibold text-ink">{summary(r)}</strong>.</>}
      </p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Grades changed" value={num(c.grade)} sub={c.grade ? `▲ ${c.grade_up} up · ▼ ${c.grade_down} down` : "none"} />
        <Stat label="Stages changed" value={num(c.stage)} />
        <Stat label="Owners changed" value={num(c.owner)} />
        <Stat label="Next actions changed" value={num(c.action)} sub="open leads" />
        <Stat label="Quality changed" value={num(c.quality)} sub="quarantine and merges" />
        <Stat label="Deals changed" value={num(deals)} sub={deals ? `${c.deals_opened} new · ${c.deals_closed} gone · ${c.deals_stage} moved` : "none"} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Mix title="Grade mix" rows={GRADES.map((g) => [<GradePill key={g} grade={g} />, r.grades.before[g] ?? 0, r.grades.after[g] ?? 0])} />
        <Mix title="Stage mix" rows={STAGES.filter((s) => r.stages.before[s] || r.stages.after[s]).map((s) => [<span key={s} className="capitalize">{human(s)}</span>, r.stages.before[s] ?? 0, r.stages.after[s] ?? 0])} />
        <Mix title="Deals and leads" rows={[
          ["Open deals", r.deals.before.open, r.deals.after.open],
          ["Won / lost", r.deals.before.won + r.deals.before.lost, r.deals.after.won + r.deals.after.lost],
          ["Stalled deals", r.deals.before.stalled, r.deals.after.stalled],
          ["Pipeline (expected)", r.deals.before.pipeline, r.deals.after.pipeline, money],
          ["Quarantined leads", r.leads.before.quarantined, r.leads.after.quarantined],
          ["Merged leads", r.leads.before.merged, r.leads.after.merged],
        ]} />
      </div>
      {!r.unchanged && (
        <div>
          <div className="scroll-thin -mx-1 mb-2 overflow-x-auto px-1 pb-1">
            <Segmented label="Changes" value={kind} onChange={setKind}
              options={KINDS.map((k) => ({ value: k.value, label: `${k.label} (${k.value === "deals" ? deals : c[k.value]})` }))} />
          </div>
          {kind === "deals" ? <DealChanges r={r} /> : <LeadChanges kind={kind} rows={r.changes[kind]} total={c[kind]} />}
        </div>
      )}
    </div>
  );
}

function summary(r: WhatIfResult): string {
  const c = r.counts, parts: string[] = [];
  const n = (v: number, one: string, many = `${one}s`) => `${num(v)} ${v === 1 ? one : many}`;
  if (c.grade) parts.push(`${n(c.grade, "lead")} would change grade`);
  if (c.stage) parts.push(`${n(c.stage, "lead")} would be in another stage`);
  if (c.owner) parts.push(`${n(c.owner, "lead")} would have another owner`);
  if (c.action) parts.push(`${n(c.action, "open lead")} would get another next action`);
  if (c.quality) parts.push(`${n(c.quality, "lead")} would be treated differently for quality`);
  const deals = c.deals_opened + c.deals_closed + c.deals_stage;
  if (deals) parts.push(`${n(deals, "deal")} would differ`);
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0] ?? "nothing would change";
}

function Mix({ title, rows }: { title: string; rows: [ReactNode, number, number, ((v: number) => string)?][] }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="mb-1.5 text-xs font-medium text-ink-2">{title}</div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-ink-3"><tr><th className="py-1 font-medium" /><th className="py-1 text-right font-medium">In force</th><th className="py-1 text-right font-medium">What if</th><th className="py-1 text-right font-medium">Change</th></tr></thead>
        <tbody className="tabular">
          {rows.map(([label, b, a, fmt], i) => (
            <tr key={i} className="border-t border-line">
              <td className="py-1.5 pr-2 text-ink-2">{label}</td>
              <td className="py-1.5 text-right">{fmt ? fmt(b) : num(b)}</td>
              <td className="py-1.5 text-right">{fmt ? fmt(a) : num(a)}</td>
              <td className="py-1.5 text-right">{delta(b, a, fmt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const More = ({ total }: { total: number }) => total > SHOWN ? <p className="mt-2 text-xs text-ink-3">Showing the first {SHOWN} of {num(total)}.</p> : null;

function LeadChanges({ kind, rows, total }: { kind: Exclude<Kind, "deals">; rows: WhatIfLead[]; total: number }) {
  if (!rows.length) return <p className="text-sm text-ink-3">No lead would change here.</p>;
  const cell = (v: string | null, score?: number) =>
    kind === "grade" && v ? <GradePill grade={v} score={score} /> : kind === "stage" && v ? <span className="capitalize">{human(v)}</span> : <span>{v ?? "-"}</span>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="text-left text-xs text-ink-3"><tr className="border-b border-line"><th className="py-2 pr-4 font-medium">Lead</th><th className="py-2 pr-4 font-medium">In force</th><th className="py-2 font-medium">What if</th></tr></thead>
        <tbody>
          {rows.map((l) => (
            <tr key={l.lead_id} className="border-b border-line align-top last:border-0">
              <td className="py-1.5 pr-4"><Link to={to.lead(l.lead_id)} className="drill font-medium text-ink">{l.name ?? l.lead_id}</Link>{l.company && <div className="text-xs text-ink-3">{l.company}</div>}</td>
              <td className="py-1.5 pr-4 text-ink-2">{cell(l.before, l.score_before)}</td>
              <td className="py-1.5 text-ink">{cell(l.after, l.score_after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <More total={total} />
    </div>
  );
}

function DealChanges({ r }: { r: WhatIfResult }) {
  const rows: (WhatIfDeal & { change: string; link: boolean })[] = [
    ...r.changes.deals_stage.map((d) => ({ ...d, change: `${human(d.before)} → ${human(d.after)}`, link: true })),
    ...r.changes.deals_opened.map((d) => ({ ...d, change: `would open (${human(d.stage)})`, link: false })),
    ...r.changes.deals_closed.map((d) => ({ ...d, change: `would not exist (now ${human(d.stage)})`, link: true })),
  ];
  if (!rows.length) return <p className="text-sm text-ink-3">No deal would change.</p>;
  const total = r.counts.deals_opened + r.counts.deals_closed + r.counts.deals_stage;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="text-left text-xs text-ink-3"><tr className="border-b border-line"><th className="py-2 pr-4 font-medium">Deal</th><th className="py-2 pr-4 font-medium">Change</th><th className="py-2 text-right font-medium">Expected value</th></tr></thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.opp_id} className="border-b border-line align-top last:border-0">
              <td className="py-1.5 pr-4">{d.link ? <Link to={to.deal(d.opp_id)} className="drill font-medium text-ink">{d.name}</Link> : <span className="font-medium text-ink">{d.name}</span>}</td>
              <td className="py-1.5 pr-4 text-ink-2 first-letter:uppercase">{d.change}</td>
              <td className="py-1.5 text-right tabular">{d.value_before !== undefined ? <>{money(d.value_before)} → {money(d.value_after)}</> : money(d.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <More total={total} />
    </div>
  );
}
