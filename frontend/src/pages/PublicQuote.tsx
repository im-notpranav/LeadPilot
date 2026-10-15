// The buyer's view of a quote, opened from its link (/q/<token>) without signing in. They can read it, print it,
// and accept or decline it. The link's token is the only key, so nothing internal is shown here.
import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { BuyerQuote } from "../lib/api";
import { dateTime, day } from "../lib/format";
import { Field, inputCls } from "../components/deals";
import { Icon } from "../components/icons";
import { QuoteStatusTag, QuoteTable, cash } from "../components/quotes";
import { Button } from "../components/ui";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Something went wrong (${r.status})`);
  return data as T;
}

export default function PublicQuote() {
  const [, , token = ""] = window.location.pathname.split("/");
  const preview = new URLSearchParams(window.location.search).has("preview");
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["public-quote", token], queryFn: () => call<BuyerQuote>("GET", `/api/public/quotes/${encodeURIComponent(token)}${preview ? "?preview=1" : ""}`), retry: false });
  const [mode, setMode] = useState<"accept" | "decline" | null>(null);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [reason, setReason] = useState("");
  const answer = useMutation({
    mutationFn: () => mode === "accept" ? call<BuyerQuote>("POST", `/api/public/quotes/${encodeURIComponent(token)}/accept`, { name, title })
      : call<BuyerQuote>("POST", `/api/public/quotes/${encodeURIComponent(token)}/decline`, { reason }),
    onSuccess: (fresh) => { qc.setQueryData(["public-quote", token], fresh); setMode(null); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); answer.mutate(); };

  if (q.isLoading) return <Frame><p className="text-sm text-ink-3">Loading your quote…</p></Frame>;
  if (q.error || !q.data) return <Frame><h1 className="font-display text-xl font-bold">Quote not found</h1><p className="mt-2 text-sm text-ink-2">This link is not valid, or the quote was withdrawn. Ask your contact for a new link.</p></Frame>;
  const d = q.data;
  return (
    <Frame>
      {preview && <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs text-ink-2 print:hidden">Preview: this is what the buyer sees. Opening it here does not count as a view.</p>}
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-3">{d.seller_name}</div>
          <h1 className="mt-1 font-display text-2xl font-extrabold tracking-tight text-ink">{d.title}</h1>
          <p className="mt-1 text-sm text-ink-2">Quote {d.quote_id}{d.recipient.name ? ` for ${d.recipient.name}` : ""}{d.company ? `, ${d.company}` : ""}</p>
        </div>
        <div className="text-sm sm:text-right">
          <QuoteStatusTag status={d.status} />
          <div className="mt-2 text-ink-3">Valid until <span className="font-medium text-ink">{day(d.valid_until)}</span></div>
          {d.sent_at && <div className="text-ink-3">Sent {day(d.sent_at)}</div>}
        </div>
      </header>
      <section className="py-4"><QuoteTable lines={d.lines} totals={d.totals} discountPct={d.discount_pct} currency={d.currency} /></section>
      {d.notes && <section className="border-t border-line py-4"><h2 className="text-xs font-semibold uppercase tracking-wider text-ink-3">Note</h2><p className="mt-1 whitespace-pre-wrap text-sm text-ink-2">{d.notes}</p></section>}
      {d.terms && <section className="border-t border-line py-4"><h2 className="text-xs font-semibold uppercase tracking-wider text-ink-3">Terms</h2><p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-ink-3">{d.terms}</p></section>}

      <section className="border-t border-line pt-4 print:hidden" aria-label="Your answer">
        {d.status === "accepted" && <p role="status" className="text-sm font-medium text-good-ink">Accepted {dateTime(d.accepted_at)}{d.accepted_by?.name ? ` by ${d.accepted_by.name}` : ""}. Thank you, we will be in touch about next steps.</p>}
        {d.status === "declined" && <p role="status" className="text-sm text-ink-2">You declined this quote {dateTime(d.declined_at)}. Thanks for letting us know.</p>}
        {d.status === "expired" && <p className="text-sm text-ink-2">This quote has expired. Ask your contact for an updated one.</p>}
        {d.status === "superseded" && <p className="text-sm text-ink-2">There is a newer version of this quote. Ask your contact for its link.</p>}
        {d.answerable && !mode && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={() => setMode("accept")}>Accept quote · {cash(d.totals.total, d.currency)}</Button>
            <Button onClick={() => setMode("decline")}>Decline</Button>
            <Button variant="ghost" onClick={() => window.print()}><Icon name="printer" size={14} />Print or save as PDF</Button>
          </div>
        )}
        {mode === "accept" && (
          <form onSubmit={submit} className="space-y-3">
            <p className="text-sm text-ink-2">By accepting you agree to this quote and its terms. Type your name to sign.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Your full name"><input required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} autoComplete="name" /></Field>
              <Field label="Your title" hint="optional"><input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} autoComplete="organization-title" /></Field>
            </div>
            <div className="flex gap-2"><Button type="submit" variant="primary" disabled={answer.isPending || !name.trim()}>{answer.isPending ? "Sending…" : "Accept and sign"}</Button><Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button></div>
          </form>
        )}
        {mode === "decline" && (
          <form onSubmit={submit} className="space-y-3">
            <Field label="Anything we should know?" hint="optional"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink shadow-sm outline-none focus:border-brand focus:ring-4 focus:ring-brand/15" /></Field>
            <div className="flex gap-2"><Button type="submit" variant="danger" disabled={answer.isPending}>{answer.isPending ? "Sending…" : "Decline quote"}</Button><Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button></div>
          </form>
        )}
        {answer.error && <p role="alert" className="mt-2 text-sm text-critical-ink">{answer.error.message}</p>}
      </section>
    </Frame>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen px-4 py-8 print:bg-white print:p-0">
      <div className="card mx-auto max-w-3xl rounded-2xl p-6 print:border-0 print:shadow-none sm:p-8">{children}</div>
    </main>
  );
}
