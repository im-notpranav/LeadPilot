// Sign in (/login) and Create account (/signup) share one page so the brand panel and the form
// can slide past each other: sign in = brand left, form right; create account = form left, brand right.
import { useRef, useState, type CSSProperties, type FormEvent, type ReactNode, type RefObject } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AuthError, DEMO, MIN_PASSWORD, passwordStrength, useAuth } from "../lib/auth";
import { api, type SimStatus } from "../lib/api";
import { num } from "../lib/format";
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
    window.setTimeout(() => nav(from, { replace: true, state: { arrived: message } }), reduce ? 0 : 340);
  };
  const vars = origin ? ({ "--x": `${origin.x}px`, "--y": `${origin.y}px` } as CSSProperties) : undefined;

  return (
    <div className="auth relative min-h-full bg-page" data-mode={mode}>
      <div className="app-backdrop" aria-hidden />
      <div className="auth-brand relative z-10 hidden p-3 md:block"><BrandPanel /></div>

      <div className="auth-form relative z-10 flex min-h-full flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <span className="md:invisible"><Logo size={32} /></span>
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">
          <ModeSwitch mode={mode} onChange={switchTo} />
          <div key={mode} className="auth-swap mt-8">
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
          : <>Demo login: <button type="button" onClick={() => { setEmail(DEMO.email); setPassword(DEMO.password); setError(null); }} className="font-semibold text-accent-ink hover:underline" title="Fill in the demo account">{DEMO.email} / {DEMO.password}</button></>}
      </p>


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
      <p className="mt-2 text-sm text-ink-2">The account is saved in this browser. You can sign in with it straight away.</p>

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
      className={`relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-2xl text-sm font-semibold text-white transition active:scale-[0.98] ${busy === "success" ? "bg-good-ink" : "btn-brand"}`}>
      {busy === "idle" && <>{idle} <Icon name="arrowRight" /></>}
      {busy === "loading" && <><span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white" style={{ animation: "spin 700ms linear infinite" }} />{loading}</>}
      {busy === "success" && <span className="flex items-center gap-2" style={{ animation: "pop 140ms" }}><Icon name="check" />{done}</span>}
    </button>
  );
}

/* ---------------- mode switch ---------------- */

function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div role="tablist" aria-label="Sign in or create account" className="relative grid grid-cols-2 rounded-2xl border border-line bg-surface-2 p-1">
      <span aria-hidden className="absolute bottom-1 top-1 w-[calc(50%-4px)] rounded-xl bg-surface shadow-sm ring-1 ring-line transition-transform duration-200 ease-out"
        style={{ transform: mode === "signup" ? "translateX(calc(100% + 0px))" : "translateX(0)", left: 4 }} />
      {(["signin", "signup"] as Mode[]).map((m) => (
        <button key={m} role="tab" aria-selected={mode === m} onClick={() => onChange(m)}
          className={`relative z-10 h-10 rounded-xl text-sm font-semibold transition-colors ${mode === m ? "text-ink" : "text-ink-3 hover:text-ink"}`}>
          {m === "signin" ? "Sign in" : "Create account"}
        </button>
      ))}
    </div>
  );
}

/* ---------------- brand panel: the logo, large, with a live status line ---------------- */

function BrandPanel() {
  const status = useQuery({ queryKey: ["auth", "status"], queryFn: () => api.get<SimStatus>("/api/sim/status"), refetchInterval: 5000, retry: false });
  const s = status.data;
  const state = status.isError ? "offline" : !s ? "connecting" : s.status === "resetting" ? "building" : s.clock.paused ? "paused" : "live";
  const label = { offline: "API not reachable", connecting: "Connecting…", building: "Generating history", paused: "Simulation paused", live: "Simulation running" }[state];

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-[28px] bg-gradient-to-br from-[#0f172a] via-[#1e3a8a] to-[#2563eb] p-8 text-white shadow-pop lg:p-10">
      <div className="login-orb left-[-18%] top-[-18%] h-96 w-96" style={{ background: "radial-gradient(closest-side, #60a5fa, transparent)" }} />
      <div className="login-orb bottom-[-22%] right-[-18%] h-[26rem] w-[26rem]" style={{ background: "radial-gradient(closest-side, #3b82f6, transparent)" }} />
      <div className="pointer-events-none absolute inset-0 opacity-[0.12]" style={{ backgroundImage: "linear-gradient(rgb(255 255 255 / .6) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / .6) 1px, transparent 1px)", backgroundSize: "44px 44px", maskImage: "radial-gradient(circle at 50% 45%, black, transparent 75%)" }} />
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 600 800" preserveAspectRatio="none" aria-hidden>
        <path d="M-20 700 C 140 640, 220 600, 300 470 S 520 160, 640 120" fill="none" stroke="rgb(147 197 253 / .4)" strokeWidth="2" strokeDasharray="3 10" />
      </svg>

      {/* stacked logo, as on the brand sheet */}
      <div className="relative m-auto flex flex-col items-center text-center">
        <div className="relative">
          <div className="absolute inset-0 -z-10 scale-[2]" style={{ background: "radial-gradient(closest-side, rgb(96 165 250 / .35), transparent)" }} aria-hidden />
          <LogoMark size={148} tone="white" className="drop-shadow-[0_20px_30px_rgb(15_23_42/.45)]" />
        </div>
        <div className="mt-6 font-display text-5xl font-extrabold tracking-tight lg:text-6xl" >
          Lead<span className="text-[#93c5fd]">Pilot</span>
        </div>
        <div className="mt-3 text-lg font-medium text-white/80 lg:text-xl" >
          Smarter Leads. <span className="text-white">Bigger Deals.</span>
        </div>
      </div>

      <div className="relative flex flex-wrap items-center justify-center gap-x-4 gap-y-1 rounded-2xl border border-white/15 bg-white/10 px-4 py-2.5 text-xs text-white/80">
        <span className="inline-flex items-center gap-2 font-medium text-white">
          <span className={`h-2 w-2 rounded-full ${state === "live" ? "live-dot bg-[#86efac]" : state === "offline" ? "bg-[#fca5a5]" : "bg-[#fde68a]"}`} />{label}
        </span>
        {s && <span className="tabular">{num(s.open_leads)} open leads</span>}
        {s && <span className="tabular">{num(s.events)} events processed</span>}
        {state === "offline" && <span>Start it with <code className="rounded bg-white/15 px-1">python scripts/dev.py</code></span>}
      </div>
    </div>
  );
}
