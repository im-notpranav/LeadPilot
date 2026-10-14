// App chrome: floating glass sidebar, top bar (search, sim clock, notifications, theme, account), toasts.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLive, type Toast } from "../lib/live";
import { useAuth } from "../lib/auth";
import { api, type LeadView, type SimStatus } from "../lib/api";
import { dateTime, human } from "../lib/format";
import { GradePill, Segmented, ThemeToggle } from "./ui";
import { Icon, type IconName } from "./icons";
import { Logo, LogoMark } from "./Logo";
import { to } from "../lib/links";

type NavItem = { to: string; label: string; icon: IconName; badge?: { key: "stalled" | "quarantined"; href: string; label: string }; live?: boolean };
const NAV: { section: string; items: NavItem[] }[] = [
  { section: "Main", items: [
    { to: "/queue", label: "My Queue", icon: "queue" },
    { to: "/leads", label: "Leads", icon: "list" },
    { to: "/pipeline", label: "Pipeline", icon: "pipeline", badge: { key: "stalled", href: to.pipeline({ stalled: true }), label: "stalled deals" } },
    { to: "/feed", label: "Live Feed", icon: "feed", live: true },
  ] },
  { section: "Insights", items: [
    { to: "/analytics", label: "Analytics", icon: "analytics" },
    { to: "/quality", label: "Quality", icon: "quality", badge: { key: "quarantined", href: to.quality("quarantine"), label: "quarantined leads" } },
  ] },
  { section: "System", items: [{ to: "/simulator", label: "Simulator", icon: "simulator" }] },
];

function readCollapsed() { try { return localStorage.getItem("lp.sidebar") === "collapsed"; } catch { return false; } }

export default function Shell() {
  const loc = useLocation();
  const nav = useNavigate();
  const { notify } = useLive();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawer, setDrawer] = useState(false);
  // Arriving from the login takeoff: play the entrance once, then drop the flag so reloads don't replay it.
  const [arrived] = useState(() => (loc.state as { arrived?: string } | null)?.arrived ?? "");
  const arrive = Boolean(arrived);
  useEffect(() => {
    if (!arrive) return;
    const t = window.setTimeout(() => notify(arrived, "welcome"), 250);
    nav(loc.pathname + loc.search, { replace: true, state: null });
    return () => clearTimeout(t);
  }, []); // mount only
  useEffect(() => setDrawer(false), [loc.pathname]);
  const toggleCollapsed = () => setCollapsed((c) => { try { localStorage.setItem("lp.sidebar", c ? "open" : "collapsed"); } catch { /* storage blocked */ } return !c; });

  return (
    <div className={`relative flex h-full ${arrive ? "arrive" : ""}`}>
      <div className="app-backdrop" aria-hidden />
      {arrive && <div className="arrive-veil" aria-hidden />}

      <div className="arrive-side relative z-20 hidden md:flex">
        <Sidebar collapsed={collapsed} onToggle={toggleCollapsed} />
      </div>
      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-navy/50" style={{ animation: "fadein 150ms ease-out" }} onClick={() => setDrawer(false)} />
          <div className="relative h-full w-72" style={{ animation: "arrive-left 200ms var(--ease-out)" }}>
            <Sidebar collapsed={false} drawer onClose={() => setDrawer(false)} />
          </div>
        </div>
      )}

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <div className="arrive-top relative z-30"><TopBar onMenu={() => setDrawer(true)} /></div>
        <main className="arrive-main scroll-thin min-h-0 flex-1 overflow-y-auto px-4 pb-10 pt-4 md:px-6 lg:px-8">
          <ApiStatus />
          <div key={loc.pathname} className="page-enter">
            <Outlet />
          </div>
        </main>
      </div>
      <Toasts />
    </div>
  );
}

/** Explains an empty dashboard instead of leaving skeletons spinning: API down, or still building history. */
function ApiStatus() {
  const { clock } = useLive();
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<unknown>("/api/health"), refetchInterval: (q) => (q.state.status === "error" ? 3000 : 15000), retry: false });
  const recovered = useRef(false);
  useEffect(() => {
    if (health.isError) recovered.current = true;
    else if (health.isSuccess && recovered.current) { recovered.current = false; qc.invalidateQueries(); }
  }, [health.isError, health.isSuccess, qc]);
  if (health.isError) {
    return (
      <div role="alert" className="pop mb-4 flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-3 text-sm" style={{ borderColor: "color-mix(in srgb, var(--c-critical) 40%, transparent)", background: "color-mix(in srgb, var(--c-critical) 8%, var(--c-surface))" }}>
        <Icon name="alert" className="shrink-0 text-critical-ink" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-ink">The LeadPilot API is not reachable</div>
          <div className="text-ink-2">Start it with <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">python scripts/dev.py</code> from the project folder (or <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">make dev</code>). This page reconnects on its own.</div>
        </div>
        <button onClick={() => health.refetch()} className="rounded-xl border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink shadow-sm hover:bg-surface-2">Retry now</button>
      </div>
    );
  }
  if (clock.status === "resetting" || clock.status === "starting") {
    return (
      <div role="status" className="pop mb-4 flex items-center gap-3 rounded-2xl border border-brand/30 bg-accent-soft/60 px-4 py-3 text-sm text-ink-2">
        <span className="h-4 w-4 shrink-0 rounded-full border-2 border-brand/30 border-t-brand" style={{ animation: "spin 700ms linear infinite" }} />
        {clock.status === "resetting" ? "Generating 6 months of simulated history. Numbers appear in about 20 seconds." : "Connecting to the live engine…"}
      </div>
    );
  }
  return null;
}

function Sidebar({ collapsed, onToggle, onClose, drawer }: { collapsed: boolean; onToggle?: () => void; onClose?: () => void; drawer?: boolean }) {
  const { connected, eventsPerMin } = useLive();
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const status = useQuery({ queryKey: ["sim", "status"], queryFn: () => api.get<SimStatus>("/api/sim/status"), refetchInterval: 5000 });
  const badge = (b?: NavItem["badge"]) => (b ? status.data?.[b.key] : undefined);

  return (
    <aside className={`relative m-3 mr-0 flex h-[calc(100%-1.5rem)] flex-col rounded-3xl shadow-card transition-[width] duration-200 ease-out ${drawer ? "card" : "glass"} ${collapsed ? "w-[76px]" : "w-64"}`}>
      <div className={`flex items-center pt-5 ${collapsed ? "justify-center px-0" : "justify-between px-5"}`}>
        <NavLink to="/queue" aria-label="LeadPilot home" className="rounded-lg">
          {collapsed ? <LogoMark size={34} /> : <Logo size={34} tagline={!drawer} />}
        </NavLink>
        {onClose && <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-ink-2 hover:bg-surface-2" aria-label="Close menu"><Icon name="close" /></button>}
      </div>
      {onToggle && (
        <button onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand" : "Collapse"}
          className="absolute -right-3 top-8 z-10 grid h-6 w-6 place-items-center rounded-full border border-line bg-surface text-ink-2 shadow-card transition hover:scale-110 hover:text-accent-ink">
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} size={13} />
        </button>
      )}
      <div className={`mx-4 mt-5 h-px bg-gradient-to-r from-transparent via-[var(--c-line)] to-transparent`} />

      <nav className="scroll-thin mt-3 flex-1 overflow-y-auto px-3" aria-label="Primary">
        {NAV.map((g) => (
          <div key={g.section} className="mb-3">
            {collapsed ? <div className="mx-auto my-2 h-px w-6 bg-[var(--c-line)]" /> : <div className="px-3 pb-1.5 pt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-3">{g.section}</div>}
            <div className="flex flex-col gap-1">
              {g.items.map((n) => {
                const count = badge(n.badge);
                return (
                  <NavLink key={n.to} to={n.to} title={collapsed ? n.label : undefined}
                    className={({ isActive }) => `group relative flex items-center gap-3 rounded-xl text-sm transition duration-200 ${collapsed ? "h-11 justify-center" : "px-3 py-2.5"} ${isActive ? "bg-surface font-semibold text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:bg-surface/60 hover:text-ink"}`}>
                    {({ isActive }) => (
                      <>
                        {isActive && <span className="absolute -left-3 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-brand" style={{ animation: "fadein 300ms" }} aria-hidden />}
                        <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg transition ${isActive ? "bg-gradient-to-br from-[#60a5fa] to-[#2563eb] text-white shadow-[0_4px_12px_-4px_rgb(37_99_235/.8)]" : "text-ink-3 group-hover:text-accent-ink"}`}>
                          <Icon name={n.icon} size={15} />
                        </span>
                        {!collapsed && <span className="flex-1 truncate">{n.label}</span>}
                        {/* The live stream's health rides on its own nav item instead of a card that crowds the menu. */}
                        {n.live && (
                          <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium tabular ${connected ? "text-good-ink" : "text-critical-ink"} ${collapsed ? "absolute right-2.5 top-2.5" : ""}`}
                            title={connected ? `Live: ${eventsPerMin} events per minute` : "Reconnecting to the live stream"}>
                            <span className={`h-2 w-2 rounded-full ${connected ? "live-dot bg-good" : "bg-critical"}`} aria-hidden />
                            {!collapsed && (connected ? `${eventsPerMin}/min` : "Offline")}
                          </span>
                        )}
                        {!!count && n.badge && (
                          <span role="link" tabIndex={0} onClick={(e) => { e.preventDefault(); e.stopPropagation(); nav(n.badge!.href); }} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); nav(n.badge!.href); } }}
                            className={`rounded-full bg-critical px-1.5 text-[10px] font-semibold leading-[18px] tabular text-white transition hover:scale-110 hover:brightness-110 ${collapsed ? "absolute right-1 top-1" : ""}`} title={`${count} ${n.badge.label}: open them`}>{count > 99 ? "99+" : count}</span>
                        )}
                      </>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className={`flex items-center gap-2.5 border-t border-line px-3 py-3 ${collapsed ? "justify-center" : ""}`}>
        <Avatar initials={user?.initials ?? "LP"} />
        {!collapsed && (
          <>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-ink">{user?.name}</div>
              <div className="truncate text-[11px] text-ink-3">{user?.email}</div>
            </div>
            <button onClick={() => { signOut(); nav("/login", { replace: true }); }} className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition hover:bg-surface hover:text-critical-ink" aria-label="Sign out" title="Sign out">
              <Icon name="logout" />
            </button>
          </>
        )}
      </div>
    </aside>
  );
}

export function Avatar({ initials, size = 36 }: { initials: string; size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#60a5fa] to-[#1d4ed8] font-semibold text-white ring-2 ring-surface" style={{ width: size, height: size, fontSize: size * 0.36 }} aria-hidden>
      {initials}
    </span>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { clock, connected } = useLive();
  const qc = useQueryClient();
  const act = async (path: string, body?: unknown) => { await api.post(path, body); qc.invalidateQueries({ queryKey: ["sim"] }); };
  const resetting = clock.status === "resetting";
  return (
    <header className="glass mx-3 mt-3 flex flex-wrap items-center gap-2 rounded-2xl px-3 py-2 shadow-card md:ml-4 md:mr-4 lg:mr-6">
      <button onClick={onMenu} className="grid h-9 w-9 place-items-center rounded-xl text-ink-2 hover:bg-surface md:hidden" aria-label="Open menu"><Icon name="menu" size={18} /></button>
      <LogoMark size={28} className="md:hidden" />
      <SearchBox />
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <NavLink to="/simulator" className="hidden items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 shadow-sm transition hover:border-brand/40 sm:flex" title={`${connected ? "Connected" : "Reconnecting"} · simulated clock, open the Simulator`}>
          <span className={`live-dot h-2 w-2 rounded-full ${connected ? "bg-good" : "bg-critical"}`} aria-hidden />
          <span className="text-xs font-medium tabular text-ink">{resetting ? "Generating history…" : dateTime(clock.now)}</span>
          <span className="hidden text-[11px] text-ink-3 xl:inline">UTC · sim</span>
        </NavLink>
        <button disabled={resetting} onClick={() => act(clock.paused ? "/api/sim/start" : "/api/sim/pause")}
          className={`inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-sm font-medium transition active:scale-[0.97] disabled:opacity-50 ${clock.paused ? "btn-brand" : "border border-line bg-surface text-ink shadow-sm hover:bg-surface-2"}`}>
          <Icon name={clock.paused ? "play" : "pause"} size={14} />{clock.paused ? "Run" : "Pause"}
        </button>
        <div className="hidden lg:block">
          <Segmented label="Speed" value={clock.speed} onChange={(v) => act("/api/sim/speed", { speed: v })} options={[1, 10, 60, 600].map((s) => ({ value: s, label: `${s}×` }))} />
        </div>
        <button disabled={resetting} onClick={() => act("/api/sim/step", { minutes: 60 })} className="hidden h-9 items-center gap-1 rounded-xl px-2.5 text-xs font-medium text-ink-2 transition hover:bg-surface disabled:opacity-50 sm:inline-flex" title="Advance 1 simulated hour">
          <Icon name="forward" size={13} />1h
        </button>
        <span className="mx-1 hidden h-6 w-px bg-[var(--c-line)] sm:block" aria-hidden />
        <Notifications />
        <ThemeToggle compact />
        <UserMenu />
      </div>
    </header>
  );
}

function useOutside<T extends HTMLElement>(open: boolean, close: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close]);
  return ref;
}

function SearchBox() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const wrap = useOutside<HTMLDivElement>(open, () => setOpen(false));
  useEffect(() => { const t = window.setTimeout(() => setDebounced(q.trim()), 180); return () => clearTimeout(t); }, [q]);
  useEffect(() => setHi(0), [debounced]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]");
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); input.current?.focus(); setOpen(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const res = useQuery({
    queryKey: ["search", debounced], enabled: debounced.length >= 2,
    queryFn: () => api.get<{ items: LeadView[]; total: number }>(`/api/leads?q=${encodeURIComponent(debounced)}&limit=7`),
  });
  const items = debounced.length >= 2 ? res.data?.items ?? [] : [];
  const go = (l: LeadView) => { nav(`/leads/${l.lead_id}`); setOpen(false); setQ(""); input.current?.blur(); };
  const all = () => { nav(to.leads({ q: q.trim() })); setOpen(false); setQ(""); input.current?.blur(); };

  return (
    <div ref={wrap} className="relative order-last w-full sm:order-none sm:w-auto sm:min-w-[220px] sm:flex-1 lg:max-w-md">
      <label className="group flex h-9 items-center gap-2 rounded-xl border border-line bg-surface px-3 shadow-sm transition focus-within:border-brand focus-within:ring-4 focus-within:ring-brand/15">
        <Icon name="search" className="text-ink-3 group-focus-within:text-accent-ink" />
        <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, items.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
            if (e.key === "Enter") { if (items[hi]) go(items[hi]); else if (q.trim()) all(); }
          }}
          placeholder="Search leads, companies, emails…" aria-label="Search leads" role="combobox" aria-expanded={open && items.length > 0} aria-controls="lead-search-results"
          className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none" />
        <kbd className="hidden rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-3 md:inline">Ctrl K</kbd>
      </label>
      {open && debounced.length >= 2 && (
        <div id="lead-search-results" role="listbox" className="pop card absolute left-0 right-0 top-11 z-50 overflow-hidden rounded-2xl p-1.5 shadow-pop">
          {res.isLoading ? <div className="px-3 py-3 text-sm text-ink-3">Searching…</div>
            : !items.length ? <div className="px-3 py-3 text-sm text-ink-3">No leads match “{debounced}”.</div>
            : items.map((l, i) => (
              <button key={l.lead_id} role="option" aria-selected={i === hi} onMouseEnter={() => setHi(i)} onClick={() => go(l)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition ${i === hi ? "bg-accent-soft" : ""}`}>
                <GradePill grade={l.grade} score={l.score} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{l.name}</span>
                  <span className="block truncate text-xs text-ink-3">{l.company ?? "-"} · {l.lead_id}</span>
                </span>
                <span className="text-xs capitalize text-ink-3">{human(l.stage)}</span>
              </button>
            ))}
          {!!res.data && res.data.total > 0 && (
            <button onClick={all} className="mt-1 flex w-full items-center justify-between rounded-xl border-t border-line px-3 pb-1.5 pt-2.5 text-left text-xs font-medium text-accent-ink hover:bg-accent-soft/50">
              <span>See all {res.data.total} results in Leads</span><Icon name="arrowRight" size={12} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Where a notification leads: its lead if it has one, otherwise the page about it. */
const toastHref = (t: Toast) => (t.lead_id ? to.lead(t.lead_id) : t.kind === "source.flagged" ? to.quality("sources") : t.kind === "lead.merged" ? to.quality("merges") : null);

const KIND_ICON: Record<string, IconName> = { "lead.reassigned": "users", "stall.detected": "alert", "lead.merged": "merge", "source.flagged": "quality", "scenario.launched": "zap", welcome: "check" };

function Notifications() {
  const { history, unread, markRead } = useLive();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useOutside<HTMLDivElement>(open, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <button onClick={() => { setOpen((o) => !o); markRead(); }} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} aria-expanded={open}
        className="relative grid h-9 w-9 place-items-center rounded-xl border border-line bg-surface text-ink-2 shadow-sm transition hover:text-ink">
        <Icon name="bell" />
        {unread > 0 && <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-critical px-1 text-[9px] font-bold text-white ring-2 ring-surface" style={{ animation: "pop 200ms" }}>{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="pop card absolute right-0 top-11 z-50 w-80 overflow-hidden rounded-2xl shadow-pop">
          <div className="flex items-center justify-between border-b border-line px-4 py-3"><span className="font-display text-sm font-bold">Notifications</span><span className="text-[11px] text-ink-3">Last {history.length}</span></div>
          <div className="scroll-thin max-h-80 overflow-y-auto p-1.5">
            {!history.length ? <div className="px-3 py-6 text-center text-sm text-ink-3">No notifications yet. Reassignments, stalls and merges appear here.</div>
              : history.map((t) => (
                <button key={t.id} onClick={() => { const h = toastHref(t); if (h) nav(h); setOpen(false); }} className="flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm transition hover:bg-surface-2">
                  <ToastIcon t={t} />
                  <span className="min-w-0 flex-1 text-ink-2">{t.text}</span>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useOutside<HTMLDivElement>(open, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-label="Account menu" aria-expanded={open} className="flex items-center gap-1 rounded-full transition hover:opacity-90">
        <Avatar initials={user?.initials ?? "LP"} size={34} />
      </button>
      {open && (
        <div className="pop card absolute right-0 top-11 z-50 w-64 overflow-hidden rounded-2xl p-1.5 shadow-pop">
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <Avatar initials={user?.initials ?? "LP"} size={40} />
            <div className="min-w-0"><div className="truncate text-sm font-semibold">{user?.name}</div><div className="truncate text-xs text-ink-3">{user?.email}</div></div>
          </div>
          <div className="my-1 h-px bg-[var(--c-line)]" />
          <div className="flex items-center justify-between px-2.5 py-2 text-sm text-ink-2">Theme <ThemeToggle /></div>
          <MenuItem icon="simulator" onClick={() => { nav("/simulator"); setOpen(false); }}>Simulator settings</MenuItem>
          <MenuItem icon="logout" danger onClick={() => { signOut(); nav("/login", { replace: true }); }}>Sign out</MenuItem>
        </div>
      )}
    </div>
  );
}

function MenuItem({ icon, children, onClick, danger }: { icon: IconName; children: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button onClick={onClick} className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm transition hover:bg-surface-2 ${danger ? "text-critical-ink" : "text-ink-2 hover:text-ink"}`}>
      <Icon name={icon} />{children}
    </button>
  );
}

function ToastIcon({ t }: { t: Toast }) {
  const bad = t.kind === "stall.detected" || t.kind === "source.flagged";
  return (
    <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${bad ? "bg-[color-mix(in_srgb,var(--c-critical)_14%,transparent)] text-critical-ink" : "bg-accent-soft text-accent-ink"}`}>
      <Icon name={KIND_ICON[t.kind] ?? "bell"} size={14} />
    </span>
  );
}

function Toasts() {
  const { toasts, dismiss } = useLive();
  const nav = useNavigate();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toastin card pointer-events-auto relative overflow-hidden rounded-2xl shadow-pop">
          <div className="flex items-start gap-2.5 px-3 py-3 text-sm">
            <ToastIcon t={t} />
            <button className="flex-1 text-left text-ink" onClick={() => { const h = toastHref(t); if (h) nav(h); dismiss(t.id); }}>{t.text}</button>
            <button className="grid h-6 w-6 place-items-center rounded-md text-ink-3 hover:bg-surface-2 hover:text-ink" onClick={() => dismiss(t.id)} aria-label="Dismiss"><Icon name="close" size={13} /></button>
          </div>
          <div className="absolute bottom-0 left-0 h-0.5 w-full origin-left bg-gradient-to-r from-[#60a5fa] to-[#2563eb]" style={{ animation: "drain 7s linear forwards" }} aria-hidden />
        </div>
      ))}
    </div>
  );
}
