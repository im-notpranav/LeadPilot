// Session layer: reads /api/auth/config, signs in with Supabase Auth, and exposes the LeadPilot user (/api/me).
// With auth off on the server, everyone is a local admin and no login screen is shown.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { api, configureAuth, type AuthConfig, type Me } from "./api";

type Status = "loading" | "off" | "misconfigured" | "signed-out" | "recovery" | "signed-in" | "error";
type Auth = {
  status: Status;
  me: Me | null;
  error: string | null;
  signIn: (email: string, password: string) => Promise<string | null>;
  signUp: (email: string, password: string, name: string) => Promise<{ error: string | null; confirm: boolean }>;
  resetPassword: (email: string) => Promise<string | null>;
  setNewPassword: (password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
};

const AuthCtx = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export const can = {
  manage: (me: Me | null) => me?.role === "admin" || me?.role === "manager",
  admin: (me: Me | null) => me?.role === "admin",
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const client = useRef<SupabaseClient | null>(null);
  const session = useRef<Session | null>(null);

  const loadMe = useCallback(async () => {
    try {
      setMe(await api.get<Me>("/api/me"));
      setStatus((s) => (s === "off" ? "off" : "signed-in"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const signOut = useCallback(async () => {
    session.current = null;
    setMe(null);
    if (client.current) await client.current.auth.signOut();
    setStatus(client.current ? "signed-out" : "off");
  }, []);

  useEffect(() => {
    let unsub: (() => void) | undefined;
    configureAuth(() => session.current?.access_token ?? null, () => { void signOut(); });
    (async () => {
      let cfg: AuthConfig;
      try {
        cfg = await (await fetch("/api/auth/config")).json();
      } catch {
        setStatus("error");
        setError("Cannot reach the LeadPilot server.");
        return;
      }
      if (!cfg.enabled) {
        setStatus("off");
        await loadMe();
        return;
      }
      if (!cfg.login_ready || !cfg.supabase_url || !cfg.anon_key) {
        setStatus("misconfigured");
        return;
      }
      const sb = createClient(cfg.supabase_url, cfg.anon_key, { auth: { persistSession: true, autoRefreshToken: true } });
      client.current = sb;
      const { data } = sb.auth.onAuthStateChange((event, s) => {
        session.current = s;
        if (event === "PASSWORD_RECOVERY") { setStatus("recovery"); return; }
        if (!s) { setMe(null); setStatus("signed-out"); return; }
        if (event === "SIGNED_IN" || event === "INITIAL_SESSION" || event === "USER_UPDATED") void loadMe();
      });
      unsub = () => data.subscription.unsubscribe();
      const { data: initial } = await sb.auth.getSession();
      session.current = initial.session;
      if (initial.session) await loadMe();
      else setStatus((s) => (s === "recovery" ? s : "signed-out"));
    })();
    return () => unsub?.();
  }, [loadMe, signOut]);

  const value = useMemo<Auth>(() => ({
    status, me, error, signOut, refreshMe: loadMe,
    signIn: async (email, password) => {
      const { error: err } = await client.current!.auth.signInWithPassword({ email, password });
      return err ? friendly(err.message) : null;
    },
    signUp: async (email, password, name) => {
      const { data, error: err } = await client.current!.auth.signUp({
        email, password, options: { data: { full_name: name }, emailRedirectTo: location.origin },
      });
      return { error: err ? friendly(err.message) : null, confirm: !err && !data.session };
    },
    resetPassword: async (email) => {
      const { error: err } = await client.current!.auth.resetPasswordForEmail(email, { redirectTo: location.origin });
      return err ? friendly(err.message) : null;
    },
    setNewPassword: async (password) => {
      const { error: err } = await client.current!.auth.updateUser({ password });
      if (err) return friendly(err.message);
      await loadMe();
      return null;
    },
  }), [status, me, error, signOut, loadMe]);

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

function friendly(message: string): string {
  if (/invalid login credentials/i.test(message)) return "That email and password don't match an account.";
  if (/email not confirmed/i.test(message)) return "Confirm your email first: check your inbox for the link.";
  if (/rate limit/i.test(message)) return "Too many attempts. Wait a minute and try again.";
  return message;
}

/** Display name and initials for the signed-in person (falls back to the email's local part). */
export function profile(me: Me | null): { name: string; email: string; initials: string } {
  const email = me?.email ?? "";
  const raw = me?.name?.trim() || email.split("@")[0].replace(/[._-]+/g, " ").trim() || "Pilot";
  const name = raw.replace(/\b\w/g, (c) => c.toUpperCase());
  const initials = name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return { name, email, initials };
}

// Set by the login screen on a successful sign-in so the app shell plays its entrance once.
let arriving = false;
export const markArrival = () => { arriving = true; };
export const takeArrival = () => { const a = arriving; arriving = false; return a; };

export const MIN_PASSWORD = 8;

/** 0–4: length and character variety. */
export function passwordStrength(p: string): number {
  if (!p) return 0;
  let s = p.length >= MIN_PASSWORD ? 1 : 0;
  if (p.length >= 12) s++;
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s++;
  if (/\d/.test(p) && /[^A-Za-z0-9]/.test(p)) s++;
  return Math.min(4, s);
}
