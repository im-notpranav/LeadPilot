import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Rep } from "../lib/api";
import { day, human, minutes, money, num, pct } from "../lib/format";
import { AXIS, ChartTooltip, GRID, Legend, SERIES } from "../components/charts";
import { Card, Loading, PageHeader } from "../components/ui";
import { to, useHashScroll } from "../lib/links";
import { Icon } from "../components/icons";

export default function Analytics() {
  const funnel = useQuery({ queryKey: ["analytics", "funnel"], queryFn: () => api.get<any>("/api/analytics/funnel") });
  const rt = useQuery({ queryKey: ["analytics", "rt"], queryFn: () => api.get<any>("/api/analytics/response-times") });
  const cal = useQuery({ queryKey: ["analytics", "cal"], queryFn: () => api.get<any>("/api/analytics/score-calibration") });
  const reps = useQuery({ queryKey: ["analytics", "reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/analytics/rep-performance") });
  const nav = useNavigate();
  useHashScroll(!!(funnel.data && rt.data && cal.data && reps.data));

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Analytics" subtitle="Conversion, speed to lead, engagement and whether the score actually predicts outcomes." />
      <div className="stagger grid gap-4 lg:grid-cols-2">
        <Card id="funnel" title="Funnel" subtitle={funnel.data ? `${funnel.data.total} real leads (duplicates and fakes excluded) · bars = leads that ever reached the stage` : undefined}>
          {!funnel.data ? <Loading /> : <Funnel data={funnel.data} />}
        </Card>
        <Card id="response" title="First response time by rep" subtitle={rt.data ? `Team median ${minutes(rt.data.overall.median_first_response_min)} · p90 ${minutes(rt.data.overall.p90_first_response_min)}` : undefined}>
          {!rt.data ? <Loading /> : <ResponseChart reps={rt.data.reps} onRep={(id) => nav(to.queue(id))} />}
        </Card>
        <Card title="Prospect engagement" subtitle="Prospect events per simulated day (last 14 days)" right={<Link to={to.feed()} className="inline-flex items-center gap-1 text-xs font-medium text-accent-ink hover:underline">Live feed <Icon name="arrowRight" size={12} /></Link>}>
          {!rt.data ? <Loading /> : (
            <div className="h-56">
              <ResponsiveContainer>
                <AreaChart data={rt.data.daily_engagement} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} className="cursor-pointer" onClick={() => nav(to.feed())}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => day(d)} minTickGap={24} />
                  <YAxis {...AXIS} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip labelFormat={(d) => day(d)} />} />
                  <Area type="monotone" dataKey="prospect_events" name="Prospect events" stroke="var(--series-1)" strokeWidth={2} fill="var(--series-1)" fillOpacity={0.1} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          {rt.data && <div className="mt-2 text-xs text-ink-3">Events per lead-week by grade: {Object.entries(rt.data.events_per_lead_week_by_grade).map(([g, v]) => `${g} ${v}`).join(" · ")}</div>}
        </Card>
        <Card id="scores" title="Score distribution" subtitle="Open leads by score band">
          {!cal.data ? <Loading /> : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={cal.data.score_distribution} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="bin" {...AXIS} />
                  <YAxis {...AXIS} allowDecimals={false} />
                  <Tooltip cursor={{ fill: "var(--c-surface-2)" }} content={<ChartTooltip />} />
                  <Bar dataKey="count" name="Leads" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} className="cursor-pointer"
                    onClick={(d: any) => { const [lo, hi] = String(d.bin ?? d.payload?.bin).split("-").map(Number); nav(to.leads({ open: true, min: lo, max: hi >= 99 ? 100 : hi + 0.99, sort: "score" })); }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card id="grades" title="Does the score work? Grade vs actual win rate" subtitle="Historical closed deals (6 months) and deals closed during this simulation">
          {!cal.data ? <Loading /> : (
            <>
              <Legend items={[{ label: "Historical", color: SERIES[0] }, { label: "Live", color: SERIES[1] }]} />
              <div className="mt-2 h-52">
                <ResponsiveContainer>
                  <BarChart data={cal.data.grades} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} barGap={2}>
                    <CartesianGrid {...GRID} />
                    <XAxis dataKey="grade" {...AXIS} />
                    <YAxis {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                    <Tooltip cursor={{ fill: "var(--c-surface-2)" }} content={<ChartTooltip format={(v) => (v == null ? "-" : pct(v, 1))} labelFormat={(g) => `Grade ${g}`} />} />
                    <Bar dataKey="historical_win_rate" name="Historical" fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} className="cursor-pointer" onClick={(d: any) => nav(to.leads({ grade: d.grade ?? d.payload?.grade }))} />
                    <Bar dataKey="live_win_rate" name="Live" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} className="cursor-pointer" onClick={(d: any) => nav(to.leads({ grade: d.grade ?? d.payload?.grade }))} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </Card>
        <Card title="Close-probability model calibration" subtitle="Logistic model fitted on simulated historical deals: predicted vs actual win rate by decile">
          {!cal.data?.model ? <Loading /> : <Calibration model={cal.data.model} />}
        </Card>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card id="stages" title="Average time in stage" className="lg:col-span-1">
          {!funnel.data ? <Loading /> : (
            <table className="w-full text-sm"><tbody>
              {funnel.data.stages.slice(0, 7).map((s: any) => (
                <tr key={s.stage} className="border-b border-line last:border-0"><td className="py-1.5 capitalize text-ink-2"><Link to={to.pipeline({ stage: s.stage })} className="drill">{human(s.stage)}</Link></td><td className="text-right tabular">{s.avg_hours_in_stage == null ? "-" : minutes(s.avg_hours_in_stage * 60)}</td><td className="w-20 text-right text-xs tabular"><Link to={to.leads({ stage: s.stage })} className="drill text-ink-3">{s.current} now</Link></td></tr>
              ))}
              <tr><td className="pt-2 text-xs text-ink-3" colSpan={3}>Side exits now: {Object.entries(funnel.data.side).map(([k, v]) => `${k} ${v}`).join(" · ")}</td></tr>
            </tbody></table>
          )}
        </Card>
        <Card id="reps" title="Rep leaderboard" className="lg:col-span-2" pad={false}>
          {!reps.data || !rt.data ? <Loading /> : (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead><tr className="border-b border-line bg-surface-2/60 text-left text-[11px] uppercase tracking-[0.06em] text-ink-3">
                  {["Rep", "Profile", "Open", "Load", "Pipeline EV", "Won / closed", "Win rate", "Median 1st resp.", "SLA met", "Neglected"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
                </tr></thead>
                <tbody>{reps.data.items.map((r) => (
                  <tr key={r.rep_id} onClick={() => nav(to.queue(r.rep_id))} className="cursor-pointer border-b border-line transition-colors last:border-0 hover:bg-accent-soft/40">
                    <td className="px-3 py-2 font-medium"><Link to={to.queue(r.rep_id)} className="hover:underline">{r.name}</Link></td>
                    <td className="px-3 py-2 text-ink-2">{r.profile}</td>
                    <td className="px-3 py-2 tabular"><Link to={to.leads({ rep_id: r.rep_id, open: true })} onClick={(e) => e.stopPropagation()} className="drill">{r.open_leads}</Link></td>
                    <td className="px-3 py-2 tabular">{r.load}/{r.capacity}</td>
                    <td className="px-3 py-2 tabular"><Link to={to.pipeline({ rep: r.rep_id })} onClick={(e) => e.stopPropagation()} className="drill">{money(r.pipeline_ev)}</Link></td>
                    <td className="px-3 py-2 tabular">{r.wins_total} / {r.closed_total}</td>
                    <td className="px-3 py-2 tabular">{pct(r.win_rate)}</td>
                    <td className="px-3 py-2 tabular">{minutes(r.median_first_response_min)}</td>
                    <td className="px-3 py-2 tabular">{pct(r.sla_attainment)}</td>
                    <td className="px-3 py-2 tabular">{r.neglect_count}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Funnel({ data }: { data: any }) {
  const stages = data.stages.slice(0, 8);
  const max = Math.max(1, ...stages.map((s: any) => s.reached));
  return (
    <div className="space-y-1.5">
      {stages.map((s: any, i: number) => {
        const conv = i > 0 ? data.conversions[i - 1]?.rate : null;
        return (
          <Link key={s.stage} to={to.leads({ stage: s.stage })} title={`${s.current} leads in ${human(s.stage)} now`} className="group grid grid-cols-[96px_1fr_92px] items-center gap-3 rounded-lg text-sm">
            <span className="capitalize text-ink-2 group-hover:text-accent-ink">{human(s.stage)}</span>
            <div className="h-5 rounded bg-surface-2"><div className="h-5 rounded-r transition-[filter] group-hover:brightness-110" style={{ width: `${(s.reached / max) * 100}%`, background: "var(--series-1)", minWidth: 2 }} /></div>
            <span className="text-right tabular">{num(s.reached)} <span className="text-xs text-ink-3">{conv == null ? "" : pct(conv)}</span></span>
          </Link>
        );
      })}
      <div className="pt-1 text-xs text-ink-3">Percentages are stage-to-stage conversion.</div>
    </div>
  );
}

function ResponseChart({ reps, onRep }: { reps: any[]; onRep: (id: string) => void }) {
  const data = reps.map((r) => ({ rep_id: r.rep_id, name: r.name.split(" ")[0], median: r.median_first_response_min, p90: r.p90_first_response_min, sla: r.sla_attainment, profile: r.profile }));
  return (
    <>
      <Legend items={[{ label: "Median", color: SERIES[0] }, { label: "p90", color: SERIES[1] }]} />
      <div className="mt-2 h-52">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barGap={2} className="cursor-pointer" onClick={(e: any) => { const id = e?.activePayload?.[0]?.payload?.rep_id; if (id) onRep(id); }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="name" {...AXIS} />
            <YAxis {...AXIS} tickFormatter={(v) => minutes(v)} />
            <Tooltip cursor={{ fill: "var(--c-surface-2)" }} content={<ChartTooltip format={(v) => minutes(v)} />} />
            <Bar dataKey="median" name="Median" fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={20} isAnimationActive={false} />
            <Bar dataKey="p90" name="p90" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={20} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">{data.map((d) => <button key={d.rep_id} onClick={() => onRep(d.rep_id)} className="drill">{d.name}: SLA met {pct(d.sla)}</button>)}</div>
    </>
  );
}

function Calibration({ model }: { model: any }) {
  return (
    <>
      <Legend items={[{ label: "Predicted", color: SERIES[0] }, { label: "Actual", color: SERIES[1] }]} />
      <div className="mt-2 h-44">
        <ResponsiveContainer>
          <LineChart data={model.calibration} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="decile" {...AXIS} />
            <YAxis {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
            <Tooltip content={<ChartTooltip format={(v) => pct(v, 1)} labelFormat={(d) => `Decile ${d}`} />} />
            <Line dataKey="predicted" name="Predicted" stroke={SERIES[0]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--c-surface)" }} isAnimationActive={false} />
            <Line dataKey="actual" name="Actual" stroke={SERIES[1]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--c-surface)" }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-4 text-xs sm:grid-cols-3">
        {model.coefficients.map((c: any) => <div key={c.feature} className="flex justify-between"><span className="text-ink-2">{human(c.feature)}</span><span className="tabular">{c.coef > 0 ? "+" : ""}{c.coef}</span></div>)}
      </div>
      <div className="mt-1 text-xs text-ink-3">n = {model.n} deals · base win rate {pct(model.base_rate, 1)}</div>
    </>
  );
}
