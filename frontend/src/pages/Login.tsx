// Everything shown before the dashboard: sign in / sign up / reset, waiting for approval, and setup problems.
import { useId, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { markArrival, takeArrival, useAuth } from "../lib/auth";
import { Logo, LogoMark, Wordmark } from "../components/Logo";
import { Icon, type IconName } from "../components/icons";
import { ThemeToggle } from "../components/ui";

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
        <AuthLayout title="Sign-in is not set up yet">
          <p className="text-sm text-ink-2">
            The server requires a login, but it does not have the Supabase anon (publishable) key. Add
            <code className="mx-1 rounded bg-surface-2 px-1 py-0.5 text-xs">SUPABASE_ANON_KEY</code>
            to <code className="mx-1 rounded bg-surface-2 px-1 py-0.5 text-xs">backend/.env</code> and restart it.
          </p>
        </AuthLayout>
      );
    case "error":
      return <AuthLayout title="Can't reach LeadPilot"><p className="text-sm text-ink-2">{auth.error}</p></AuthLayout>;
    default:
      return <Waiting text="Loading…" />;
  }
}

function Waiting({ text }: { text: string }) {
  return <div className="flex min-h-full items-center justify-center bg-page text-sm text-ink-3">{text}</div>;
}

/** Brand panel on the left (large screens), the form column on the right. */
function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
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
            <h1 className="font-display text-[34px] font-extrabold leading-tight tracking-tight text-ink">{title}</h1>
            {subtitle && <p className="mt-2 text-sm text-ink-2">{subtitle}</p>}
            <div className="mt-6">{children}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, icon, type = "text", value, onChange, autoComplete, minLength, placeholder, invalid, aside, disabled }: {
  label: string; icon: IconName; type?: string; value: string; onChange: (v: string) => void; autoComplete?: string;
  minLength?: number; placeholder?: string; invalid?: boolean; aside?: ReactNode; disabled?: boolean;
}) {
  const id = useId();
  const [show, setShow] = useState(false);
  const secret = type === "password";
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between"><label htmlFor={id} className="text-sm font-medium text-ink">{label}</label>{aside}</div>
      <div className={`group flex h-12 items-center gap-2.5 rounded-2xl border bg-surface px-4 shadow-sm transition focus-within:ring-4 ${invalid ? "border-critical focus-within:ring-critical/15" : "border-line focus-within:border-brand focus-within:ring-brand/15"}`}>
        <Icon name={icon} className="shrink-0 text-ink-3 transition group-focus-within:text-accent-ink" />
        <input id={id} type={secret && show ? "text" : type} value={value} required minLength={minLength} autoComplete={autoComplete}
          placeholder={placeholder} disabled={disabled} onChange={(e) => onChange(e.target.value)}
          className="min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none sm:text-sm" />
        {secret && (
          <button type="button" onClick={() => setShow((s) => !s)} className="text-ink-3 transition hover:text-ink" aria-label={show ? "Hide password" : "Show password"}>
            <Icon name={show ? "eyeOff" : "eye"} />
          </button>
        )}
      </div>
    </div>
  );
}

function Submit({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button type="submit" disabled={busy}
      className="btn-brand relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-2xl text-sm font-semibold text-white transition duration-300 active:scale-[0.98] disabled:opacity-70">
      {busy
        ? <><span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white" style={{ animation: "spin 700ms linear infinite" }} />Please wait…</>
        : <>{children} <Icon name="arrowRight" /></>}
    </button>
  );
}

function Note({ tone, children }: { tone: "error" | "ok"; children: ReactNode }) {
  if (tone === "ok") return <p role="status" className="pop rounded-xl bg-accent-soft px-3 py-2.5 text-sm text-accent-ink">{children}</p>;
  return (
    <div role="alert" className="pop flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm text-critical-ink"
      style={{ borderColor: "color-mix(in srgb, var(--c-critical) 40%, transparent)", background: "color-mix(in srgb, var(--c-critical) 8%, transparent)" }}>
      <Icon name="alert" className="mt-0.5 shrink-0" />{children}
    </div>
  );
}

type Mode = "sign-in" | "sign-up" | "reset";

function Login() {
  const auth = useAuth();
  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [shakeKey, setShakeKey] = useState(0);

  const go = (m: Mode) => { setMode(m); setError(null); setInfo(null); };
  const fail = (msg: string) => { setError(msg); setShakeKey((k) => k + 1); };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setInfo(null);
    try {
      if (mode === "sign-in") {
        markArrival();   // the session can land before signIn resolves, so flag the shell's entrance up front
        const err = await auth.signIn(email.trim(), password);
        if (err) { takeArrival(); fail(err); }
      } else if (mode === "sign-up") {
        const r = await auth.signUp(email.trim(), password, name.trim());
        if (r.error) fail(r.error);
        else if (r.confirm) { setInfo("Check your inbox and click the confirmation link, then sign in here."); setMode("sign-in"); }
      } else {
        const err = await auth.resetPassword(email.trim());
        if (err) fail(err);
        else setInfo("If that email has an account, a reset link is on its way.");
      }
    } finally {
      setBusy(false);
    }
  };

  const titles: Record<Mode, [string, ReactNode]> = {
    "sign-in": ["Sign in", <>Sign in to your <Wordmark className="text-sm" /> workspace and pick up where your pipeline left off.</>],
    "sign-up": ["Create your account", "An admin approves new accounts before they can see any leads."],
    reset: ["Reset your password", "We'll email you a link to choose a new one."],
  };
  return (
    <AuthLayout title={titles[mode][0]} subtitle={titles[mode][1]}>
      <form key={shakeKey} onSubmit={submit} className={`space-y-4 ${shakeKey ? "shake" : ""}`}>
        {info && <Note tone="ok">{info}</Note>}
        {mode === "sign-up" && <Field label="Full name" icon="user" value={name} onChange={setName} autoComplete="name" placeholder="Ananya Rao" disabled={busy} />}
        <Field label="Work email" icon="mail" type="email" value={email} onChange={setEmail} autoComplete="email" placeholder="you@company.com"
          invalid={!!error && /email/i.test(error)} disabled={busy} />
        {mode !== "reset" && (
          <Field label="Password" icon="lock" type="password" value={password} onChange={setPassword} minLength={mode === "sign-up" ? 8 : undefined}
            autoComplete={mode === "sign-up" ? "new-password" : "current-password"} placeholder={mode === "sign-up" ? "At least 8 characters" : "Enter your password"}
            invalid={!!error && /password/i.test(error)} disabled={busy}
            aside={mode === "sign-in" && <button type="button" onClick={() => go("reset")} className="text-xs font-medium text-accent-ink hover:underline">Forgot password?</button>} />
        )}
        {error && <Note tone="error">{error}</Note>}
        <Submit busy={busy}>{mode === "sign-in" ? "Sign in" : mode === "sign-up" ? "Create account" : "Send reset link"}</Submit>
      </form>
      <div className="mt-5 text-center text-sm">
        {mode === "sign-in" ? (
          <span className="text-ink-2">New here? <button className="font-medium text-accent-ink hover:underline" onClick={() => go("sign-up")}>Create an account</button></span>
        ) : (
          <button className="inline-flex items-center gap-1 font-medium text-accent-ink hover:underline" onClick={() => go("sign-in")}><Icon name="arrowLeft" size={14} />Back to sign in</button>
        )}
      </div>
      <p className="mt-6 text-center text-xs text-ink-3">Protected workspace · Every score, stage and assignment is explained.</p>
    </AuthLayout>
  );
}

function NewPassword() {
  const auth = useAuth();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(await auth.setNewPassword(password));
    setBusy(false);
  };
  return (
    <AuthLayout title="Choose a new password">
      <form onSubmit={submit} className="space-y-4">
        <Field label="New password" icon="lock" type="password" value={password} onChange={setPassword} minLength={8} autoComplete="new-password" placeholder="At least 8 characters" />
        {error && <Note tone="error">{error}</Note>}
        <Submit busy={busy}>Save password</Submit>
      </form>
    </AuthLayout>
  );
}

function Pending() {
  const auth = useAuth();
  return (
    <AuthLayout title="Waiting for access" subtitle={auth.me?.email ?? undefined}>
      <p className="text-sm text-ink-2">
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
