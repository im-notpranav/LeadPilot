// Sign in (/login) and Create account (/signup) share one page so the brand panel and the form
// can slide past each other: sign in = brand left, form right; create account = form left, brand right.
import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type ReactNode, type RefObject } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AuthError, DEMO, MIN_PASSWORD, passwordStrength, useAuth } from "../lib/auth";
import { api, type FeedItem, type SimStatus } from "../lib/api";
import { human, num, signed } from "../lib/format";
import { Logo, LogoMark } from "../components/Logo";
import { Icon, type IconName } from "../components/icons";
import { ThemeToggle } from "../components/ui";

type Mode = "signin" | "signup";
type Busy = "idle" | "loading" | "success";

export default function Login() {
  const { user } = useAuth();
  const loc = useLocation();
  const nav = useNavigate();
  const mode: Mode = loc.pathname.startsWith("/signup") ? "signup" : "signin";
  const from = (loc.state as { from?: string } | null)?.from ?? "/queue";
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);

  // Already signed in (and not mid-transition): go straight to the app.
  if (user && !origin) return <Navigate to={from} replace />;

  const switchTo = (m: Mode) => nav(m === "signup" ? "/signup" : "/login", { replace: true, state: loc.state });
  const takeoff = (btn: HTMLElement | null, message: string) => {
    const r = btn?.getBoundingClientRect();
    setOrigin(r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : { x: innerWidth / 2, y: innerHeight / 2 });
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.setTimeout(() => nav(from, { replace: true, state: { arrived: message } }), reduce ? 150 : 1100);
  };
  const vars = origin ? ({ "--x": `${origin.x}px`, "--y": `${origin.y}px` } as CSSProperties) : undefined;

  return (
    <div className="auth relative min-h-full bg-page" data-mode={mode}>
      <div className="app-backdrop" aria-hidden />
      <div className="auth-brand relative z-10 hidden p-3 lg:block"><BrandPanel mode={mode} /></div>

      <div className="auth-form relative z-10 flex min-h-full flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <span className="lg:invisible"><Logo size={32} /></span>
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">
          <div key={mode} className="auth-swap">
            {mode === "signin" ? <SignInForm onSwitch={() => switchTo("signup")} onDone={takeoff} /> : <SignUpForm onSwitch={() => switchTo("signin")} onDone={takeoff} />}
          </div>
          <p className="mt-8 text-center text-xs leading-relaxed text-ink-3">
            Accounts are stored in this browser. The LeadPilot API does not have authentication yet.
          </p>
        </div>
      </div>

      {origin && (
        <>
          <div className="takeoff-wipe" style={vars} aria-hidden />
          <div className="takeoff-plane" style={vars} aria-hidden><LogoMark size={64} /></div>
        </>
      )}
    </div>
  );
}

/* ---------------- forms ---------------- */

function useSubmit(onDone: (btn: HTMLElement | null, message: string) => void) {
  const [busy, setBusy] = useState<Busy>("idle");
  const [error, setError] = useState<AuthError | null>(null);
  const [shake, setShake] = useState(0);
  const btn = useRef<HTMLButtonElement>(null);
  const run = async (fn: () => Promise<string | void>, finish = true) => {
    if (busy !== "idle") return;
    setError(null);
    setBusy("loading");
    try {
      const message = await fn();
      if (!finish) { setBusy("idle"); return; }
      setBusy("success");
      onDone(btn.current, message || "");
    } catch (e) {
      setBusy("idle");
      setError(e instanceof AuthError ? e : new AuthError(e instanceof Error ? e.message : "Something went wrong."));
      setShake((n) => n + 1);
    }
  };
  return { busy, error, setError, shake, btn, run };
}

function SignInForm({ onSwitch, onDone }: { onSwitch: () => void; onDone: (btn: HTMLElement | null, message: string) => void }) {
  const { signIn, resetPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [notice, setNotice] = useState("");
  const { busy, error, setError, shake, btn, run } = useSubmit(onDone);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (resetting) {
      run(async () => {
        await resetPassword(email, password);
        setResetting(false); setPassword(""); setNotice("Password updated. Sign in with the new one.");
      }, false);
    } else {
      setNotice("");
      run(async () => `Signed in as ${(await signIn(email, password, remember)).email}`);
    }
  };

  return (
    <>
      <h1 className="font-display text-[32px] font-extrabold leading-tight tracking-tight text-ink">{resetting ? "Reset password" : "Sign in"}</h1>
      <p className="mt-2 text-sm text-ink-2">
        {resetting ? <>Set a new password for an account in this browser. <button type="button" onClick={() => { setResetting(false); setError(null); }} className="font-semibold text-accent-ink hover:underline">Back to sign in</button></>
          : <>New to LeadPilot? <button type="button" onClick={onSwitch} className="font-semibold text-accent-ink hover:underline">Create an account</button></>}
      </p>

      {!resetting && (
        <button type="button" onClick={() => { setEmail(DEMO.email); setPassword(DEMO.password); setError(null); }}
          className="group mt-6 flex w-full items-center gap-3 rounded-2xl border border-dashed border-brand/40 bg-accent-soft/50 px-4 py-3 text-left transition hover:border-brand hover:bg-accent-soft">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface text-accent-ink shadow-sm"><Icon name="user" /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-ink">Fill in the demo account</span>
            <span className="block truncate text-xs text-ink-2">{DEMO.email} · {DEMO.password}</span>
          </span>
          <Icon name="arrowRight" className="text-accent-ink transition group-hover:translate-x-0.5" />
        </button>
      )}

      <form key={shake} onSubmit={submit} noValidate className={`mt-6 space-y-4 ${shake ? "shake" : ""}`}>
        <Field label="Email" icon="mail" invalid={error?.field === "email"}>
          <input type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className="field-input" disabled={busy !== "idle"} />
        </Field>
        <Field label={resetting ? "New password" : "Password"} icon="lock" invalid={error?.field === "password"}
          aside={!resetting && <button type="button" onClick={() => { setResetting(true); setError(null); setNotice(""); setPassword(""); }} className="text-xs font-medium text-accent-ink hover:underline">Forgot password?</button>}>
          <PasswordInput value={password} onChange={setPassword} autoComplete={resetting ? "new-password" : "current-password"} placeholder={resetting ? `At least ${MIN_PASSWORD} characters` : "Your password"} disabled={busy !== "idle"} />
        </Field>
        {!resetting && (
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 rounded accent-[var(--c-accent)]" />
            Keep me signed in on this device
          </label>
        )}
        {notice && <Notice tone="good">{notice}</Notice>}
        {error && <Notice tone="bad">{error.message}{error.message.includes("Create one") && <> <button type="button" onClick={onSwitch} className="font-semibold underline">Create account</button></>}</Notice>}
        <SubmitButton btn={btn} busy={busy} idle={resetting ? "Set new password" : "Sign in"} loading={resetting ? "Saving…" : "Signing in…"} done="Signed in" />
      </form>
    </>
  );
}

function SignUpForm({ onSwitch, onDone }: { onSwitch: () => void; onDone: (btn: HTMLElement | null, message: string) => void }) {
  const { signUp } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, shake, btn, run } = useSubmit(onDone);
  const strength = passwordStrength(password);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => `Account created. Signed in as ${(await signUp({ name, email, company, password }, true)).email}`);
  };

  return (
    <>
      <h1 className="font-display text-[32px] font-extrabold leading-tight tracking-tight text-ink">Create account</h1>
      <p className="mt-2 text-sm text-ink-2">Already have one? <button type="button" onClick={onSwitch} className="font-semibold text-accent-ink hover:underline">Sign in</button></p>

      <form key={shake} onSubmit={submit} noValidate className={`mt-6 space-y-4 ${shake ? "shake" : ""}`}>
        <Field label="Full name" icon="user" invalid={error?.field === "name"}>
          <input autoComplete="name" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Priya Nair" className="field-input" disabled={busy !== "idle"} />
        </Field>
        <Field label="Work email" icon="mail" invalid={error?.field === "email"}>
          <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className="field-input" disabled={busy !== "idle"} />
        </Field>
        <Field label="Company" icon="building" aside={<span className="text-xs text-ink-3">Optional</span>}>
          <input autoComplete="organization" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme Inc." className="field-input" disabled={busy !== "idle"} />
        </Field>
        <Field label="Password" icon="lock" invalid={error?.field === "password"}>
          <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" placeholder={`At least ${MIN_PASSWORD} characters`} disabled={busy !== "idle"} />
        </Field>
        <div className="-mt-1 flex items-center gap-2" aria-live="polite">
          <div className="flex flex-1 gap-1" aria-hidden>
            {[1, 2, 3, 4].map((i) => <span key={i} className="h-1 flex-1 rounded-full transition-colors duration-300" style={{ background: i <= strength ? ["", "var(--c-critical)", "var(--c-warn)", "var(--c-brand)", "var(--c-good)"][strength] : "var(--c-line)" }} />)}
          </div>
          <span className="w-24 text-right text-xs text-ink-3">{password ? ["Too short", "Weak", "Fair", "Good", "Strong"][strength] : `${MIN_PASSWORD}+ characters`}</span>
        </div>
        {error && <Notice tone="bad">{error.message}{error.message.includes("Sign in instead") && <> <button type="button" onClick={onSwitch} className="font-semibold underline">Sign in</button></>}</Notice>}
        <SubmitButton btn={btn} busy={busy} idle="Create account" loading="Creating account…" done="Account created" />
      </form>
    </>
  );
}

/* ---------------- form pieces ---------------- */

function Field({ label, icon, children, aside, invalid }: { label: string; icon: IconName; children: ReactNode; aside?: ReactNode; invalid?: boolean }) {
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

function PasswordInput({ value, onChange, autoComplete, placeholder, disabled }: { value: string; onChange: (v: string) => void; autoComplete: string; placeholder: string; disabled?: boolean }) {
  const [show, setShow] = useState(false);
  return (
    <>
      <input type={show ? "text" : "password"} autoComplete={autoComplete} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="field-input" disabled={disabled} />
      <button type="button" onClick={() => setShow((s) => !s)} className="text-ink-3 transition hover:text-ink" aria-label={show ? "Hide password" : "Show password"}><Icon name={show ? "eyeOff" : "eye"} /></button>
    </>
  );
}

function Notice({ tone, children }: { tone: "good" | "bad"; children: ReactNode }) {
  const c = tone === "bad" ? "var(--c-critical)" : "var(--c-good)";
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={`pop flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm ${tone === "bad" ? "text-critical-ink" : "text-good-ink"}`}
      style={{ borderColor: `color-mix(in srgb, ${c} 40%, transparent)`, background: `color-mix(in srgb, ${c} 8%, transparent)` }}>
      <Icon name={tone === "bad" ? "alert" : "check"} className="mt-0.5 shrink-0" /><span>{children}</span>
    </div>
  );
}

function SubmitButton({ btn, busy, idle, loading, done }: { btn: RefObject<HTMLButtonElement>; busy: Busy; idle: string; loading: string; done: string }) {
  return (
    <button ref={btn} type="submit" disabled={busy !== "idle"}
      className={`relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-2xl text-sm font-semibold text-white transition duration-300 active:scale-[0.98] ${busy === "success" ? "bg-good-ink" : "btn-brand"}`}>
      {busy === "idle" && <>{idle} <Icon name="arrowRight" /></>}
      {busy === "loading" && <><span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white" style={{ animation: "spin 700ms linear infinite" }} />{loading}</>}
      {busy === "success" && <span className="flex items-center gap-2" style={{ animation: "pop 240ms" }}><Icon name="check" />{done}</span>}
    </button>
  );
}

/* ---------------- brand panel: live numbers from the running engine ---------------- */

function BrandPanel({ mode }: { mode: Mode }) {
  const status = useQuery({ queryKey: ["auth", "status"], queryFn: () => api.get<SimStatus>("/api/sim/status"), refetchInterval: 4000, retry: false });
  const feed = useQuery({ queryKey: ["auth", "feed"], queryFn: () => api.get<{ items: FeedItem[] }>("/api/feed?limit=4"), refetchInterval: 4000, retry: false });
  const s = status.data;
  const state = status.isError ? "offline" : !s ? "connecting" : s.status === "resetting" ? "building" : s.clock.paused ? "paused" : "live";
  const label = { offline: "API unreachable", connecting: "Connecting…", building: "Generating history", paused: "Simulation paused", live: "Simulation running" }[state];

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-[28px] bg-gradient-to-br from-[#0f172a] via-[#1e3a8a] to-[#2563eb] p-10 text-white shadow-pop">
      <div className="login-orb left-[-10%] top-[-10%] h-72 w-72 bg-[#60a5fa]" />
      <div className="login-orb bottom-[-15%] right-[-10%] h-80 w-80 bg-[#3b82f6]" style={{ animationDelay: "-3s" }} />
      <div className="pointer-events-none absolute inset-0 opacity-[0.12]" style={{ backgroundImage: "linear-gradient(rgb(255 255 255 / .6) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / .6) 1px, transparent 1px)", backgroundSize: "44px 44px", maskImage: "radial-gradient(circle at 50% 40%, black, transparent 75%)" }} />
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 600 800" preserveAspectRatio="none" aria-hidden>
        <path d="M-20 640 C 140 560, 260 520, 340 380 S 520 160, 640 120" fill="none" stroke="rgb(147 197 253 / .45)" strokeWidth="2" strokeDasharray="3 10" />
      </svg>
      <div className="pointer-events-none absolute left-0 top-0" style={{ offsetPath: "path('M -20 640 C 140 560, 260 520, 340 380 S 520 160, 640 120')", offsetRotate: "auto 45deg", animation: "login-loop 9s cubic-bezier(.45,.05,.55,.95) infinite" } as CSSProperties} aria-hidden>
        <LogoMark size={44} tone="white" />
      </div>

      <div className="relative flex items-center justify-between">
        <span className="flex items-center gap-2.5"><LogoMark size={36} tone="white" /><span className="font-display text-xl font-extrabold tracking-tight">Lead<span className="text-[#93c5fd]">Pilot</span></span></span>
        <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium backdrop-blur">
          <span className={`h-2 w-2 rounded-full ${state === "live" ? "live-dot bg-[#86efac]" : state === "offline" ? "bg-[#fca5a5]" : "bg-[#fde68a]"}`} />{label}
        </span>
      </div>

      <div className="relative mt-auto">
        <div className="mb-8 grid grid-cols-2 gap-3">
          <GlassStat label="Open leads" value={s ? num(s.open_leads) : "–"} sub={s ? `${num(s.stalled)} stalled · ${num(s.quarantined)} quarantined` : " "} delay={150} />
          <GlassStat label="Deals closed" value={s ? `${num(s.won)} won` : "–"} sub={s ? `${num(s.lost)} lost · ${num(s.historical_deals)} in history` : " "} delay={250} />
          <div className="col-span-2 rounded-2xl border border-white/20 bg-white/10 p-4 shadow-[0_20px_40px_-20px_rgb(0_0_0/.5)] backdrop-blur-xl" style={{ animation: "rise 700ms cubic-bezier(.2,.8,.2,1) 350ms both" }}>
            <div className="mb-2 flex items-baseline justify-between text-xs text-white/70"><span>Latest events</span><span className="tabular">{s ? `${num(s.events)} processed` : ""}</span></div>
            <ul className="space-y-1.5">
              {(feed.data?.items ?? []).slice(0, 4).map((f) => (
                <li key={f.event_id} className="flex items-center gap-2.5 text-sm" style={{ animation: "rise 400ms both" }}>
                  {f.grade ? <span className="w-12 shrink-0 rounded-md bg-white px-1.5 py-0.5 text-center text-[11px] font-bold tabular text-[#1d4ed8]">{f.grade} {Math.round(f.score ?? 0)}</span> : <span className="w-12 shrink-0" />}
                  <span className="min-w-0 flex-1 truncate"><span className="font-medium">{f.name ?? f.lead_id}</span> <span className="text-white/65">· {human(f.type)}</span></span>
                  <span className={`shrink-0 text-xs tabular ${f.delta >= 0.05 ? "text-[#86efac]" : f.delta <= -0.05 ? "text-[#fca5a5]" : "text-white/60"}`}>{Math.abs(f.delta) < 0.05 ? "±0" : signed(f.delta)}</span>
                </li>
              ))}
              {!feed.data?.items.length && <li className="text-sm text-white/60">{state === "offline" ? "Start the backend to see live events here." : "Waiting for the first events…"}</li>}
            </ul>
          </div>
        </div>
        <h2 key={mode} className="font-display text-4xl font-extrabold leading-[1.1] tracking-tight" style={{ animation: "rise 600ms both" }}>
          Smarter leads.<br /><span className="text-[#93c5fd]">Bigger deals.</span>
        </h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-white/75">
          {mode === "signin"
            ? "Your queue is ordered by score, deal value and SLA risk. Open any lead to see why its score moved."
            : "Each lead is scored on every event, moved through the pipeline on evidence and routed to the rep most likely to close it."}
        </p>
      </div>
    </div>
  );
}

function GlassStat({ label, value, sub, delay }: { label: string; value: string; sub: string; delay: number }) {
  const [flash, setFlash] = useState(false);
  const prev = useRef(value);
  useEffect(() => { if (prev.current !== value) { prev.current = value; setFlash(true); const t = setTimeout(() => setFlash(false), 600); return () => clearTimeout(t); } }, [value]);
  return (
    <div className="rounded-2xl border border-white/20 bg-white/10 p-4 shadow-[0_20px_40px_-20px_rgb(0_0_0/.5)] backdrop-blur-xl" style={{ animation: `rise 700ms cubic-bezier(.2,.8,.2,1) ${delay}ms both` }}>
      <div className="text-xs text-white/70">{label}</div>
      <div className={`mt-1 font-display text-3xl font-bold tabular transition-colors duration-500 ${flash ? "text-[#bfdbfe]" : ""}`}>{value}</div>
      <div className="mt-0.5 truncate text-xs text-white/65">{sub}</div>
    </div>
  );
}

