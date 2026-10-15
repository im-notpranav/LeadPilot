// Calls: the AI summary, outcome, signals, recording and transcript of each call, and logging a call by hand.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Call, type CallList } from "../lib/api";
import { dateTime, human } from "../lib/format";
import { errText, inputCls } from "./deals";
import { Icon } from "./icons";
import { Button, Card, Chip, Empty, Loading, StatusTag } from "./ui";

const OUTCOME: Record<string, { label: string; tone: "good" | "warn" | "serious" }> = {
  connected: { label: "Connected", tone: "good" }, voicemail: { label: "Voicemail", tone: "warn" }, no_answer: { label: "No answer", tone: "serious" },
};
const RESULT: Record<string, string> = {
  meeting_booked: "Meeting booked", interested: "Interested", callback_requested: "Call back", needs_info: "Needs more info",
  not_interested: "Not interested", wrong_person: "Wrong person", no_conversation: "No conversation",
};
const PENDING = new Set(["queued", "analyzing"]);

export const duration = (s: number | null | undefined) => (s == null ? null : s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`);

export function analyzedBy(by: string | null) {
  if (!by) return null;
  if (by.startsWith("gemini:")) return `Summarised by Gemini (${by.slice(7)})`;
  return by === "provider" ? "Summary from the phone system; intent by keywords" : "Analysed by rules (Gemini not set up)";
}

export function CallStatus({ c }: { c: Pick<Call, "status"> }) {
  if (c.status === "done") return null;
  if (PENDING.has(c.status)) return <StatusTag status="warn">{c.status === "queued" ? "Waiting" : "Analysing…"}</StatusTag>;
  return <StatusTag status={c.status === "failed" ? "critical" : "serious"}>{c.status === "failed" ? "Failed" : "Needs a lead"}</StatusTag>;
}

export function CallView({ c }: { c: Call }) {
  const a = c.analysis;
  const [showText, setShowText] = useState(false);
  const rec = useMutation({ mutationFn: () => api.get<{ url: string }>(`/api/calls/${encodeURIComponent(c.id)}/recording`) });
  const o = a ? OUTCOME[a.outcome] : null;
  return (
    <article className="space-y-2 py-3 first:pt-0 last:pb-0" aria-label={`Call ${dateTime(c.ended_at ?? c.created_at)}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Icon name="phone" size={14} className="text-ink-3" />
        <span className="font-medium text-ink">{c.direction === "inbound" ? "They called" : "We called"}</span>
        <span className="text-xs text-ink-3">{dateTime(c.ended_at ?? c.created_at)}{duration(c.duration_s) ? ` · ${duration(c.duration_s)}` : ""}{c.provider === "manual" ? " · logged by hand" : ` · ${human(c.provider)}`}</span>
        <span className="ml-auto flex flex-wrap items-center gap-1.5">
          <CallStatus c={c} />
          {o && <StatusTag status={o.tone}>{o.label}</StatusTag>}
          {a && a.outcome === "connected" && <Chip tone={a.meeting_booked || a.result === "interested" ? "accent" : "neutral"}>{RESULT[a.result] ?? human(a.result)}</Chip>}
        </span>
      </div>
      {a?.summary ? <p className="text-sm text-ink-2">{a.summary}</p> : a && <p className="text-sm text-ink-3">No summary for this call.</p>}
      {a?.next_step && <p className="text-sm"><span className="font-medium text-ink">Next step: </span><span className="text-ink-2">{a.next_step}</span></p>}
      {a && (a.buying_signals.length > 0 || a.objections.length > 0 || a.competitors.length > 0) && (
        <dl className="grid gap-1 text-xs sm:grid-cols-[110px_1fr]">
          {a.buying_signals.length > 0 && <><dt className="text-ink-3">Buying signals</dt><dd className="text-good-ink">{a.buying_signals.join(" · ")}</dd></>}
          {a.objections.length > 0 && <><dt className="text-ink-3">Objections</dt><dd className="text-critical-ink">{a.objections.join(" · ")}</dd></>}
          {a.competitors.length > 0 && <><dt className="text-ink-3">Competitors</dt><dd className="text-ink-2">{a.competitors.join(" · ")}</dd></>}
        </dl>
      )}
      {c.error && <p role="alert" className="text-xs text-critical-ink">{c.error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {a && <span className="text-[11px] text-ink-3">{analyzedBy(c.analyzed_by)}{a.outcome === "connected" ? ` · sentiment ${a.sentiment}` : ""}</span>}
        <span className="ml-auto flex gap-1.5">
          {c.has_recording && !rec.data && <Button size="sm" variant="ghost" disabled={rec.isPending} onClick={() => rec.mutate()}>{rec.isPending ? "Loading…" : "Play recording"}</Button>}
          {!!c.transcript && <Button size="sm" variant="ghost" onClick={() => setShowText((s) => !s)}>{showText ? "Hide transcript" : c.provider === "manual" ? "Notes" : "Transcript"}</Button>}
        </span>
      </div>
      {rec.error && <p role="alert" className="text-xs text-critical-ink">Could not load the recording. {errText(rec.error)}</p>}
      {rec.data && <audio controls autoPlay src={rec.data.url} className="w-full" aria-label="Call recording" />}
      {showText && <pre className="scroll-thin max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface-2/50 p-3 text-xs leading-relaxed text-ink-2">{c.transcript}</pre>}
    </article>
  );
}

export function LeadCallsCard({ leadId }: { leadId: string }) {
  const [logging, setLogging] = useState(false);
  const q = useQuery({
    queryKey: ["lead", leadId, "calls"], queryFn: () => api.get<CallList>(`/api/leads/${leadId}/calls`),
    refetchInterval: (query) => (query.state.data?.items.some((c) => PENDING.has(c.status)) ? 1500 : false),
  });
  const items = q.data?.items ?? [];
  return (
    <Card id="calls" title="Calls" subtitle={q.data ? (q.data.gemini.configured ? "Summaries, outcomes and next steps by Gemini." : "Gemini is not set up: outcomes come from the phone system or simple rules.") : undefined}
      right={!logging ? <Button size="sm" onClick={() => setLogging(true)}>Log a call</Button> : undefined}>
      {logging && <LogCall leadId={leadId} ai={!!q.data?.gemini.configured} onDone={() => setLogging(false)} />}
      {q.isLoading ? <Loading rows={2} /> : q.error ? <Empty>Could not load calls. {errText(q.error)}</Empty>
        : !items.length ? (!logging && <p className="text-sm text-ink-3">No calls yet. Calls from your phone system appear here with a summary.</p>)
        : <div className="divide-y divide-[var(--c-line)]">{items.map((c) => <CallView key={c.id} c={c} />)}</div>}
    </Card>
  );
}

function LogCall({ leadId, ai, onDone }: { leadId: string; ai: boolean; onDone: () => void }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [outcome, setOutcome] = useState("");
  const [minutes, setMinutes] = useState("");
  const [direction, setDirection] = useState("outbound");
  const save = useMutation({
    mutationFn: () => api.post<Call>(`/api/leads/${leadId}/calls`, {
      notes, direction, outcome: outcome || null, duration_minutes: minutes === "" ? null : Number(minutes) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lead", leadId] }); onDone(); },
  });
  return (
    <form className="mb-4 space-y-3 rounded-xl border border-line p-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">What was said</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={5} placeholder={"Your notes, or paste a transcript (\"Customer: …\" lines are read as the prospect)."}
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink shadow-sm outline-none focus:border-brand focus:ring-4 focus:ring-brand/15" /></label>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">How it went</span>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className={inputCls} aria-label="How it went">
            <option value="">{ai ? "Let Gemini decide" : "Work it out from the notes"}</option>
            <option value="connected">Connected</option><option value="voicemail">Voicemail</option><option value="no_answer">No answer</option>
          </select></label>
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Who called</span>
          <select value={direction} onChange={(e) => setDirection(e.target.value)} className={inputCls} aria-label="Who called">
            <option value="outbound">We called them</option><option value="inbound">They called us</option>
          </select></label>
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Minutes</span>
          <input type="number" min={0} step={1} value={minutes} onChange={(e) => setMinutes(e.target.value)} className={inputCls} aria-label="Minutes" /></label>
      </div>
      {save.error && <p role="alert" className="text-sm text-critical-ink">{errText(save.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending || (!notes.trim() && !outcome)}>{save.isPending ? "Saving…" : "Save call"}</Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}
