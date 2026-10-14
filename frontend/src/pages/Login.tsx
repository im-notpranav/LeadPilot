// Everything shown before the dashboard: sign in / create account / reset, waiting for approval, and setup problems.
// Sign in and Create account share one page so the brand panel and the form slide past each other:
// sign in = brand left, form right; create account = form left, brand right.
import { useState, type FormEvent, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MIN_PASSWORD, markArrival, passwordStrength, takeArrival, useAuth } from "../lib/auth";
import { Logo, LogoMark } from "../components/Logo";
import { Icon, type IconName } from "../components/icons";
import { ThemeToggle } from "../components/ui";

type Mode = "signin" | "signup";

export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  switch (auth.status) {
    case "off":
      return auth.me ? <>{children}</> : <Waiting text="Connecting…" />;
    case "signed-in":
      if (!auth.me) return <Waiting text="Loading your workspace…" />;
      return auth.me.role === "pending" ? <Pending /> : <>{children}</>;
    case "signed-out":
      return <Login />;
    case "recovery":
      return <NewPassword />;
    case "misconfigured":
      return (
        <AuthLayout>
          <Heading title="Sign-in is not set up yet" />
          <p className="mt-4 text-sm text-ink-2">
            The server requires a login, but it does not have the Supabase anon (publishable) key. Add
            <code className="mx-1 rounded bg-surface-2 px-1 py-0.5 text-xs">SUPABASE_ANON_KEY</code>
            to <code className="mx-1 rounded bg-surface-2 px-1 py-0.5 text-xs">backend/.env</code> and restart it.
          </p>
        </AuthLayout>
      );
    case "error":
      return <AuthLayout><Heading title="Can't reach LeadPilot" subtitle={auth.error} /></AuthLayout>;
    default:
      return <Waiting text="Loading…" />;
  }
}

function Waiting({ text }: { text: string }) {
  return <div className="flex min-h-full items-center justify-center bg-page text-sm text-ink-3">{text}</div>;
}

/** Brand panel and form column; `mode` decides which side each sits on (md and up). */
function AuthLayout({ mode = "signin", children }: { mode?: Mode; children: ReactNode }) {
  return (
    <div className="auth relative min-h-full bg-page" data-mode={mode}>
      <div className="app-backdrop" aria-hidden />
      <div className="auth-brand relative z-10 hidden p-3 md:block"><BrandPanel /></div>
      <div className="auth-form relative z-10 flex min-h-full flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <span className="md:invisible"><Logo size={32} /></span>
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">{children}</div>
      </div>
    </div>
  );
}

function Heading({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <>
      <h1 className="font-display text-[32px] font-extrabold leading-tight tracking-tight text-ink">{title}</h1>
      {subtitle && <p className="mt-2 text-sm text-ink-2">{subtitle}</p>}
    </>
  );
}

function Login() {
  const loc = useLocation();
  const [mode, setMode] = useState<Mode>(loc.pathname.startsWith("/signup") ? "signup" : "signin");
  const [info, setInfo] = useState<string | null>(null);
  const switchTo = (m: Mode) => { setMode(m); setInfo(null); };
  return (
    <AuthLayout mode={mode}>
      <ModeSwitch mode={mode} onChange={switchTo} />
      <div key={mode} className="auth-swap mt-8">
        {mode === "signin"
          ? <SignInForm info={info} />
          : <SignUpForm onConfirm={(msg) => { setInfo(msg); setMode("signin"); }} />}
      </div>
      <p className="mt-8 text-center text-xs leading-relaxed text-ink-3">Protected workspace · Every score, stage and assignment is explained.</p>
    </AuthLayout>
  );
}

/* ---------------- forms ---------------- */

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(0);
  const run = async (fn: () => Promise<string | null>) => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const err = await fn();
      if (err) { setError(err); setShake((n) => n + 1); }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong."); setShake((n) => n + 1);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, shake, run };
}

function SignInForm({ info }: { info: string | null }) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [resetting, setResetting] = useState(false);
  const [notice, setNotice] = useState<string | null>(info);
  const { busy, error, setError, shake, run } = useSubmit();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setNotice(null);
    if (resetting) {
      run(async () => {
        const err = await auth.resetPassword(email.trim());
        if (!err) { setResetting(false); setNotice("If that email has an account, a reset link is on its way."); }
        return err;
      });
    } else {
      run(async () => {
        markArrival();   // the session can land before signIn resolves, so flag the shell's entrance up front
        const err = await auth.signIn(email.trim(), password);
        if (err) takeArrival();
        return err;
      });
    }
  };

  return (
    <>
      <Heading title={resetting ? "Reset your password" : "Sign in"}
        subtitle={resetting
          ? <>We'll email you a link to choose a new one. <button type="button" onClick={() => { setResetting(false); setError(null); }} className="font-semibold text-accent-ink hover:underline">Back to sign in</button></>
          : "Sign in to your workspace and pick up where your pipeline left off."} />
      <form key={shake} onSubmit={submit} className={`mt-6 space-y-4 ${shake ? "shake" : ""}`}>
        {notice && <Notice tone="good">{notice}</Notice>}
        <Field label="Work email" icon="mail" invalid={!!error && /email/i.test(error)}>
          <input type="email" required autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className="field-input" disabled={busy} />
        </Field>
        {!resetting && (
          <Field label="Password" icon="lock" invalid={!!error && /password/i.test(error)}
            aside={<button type="button" onClick={() => { setResetting(true); setError(null); setNotice(null); }} className="text-xs font-medium text-accent-ink hover:underline">Forgot password?</button>}>
            <PasswordInput value={password} onChange={setPassword} autoComplete="current-password" placeholder="Your password" disabled={busy} />
          </Field>
        )}
        {error && <Notice tone="bad">{error}</Notice>}
        <SubmitButton busy={busy}>{resetting ? "Send reset link" : "Sign in"}</SubmitButton>
      </form>
    </>
  );
}

function SignUpForm({ onConfirm }: { onConfirm: (message: string) => void }) {
  const auth = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, shake, run } = useSubmit();
  const strength = passwordStrength(password);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      if (name.trim().length < 2) return "Enter your full name.";
      if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters for the password.`;
      const r = await auth.signUp(email.trim(), password, name.trim().replace(/\s+/g, " "));
      if (!r.error && r.confirm) onConfirm("Check your inbox and click the confirmation link, then sign in here.");
      return r.error;
    });
  };

  return (
    <>
      <Heading title="Create account" subtitle="An admin approves new accounts before they can see any leads." />
      <form key={shake} onSubmit={submit} className={`mt-6 space-y-4 ${shake ? "shake" : ""}`}>
        <Field label="Full name" icon="user" invalid={!!error && /name/i.test(error)}>
          <input required autoComplete="name" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Priya Nair" className="field-input" disabled={busy} />
        </Field>
        <Field label="Work email" icon="mail" invalid={!!error && /email/i.test(error)}>
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className="field-input" disabled={busy} />
        </Field>
        <Field label="Password" icon="lock" invalid={!!error && /password/i.test(error)}>
          <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" placeholder={`At least ${MIN_PASSWORD} characters`} disabled={busy} />
        </Field>
        <StrengthMeter password={password} strength={strength} />
        {error && <Notice tone="bad">{error}</Notice>}
        <SubmitButton busy={busy}>Create account</SubmitButton>
      </form>
    </>
  );
}

function NewPassword() {
  const auth = useAuth();
  const [password, setPassword] = useState("");
  const { busy, error, shake, run } = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => (password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters for the password.` : auth.setNewPassword(password)));
  };
  return (
    <AuthLayout>
      <Heading title="Choose a new password" />
      <form key={shake} onSubmit={submit} className={`mt-6 space-y-4 ${shake ? "shake" : ""}`}>
        <Field label="New password" icon="lock" invalid={!!error}>
          <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" placeholder={`At least ${MIN_PASSWORD} characters`} disabled={busy} />
        </Field>
        <StrengthMeter password={password} strength={passwordStrength(password)} />
        {error && <Notice tone="bad">{error}</Notice>}
        <SubmitButton busy={busy}>Save password</SubmitButton>
      </form>
    </AuthLayout>
  );
}

function Pending() {
  const auth = useAuth();
  return (
    <AuthLayout>
      <Heading title="Waiting for access" subtitle={auth.me?.email ?? undefined} />
      <p className="mt-4 text-sm text-ink-2">
        Your account is set up. An admin needs to give you a role (rep, manager or admin) before you can see any leads.
        This page updates when you check again.
      </p>
      <div className="mt-6 flex gap-2">
        <button onClick={() => auth.refreshMe()} className="btn-brand h-11 flex-1 rounded-2xl text-sm font-semibold text-white">Check again</button>
        <button onClick={() => auth.signOut()} className="h-11 flex-1 rounded-2xl border border-line bg-surface text-sm font-medium text-ink shadow-sm hover:bg-surface-2">Sign out</button>
      </div>
    </AuthLayout>
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
      <input type={show ? "text" : "password"} required autoComplete={autoComplete} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="field-input" disabled={disabled} />
      <button type="button" onClick={() => setShow((s) => !s)} className="text-ink-3 transition hover:text-ink" aria-label={show ? "Hide password" : "Show password"}><Icon name={show ? "eyeOff" : "eye"} /></button>
    </>
  );
}

function StrengthMeter({ password, strength }: { password: string; strength: number }) {
  return (
    <div className="-mt-1 flex items-center gap-2" aria-live="polite">
      <div className="flex flex-1 gap-1" aria-hidden>
        {[1, 2, 3, 4].map((i) => <span key={i} className="h-1 flex-1 rounded-full transition-colors duration-300" style={{ background: i <= strength ? ["", "var(--c-critical)", "var(--c-warn)", "var(--c-brand)", "var(--c-good)"][strength] : "var(--c-line)" }} />)}
      </div>
      <span className="w-24 text-right text-xs text-ink-3">{password ? ["Too short", "Weak", "Fair", "Good", "Strong"][strength] : `${MIN_PASSWORD}+ characters`}</span>
    </div>
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

function SubmitButton({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button type="submit" disabled={busy}
      className="btn-brand relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-2xl text-sm font-semibold text-white transition active:scale-[0.98] disabled:opacity-70">
      {busy
        ? <><span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white" style={{ animation: "spin 700ms linear infinite" }} />Please wait…</>
        : <>{children} <Icon name="arrowRight" /></>}
    </button>
  );
}

function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div role="tablist" aria-label="Sign in or create account" className="relative grid grid-cols-2 rounded-2xl border border-line bg-surface-2 p-1">
      <span aria-hidden className="absolute bottom-1 top-1 w-[calc(50%-4px)] rounded-xl bg-surface shadow-sm ring-1 ring-line transition-transform duration-200 ease-out"
        style={{ transform: mode === "signup" ? "translateX(100%)" : "translateX(0)", left: 4 }} />
      {(["signin", "signup"] as Mode[]).map((m) => (
        <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => onChange(m)}
          className={`relative z-10 h-10 rounded-xl text-sm font-semibold transition-colors ${mode === m ? "text-ink" : "text-ink-3 hover:text-ink"}`}>
          {m === "signin" ? "Sign in" : "Create account"}
        </button>
      ))}
    </div>
  );
}

/* ---------------- brand panel: the logo, large, with a status line from the public health check ---------------- */

type Health = { ok: boolean; status: string; mode: "live" | "demo" | null };

function BrandPanel() {
  const health = useQuery({ queryKey: ["auth", "health"], queryFn: async () => {
    const r = await fetch("/api/health");
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()) as Health;
  }, refetchInterval: 5000, retry: false });
  const h = health.data;
  const state = health.isError ? "offline" : !h ? "connecting" : h.status === "resetting" || h.status === "starting" ? "building" : "online";
  const label = {
    offline: "API not reachable", connecting: "Connecting…",
    building: h?.mode === "live" ? "Rebuilding from the event log" : "Generating history",
    online: h?.mode === "live" ? "Live engine running" : "Simulation running",
  }[state];

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
        <div className="mt-6 font-display text-5xl font-extrabold tracking-tight lg:text-6xl">
          Lead<span className="text-[#93c5fd]">Pilot</span>
        </div>
        <div className="mt-3 text-lg font-medium text-white/80 lg:text-xl">
          Smarter Leads. <span className="text-white">Bigger Deals.</span>
        </div>
      </div>

      <div className="relative flex flex-wrap items-center justify-center gap-x-4 gap-y-1 rounded-2xl border border-white/15 bg-white/10 px-4 py-2.5 text-xs text-white/80">
        <span className="inline-flex items-center gap-2 font-medium text-white">
          <span className={`h-2 w-2 rounded-full ${state === "online" ? "live-dot bg-[#86efac]" : state === "offline" ? "bg-[#fca5a5]" : "bg-[#fde68a]"}`} />{label}
        </span>
        {state === "offline" && <span>Start it with <code className="rounded bg-white/15 px-1">python scripts/dev.py</code></span>}
      </div>
    </div>
  );
}
