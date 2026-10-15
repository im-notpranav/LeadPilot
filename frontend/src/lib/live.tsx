// WebSocket live layer: keeps the sim clock, a rolling feed, toasts, and invalidates queries (throttled).
// Notifications live on the server (the bell reads them); a new one refreshes the bell, and urgent ones also toast.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { currentToken, type FeedItem } from "./api";

type Clock = { now: string | null; speed: number; paused: boolean; status: string; live?: boolean };
export type Toast = { id: number; kind: string; text: string; lead_id?: string; href?: string };
type Live = { clock: Clock; connected: boolean; feed: FeedItem[]; toasts: Toast[]; dismiss: (id: number) => void; eventsPerMin: number; notify: (text: string, kind?: string) => void };

const LiveCtx = createContext<Live>({ clock: { now: null, speed: 60, paused: true, status: "starting" }, connected: false, feed: [], toasts: [], dismiss: () => {}, eventsPerMin: 0, notify: () => {} });

// The backend's WebSocket origin. Same host by default; a split deploy (dashboard on Vercel, API elsewhere) sets
// VITE_BACKEND_WS_URL at build time, because Vercel proxies /api but cannot proxy WebSockets.
function wsBase(): string {
  const configured = import.meta.env.VITE_BACKEND_WS_URL?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
}

const DATA_KEYS =[["leads"], ["queue"], ["pipeline"], ["lead"], ["feed"], ["reps"], ["sim"]];
const QUALITY_KEYS = [["quality"]];

export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [clock, setClock] = useState<Clock>({ now: null, speed: 60, paused: true, status: "starting" });
  const [connected, setConnected] = useState(false);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [eventsPerMin, setEpm] = useState(0);
  const dirty = useRef({ data: false, quality: false, all: false, notices: false });
  const counter = useRef<number[]>([]);
  const toastId = useRef(0);

  const push = (items: Toast[]) => {
    setToasts((ts) => [...items.slice(-3), ...ts].slice(0, 4));
    for (const t of items) window.setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== t.id)), 7000);
  };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    let retry: number | undefined;
    const connect = () => {
      const token = currentToken();          // read at every (re)connect, so refreshed sessions are picked up
      ws = new WebSocket(`${wsBase()}/ws${token ? `?token=${encodeURIComponent(token)}` : ""}`);
      ws.onopen = () => setConnected(true);
      ws.onclose = (e) => { setConnected(false); if (!stop) retry = window.setTimeout(connect, e.code === 4401 ? 5000 : 1500); };
      ws.onmessage = (ev) => {
        const env = JSON.parse(ev.data);
        const msgs: { type: string; data: any }[] = env.type === "batch" ? env.messages : [env];
        const fresh: FeedItem[] = [];
        const newToasts: Toast[] = [];
        for (const m of msgs) {
          const d = m.data;
          switch (m.type) {
            case "sim.clock": setClock({ now: d.now, speed: d.speed, paused: d.paused, status: d.status ?? "ready", live: !!d.live }); break;
            case "sim.reset": dirty.current.all = true; if (d.status === "resetting") setFeed([]); setClock((c) => ({ ...c, status: d.status ?? c.status })); break;
            case "event.processed": fresh.push(d); dirty.current.data = true; counter.current.push(Date.now()); break;
            case "lead.flagged": case "lead.merged": case "source.flagged": dirty.current.quality = true; dirty.current.data = true; break;
            case "notification.created": dirty.current.notices = true; break;
            default: dirty.current.data = true;
          }
          const t = toastFor(m.type, d);
          if (t) newToasts.push({ id: ++toastId.current, kind: m.type, ...t });
        }
        if (fresh.length) setFeed((f) => [...fresh.reverse(), ...f].slice(0, 250));
        if (newToasts.length) push(newToasts);
      };
    };
    connect();
    return () => { stop = true; if (retry) clearTimeout(retry); ws?.close(); };
  }, []);

  useEffect(() => {
    const iv = window.setInterval(() => {
      const d = dirty.current;
      if (d.all) { qc.invalidateQueries(); dirty.current = { data: false, quality: false, all: false, notices: false }; return; }
      if (d.data) DATA_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }));
      if (d.quality) QUALITY_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }));
      if (d.notices) qc.invalidateQueries({ queryKey: ["notifications"] });
      dirty.current = { data: false, quality: false, all: false, notices: false };
      const cutoff = Date.now() - 60000;
      counter.current = counter.current.filter((t) => t > cutoff);
      setEpm(counter.current.length);
    }, 1500);
    const slow = window.setInterval(() => qc.invalidateQueries({ queryKey: ["analytics"] }), 12000);
    return () => { clearInterval(iv); clearInterval(slow); };
  }, [qc]);

  const dismiss = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const notify = (text: string, kind = "info") => push([{ id: ++toastId.current, kind, text }]);
  return <LiveCtx.Provider value={{ clock, connected, feed, toasts, dismiss, eventsPerMin, notify }}>{children}</LiveCtx.Provider>;
}

function toastFor(type: string, d: any): { text: string; lead_id?: string; href?: string } | null {
  switch (type) {
    case "notification.created": return d.severity === "urgent" ? { text: d.title, lead_id: d.lead_id ?? undefined, href: d.link ?? undefined } : null;
    case "lead.reassigned": return d.rule_id ? { text: `${d.lead_id} reassigned to ${d.rep_name} (${d.rule_id})`, lead_id: d.lead_id } : null;
    case "stall.detected": return d.risk >= 50 ? { text: `${d.lead_id} stalled: ${d.details?.[0] ?? d.rules.join(", ")}`, lead_id: d.lead_id } : null;
    case "lead.merged": return { text: `Merged ${d.merged_id} into ${d.survivor_id} (${Math.round(d.confidence * 100)}%)`, lead_id: d.survivor_id };
    case "source.flagged": return { text: `Source flagged: ${d.reasons?.[0] ?? d.source_id}` };
    case "scenario.launched": return { text: `Scenario started: ${d.title}`, lead_id: d.lead_id };
    default: return null;
  }
}

export const useLive = () => useContext(LiveCtx);
