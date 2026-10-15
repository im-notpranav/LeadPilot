// Calls (managers): every call from the phone system or logged by a rep, newest first. Calls for a number no lead
// has yet wait here until someone links them to a lead; failed ones can be retried.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Call, type CallList } from "../lib/api";
import { dateTime, human, titleCase } from "../lib/format";
import { to } from "../lib/links";
import { errText, inputCls } from "../components/deals";
import { CallStatus, CallView, duration } from "../components/calls";
import { Button, Card, Empty, Loading, PageHeader, Segmented, StatusTag } from "../components/ui";

type Show = "all" | "unmatched" | "failed";

export default function Calls() {
  const [show, setShow] = useState<Show>("all");
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["calls", show], queryFn: () => api.get<CallList>(`/api/calls${show === "all" ? "" : `?status=${show}`}`),
    refetchInterval: (query) => (query.state.data?.items.some((c) => c.status === "queued" || c.status === "analyzing") ? 1500 : 15_000),
  });
  const items = q.data?.items ?? [];
  return (
    <div className="mx-auto max-w-[1200px] space-y-4">
      <PageHeader title="Calls" subtitle="Every call, summarised and attached to its lead. A call's analysis is saved with it, so replays never ask the AI again." />
      {q.data && <Setup s={q.data} />}
      <Card pad={false} title="Recent calls" right={<Segmented label="Show" value={show} onChange={setShow} options={[{ value: "all", label: "All" }, { value: "unmatched", label: "Needs a lead" }, { value: "failed", label: "Failed" }]} />}>
        {q.isLoading ? <div className="p-5"><Loading rows={4} /></div>
          : q.error ? <Empty>Could not load calls. {errText(q.error)}</Empty>
          : !items.length ? <Empty>{show === "all" ? "No calls yet. Add a Phone calls connector, or log a call from a lead's page." : "Nothing here."}</Empty>
          : (
            <ul className="divide-y divide-[var(--c-line)]">
              {items.map((c) => (
                <li key={c.id} className="px-5 py-3">
                  <button type="button" className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left text-sm" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                    <span className="min-w-[160px] font-medium text-ink">{c.lead_name ?? c.number ?? "Unknown caller"}</span>
                    <span className="text-xs text-ink-3">{c.direction === "inbound" ? "They called" : "We called"} · {dateTime(c.ended_at ?? c.created_at)}{duration(c.duration_s) ? ` · ${duration(c.duration_s)}` : ""} · {c.provider === "manual" ? "logged by hand" : human(c.provider)}</span>
                    <span className="ml-auto flex items-center gap-1.5"><CallStatus c={c} />{c.analysis && <StatusTag status={c.analysis.outcome === "connected" ? "good" : "warn"}>{titleCase(c.analysis.outcome)}</StatusTag>}</span>
                    {c.analysis?.summary && <span className="w-full truncate text-xs text-ink-2">{c.analysis.summary}</span>}
                  </button>
                  {open === c.id && <Detail c={c} />}
                </li>
              ))}
            </ul>
          )}
      </Card>
    </div>
  );
}

function Setup({ s }: { s: CallList }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5">
        {s.gemini.configured ? <StatusTag status="good">Gemini on</StatusTag> : <StatusTag status="warn">Gemini off</StatusTag>}
        <span className="text-ink-2">{s.gemini.configured ? `Summaries by ${s.gemini.model}` : <>Set <code className="font-mono">GEMINI_API_KEY</code> for AI summaries</>}</span>
      </span>
      <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5">
        {s.recordings.configured ? <StatusTag status="good">Recordings stored</StatusTag> : <StatusTag status="warn">Recordings not stored</StatusTag>}
        <span className="text-ink-2">{s.recordings.configured ? `Private bucket ${s.recordings.bucket}` : <>Set <code className="font-mono">SUPABASE_SERVICE_ROLE_KEY</code> to keep copies; until then the phone system's link is used</>}</span>
      </span>
    </div>
  );
}

function Detail({ c }: { c: Call }) {
  const qc = useQueryClient();
  const full = useQuery({ queryKey: ["calls", "one", c.id], queryFn: () => api.get<Call>(`/api/calls/${encodeURIComponent(c.id)}`) });
  const [leadId, setLeadId] = useState("");
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: ["calls"] }) };
  const link = useMutation({ mutationFn: () => api.post<Call>(`/api/calls/${encodeURIComponent(c.id)}/link`, { lead_id: leadId.trim() }), ...done });
  const retry = useMutation({ mutationFn: () => api.post<Call>(`/api/calls/${encodeURIComponent(c.id)}/retry`), ...done });
  return (
    <div className="mt-3 space-y-3 rounded-xl border border-line p-3">
      {full.data ? <CallView c={full.data} /> : <Loading rows={2} />}
      {c.lead_id && <p className="text-xs"><Link to={`${to.lead(c.lead_id)}#calls`} className="drill font-medium text-accent-ink">Open the lead</Link></p>}
      {(c.status === "unmatched" || c.status === "failed") && (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); link.mutate(); }}>
          <label className="min-w-[200px] flex-1"><span className="mb-1 block text-xs font-medium text-ink-2">Link to lead (ID, e.g. L-1042)</span>
            <input value={leadId} onChange={(e) => setLeadId(e.target.value)} className={inputCls} placeholder="L-…" /></label>
          <Button type="submit" variant="primary" disabled={!leadId.trim() || link.isPending}>Link and analyse</Button>
          {c.status === "failed" && <Button disabled={retry.isPending} onClick={() => retry.mutate()}>Retry</Button>}
        </form>
      )}
      {(link.error || retry.error) && <p role="alert" className="text-sm text-critical-ink">{errText(link.error ?? retry.error)}</p>}
    </div>
  );
}
