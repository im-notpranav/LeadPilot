// Everything shown before the dashboard: sign in / sign up / reset, waiting for approval, and setup problems.
import { useState, type FormEvent, type ReactNode } from "react";
import { useAuth } from "../lib/auth";

export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  switch (auth.status) {
    case "off":
      return auth.me ? <>{children}</> : <Splash text="Connecting…" />;
    case "signed-in":
      if (!auth.me) return <Splash text="Loading your workspace…" />;
      return auth.me.role === "pending" ? <Pending /> : <>{children}</>;
    case "signed-out":
      return <Login />;
    case "recovery":
      return <NewPassword />;
    case "misconfigured":
      return (
        <Shell title="Sign-in is not set up yet">
          <p className="text-sm text-ink-2">
            The server requires a login, but it does not have the Supabase anon (publishable) key. Add
            <code className="mx-1 rounded bg-surface-2 px-1 py-0.5 text-xs">SUPABASE_ANON_KEY</code>
            to <code className="mx-1 rounded bg-surface-2 px-1 py-0.5 text-xs">backend/.env</code> and restart it.
          </p>
        </Shell>
      );
    case "error":
      return <Shell title="Can't reach LeadPilot"><p className="text-sm text-ink-2">{auth.error}</p></Shell>;
    default:
      return <Splash text="Loading…" />;
  }
}

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-page px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="7" fill="var(--c-accent)" /><path d="M9 22 L16 9 L23 22 L16 18 Z" fill="white" /></svg>
          <span className="text-base font-semibold tracking-tight">LeadPilot</span>
        </div>
        <div className="rounded-xl border border-line bg-surface p-6 shadow-sm">
          <h1 className="text-lg font-semibold tracking-tight text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </div>
      </div>
    </div>
  );
}

function Splash({ text }: { text: string }) {
  return <div className="flex min-h-full items-center justify-center bg-page text-sm text-ink-3">{text}</div>;
}

function Field({ label, type = "text", value, onChange, autoComplete, minLength }: {
  label: string; type?: string; value: string; onChange: (v: string) => void; autoComplete?: string; minLength?: number;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      <input type={type} value={value} required minLength={minLength} autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-base text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 sm:text-sm" />
    </label>
  );
}

function Submit({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button type="submit" disabled={busy}
      className="h-10 w-full rounded-lg bg-accent text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60">
      {busy ? "Please wait…" : children}
    </button>
  );
}

function Note({ tone, children }: { tone: "error" | "ok"; children: ReactNode }) {
  return (
    <p role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg px-3 py-2 text-sm ${tone === "error" ? "bg-[color-mix(in_srgb,var(--c-critical)_10%,transparent)] text-critical-ink" : "bg-accent-soft text-accent-ink"}`}>
      {children}
    </p>
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

  const go = (m: Mode) => { setMode(m); setError(null); setInfo(null); };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setInfo(null);
    try {
      if (mode === "sign-in") {
        setError(await auth.signIn(email.trim(), password));
      } else if (mode === "sign-up") {
        const r = await auth.signUp(email.trim(), password, name.trim());
        if (r.error) setError(r.error);
        else if (r.confirm) { setInfo("Check your inbox and click the confirmation link, then sign in here."); setMode("sign-in"); }
      } else {
        const err = await auth.resetPassword(email.trim());
        if (err) setError(err);
        else setInfo("If that email has an account, a reset link is on its way.");
      }
    } finally {
      setBusy(false);
    }
  };

  const titles: Record<Mode, [string, string]> = {
    "sign-in": ["Sign in", "Your queue, pipeline and leads, scored and explained."],
    "sign-up": ["Create your account", "An admin approves new accounts before they can see any leads."],
    reset: ["Reset your password", "We'll email you a link to choose a new one."],
  };
  return (
    <Shell title={titles[mode][0]} subtitle={titles[mode][1]}>
      <form onSubmit={submit} className="space-y-3">
        {error && <Note tone="error">{error}</Note>}
        {info && <Note tone="ok">{info}</Note>}
        {mode === "sign-up" && <Field label="Full name" value={name} onChange={setName} autoComplete="name" />}
        <Field label="Work email" type="email" value={email} onChange={setEmail} autoComplete="email" />
        {mode !== "reset" && (
          <Field label="Password" type="password" value={password} onChange={setPassword} minLength={mode === "sign-up" ? 8 : undefined}
            autoComplete={mode === "sign-up" ? "new-password" : "current-password"} />
        )}
        <Submit busy={busy}>{mode === "sign-in" ? "Sign in" : mode === "sign-up" ? "Create account" : "Send reset link"}</Submit>
      </form>
      <div className="mt-4 flex flex-wrap justify-between gap-2 text-sm">
        {mode === "sign-in" ? (
          <>
            <button className="text-accent-ink hover:underline" onClick={() => go("sign-up")}>Create an account</button>
            <button className="text-ink-2 hover:underline" onClick={() => go("reset")}>Forgot password?</button>
          </>
        ) : (
          <button className="text-accent-ink hover:underline" onClick={() => go("sign-in")}>← Back to sign in</button>
        )}
      </div>
    </Shell>
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
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="space-y-3">
        {error && <Note tone="error">{error}</Note>}
        <Field label="New password" type="password" value={password} onChange={setPassword} minLength={8} autoComplete="new-password" />
        <Submit busy={busy}>Save password</Submit>
      </form>
    </Shell>
  );
}

function Pending() {
  const auth = useAuth();
  return (
    <Shell title="Waiting for access" subtitle={auth.me?.email ?? undefined}>
      <p className="text-sm text-ink-2">
        Your account is set up. An admin needs to give you a role (rep, manager or admin) before you can see any leads.
        This page updates when you check again.
      </p>
      <div className="mt-5 flex gap-2">
        <button onClick={() => auth.refreshMe()} className="h-9 flex-1 rounded-lg bg-accent text-sm font-medium text-white hover:brightness-110">Check again</button>
        <button onClick={() => auth.signOut()} className="h-9 flex-1 rounded-lg border border-line text-sm font-medium text-ink hover:bg-surface-2">Sign out</button>
      </div>
    </Shell>
  );
}
