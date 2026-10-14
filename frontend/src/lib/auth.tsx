// Demo sign-in. The LeadPilot API has no authentication, so this is a client-side gate for the
// dashboard experience only: it is not access control. Swap `signIn` for a real call when the API grows one.
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

export type User = { name: string; email: string; initials: string };
type Auth = { user: User | null; signIn: (email: string, password: string, remember: boolean) => Promise<User>; signOut: () => void };

const KEY = "lp.session";
export const DEMO = { email: "demo@leadpilot.io", password: "pilot123" };

function load(): User | null {
  for (const store of [() => localStorage, () => sessionStorage]) {
    try { const raw = store().getItem(KEY); if (raw) return JSON.parse(raw) as User; } catch { /* storage blocked */ }
  }
  return null;
}

function toUser(email: string): User {
  const local = email.split("@")[0].replace(/[._-]+/g, " ").trim() || "Pilot";
  const name = local.replace(/\b\w/g, (c) => c.toUpperCase());
  const initials = name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return { name, email, initials };
}

const AuthCtx = createContext<Auth>({ user: null, signIn: async () => toUser("pilot"), signOut: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(load);

  const signIn = useCallback(async (email: string, password: string, remember: boolean) => {
    await new Promise((r) => setTimeout(r, 900)); // feels like a round-trip; drives the button state
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error("Enter a valid work email.");
    if (password.length < 6) throw new Error("That password doesn't look right. It needs at least 6 characters.");
    const u = toUser(email.trim().toLowerCase());
    try { (remember ? localStorage : sessionStorage).setItem(KEY, JSON.stringify(u)); } catch { /* storage blocked */ }
    setUser(u);
    return u;
  }, []);

  const signOut = useCallback(() => {
    for (const s of [() => localStorage, () => sessionStorage]) { try { s().removeItem(KEY); } catch { /* storage blocked */ } }
    setUser(null);
  }, []);

  return <AuthCtx.Provider value={{ user, signIn, signOut }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <>{children}</>;
}
