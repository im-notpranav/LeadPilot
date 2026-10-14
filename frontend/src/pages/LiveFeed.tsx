import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type FeedItem } from "../lib/api";
import { useLive } from "../lib/live";
import { human, time } from "../lib/format";
import { Card, Delta, Empty, GradePill, PageHeader } from "../components/ui";
import { Icon } from "../components/icons";
import { to } from "../lib/links";

const GROUPS: Record<string, string[]> = {
  Capture: ["lead_created"],
  Web: ["page_view", "content_download", "webinar_registered", "webinar_attended"],
  "High intent": ["demo_request", "contact_sales", "trial_signup", "proposal_viewed"],
  Email: ["email_sent", "email_opened", "email_clicked", "email_replied", "email_bounced", "unsubscribed"],
  Calls: ["call_logged", "meeting_scheduled", "meeting_held", "meeting_no_show"],
  Deals: ["proposal_sent", "contract_sent", "deal_won", "deal_lost"],
  Manual: ["stage_override", "lead_disqualified", "bant_qualified", "manual_assign", "quality_cleared", "task_completed"],
};

export default function LiveFeed() {
  const { feed } = useLive();
  const initial = useQuery({ queryKey: ["feed", "initial"], queryFn: () => api.get<{ items: FeedItem[] }>("/api/feed?limit=200"), staleTime: Infinity });
  const [active, setActive] = useState<Set<string>>(new Set());
  const [movers, setMovers] = useState(false);
  const [params, setParams] = useSearchParams();
  const only = params.get("type") ?? "";
  const setOnly = (t: string | null) => { const n = new URLSearchParams(params); if (t) n.set("type", t); else n.delete("type"); setParams(n, { replace: true }); };
  const items = useMemo(() => {
    const seen = new Set<string>();
    const all = [...feed, ...(initial.data?.items ?? [])].filter((i) => (seen.has(i.event_id) ? false : (seen.add(i.event_id), true)));
    const types = new Set([...active].flatMap((g) => GROUPS[g]));
    return all.filter((i) => (!types.size || types.has(i.type)) && (!only || i.type === only) && (!movers || Math.abs(i.delta) >= 3))
      .sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0)).slice(0, 200);
  }, [feed, initial.data, active, movers, only]);
  const toggle = (g: string) => setActive((s) => { const n = new Set(s); n.has(g) ? n.delete(g) : n.add(g); return n; });

  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Live feed" subtitle="Every processed event with the score change it caused and a plain-English reason. Updates live." />
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {Object.keys(GROUPS).map((g) => (
          <button key={g} onClick={() => toggle(g)} aria-pressed={active.has(g)} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition active:scale-95 ${active.has(g) ? "border-transparent bg-accent text-white shadow-[0_6px_14px_-6px_rgb(37_99_235/.7)]" : "border-line bg-surface text-ink-2 shadow-sm hover:border-brand/40 hover:text-ink"}`}>{g}</button>
        ))}
        {only && <button onClick={() => setOnly(null)} className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent-ink">Only {human(only)} <Icon name="close" size={12} /></button>}
        <label className="ml-2 inline-flex items-center gap-1.5 text-xs text-ink-2"><input type="checkbox" checked={movers} onChange={(e) => setMovers(e.target.checked)} /> Only moves ≥ 3 points</label>
      </div>
      <Card pad={false}>
        {!items.length ? <Empty>{only || active.size || movers ? "No events match these filters yet." : <>No events yet. <Link to="/simulator" className="font-medium text-accent-ink hover:underline">Start the simulator</Link> to generate some.</>}</Empty> : (
          <ul>
            {items.map((i) => (
              <li key={i.event_id} className="flash grid grid-cols-[56px_150px_minmax(0,200px)_70px_1fr] items-baseline gap-3 border-b border-line px-4 py-2.5 text-sm transition-colors last:border-0 hover:bg-surface-2/50">
                <span className="text-xs tabular text-ink-3">{time(i.ts)}</span>
                <span className="truncate text-xs font-medium text-ink-2">
                  <button onClick={() => setOnly(only === i.type ? null : i.type)} className="drill" title={only === i.type ? "Show all event types" : `Only show ${human(i.type)}`}>{human(i.type)}</button>
                  {i.actor === "rep" && i.rep_id ? <> · <Link to={to.queue(i.rep_id)} className="drill">rep</Link></> : i.actor === "rep" ? " · rep" : ""}
                </span>
                <Link to={`/leads/${i.lead_id}`} className="truncate font-medium hover:underline">{i.name ?? i.lead_id}<span className="font-normal text-ink-3"> {i.company ? `· ${i.company}` : ""}</span></Link>
                <span className="flex items-center gap-1.5"><Delta value={i.delta} /></span>
                <span className="flex min-w-0 items-baseline gap-2">
                  {i.grade && <Link to={to.leads({ grade: i.grade })} title={`All grade ${i.grade} leads`}><GradePill grade={i.grade} score={i.score ?? undefined} /></Link>}
                  <span className="truncate text-xs text-ink-2">{i.summary}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
