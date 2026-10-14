import { useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { DEMO, useAuth } from "../lib/auth";
import { Logo, LogoMark, Wordmark } from "../components/Logo";
import { Icon } from "../components/icons";
import { ThemeToggle } from "../components/ui";

type Phase = "idle" | "loading" | "success";

export default function Login() {
  const { user, signIn } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/queue";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [show, setShow] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [shakeKey, setShakeKey] = useState(0);
  const [hint, setHint] = useState(false);
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);

  if (user && phase === "idle") return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (phase !== "idle") return;
    setError("");
    setPhase("loading");
    try {
      await signIn(email, password, remember);
      setPhase("success");
      const r = btn.current?.getBoundingClientRect();
      setOrigin(r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : { x: innerWidth / 2, y: innerHeight / 2 });
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.setTimeout(() => nav(from, { replace: true, state: { arrived: true } }), reduce ? 150 : 1100);
    } catch (err) {
      setPhase("idle");
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      setShakeKey((k) => k + 1);
    }
  };

  const fillDemo = () => { setEmail(DEMO.email); setPassword(DEMO.password); setError(""); };
  const vars = origin ? ({ "--x": `${origin.x}px`, "--y": `${origin.y}px` } as CSSProperties) : undefined;

  return (
    <div className="relative flex min-h-full bg-page">
      <div className="app-backdrop" aria-hidden />
      <BrandPanel />

      <div className="relative z-10 flex min-h-full flex-1 flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <span className="lg:invisible"><Logo size={32} /></span>
          <ThemeToggle />
        </div>

        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">
          <div className="stagger">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-2 shadow-sm">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-good" /> Lead engine online
            </div>
            <h1 className="font-display text-[34px] font-extrabold leading-tight tracking-tight text-ink">Welcome back</h1>
            <p className="mt-2 text-sm text-ink-2">Sign in to your <Wordmark className="text-sm" /> workspace and pick up where your pipeline left off.</p>

            <button type="button" onClick={fillDemo}
              className="group mt-6 flex w-full items-center gap-3 rounded-2xl border border-dashed border-brand/40 bg-accent-soft/50 px-4 py-3 text-left transition hover:border-brand hover:bg-accent-soft">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface text-accent-ink shadow-sm transition group-hover:scale-105"><Icon name="zap" /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-ink">Use the demo account</span>
                <span className="block truncate text-xs text-ink-2">{DEMO.email} · {DEMO.password}</span>
              </span>
              <Icon name="arrowRight" className="text-accent-ink transition group-hover:translate-x-0.5" />
            </button>

            <div className="my-6 flex items-center gap-3 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-3"><span className="h-px flex-1 bg-[var(--c-line)]" />or sign in with email<span className="h-px flex-1 bg-[var(--c-line)]" /></div>

            <form key={shakeKey} onSubmit={submit} noValidate className={`space-y-4 ${shakeKey ? "shake" : ""}`}>
              <Field label="Work email" icon="mail" invalid={!!error && /email/i.test(error)}>
                <input type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com"
                  className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none" disabled={phase !== "idle"} />
              </Field>
              <Field label="Password" icon="lock" invalid={!!error && /password/i.test(error)}
                aside={<button type="button" onClick={() => setHint((h) => !h)} className="text-xs font-medium text-accent-ink hover:underline">Forgot password?</button>}>
                <input type={show ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password"
                  className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none" disabled={phase !== "idle"} />
                <button type="button" onClick={() => setShow((s) => !s)} className="text-ink-3 transition hover:text-ink" aria-label={show ? "Hide password" : "Show password"}>
                  <Icon name={show ? "eyeOff" : "eye"} />
                </button>
              </Field>
              {hint && <p className="pop rounded-xl bg-surface-2 px-3 py-2 text-xs text-ink-2">This is a demo workspace: any email with a password of 6+ characters signs you in.</p>}

              <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink-2">
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 rounded accent-[var(--c-accent)]" />
                Keep me signed in
              </label>

              {error && (
                <div role="alert" className="pop flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm text-critical-ink" style={{ borderColor: "color-mix(in srgb, var(--c-critical) 40%, transparent)", background: "color-mix(in srgb, var(--c-critical) 8%, transparent)" }}>
                  <Icon name="alert" className="mt-0.5 shrink-0" />{error}
                </div>
              )}

              <button ref={btn} type="submit" disabled={phase !== "idle"}
                className={`relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-2xl text-sm font-semibold text-white transition duration-300 active:scale-[0.98] ${phase === "success" ? "bg-good-ink shadow-[0_10px_24px_-10px_rgb(12_163_12/.8)]" : "btn-brand"}`}>
                {phase === "idle" && <>Sign in <Icon name="arrowRight" /></>}
                {phase === "loading" && <><span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white" style={{ animation: "spin 700ms linear infinite" }} />Signing in…</>}
                {phase === "success" && <span className="flex items-center gap-2" style={{ animation: "pop 240ms" }}><Icon name="check" />Cleared for takeoff</span>}
              </button>
            </form>
            <p className="mt-6 text-center text-xs text-ink-3">Protected workspace · Every score, stage and assignment is explained.</p>
          </div>
        </div>
      </div>

      {phase === "success" && origin && (
        <>
          <div className="takeoff-wipe" style={vars} aria-hidden />
          <div className="takeoff-plane" style={vars} aria-hidden><LogoMark size={64} /></div>
        </>
      )}
    </div>
  );
}

function Field({ label, icon, children, aside, invalid }: { label: string; icon: "mail" | "lock"; children: ReactNode; aside?: ReactNode; invalid?: boolean }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between"><span className="text-sm font-medium text-ink">{label}</span>{aside}</div>
      <label className={`group flex h-12 items-center gap-2.5 rounded-2xl border bg-surface px-4 shadow-sm transition focus-within:ring-4 ${invalid ? "border-critical focus-within:ring-critical/15" : "border-line focus-within:border-brand focus-within:ring-brand/15"}`} aria-label={label}>
        <Icon name={icon} className="shrink-0 text-ink-3 transition group-focus-within:text-accent-ink" />
        {children}
      </label>
    </div>
  );
}

/** Left half: brand gradient, a plane looping over live-looking product cards. */
function BrandPanel() {
  return (
    <div className="relative z-10 m-3 hidden w-[46%] max-w-[720px] overflow-hidden rounded-[28px] bg-gradient-to-br from-[#0f172a] via-[#1e3a8a] to-[#2563eb] p-10 text-white shadow-pop lg:flex lg:flex-col">
      <div className="login-orb left-[-10%] top-[-10%] h-72 w-72 bg-[#60a5fa]" />
      <div className="login-orb bottom-[-15%] right-[-10%] h-80 w-80 bg-[#3b82f6]" style={{ animationDelay: "-3s" }} />
      <div className="pointer-events-none absolute inset-0 opacity-[0.12]" style={{ backgroundImage: "linear-gradient(rgb(255 255 255 / .6) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / .6) 1px, transparent 1px)", backgroundSize: "44px 44px", maskImage: "radial-gradient(circle at 50% 40%, black, transparent 75%)" }} />

      <div className="relative flex items-center gap-2.5" style={{ animation: "rise 600ms both" }}>
        <LogoMark size={36} tone="white" />
        <span className="font-display text-xl font-extrabold tracking-tight">Lead<span className="text-[#93c5fd]">Pilot</span></span>
      </div>

      {/* contrail + looping plane */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 600 800" preserveAspectRatio="none" aria-hidden>
        <path d="M-20 640 C 140 560, 260 520, 340 380 S 520 160, 640 120" fill="none" stroke="rgb(147 197 253 / .45)" strokeWidth="2" strokeDasharray="3 10" />
      </svg>
      <div className="pointer-events-none absolute left-0 top-0" style={{ offsetPath: "path('M -20 640 C 140 560, 260 520, 340 380 S 520 160, 640 120')", offsetRotate: "auto 45deg", animation: "login-loop 9s cubic-bezier(.45,.05,.55,.95) infinite" } as CSSProperties} aria-hidden>
        <LogoMark size={44} tone="white" />
      </div>

      <div className="relative mt-auto">
        <div className="relative mb-10 h-[230px]">
          <GlassCard className="login-float absolute left-0 top-0 w-60" style={{ animationDelay: "0s" }} delay={200}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/65">New leads</div>
            <div className="mt-1 flex items-end justify-between">
              <span className="font-display text-3xl font-bold">104</span>
              <svg width="96" height="32" viewBox="0 0 96 32" aria-hidden><path d="M2 26 C 14 22, 18 12, 30 16 S 48 28, 58 16 S 80 4, 94 6" fill="none" stroke="#86efac" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="140" strokeDashoffset="140" style={{ animation: "dash 1.4s ease-out 700ms forwards" }} /></svg>
            </div>
            <div className="mt-1 text-xs text-white/70">Trend this month <span className="font-semibold text-[#86efac]">+14.8%</span></div>
          </GlassCard>
          <GlassCard className="login-float absolute right-0 top-16 w-72" style={{ animationDelay: "-2s" }} delay={380}>
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-[#93c5fd] to-[#3b82f6] text-xs font-bold">MC</span>
              <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold">Maya Chen</div><div className="truncate text-xs text-white/70">Northwind · requested a demo</div></div>
              <span className="rounded-md bg-white px-1.5 py-0.5 text-xs font-bold text-[#1d4ed8]">A 92</span>
            </div>
          </GlassCard>
          <GlassCard className="login-float absolute bottom-0 left-10 w-60" style={{ animationDelay: "-4s" }} delay={560}>
            <div className="flex items-center gap-2 text-sm"><span className="grid h-6 w-6 place-items-center rounded-full bg-[#86efac]/25 text-[#86efac]"><Icon name="check" size={13} /></span>Assigned to Ananya in 12s</div>
          </GlassCard>
        </div>
        <h2 className="font-display text-4xl font-extrabold leading-[1.1] tracking-tight" style={{ animation: "rise 700ms 300ms both" }}>More insights.<br /><span className="text-[#93c5fd]">More closed deals.</span></h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-white/75" style={{ animation: "rise 700ms 420ms both" }}>Every lead scored, staged, assigned and explained in real time, so your team always knows who to call next and why.</p>
      </div>
    </div>
  );
}

function GlassCard({ children, className = "", style, delay = 0 }: { children: ReactNode; className?: string; style?: CSSProperties; delay?: number }) {
  return (
    <div className={className} style={style}>
      <div className="rounded-2xl border border-white/20 bg-white/10 p-4 shadow-[0_20px_40px_-20px_rgb(0_0_0/.5)] backdrop-blur-xl" style={{ animation: `rise 700ms cubic-bezier(.2,.8,.2,1) ${delay}ms both` }}>
        {children}
      </div>
    </div>
  );
}
