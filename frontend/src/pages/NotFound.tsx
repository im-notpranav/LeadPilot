import { Link, useLocation, useNavigate } from "react-router-dom";
import { can, useAuth } from "../lib/auth";
import { Logo, LogoMark } from "../components/Logo";
import { Icon, type IconName } from "../components/icons";
import { ThemeToggle } from "../components/ui";

const QUICK: { to: string; label: string; icon: IconName; hint: string }[] = [
  { to: "/queue", label: "My Queue", icon: "queue", hint: "Leads by priority" },
  { to: "/leads", label: "Leads", icon: "list", hint: "Search every lead" },
  { to: "/pipeline", label: "Pipeline", icon: "pipeline", hint: "Deals by stage" },
  { to: "/analytics", label: "Analytics", icon: "analytics", hint: "Funnel & reps" },
];

export default function NotFound() {
  const loc = useLocation();
  const nav = useNavigate();
  const { me } = useAuth();
  const home = me ? "/queue" : "/login";

  return (
    <div className="relative flex min-h-full flex-col overflow-hidden">
      <div className="app-backdrop" aria-hidden />
      <Sky />

      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <Link to={home} aria-label="LeadPilot home"><Logo size={32} /></Link>
        <ThemeToggle />
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-6 pb-16 text-center">
        <div className="flex items-center justify-center gap-5 font-display font-extrabold leading-none tracking-tighter text-ink sm:gap-9" style={{ animation: "rise 600ms cubic-bezier(.2,.8,.2,1) both" }} aria-hidden>
          <span className="text-[112px] sm:text-[168px]">4</span>
          <Radar />
          <span className="text-[112px] sm:text-[168px]">4</span>
        </div>

        <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-2 shadow-sm" style={{ animation: "rise 600ms 120ms both" }}>
          <span className="h-1.5 w-1.5 rounded-full bg-critical" /> Error 404
        </div>
        <h1 className="mt-4 font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl" style={{ animation: "rise 600ms 180ms both" }}>
          Page not found
        </h1>
        <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-ink-2" style={{ animation: "rise 600ms 240ms both" }}>
          There is no page at <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[13px] text-ink">{loc.pathname}</code>. Check the address, or go to one of the pages below. Looking for a lead? Search for it in Leads.
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3" style={{ animation: "rise 600ms 300ms both" }}>
          <Link to={home} className="btn-brand inline-flex h-11 items-center gap-2 rounded-2xl px-5 text-sm font-semibold transition active:scale-[0.97]">
            <Icon name="home" />{me ? "Back to dashboard" : "Go to sign in"}
          </Link>
          <button onClick={() => (window.history.length > 1 ? nav(-1) : nav(home))} className="inline-flex h-11 items-center gap-2 rounded-2xl border border-line bg-surface px-5 text-sm font-semibold text-ink shadow-sm transition hover:bg-surface-2 active:scale-[0.97]">
            <Icon name="arrowLeft" />Go back
          </button>
        </div>

        {me && (
          <div className="mt-10 grid w-full max-w-xl gap-3 sm:grid-cols-2" style={{ animation: "rise 600ms 380ms both" }}>
            {QUICK.filter((q) => q.to !== "/analytics" || can.manage(me)).map((q) => (
              <Link key={q.to} to={q.to} className="card group flex items-center gap-3 rounded-2xl px-4 py-3 text-left transition hover:-translate-y-0.5 hover:shadow-pop">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent-soft text-accent-ink transition group-hover:scale-110"><Icon name={q.icon} /></span>
                <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">{q.label}</span><span className="block text-xs text-ink-3">{q.hint}</span></span>
                <Icon name="arrowRight" className="text-ink-3 transition group-hover:translate-x-0.5 group-hover:text-accent-ink" />
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

/** The "0": a radar scope with a sweeping beam and the plane circling it. */
function Radar() {
  return (
    <span className="relative inline-block h-[104px] w-[104px] sm:h-[150px] sm:w-[150px]">
      <svg viewBox="0 0 160 160" className="absolute inset-0 h-full w-full" aria-hidden>
        <defs>
          <radialGradient id="nf-scope" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="var(--c-brand)" stopOpacity=".18" />
            <stop offset="1" stopColor="var(--c-brand)" stopOpacity=".02" />
          </radialGradient>
          <linearGradient id="nf-beam" x1="80" y1="80" x2="150" y2="40" gradientUnits="userSpaceOnUse">
            <stop stopColor="var(--c-brand)" stopOpacity=".55" />
            <stop offset="1" stopColor="var(--c-brand)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <circle cx="80" cy="80" r="74" fill="url(#nf-scope)" stroke="var(--c-brand)" strokeOpacity=".55" strokeWidth="3" />
        <circle cx="80" cy="80" r="50" fill="none" stroke="var(--c-brand)" strokeOpacity=".3" strokeWidth="1.5" strokeDasharray="4 6" />
        <circle cx="80" cy="80" r="26" fill="none" stroke="var(--c-brand)" strokeOpacity=".3" strokeWidth="1.5" />
        <path d="M80 6 V154 M6 80 H154" stroke="var(--c-brand)" strokeOpacity=".15" strokeWidth="1" />
        <g className="radar-sweep"><path d="M80 80 L154 80 A74 74 0 0 0 132 28 Z" fill="url(#nf-beam)" /></g>
        <circle cx="80" cy="80" r="4" fill="var(--c-brand)" />
        <circle cx="118" cy="52" r="3" fill="var(--c-critical)"><animate attributeName="opacity" values="0;1;0" dur="3.2s" repeatCount="indefinite" /></circle>
      </svg>
      {/* plane orbiting just outside the scope */}
      <span className="orbit absolute inset-[-12%]">
        <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 rotate-[45deg]"><LogoMark size={34} /></span>
      </span>
    </span>
  );
}

/** Drifting clouds in light mode, twinkling stars in dark mode. */
function Sky() {
  const clouds = [
    { top: "14%", w: 160, dur: 46, delay: -10, o: 0.9 },
    { top: "32%", w: 110, dur: 60, delay: -38, o: 0.7 },
    { top: "68%", w: 200, dur: 72, delay: -20, o: 0.8 },
    { top: "82%", w: 130, dur: 54, delay: -48, o: 0.6 },
  ];
  const stars = Array.from({ length: 36 }, (_, i) => ({ left: `${(i * 37) % 100}%`, top: `${(i * 53) % 100}%`, d: 2 + (i % 4), delay: (i % 7) * 0.4 }));
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      <div className="dark:hidden">
        {clouds.map((c, i) => (
          <span key={i} className="cloud" style={{ top: c.top, left: 0, animationDuration: `${c.dur}s`, animationDelay: `${c.delay}s`, opacity: c.o }}>
            <svg width={c.w} height={c.w * 0.42} viewBox="0 0 100 42"><path d="M20 40 h62 a14 14 0 0 0 0-28 a20 20 0 0 0-37-6 a15 15 0 0 0-25 14 a10 10 0 0 0 0 20z" fill="white" /></svg>
          </span>
        ))}
      </div>
      <div className="hidden dark:block">
        {stars.map((s, i) => (
          <span key={i} className="absolute rounded-full bg-white" style={{ left: s.left, top: s.top, width: s.d, height: s.d, opacity: 0.5, animation: `fadein 1.6s ${s.delay}s ease-in-out infinite alternate` }} />
        ))}
      </div>
    </div>
  );
}
