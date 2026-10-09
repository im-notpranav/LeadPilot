import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { dateTime, day, human, minutes, money, pct } from "../lib/format";
import { AXIS, ChartTooltip, GRID, Legend, SERIES } from "../components/charts";
import { Button, Card, Empty, Loading, Meter, PageHeader, Segmented, StatusTag } from "../components/ui";

export default function Quality() {
  const [win, setWin] = useState(30);
  const qc = useQueryClient();
  const sq = useQuery({ queryKey: ["quality", "sources", win], queryFn: () => api.get<any>(`/api/analytics/source-quality?window_days=${win}`) });
  const review = useQuery({ queryKey: ["quality", "review"], queryFn: () => api.get<{ items: any[] }>("/api/quality/review-queue") });
  const quarantine = useQuery({ queryKey: ["quality", "quarantine"], queryFn: () => api.get<{ items: any[] }>("/api/quality/quarantine") });
  const merges = useQuery({ queryKey: ["quality", "merges"], queryFn: () => api.get<{ items: any[] }>("/api/quality/merges") });
  const decide = async (id: string, decision: string) => { await api.post(`/api/quality/review/${id}`, { decision }); qc.invalidateQueries(); };
  const clear = async (lead: string) => { await api.post(`/api/quality/clear/${lead}`, { reviewer: "you" }); qc.invalidateQueries(); };

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <PageHeader title="Lead quality" subtitle="Fake and duplicate detection, the review queue, and which sources are worth paying for." />
      <Card title="Source quality" subtitle="Quality index = 0.30 SQL rate + 0.25 win rate + 0.20 (1 − fake) + 0.15 (1 − dup) + 0.10 avg score" pad={false}
        right={<Segmented value={win} onChange={setWin} options={[{ value: 7, label: "7 days" }, { value: 30, label: "30 days" }]} />}>
        {!sq.data ? <Loading /> : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[1100px] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-ink-3">
                {["Source", "Volume", "Dup", "Fake", "Contacted", "SQL", "Win", "Median 1st resp.", "Avg score", "Revenue", "Cost / SQL", "Quality index", "Flags"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>{sq.data.sources.map((s: any) => (
                <tr key={s.source_id} className="border-b border-line align-top last:border-0">
                  <td className="px-3 py-2 font-medium">{s.name}</td>
                  <td className="px-3 py-2 tabular">{s.volume}</td>
                  <td className="px-3 py-2 tabular">{pct(s.dup_rate)}</td>
                  <td className="px-3 py-2 tabular">{pct(s.fake_rate)}</td>
                  <td className="px-3 py-2 tabular">{pct(s.contact_rate)}</td>
                  <td className="px-3 py-2 tabular">{pct(s.sql_rate)}</td>
                  <td className="px-3 py-2 tabular">{pct(s.win_rate)}</td>
                  <td className="px-3 py-2 tabular">{minutes(s.median_first_response_min)}</td>
                  <td className="px-3 py-2 tabular">{s.avg_score.toFixed(0)}</td>
                  <td className="px-3 py-2 tabular">{money(s.revenue)}</td>
                  <td className="px-3 py-2 tabular">{s.cost_per_sql == null ? "-" : money(s.cost_per_sql)}</td>
                  <td className="w-32 px-3 py-2"><div className="mb-1 tabular">{s.quality_index.toFixed(2)}</div><Meter value={s.quality_index} /></td>
                  <td className="px-3 py-2">{s.flagged ? <div className="flex flex-col gap-1">{s.flag_reasons.map((r: string) => <StatusTag key={r} status="serious">{r}</StatusTag>)}</div> : <span className="text-xs text-ink-3">-</span>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Quality index trend" subtitle="Daily snapshot per source">
        {!sq.data ? <Loading /> : <Trend trend={sq.data.trend} names={Object.fromEntries(sq.data.sources.map((s: any) => [s.source_id, s.name]))} />}
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Review queue" subtitle="Possible duplicates (75–90% match) and suspicious leads (fake score 40–69)">
          {!review.data ? <Loading /> : !review.data.items.length ? <Empty>Nothing to review.</Empty> : (
            <ul className="scroll-thin max-h-[520px] space-y-3 overflow-y-auto">
              {review.data.items.map((r) => (
                <li key={r.id} className="rounded-lg border border-line p-3">
                  <div className="flex items-center justify-between text-xs text-ink-3"><span>{r.kind === "duplicate" ? `Possible duplicate · ${pct(r.confidence)} · ${(r.match_keys ?? []).join(", ")}` : `Suspicious · fake score ${r.lead?.fake_score}`}</span><span>{dateTime(r.ts)}</span></div>
                  <div className={`mt-2 grid gap-2 ${r.candidate ? "grid-cols-2" : "grid-cols-1"}`}>
                    <Brief b={r.lead} />{r.candidate && <Brief b={r.candidate} />}
                  </div>
                  <div className="mt-2 flex gap-2">
                    {r.kind === "duplicate" ? <><Button size="sm" variant="primary" onClick={() => decide(r.id, "merge")}>Merge</Button><Button size="sm" onClick={() => decide(r.id, "reject")}>Not a duplicate</Button></>
                      : <><Button size="sm" onClick={() => decide(r.id, "approve")}>Looks legit</Button><Button size="sm" variant="danger" onClick={() => decide(r.id, "disqualify")}>Disqualify</Button></>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={`Quarantine (${quarantine.data?.items.length ?? 0})`} subtitle="Fake score ≥ 70: never assigned, excluded from conversion stats, counted in source fake rate" pad={false}>
          {!quarantine.data ? <Loading /> : !quarantine.data.items.length ? <Empty>No quarantined leads.</Empty> : (
            <ul className="scroll-thin max-h-[520px] overflow-y-auto">
              {quarantine.data.items.map((l) => (
                <li key={l.lead_id} className="flex items-start justify-between gap-3 border-b border-line px-4 py-2.5 text-sm last:border-0">
                  <div className="min-w-0">
                    <Link to={`/leads/${l.lead_id}`} className="font-medium hover:underline">{l.name}</Link> <span className="text-xs text-ink-3">{l.email} · {human(l.source)}</span>
                    <div className="mt-0.5 text-xs text-ink-2">{l.signals.map((s: any) => `${human(s.key)} +${s.weight}`).join(" · ")}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2"><span className="text-xs tabular text-ink-3">{l.fake_score}</span><Button size="sm" variant="ghost" onClick={() => clear(l.lead_id)}>False positive</Button></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Card title="Merge history" pad={false}>
        {!merges.data ? <Loading /> : !merges.data.items.length ? <Empty>No merges yet.</Empty> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line text-left text-xs text-ink-3">{["When", "Survivor", "Merged", "Confidence", "Matched on", "Source", "Mode"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{merges.data.items.slice(0, 50).map((m) => (
              <tr key={m.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2 text-xs tabular text-ink-3">{dateTime(m.ts)}</td>
                <td className="px-4 py-2"><Link className="font-medium hover:underline" to={`/leads/${m.survivor_id}`}>{m.survivor?.name ?? m.survivor_id}</Link> <span className="text-xs text-ink-3">{m.survivor_id}</span></td>
                <td className="px-4 py-2 text-ink-2">{m.merged_id}</td>
                <td className="px-4 py-2 tabular">{pct(m.confidence)}</td>
                <td className="px-4 py-2 text-xs text-ink-2">{(m.match_keys ?? []).join(", ")}</td>
                <td className="px-4 py-2 text-xs">{human(m.source)}</td>
                <td className="px-4 py-2 text-xs">{m.mode}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function Brief({ b }: { b: any }) {
  if (!b) return null;
  return (
    <div className="rounded-md bg-surface-2 p-2 text-xs">
      <Link to={`/leads/${b.lead_id}`} className="font-medium text-ink hover:underline">{b.name ?? b.lead_id}</Link>
      <div className="text-ink-2">{b.email}</div>
      <div className="text-ink-3">{b.phone ?? "no phone"} · {b.company ?? "-"} · {human(b.source)}</div>
      {b.signals?.length > 0 && <div className="text-ink-3">{b.signals.map(human).join(", ")}</div>}
    </div>
  );
}

function Trend({ trend, names }: { trend: Record<string, any[]>; names: Record<string, string> }) {
  const ids = Object.keys(trend).sort((a, b) => (names[a] ?? a).localeCompare(names[b] ?? b)).slice(0, 8);
  const dates = Array.from(new Set(ids.flatMap((id) => trend[id].map((r) => r.date)))).sort();
  if (dates.length < 2) return <Empty>Trend appears after the second simulated day.</Empty>;
  const data = dates.map((d) => Object.fromEntries([["date", d], ...ids.map((id) => [id, trend[id].find((r) => r.date === d)?.quality_index ?? null])]));
  return (
    <>
      <Legend items={ids.map((id, i) => ({ label: names[id] ?? id, color: SERIES[i] }))} />
      <div className="mt-2 h-60">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => day(d)} minTickGap={28} />
            <YAxis {...AXIS} domain={[0, 1]} />
            <Tooltip content={<ChartTooltip format={(v) => (v == null ? "-" : v.toFixed(2))} labelFormat={(d) => day(d)} />} />
            {ids.map((id, i) => <Line key={id} dataKey={id} name={names[id] ?? id} stroke={SERIES[i]} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
