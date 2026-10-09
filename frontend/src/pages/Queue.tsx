import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LeadView, type Rep } from "../lib/api";
import { useLive } from "../lib/live";
import { human, minutes, minutesUntil, money, pct } from "../lib/format";
import { Button, Card, Chip, Empty, GradePill, IntentBadge, Loading, PageHeader, Select, Sparkline, StageBadge, StallFlag } from "../components/ui";

function readRep(): string {
  try { return localStorage.getItem("lp.rep") ?? "R-ANANYA"; } catch { return "R-ANANYA"; }
}

export default function Queue() {
  const [rep, setRep] = useState<string>(readRep);
  const choose = (v: string) => { setRep(v); try { localStorage.setItem("lp.rep", v); } catch { /* storage blocked */ } };
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const q = useQuery({ queryKey: ["queue", rep], queryFn: () => api.get<{ items: LeadView[]; total: number; rep_name: string }>(`/api/queue/${rep}`) });
  const me = reps.data?.items.find((r) => r.rep_id === rep);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title="My Queue"
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
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Open leads", me.open_leads],
            ["Load / capacity", `${me.load} / ${me.capacity}`],
            ["Pipeline EV", money(me.pipeline_ev)],
            ["Stalled", me.stalled],
            ["Win rate", pct(me.win_rate)],
            ["Median 1st response", minutes(me.median_first_response_min)],
          ].map(([l, v]) => (
            <div key={l as string} className="rounded-xl border border-line bg-surface px-3 py-2.5">
              <div className="text-xs text-ink-3">{l}</div>
              <div className="text-base font-semibold tabular">{v}</div>
            </div>
          ))}
        </div>
      )}
      <Card pad={false} title={`${q.data?.total ?? 0} leads`} subtitle="Click a lead for its full explanation">
        {q.isLoading ? <Loading /> : !q.data?.items.length ? <Empty>No open leads in this queue yet.</Empty> : <QueueTable rows={q.data.items} />}
      </Card>
    </div>
  );
}

function QueueTable({ rows }: { rows: LeadView[] }) {
  const { clock } = useLive();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const done = async (id: string) => {
    setBusy(id);
    try { await api.post(`/api/actions/${id}/done`); } finally { setBusy(null); qc.invalidateQueries({ queryKey: ["queue"] }); }
  };
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[1100px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th className="px-4 py-2 font-medium">#</th>
            <th className="px-2 py-2 font-medium">Lead</th>
            <th className="px-2 py-2 font-medium">Score</th>
            <th className="px-2 py-2 font-medium">Intent</th>
            <th className="px-2 py-2 font-medium">Stage</th>
            <th className="px-2 py-2 font-medium">SLA</th>
            <th className="px-2 py-2 font-medium">Next best action</th>
            <th className="px-2 py-2 pr-4 font-medium">Why it's here</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const a = r.primary_action;
            const due = minutesUntil(a?.due_at, clock.now);
            const sla = minutesUntil(r.sla_deadline, clock.now);
            return (
              <tr key={r.lead_id} onClick={() => nav(`/leads/${r.lead_id}`)} className="cursor-pointer border-b border-line align-top last:border-0 hover:bg-surface-2/60">
                <td className="px-4 py-3 text-xs tabular text-ink-3">{i + 1}</td>
                <td className="max-w-[220px] px-2 py-3">
                  <Link to={`/leads/${r.lead_id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-ink hover:underline">{r.name}</Link>
                  <div className="truncate text-xs text-ink-3">{r.company ?? "-"} · {human(r.source)}</div>
                </td>
                <td className="px-2 py-3">
                  <div className="flex items-center gap-2"><GradePill grade={r.grade} score={r.score} /><Sparkline values={r.sparkline} /></div>
                  <div className="mt-1 text-xs tabular text-ink-3">{money(r.expected_value)} EV · {pct(r.close_prob)}</div>
                </td>
                <td className="max-w-[200px] px-2 py-3">
                  <IntentBadge level={r.intent_level} />
                  <div className="mt-1 flex flex-wrap gap-1">{r.active_signals.slice(0, 3).map((s) => <Chip key={s}>{human(s)}</Chip>)}</div>
                </td>
                <td className="px-2 py-3">
                  <div className="flex flex-col items-start gap-1">
                    <StageBadge stage={r.stage} />
                    {r.is_stalled && <StallFlag rules={r.stall.rules} risk={r.stall.risk} />}
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
