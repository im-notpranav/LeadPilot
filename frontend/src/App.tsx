import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useLive } from "./lib/live";
import { api } from "./lib/api";
import { dateTime } from "./lib/format";
import { Segmented } from "./components/ui";
import Queue from "./pages/Queue";
import LeadDetail from "./pages/LeadDetail";
import Pipeline from "./pages/Pipeline";
import LiveFeed from "./pages/LiveFeed";
import Analytics from "./pages/Analytics";
import Quality from "./pages/Quality";
import Simulator from "./pages/Simulator";

const NAV = [
  { to: "/queue", label: "My Queue", icon: "M4 6h16M4 12h16M4 18h10" },
  { to: "/pipeline", label: "Pipeline", icon: "M4 5h4v14H4zM10 5h4v9h-4zM16 5h4v5h-4z" },
  { to: "/feed", label: "Live Feed", icon: "M4 12h4l3-7 4 14 3-7h2" },
  { to: "/analytics", label: "Analytics", icon: "M5 19V9M12 19V5M19 19v-7" },
  { to: "/quality", label: "Quality", icon: "M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" },
  { to: "/simulator", label: "Simulator", icon: "M7 4v16l13-8z" },
];

export default function App() {
  return (
    <div className="flex h-full">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="7" fill="var(--c-accent)" /><path d="M9 22 L16 9 L23 22 L16 18 Z" fill="white" /></svg>
          <div>
            <div className="text-sm font-semibold leading-tight">LeadPilot</div>
            <div className="text-[11px] text-ink-3">Lead-to-deal intelligence</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${isActive ? "bg-accent-soft font-medium text-accent-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={n.icon} /></svg>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-5 py-4 text-[11px] leading-relaxed text-ink-3">Every score, stage and assignment is explained. Click any lead to see why.</div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-6">
          <Routes>
            <Route path="/" element={<Navigate to="/queue" replace />} />
            <Route path="/queue" element={<Queue />} />
            <Route path="/leads/:id" element={<LeadDetail />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/feed" element={<LiveFeed />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/quality" element={<Quality />} />
            <Route path="/simulator" element={<Simulator />} />
          </Routes>
        </main>
      </div>
      <Toasts />
    </div>
  );
}

function TopBar() {
  const { clock, connected, eventsPerMin } = useLive();
  const qc = useQueryClient();
  const act = async (path: string, body?: unknown) => { await api.post(path, body); qc.invalidateQueries({ queryKey: ["sim"] }); };
  const resetting = clock.status === "resetting";
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-2.5 md:px-6">
      <div className="flex items-center gap-2 md:hidden">
        {NAV.map((n) => <NavLink key={n.to} to={n.to} className="text-xs text-ink-2">{n.label.split(" ").pop()}</NavLink>)}
      </div>
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${connected ? "bg-good" : "bg-critical"}`} aria-hidden />
        <span className="text-xs text-ink-3">{connected ? "Live" : "Reconnecting"}</span>
      </div>
      <div className="text-sm font-medium tabular text-ink">{resetting ? "Generating 6 months of history + warm-up…" : dateTime(clock.now)} <span className="text-xs font-normal text-ink-3">UTC · sim</span></div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <span className="hidden text-xs tabular text-ink-3 lg:inline">{eventsPerMin} events/min</span>
        <button disabled={resetting} onClick={() => act(clock.paused ? "/api/sim/start" : "/api/sim/pause")}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-sm font-medium hover:bg-surface-2 disabled:opacity-50">
          {clock.paused ? "▶ Run" : "❚❚ Pause"}
        </button>
        <Segmented label="Speed" value={clock.speed} onChange={(v) => act("/api/sim/speed", { speed: v })}
          options={[1, 10, 60, 600].map((s) => ({ value: s, label: `${s}×` }))} />
        <button disabled={resetting} onClick={() => act("/api/sim/step", { minutes: 60 })} className="h-8 rounded-lg px-2 text-xs text-ink-2 hover:bg-surface-2 disabled:opacity-50" title="Advance 1 simulated hour">+1h</button>
      </div>
    </header>
  );
}

function Toasts() {
  const { toasts, dismiss } = useLive();
  const nav = useNavigate();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <div key={t.id} className="slidein pointer-events-auto flex items-start gap-2 rounded-lg border border-line bg-surface px-3 py-2.5 text-sm shadow-lg">
          <button className="flex-1 text-left text-ink" onClick={() => { if (t.lead_id) nav(`/leads/${t.lead_id}`); dismiss(t.id); }}>{t.text}</button>
          <button className="text-ink-3 hover:text-ink" onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
        </div>
      ))}
    </div>
  );
}
