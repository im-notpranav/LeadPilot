// Browser-local accounts. The LeadPilot API has no authentication, so accounts live in this
// browser's storage: it gates the dashboard UI, it is not access control. Swap these functions
// for API calls when the backend grows auth.
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

export type User = { name: string; email: string; company: string; initials: string };
type Account = { name: string; email: string; company: string; salt: string; hash: string };
type SignUp = { name: string; email: string; company: string; password: string };
type Auth = {
  user: User | null;
  signIn: (email: string, password: string, remember: boolean) => Promise<User>;
  signUp: (input: SignUp, remember: boolean) => Promise<User>;
  resetPassword: (email: string, password: string) => Promise<void>;
  signOut: () => void;
};

const SESSION = "lp.session";
const ACCOUNTS = "lp.accounts";
export const DEMO = { name: "Demo User", email: "demo@leadpilot.io", company: "LeadPilot", password: "pilot123" };
export const MIN_PASSWORD = 8;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export class AuthError extends Error {
  constructor(message: string, readonly field?: "name" | "email" | "password") { super(message); }
}

function read<T>(store: () => Storage, key: string): T | null {
  try { const raw = store().getItem(key); return raw ? (JSON.parse(raw) as T) : null; } catch { return null; }
}
function write(store: () => Storage, key: string, value: unknown) {
  try { store().setItem(key, JSON.stringify(value)); } catch { /* storage blocked */ }
}

async function digest(password: string, salt: string): Promise<string> {
  const data = new TextEncoder().encode(`${salt}:${password}`);
  if (globalThis.crypto?.subtle) {
    const buf = await crypto.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  }
  // Non-secure origins (plain http on a LAN IP) have no SubtleCrypto; fall back to FNV-1a.
  let h = 0x811c9dc5;
  for (const b of data) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16);
}
const newSalt = () => Array.from({ length: 16 }, () => Math.floor(Math.random() * 16).toString(16)).join("");

async function accounts(): Promise<Account[]> {
  const list = read<Account[]>(() => localStorage, ACCOUNTS) ?? [];
  if (!list.some((a) => a.email === DEMO.email)) {
    const salt = newSalt();
    list.push({ name: DEMO.name, email: DEMO.email, company: DEMO.company, salt, hash: await digest(DEMO.password, salt) });
    write(() => localStorage, ACCOUNTS, list);
  }
  return list;
}

const toUser = (a: Pick<Account, "name" | "email" | "company">): User => ({
  name: a.name, email: a.email, company: a.company,
  initials: a.name.split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?",
});
const normEmail = (e: string) => e.trim().toLowerCase();
const pause = () => new Promise((r) => setTimeout(r, 650)); // lets the button show its busy state

const AuthCtx = createContext<Auth>(null as unknown as Auth);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => read<User>(() => localStorage, SESSION) ?? read<User>(() => sessionStorage, SESSION));

  const start = useCallback((u: User, remember: boolean) => {
    write(() => (remember ? localStorage : sessionStorage), SESSION, u);
    setUser(u);
    return u;
  }, []);

  const signIn = useCallback(async (email: string, password: string, remember: boolean) => {
    await pause();
    const e = normEmail(email);
    if (!EMAIL_RE.test(e)) throw new AuthError("Enter a valid email address.", "email");
    if (!password) throw new AuthError("Enter your password.", "password");
    const acct = (await accounts()).find((a) => a.email === e);
    if (!acct) throw new AuthError("No account uses this email. Create one instead.", "email");
    if ((await digest(password, acct.salt)) !== acct.hash) throw new AuthError("Incorrect password.", "password");
    return start(toUser(acct), remember);
  }, [start]);

  const signUp = useCallback(async (input: SignUp, remember: boolean) => {
    await pause();
    const name = input.name.trim().replace(/\s+/g, " ");
    const email = normEmail(input.email);
    if (name.length < 2) throw new AuthError("Enter your full name.", "name");
    if (!EMAIL_RE.test(email)) throw new AuthError("Enter a valid email address.", "email");
    if (input.password.length < MIN_PASSWORD) throw new AuthError(`Use at least ${MIN_PASSWORD} characters.`, "password");
    const list = await accounts();
    if (list.some((a) => a.email === email)) throw new AuthError("An account with this email already exists. Sign in instead.", "email");
    const salt = newSalt();
    const acct: Account = { name, email, company: input.company.trim(), salt, hash: await digest(input.password, salt) };
    write(() => localStorage, ACCOUNTS, [...list, acct]);
    return start(toUser(acct), remember);
  }, [start]);

  const resetPassword = useCallback(async (email: string, password: string) => {
    await pause();
    const e = normEmail(email);
    const list = await accounts();
    const acct = list.find((a) => a.email === e);
    if (!acct) throw new AuthError("No account uses this email.", "email");
    if (password.length < MIN_PASSWORD) throw new AuthError(`Use at least ${MIN_PASSWORD} characters.`, "password");
    acct.salt = newSalt();
    acct.hash = await digest(password, acct.salt);
    write(() => localStorage, ACCOUNTS, list);
  }, []);

  const signOut = useCallback(() => {
    for (const s of [() => localStorage, () => sessionStorage]) { try { s().removeItem(SESSION); } catch { /* storage blocked */ } }
    setUser(null);
  }, []);

  return <AuthCtx.Provider value={{ user, signIn, signUp, resetPassword, signOut }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

/** 0–4: length and character variety. */
export function passwordStrength(p: string): number {
  if (!p) return 0;
  let s = p.length >= MIN_PASSWORD ? 1 : 0;
  if (p.length >= 12) s++;
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s++;
  if (/\d/.test(p) && /[^A-Za-z0-9]/.test(p)) s++;
  return Math.min(4, s);
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <>{children}</>;
}
