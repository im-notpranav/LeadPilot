import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LeadView, type Rep } from "../lib/api";
import { useLive } from "../lib/live";
import { useAuth } from "../lib/auth";
import { human, minutes, minutesUntil, money, pct } from "../lib/format";
import { Button, Card, Chip, Empty, GradePill, IntentBadge, Loading, PageHeader, Select, Sparkline, StageBadge, StallFlag, StatTile } from "../components/ui";
import type { IconName } from "../components/icons";

function readRep(): string {
  try { return localStorage.getItem("lp.rep") ?? "R-ANANYA"; } catch { return "R-ANANYA"; }
}

export default function Queue() {
  const { me: user } = useAuth();
  const isRep = user?.role === "rep";
  const [chosen, setRep] = useState<string>(readRep);
  const choose = (v: string) => { setRep(v); try { localStorage.setItem("lp.rep", v); } catch { /* storage blocked */ } };
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  // Reps always work their own queue. Others keep their last pick while it is still a rep they can see.
  const visible = reps.data ? new Set(["all", "manager_queue", ...reps.data.items.map((r) => r.rep_id)]) : null;
  const rep = isRep ? user?.rep_id ?? "" : visible && !visible.has(chosen) ? "all" : chosen;
  const q = useQuery({ queryKey: ["queue", rep], enabled: rep !== "" && (isRep || !!visible),
    queryFn: () => api.get<{ items: LeadView[]; total: number; rep_name: string }>(`/api/queue/${rep}`) });
  const me = reps.data?.items.find((r) => r.rep_id === rep);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        eyebrow="Overview"
        title={me ? `${me.name.split(" ")[0]}'s queue` : "My Queue"}
        subtitle="Leads ordered by priority: score, expected value, urgency of the next action, stall rescue and SLA risk."
        right={
          isRep ? null : (
            <Select label="Rep" value={rep} onChange={choose}>
              <option value="all">All reps</option>
              {reps.data?.items.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name} ({r.profile})</option>)}
              <option value="manager_queue">Manager queue (unassigned)</option>
            </Select>
          )
        }
      />
      {me && (
        <div className="stagger mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {([
            ["Open leads", me.open_leads, "users", "accent", `${me.assigned} assigned all-time`],
            ["Load", `${me.load} / ${me.capacity}`, "gauge", me.load > me.capacity ? "critical" : "accent", me.load > me.capacity ? "Over capacity" : `${Math.max(0, me.capacity - me.load)} slots free`],
            ["Pipeline EV", money(me.pipeline_ev), "wallet", "accent", "Expected value"],
            ["Stalled", me.stalled, "alert", me.stalled ? "critical" : "good", me.stalled ? "Need a rescue" : "Nothing stuck"],
            ["Win rate", pct(me.win_rate), "trophy", "good", `${me.wins_total} won / ${me.closed_total} closed`],
            ["1st reply", minutes(me.median_first_response_min), "clock", "accent", `Median · SLA met ${pct(me.sla_attainment)}`],
          ] as [string, string | number, IconName, "accent" | "critical" | "good", string][]).map(([l, v, icon, tone, sub]) => (
            <StatTile key={l} label={l} value={v} icon={icon} tone={tone} sub={sub} />
          ))}
        </div>
      )}
      <Card pad={false} title={`${q.data?.total ?? 0} leads to work`} subtitle="Ordered by priority. Click a lead for its full explanation.">
        {isRep && !user?.rep_id ? <Empty>Your account isn't linked to a sales rep yet. Ask an admin to link it on the Access page.</Empty> : q.isLoading ? <Loading /> : !q.data?.items.length ? <Empty>No open leads in this queue yet.</Empty> : <QueueTable rows={q.data.items} />}
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
