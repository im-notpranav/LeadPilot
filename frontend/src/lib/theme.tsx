// Light / dark / system theme. index.html resolves it before paint; this keeps it in sync afterwards.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemePref = "light" | "dark" | "system";
type Theme = { pref: ThemePref; resolved: "light" | "dark"; setPref: (p: ThemePref) => void; toggle: () => void };

const media = () => window.matchMedia("(prefers-color-scheme: dark)");
const resolve = (p: ThemePref): "light" | "dark" => (p === "system" ? (media().matches ? "dark" : "light") : p);
function readPref(): ThemePref {
  try { const v = localStorage.getItem("lp.theme"); return v === "light" || v === "dark" ? v : "system"; } catch { return "system"; }
}

const ThemeCtx = createContext<Theme>({ pref: "system", resolved: "light", setPref: () => {}, toggle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readPref);
  const [resolved, setResolved] = useState<"light" | "dark">(() => resolve(readPref()));

  useEffect(() => {
    const apply = () => {
      const r = resolve(pref);
      const root = document.documentElement;
      if (root.dataset.theme !== r) {
        // Cross-fade colors for the switch only; normal interactions keep their own transitions.
        root.classList.add("theme-switching");
        window.setTimeout(() => root.classList.remove("theme-switching"), 320);
      }
      root.dataset.theme = r;
      root.style.background = "";
      setResolved(r);
    };
    apply();
    if (pref !== "system") return;
    const m = media();
    m.addEventListener("change", apply);
    return () => m.removeEventListener("change", apply);
  }, [pref]);

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    try { p === "system" ? localStorage.removeItem("lp.theme") : localStorage.setItem("lp.theme", p); } catch { /* storage blocked */ }
  }, []);
  const toggle = useCallback(() => setPref(resolve(pref) === "dark" ? "light" : "dark"), [pref, setPref]);

  return <ThemeCtx.Provider value={{ pref, resolved, setPref, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
