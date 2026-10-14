import { useState, type MouseEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LeadView, type Rep } from "../lib/api";
import { useLive } from "../lib/live";
import { human, minutes, minutesUntil, money, pct } from "../lib/format";
import { Button, Card, Chip, Empty, GradePill, IntentBadge, Loading, PageHeader, Select, Sparkline, StageBadge, StallFlag, StatTile } from "../components/ui";
import type { IconName } from "../components/icons";
import { signalBase, to } from "../lib/links";

function readRep(): string {
  try { return localStorage.getItem("lp.rep") ?? "R-ANANYA"; } catch { return "R-ANANYA"; }
}

export default function Queue() {
  // ?rep= wins (links from other pages), otherwise the last rep picked here.
  const [params, setParams] = useSearchParams();
  const rep = params.get("rep") ?? readRep();
  const choose = (v: string) => { setParams({ rep: v }, { replace: true }); try { localStorage.setItem("lp.rep", v); } catch { /* storage blocked */ } };
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const q = useQuery({ queryKey: ["queue", rep], queryFn: () => api.get<{ items: LeadView[]; total: number; rep_name: string }>(`/api/queue/${rep}`) });
  const me = reps.data?.items.find((r) => r.rep_id === rep);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        eyebrow={me ? `${me.profile} rep · ${me.territories.join(", ")}` : undefined}
        title={me ? `${me.name.split(" ")[0]}'s queue` : rep === "all" ? "All open leads" : rep === "manager_queue" ? "Manager queue" : "My Queue"}
        subtitle="Leads ordered by priority: score, expected value, urgency of the next action, stall rescue and SLA risk."
        right={
          <Select label="Rep" value={rep} onChange={choose}>
            <option value="all">All reps</option>
            {reps.data?.items.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name} ({r.profile})</option>)}
            <option value="manager_queue">Manager queue</option>
          </Select>
        }
      />
      {me && (
        <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {([
            ["Open leads", me.open_leads, "users", "accent", `${me.assigned} assigned all-time`, to.leads({ rep_id: me.rep_id, open: true })],
            ["Load", `${me.load} / ${me.capacity}`, "gauge", me.load > me.capacity ? "critical" : "accent", me.load > me.capacity ? "Over capacity" : `${Math.max(0, me.capacity - me.load)} slots free`, to.analytics("reps")],
            ["Pipeline EV", money(me.pipeline_ev), "wallet", "accent", "Expected value", to.pipeline({ rep: me.rep_id })],
            ["Stalled", me.stalled, "alert", me.stalled ? "critical" : "good", me.stalled ? "Open the stalled deals" : "None right now", to.pipeline({ rep: me.rep_id, stalled: true })],
            ["Win rate", pct(me.win_rate), "trophy", "good", `${me.wins_total} won / ${me.closed_total} closed`, to.leads({ rep_id: me.rep_id, stage: "won" })],
            ["1st reply", minutes(me.median_first_response_min), "clock", "accent", `Median · SLA met ${pct(me.sla_attainment)}`, to.analytics("response")],
          ] as [string, string | number, IconName, "accent" | "critical" | "good", string, string][]).map(([l, v, icon, tone, sub, href]) => (
            <StatTile key={l} label={l} value={v} icon={icon} tone={tone} sub={sub} to={href} />
          ))}
        </div>
      )}
      <Card pad={false} title={`${q.data?.total ?? 0} leads to work`} subtitle="Highest priority first">
        {q.isLoading ? <Loading /> : q.isError ? <Empty>Could not load this queue. <button onClick={() => q.refetch()} className="font-medium text-accent-ink hover:underline">Try again</button></Empty> : !q.data?.items.length ? <Empty>No open leads in this queue.</Empty> : <QueueTable rows={q.data.items} rep={rep} />}
      </Card>
    </div>
  );
}

function QueueTable({ rows, rep }: { rows: LeadView[]; rep: string }) {
  const { clock } = useLive();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const stop = (e: MouseEvent) => e.stopPropagation();
  const done = async (id: string) => {
    setBusy(id);
    try { await api.post(`/api/actions/${id}/done`); } finally { setBusy(null); qc.invalidateQueries({ queryKey: ["queue"] }); }
  };
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[1100px] text-sm">
        <thead>
          <tr className="border-b border-line bg-surface-2/60 text-left text-[11px] uppercase tracking-[0.06em] text-ink-3">
            <th className="px-4 py-2.5 font-semibold">#</th>
            <th className="px-2 py-2.5 font-semibold">Lead</th>
            <th className="px-2 py-2.5 font-semibold">Score</th>
            <th className="px-2 py-2.5 font-semibold">Intent</th>
            <th className="px-2 py-2.5 font-semibold">Stage</th>
            <th className="px-2 py-2.5 font-semibold">SLA</th>
            <th className="px-2 py-2.5 font-semibold">Next best action</th>
            <th className="px-2 py-2.5 pr-4 font-semibold">Why it's here</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const a = r.primary_action;
            const due = minutesUntil(a?.due_at, clock.now);
            const sla = minutesUntil(r.sla_deadline, clock.now);
            return (
              <tr key={r.lead_id} onClick={() => nav(`/leads/${r.lead_id}`)} className="cursor-pointer border-b border-line align-top transition-colors last:border-0 hover:bg-accent-soft/40">
                <td className="px-4 py-3"><span className={`grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold tabular ${i < 3 ? "bg-accent-soft text-accent-ink" : "text-ink-3"}`}>{i + 1}</span></td>
                <td className="max-w-[220px] px-2 py-3">
                  <Link to={`/leads/${r.lead_id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-ink hover:underline">{r.name}</Link>
                  <div className="truncate text-xs text-ink-3">
                    {r.company ? <Link to={to.leads({ q: r.company })} onClick={stop} className="drill">{r.company}</Link> : "-"} · <Link to={to.leads({ source: r.source })} onClick={stop} className="drill">{human(r.source)}</Link>
                  </div>
                  {r.owner_name && rep === "all" && <Link to={to.queue(r.owner_rep_id)} onClick={stop} className="drill text-xs text-ink-2">{r.owner_name}</Link>}
                </td>
                <td className="px-2 py-3">
                  <div className="flex items-center gap-2"><Link to={to.leads({ grade: r.grade })} onClick={stop} title={`All grade ${r.grade} leads`}><GradePill grade={r.grade} score={r.score} /></Link><Sparkline values={r.sparkline} /></div>
                  <div className="mt-1 text-xs tabular text-ink-3">{money(r.expected_value)} EV · {pct(r.close_prob)}</div>
                </td>
                <td className="max-w-[200px] px-2 py-3">
                  <Link to={to.leads({ intent: r.intent_level })} onClick={stop} title={`All ${r.intent_level}-intent leads`}><IntentBadge level={r.intent_level} /></Link>
                  <div className="mt-1 flex flex-wrap gap-1">{r.active_signals.slice(0, 3).map((s) => <Link key={s} to={to.leads({ signal: signalBase(s) })} onClick={stop} title="Leads with this signal"><Chip>{human(s)}</Chip></Link>)}</div>
                </td>
                <td className="px-2 py-3">
                  <div className="flex flex-col items-start gap-1">
                    <Link to={to.pipeline({ stage: r.stage, rep: rep === "all" ? undefined : rep })} onClick={stop} title="Show in pipeline"><StageBadge stage={r.stage} /></Link>
                    {r.is_stalled && <Link to={to.pipeline({ rep: rep === "all" ? undefined : rep, stalled: true })} onClick={stop}><StallFlag rules={r.stall.rules} risk={r.stall.risk} /></Link>}
                  </div>
                </td>
                <td className="px-2 py-3 text-xs tabular">
                  {sla == null ? <span className="text-ink-3">Touched</span> : sla < 0
                    ? <span className="font-medium text-critical-ink">■ Breached {minutes(-sla)} ago</span>
                    : <span className={sla < 30 ? "font-medium text-critical-ink" : "text-ink"}>{minutes(sla)} left</span>}
                </td>
                <td className="max-w-[300px] px-2 py-3">
                  {a ? (
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-ink">{a.action}</div>
                        <div className="text-xs text-ink-3">{a.reason}</div>
                        <div className={`text-xs tabular ${due != null && due < 0 ? "text-critical-ink" : "text-ink-2"}`}>{a.rule_id} · {due == null ? "" : due < 0 ? `overdue ${minutes(-due)}` : `due in ${minutes(due)}`}</div>
                      </div>
                      {a.completion?.type && (
                        <span onClick={(e) => e.stopPropagation()}>
                          <Button size="sm" disabled={busy === a.id} onClick={() => done(a.id)} title={`Logs ${a.completion.type.replace("_", " ")}`}>Mark done</Button>
                        </span>
                      )}
                    </div>
                  ) : <span className="text-xs text-ink-3">-</span>}
                </td>
                <td className="px-2 py-3 pr-4 text-xs text-ink-2">
                  {r.priority_drivers.map((d) => <div key={d.key}>{d.label}</div>)}
                  <div className="tabular text-ink-3">priority {r.priority.toFixed(0)}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
