import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SimStatus } from "../lib/api";
import { useLive } from "../lib/live";
import { dateTime, human, num } from "../lib/format";
import { Button, Card, Loading, PageHeader, Segmented } from "../components/ui";

type Scenario = { name: string; title: string; description: string; expected: string[]; duration_hours: number; runs: number };

export default function Simulator() {
  const { clock } = useLive();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["sim", "status"], queryFn: () => api.get<SimStatus>("/api/sim/status"), refetchInterval: 2000 });
  const scenarios = useQuery({ queryKey: ["sim", "scenarios"], queryFn: () => api.get<{ items: Scenario[] }>("/api/sim/scenarios") });
  const [seed, setSeed] = useState("42");
  const [launched, setLaunched] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState("");
  const post = async (path: string, body?: unknown) => {
    try { const r = await api.post<any>(path, body); qc.invalidateQueries({ queryKey: ["sim"] }); return r; } catch (e) { setMsg(String(e)); }
  };
  const s = status.data;
  const resetting = clock.status === "resetting" || s?.status === "resetting";

  return (
    <div className="mx-auto max-w-[1300px] space-y-4">
      <PageHeader eyebrow="System" title="Simulator" subtitle="A seeded, deterministic simulation: personas, sources, reps with response-delay profiles, 6 months of closed-deal history." />
      <div className="stagger grid gap-4 lg:grid-cols-3">
        <Card title="Clock" subtitle={resetting ? "Resetting…" : dateTime(clock.now)}>
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" disabled={resetting} onClick={() => post(clock.paused ? "/api/sim/start" : "/api/sim/pause")}>{clock.paused ? "▶ Start" : "❚❚ Pause"}</Button>
              {[15, 60, 360, 1440].map((m) => <Button key={m} disabled={resetting} onClick={() => post("/api/sim/step", { minutes: m })}>+{m < 60 ? `${m}m` : m < 1440 ? `${m / 60}h` : "1d"}</Button>)}
            </div>
            <div className="flex items-center gap-2 text-xs text-ink-2">Speed <Segmented value={clock.speed} onChange={(v) => post("/api/sim/speed", { speed: v })} options={[1, 10, 60, 600].map((x) => ({ value: x, label: `${x}×` }))} /></div>
            <div className="text-xs text-ink-3">At 600× one simulated hour passes every 6 seconds. Hourly time ticks decay scores and check stalls and SLAs.</div>
          </div>
        </Card>
        <Card title="Reset" subtitle="Regenerates history and ~150 open leads from a seed">
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm">Seed <input value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} className="w-24 rounded-xl border border-line bg-surface px-2 py-1.5 tabular" /></label>
            <Button variant="danger" disabled={resetting} onClick={() => post("/api/sim/reset", { seed: Number(seed || 42) })}>Reset world</Button>
            <div className="flex flex-col gap-1.5 text-sm">
              <label className="inline-flex items-center gap-2"><input type="checkbox" checked={s?.background ?? true} onChange={(e) => post("/api/sim/background", { enabled: e.target.checked })} /> Background lead arrivals</label>
              <label className="inline-flex items-center gap-2"><input type="checkbox" checked={s?.rep_actions ?? true} onChange={(e) => post("/api/sim/rep-actions", { enabled: e.target.checked })} /> Simulated reps work their queues</label>
            </div>
            <Button size="sm" variant="ghost" onClick={async () => { const r = await post("/api/replay"); if (r) setMsg(`Replayed ${num(r.replayed_events)} events → ${r.leads} leads (identical projections)`); }}>Replay event log</Button>
            {msg && <div className="text-xs text-ink-2">{msg}</div>}
          </div>
        </Card>
        <Card title="Live counters">
          {!s ? <Loading /> : (
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              {[["Events processed", num(s.events)], ["Leads", num(s.leads)], ["Open leads", num(s.open_leads)], ["Stalled", num(s.stalled)], ["Quarantined", num(s.quarantined)], ["Merged duplicates", num(s.merged)], ["Won / lost", `${s.won} / ${s.lost}`], ["Historical deals", num(s.historical_deals)], ["p50 latency", s.latency.p50_ms != null ? `${s.latency.p50_ms} ms` : "-"], ["p95 latency", s.latency.p95_ms != null ? `${s.latency.p95_ms} ms` : "-"]].map(([l, v]) => (
                <div key={l} className="flex justify-between gap-2 border-b border-line pb-1"><span className="text-ink-2">{l}</span><span className="font-medium tabular">{v}</span></div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <Card title="Scripted scenarios" subtitle="Deterministic demos. Launch one, then run the clock (600× is a good speed) and open the lead.">
        {!scenarios.data ? <Loading /> : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {scenarios.data.items.map((sc) => {
              const info = launched[sc.name];
              return (
                <div key={sc.name} className="flex flex-col rounded-xl border border-line bg-surface-2/40 p-4 transition duration-200 hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-card">
                  <div className="flex items-baseline justify-between"><h3 className="font-semibold">{sc.title}</h3><span className="text-xs text-ink-3">~{sc.duration_hours >= 24 ? `${sc.duration_hours / 24}d` : `${sc.duration_hours}h`} sim</span></div>
                  <p className="mt-1 text-sm text-ink-2">{sc.description}</p>
                  <ul className="mt-2 flex-1 space-y-0.5 text-xs text-ink-2">{sc.expected.map((e) => <li key={e}>✓ {e}</li>)}</ul>
                  <div className="mt-3 flex items-center gap-2">
                    <Button size="sm" variant="primary" disabled={resetting} onClick={async () => { const r = await post(`/api/sim/scenario/${sc.name}`); if (r) setLaunched((x) => ({ ...x, [sc.name]: r })); }}>Launch</Button>
                    {info?.lead_id && <Link className="text-sm font-medium text-accent-ink hover:underline" to={`/leads/${info.lead_id}`}>Open {info.lead_id} →</Link>}
                    {info && !info.lead_id && <Link className="text-sm font-medium text-accent-ink hover:underline" to="/quality">Open quality →</Link>}
                    {sc.runs > 0 && <span className="ml-auto text-xs text-ink-3">run {sc.runs}×</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
      {s && (
        <Card title="Simulated activity" subtitle="Event counts generated by personas and reps since reset">
          <div className="flex flex-wrap gap-2 text-xs">{Object.entries(s.sim_counts).map(([k, v]) => <span key={k} className="rounded-md bg-surface-2 px-2 py-1 text-ink-2">{human(k)} <span className="font-medium tabular text-ink">{num(v)}</span></span>)}</div>
        </Card>
      )}
    </div>
  );
}
