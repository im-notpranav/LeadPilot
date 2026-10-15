// Quotes on a deal: build one from the catalog or custom lines, get a big discount approved, send it, share the
// buyer's link, and record the answer. Every action is an event, so quotes replay like the rest of the deal.
import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type OpportunityDetail, type Quote, type QuoteCatalog, type QuoteLine, type QuoteStatus, type QuoteTotals } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, day } from "../lib/format";
import { Field, errText, inputCls } from "./deals";
import { Icon } from "./icons";
import { Button, Card, Chip, Loading, StatusTag } from "./ui";

export const QUOTE_STATUS: Record<QuoteStatus, { label: string; tone: "good" | "warn" | "serious" | "critical" | null }> = {
  draft: { label: "Draft", tone: null }, needs_approval: { label: "Needs approval", tone: "warn" }, sent: { label: "Sent", tone: "good" },
  expired: { label: "Expired", tone: "serious" }, accepted: { label: "Accepted", tone: "good" }, declined: { label: "Declined", tone: "critical" },
  void: { label: "Withdrawn", tone: null }, superseded: { label: "Replaced", tone: null },
};

export function QuoteStatusTag({ status }: { status: QuoteStatus }) {
  const s = QUOTE_STATUS[status];
  return s.tone ? <StatusTag status={s.tone}>{s.label}</StatusTag> : <Chip>{s.label}</Chip>;
}

export const cash = (v: number | null | undefined, currency = "USD") =>
  v == null ? "-" : new Intl.NumberFormat(undefined, { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);

/** Same arithmetic as the server (engine/quotes.py totals), for the live preview while editing. */
export function quoteTotals(lines: QuoteLine[], discountPct: number): QuoteTotals {
  const k = 1 - (discountPct || 0) / 100;
  const r2 = (x: number) => Math.round(x * 100) / 100;
  const list = lines.reduce((s, l) => s + l.qty * l.unit_price, 0);
  const net = lines.map((l) => l.qty * l.unit_price * (1 - l.discount_pct / 100));
  const subtotal = net.reduce((s, n) => s + n, 0);
  const recurring = net.reduce((s, n, i) => s + (lines[i].billing === "recurring" ? n : 0), 0) * k;
  const oneTime = net.reduce((s, n, i) => s + (lines[i].billing === "one_time" ? n : 0), 0) * k;
  const total = recurring + oneTime;
  return { list_total: r2(list), line_discounts: r2(list - subtotal), subtotal: r2(subtotal), quote_discount: r2(subtotal - total), recurring: r2(recurring), one_time: r2(oneTime), total: r2(total), effective_discount_pct: list ? r2(((list - total) / list) * 100) : 0, line_totals: net.map(r2) };
}

const per = (l: Pick<QuoteLine, "unit" | "billing">) => (l.billing === "one_time" ? `${l.unit ? `per ${l.unit}, ` : ""}one-time` : `${l.unit ? `per ${l.unit}, ` : ""}per year`);

/** The lines and totals, as the buyer sees them (also used on the deal page). A list on phones, a table above. */
export function QuoteTable({ lines, totals: t, discountPct, currency }: { lines: QuoteLine[]; totals: QuoteTotals; discountPct: number; currency: string }) {
  const c = (v: number) => cash(v, currency);
  return (
    <div>
      <ul className="divide-y divide-[var(--c-line)] sm:hidden">
        {lines.map((l, i) => (
          <li key={i} className="py-2 text-sm">
            <div className="flex items-baseline justify-between gap-3"><span className="font-medium text-ink">{l.name}</span><span className="shrink-0 tabular">{c(t.line_totals[i] ?? 0)}</span></div>
            {l.description && <div className="text-xs text-ink-3">{l.description}</div>}
            <div className="text-xs text-ink-2 tabular">{l.qty} × {c(l.unit_price)} {per(l)}{l.discount_pct ? ` · ${l.discount_pct}% off` : ""}</div>
          </li>
        ))}
      </ul>
      <table className="hidden w-full text-sm sm:table">
        <thead className="text-left text-xs text-ink-3">
          <tr className="border-b border-line">{["Item", "Qty", "Unit price", "Discount", "Amount"].map((h, i) => <th key={h} className={`py-2 font-medium ${i ? "text-right" : ""} ${i === 4 ? "" : "pr-3"}`}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i} className="border-b border-line align-top last:border-0">
              <td className="py-2 pr-3">
                <div className="font-medium text-ink">{l.name}</div>
                <div className="text-xs text-ink-3">{[l.description, per(l)].filter(Boolean).join(" · ")}</div>
              </td>
              <td className="py-2 pr-3 text-right tabular">{l.qty}</td>
              <td className="py-2 pr-3 text-right tabular">{c(l.unit_price)}</td>
              <td className="py-2 pr-3 text-right tabular">{l.discount_pct ? `${l.discount_pct}%` : "-"}</td>
              <td className="py-2 text-right tabular">{c(t.line_totals[i] ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="ml-auto mt-2 grid max-w-xs grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
        {t.line_discounts > 0 && <><dt className="text-ink-3">List price</dt><dd className="text-right tabular">{c(t.list_total)}</dd></>}
        <dt className="text-ink-3">Subtotal</dt><dd className="text-right tabular">{c(t.subtotal)}</dd>
        {discountPct > 0 && <><dt className="text-ink-3">Discount ({discountPct}%)</dt><dd className="text-right tabular">−{c(t.quote_discount)}</dd></>}
        {t.recurring > 0 && t.one_time > 0 && <><dt className="text-ink-3">Per year</dt><dd className="text-right tabular">{c(t.recurring)}</dd><dt className="text-ink-3">One-time</dt><dd className="text-right tabular">{c(t.one_time)}</dd></>}
        <dt className="border-t border-line pt-1 font-semibold text-ink">Total (first year)</dt><dd className="border-t border-line pt-1 text-right font-semibold tabular text-ink">{c(t.total)}</dd>
      </dl>
    </div>
  );
}

// ================================================================================================ the deal's quotes
export function DealQuotes({ d }: { d: OpportunityDetail }) {
  const cat = useQuery({ queryKey: ["quotes", "catalog"], queryFn: () => api.get<QuoteCatalog>("/api/quotes/catalog"), staleTime: 60_000 });
  const [editing, setEditing] = useState<{ mode: "new" | "edit" | "version"; base?: Quote } | null>(null);
  const live = d.quotes.filter((q) => q.status !== "void" && q.status !== "superseded");
  const old = d.quotes.filter((q) => q.status === "void" || q.status === "superseded");
  const [showOld, setShowOld] = useState(false);
  const open = d.status === "open";
  return (
    <Card id="quotes" title="Quotes" subtitle={open ? "Sending a quote moves the deal to proposal and sets its amount. When the buyer accepts, the deal is won." : "This deal is closed, so no new quotes."}
      right={open && !editing ? <Button size="sm" variant="primary" onClick={() => setEditing({ mode: "new" })}><Icon name="plus" size={13} />New quote</Button> : undefined}>
      {editing && (cat.data ? <QuoteEditor d={d} cat={cat.data} mode={editing.mode} base={editing.base} onDone={() => setEditing(null)} /> : <Loading rows={3} />)}
      {!d.quotes.length && !editing && <p className="text-sm text-ink-3">No quotes yet.{open ? " Build one from the catalog or your own lines." : ""}</p>}
      <div className="space-y-3">
        {live.map((q) => <QuoteItem key={q.quote_id} q={q} d={d} cat={cat.data} onEdit={(mode) => setEditing({ mode, base: q })} editing={!!editing} />)}
      </div>
      {old.length > 0 && (
        <div className="mt-3">
          <button type="button" className="text-xs font-medium text-accent-ink" onClick={() => setShowOld((s) => !s)}>{showOld ? "Hide" : "Show"} {old.length} withdrawn or replaced</button>
          {showOld && <div className="mt-2 space-y-3">{old.map((q) => <QuoteItem key={q.quote_id} q={q} d={d} cat={cat.data} onEdit={() => {}} editing />)}</div>}
        </div>
      )}
    </Card>
  );
}

const lineFrom = (p: QuoteCatalog["catalog"][number]): QuoteLine => ({ sku: p.sku, name: p.name, description: p.description, unit: p.unit, qty: 1, unit_price: p.price, discount_pct: 0, billing: p.billing });

function QuoteEditor({ d, cat, mode, base, onDone }: { d: OpportunityDetail; cat: QuoteCatalog; mode: "new" | "edit" | "version"; base?: Quote; onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(base?.title ?? `${d.name} quote`);
  const [leadId, setLeadId] = useState(base?.recipient.lead_id ?? d.primary_lead_id);
  const [lines, setLines] = useState<QuoteLine[]>(base ? base.lines.map((l) => ({ ...l })) : []);
  const [discount, setDiscount] = useState(base ? String(base.discount_pct || "") : "");
  const [validUntil, setValidUntil] = useState(mode === "edit" && base?.valid_until ? base.valid_until : "");
  const [notes, setNotes] = useState(base?.notes ?? "");
  const [pick, setPick] = useState("");
  const t = useMemo(() => quoteTotals(lines, Number(discount) || 0), [lines, discount]);
  const over = t.effective_discount_pct > cat.max_discount_pct;
  const set = (i: number, patch: Partial<QuoteLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const save = useMutation({
    mutationFn: () => {
      const body = { title: title.trim(), lines, discount_pct: Number(discount) || 0, notes, ...(validUntil && { valid_until: validUntil }) };
      return mode === "edit" && base ? api.patch<Quote>(`/api/quotes/${base.quote_id}`, body)
        : api.post<Quote>(`/api/opportunities/${d.opp_id}/quotes`, { ...body, lead_id: leadId, ...(mode === "version" && base && { supersedes: base.quote_id }) });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["deal", d.opp_id] }); onDone(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <form onSubmit={submit} className="mb-4 space-y-3 rounded-xl border border-line p-3" aria-label="Quote editor">
      <div className="text-sm font-semibold text-ink">{mode === "edit" ? `Edit ${base?.quote_id}` : mode === "version" ? `New version of ${base?.quote_id}` : "New quote"}</div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} /></Field>
        <Field label="For">
          <select value={leadId} onChange={(e) => setLeadId(e.target.value)} disabled={mode === "edit"} className={inputCls} aria-label="Recipient">
            {d.contacts_detail.map((c) => <option key={c.lead_id} value={c.lead_id}>{c.name ?? c.lead_id}{c.title ? ` (${c.title})` : ""}</option>)}
          </select>
        </Field>
      </div>
      <div className="space-y-2">
        {lines.length > 0 && <div className="hidden grid-cols-[1fr_70px_110px_80px_110px_32px] gap-2 px-2 text-xs font-medium text-ink-3 sm:grid" aria-hidden><span>Item</span><span>Qty</span><span>Unit price</span><span>Disc. %</span><span>Billing</span><span /></div>}
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 rounded-xl bg-surface-2/50 p-2 sm:grid-cols-[1fr_70px_110px_80px_110px_32px]" aria-label={`Line ${i + 1}`}>
            <input value={l.name} onChange={(e) => set(i, { name: e.target.value })} aria-label="Item" placeholder="Item" className={`${inputCls} col-span-2 sm:col-span-1`} />
            <input type="number" min={0} step="any" value={l.qty} onChange={(e) => set(i, { qty: Number(e.target.value) })} aria-label="Quantity" className={inputCls} />
            <input type="number" min={0} step="any" value={l.unit_price} onChange={(e) => set(i, { unit_price: Number(e.target.value) })} aria-label="Unit price" className={inputCls} />
            <input type="number" min={0} max={100} step="any" value={l.discount_pct} onChange={(e) => set(i, { discount_pct: Number(e.target.value) })} aria-label="Line discount %" className={inputCls} />
            <select value={l.billing} onChange={(e) => set(i, { billing: e.target.value as QuoteLine["billing"] })} aria-label="Billing" className={inputCls}>
              <option value="recurring">Per year</option><option value="one_time">One-time</option>
            </select>
            <Button size="sm" variant="ghost" title="Remove line" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><Icon name="close" size={13} /></Button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <select value={pick} aria-label="Add from catalog" className={`${inputCls} max-w-xs`} onChange={(e) => { const p = cat.catalog.find((x) => x.sku === e.target.value); if (p) setLines((ls) => [...ls, lineFrom(p)]); setPick(""); }}>
            <option value="">Add from catalog…</option>
            {cat.catalog.map((p) => <option key={p.sku} value={p.sku}>{p.name} · {cash(p.price, cat.currency)} {per(p)}</option>)}
          </select>
          <Button size="sm" onClick={() => setLines((ls) => [...ls, { sku: null, name: "", description: "", unit: "", qty: 1, unit_price: 0, discount_pct: 0, billing: "recurring" }])}>Custom line</Button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Discount on the whole quote (%)"><input type="number" min={0} max={100} step="any" value={discount} onChange={(e) => setDiscount(e.target.value)} className={inputCls} aria-label="Quote discount %" /></Field>
        <Field label="Valid until" hint={validUntil ? undefined : `${cat.valid_days} days if empty`}><input type="date" min={cat.today} value={validUntil} onChange={(e) => setValidUntil(e.target.value)} className={inputCls} aria-label="Valid until" /></Field>
        <div className="self-end text-right">
          <div className="text-xs text-ink-3">Total (first year)</div>
          <div className="font-display text-xl font-bold tabular text-ink" aria-label="Quote total">{cash(t.total, cat.currency)}</div>
          {t.effective_discount_pct > 0 && <div className={`text-xs ${over ? "font-medium text-critical-ink" : "text-ink-3"}`}>{t.effective_discount_pct.toFixed(1)}% off list{over ? ` · above ${cat.max_discount_pct}%: a manager approves before it is sent` : ""}</div>}
        </div>
      </div>
      <Field label="Note to the buyer" hint="optional"><textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink shadow-sm outline-none focus:border-brand focus:ring-4 focus:ring-brand/15" /></Field>
      {save.error && <p role="alert" className="text-sm text-critical-ink">{errText(save.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending || !lines.length}>{save.isPending ? "Saving…" : mode === "edit" ? "Save changes" : "Save draft"}</Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function QuoteItem({ q, d, cat, onEdit, editing }: { q: Quote; d: OpportunityDetail; cat?: QuoteCatalog; onEdit: (mode: "edit" | "version") => void; editing: boolean }) {
  const qc = useQueryClient();
  const { me } = useAuth();
  const [open, setOpen] = useState(q.status !== "superseded" && q.status !== "void");
  const [answer, setAnswer] = useState<"accept" | "decline" | null>(null);
  const [text, setText] = useState("");
  const [email, setEmail] = useState(false);
  const [copied, setCopied] = useState(false);
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post<Quote>(`/api/quotes/${q.quote_id}/${path}`, body ?? {}),
    onSuccess: () => { setAnswer(null); setText(""); qc.invalidateQueries({ queryKey: ["deal", d.opp_id] }); qc.invalidateQueries({ queryKey: ["notifications"] }); },
  });
  const manager = me?.role === "admin" || me?.role === "manager";
  const link = q.link ? `${window.location.origin}${q.link}` : null;
  const dealOpen = d.status === "open";
  const copy = () => { if (link) navigator.clipboard?.writeText(link).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000); }); };

  return (
    <article className="rounded-xl border border-line" aria-label={`Quote ${q.quote_id}`}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-left">
        <span className="font-mono text-xs text-ink-3">{q.quote_id}</span>
        <span className="min-w-0 flex-1 truncate font-medium text-ink">{q.title}</span>
        <QuoteStatusTag status={q.status} />
        <span className="font-semibold tabular text-ink">{cash(q.totals.total, q.currency)}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-line px-3 pb-3 pt-2.5">
          <p className="text-xs text-ink-3">
            For {q.recipient.name ?? "the contact"}{q.recipient.title ? ` (${q.recipient.title})` : ""} · valid until {day(q.valid_until)} · drafted {dateTime(q.created_at)}{q.created_by ? ` by ${q.created_by}` : ""}{q.rev > 1 ? ` · revision ${q.rev}` : ""}
            {q.sent_at && ` · sent ${dateTime(q.sent_at)}`}{q.views > 0 && ` · opened ${q.views}× (last ${dateTime(q.last_viewed_at)})`}
            {q.approved_by && ` · discount approved by ${q.approved_by}`}
          </p>
          <QuoteTable lines={q.lines} totals={q.totals} discountPct={q.discount_pct} currency={q.currency} />
          {q.notes && <p className="whitespace-pre-wrap text-sm text-ink-2">{q.notes}</p>}
          {q.status === "accepted" && <p className="text-sm text-good-ink">Accepted {dateTime(q.accepted_at)}{q.accepted_by?.name ? ` by ${q.accepted_by.name}` : ""}{q.accepted_by?.recorded_by ? ` (recorded by ${q.accepted_by.recorded_by})` : " through the quote link"}.</p>}
          {q.status === "declined" && <p className="text-sm text-critical-ink">Declined {dateTime(q.declined_at)}{q.decline_reason ? `: ${q.decline_reason}` : "."}</p>}
          {q.status === "void" && <p className="text-sm text-ink-3">Withdrawn {dateTime(q.voided_at)}{q.void_reason ? `: ${q.void_reason}` : "."}</p>}
          {q.status === "superseded" && q.superseded_by && <p className="text-sm text-ink-3">Replaced by {q.superseded_by}.</p>}
          {q.status === "needs_approval" && <p className="text-sm text-ink-2">{q.totals.effective_discount_pct.toFixed(1)}% off list is above the {q.max_discount_pct}% limit. {manager ? "Approve it so the rep can send it." : "A manager has been asked to approve it."}</p>}

          {!editing && dealOpen && (
            <div className="flex flex-wrap items-center gap-2">
              {q.status === "needs_approval" && manager && <Button size="sm" variant="primary" disabled={act.isPending} onClick={() => act.mutate({ path: "approve" })}>Approve discount</Button>}
              {(q.status === "draft" || q.status === "needs_approval") && <Button size="sm" onClick={() => onEdit("edit")}>Edit</Button>}
              {q.status === "draft" && <>
                {cat?.email.ready && <label className="flex items-center gap-1.5 text-xs text-ink-2"><input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />Email it to {q.recipient.email ?? "the contact"}</label>}
                <Button size="sm" variant="primary" disabled={act.isPending} onClick={() => act.mutate({ path: "send", body: { email } })}>{email ? "Send by email" : "Mark as sent"}</Button>
              </>}
              {q.status === "sent" && link && <>
                <Button size="sm" onClick={copy}><Icon name="copy" size={13} />{copied ? "Copied" : "Copy buyer link"}</Button>
                <a href={`${q.link}?preview=1`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-xl px-2.5 py-1 text-xs font-medium text-accent-ink hover:bg-surface-2">Open as the buyer<Icon name="external" size={12} /></a>
                <Button size="sm" onClick={() => setAnswer("accept")}>Buyer accepted</Button>
                <Button size="sm" onClick={() => setAnswer("decline")}>Buyer declined</Button>
              </>}
              {["sent", "expired", "declined"].includes(q.status) && <Button size="sm" onClick={() => onEdit("version")}>New version</Button>}
              {["draft", "needs_approval", "sent", "expired"].includes(q.status) && <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => act.mutate({ path: "void" })}>Withdraw</Button>}
            </div>
          )}
          {q.status === "draft" && !cat?.email.ready && cat?.email.reason && !editing && dealOpen && <p className="text-[11px] text-ink-3">Emailing is off: {cat.email.reason} Copy the buyer link once it is sent.</p>}
          {answer && (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: answer, body: answer === "accept" ? { name: text } : { reason: text } }); }}>
              <label className="min-w-[200px] flex-1"><span className="mb-1 block text-xs font-medium text-ink-2">{answer === "accept" ? "Who accepted? (optional)" : "Why? (optional)"}</span>
                <input value={text} onChange={(e) => setText(e.target.value)} className={inputCls} /></label>
              <Button type="submit" variant={answer === "accept" ? "primary" : "danger"} disabled={act.isPending}>{answer === "accept" ? "Record acceptance (wins the deal)" : "Record decline"}</Button>
              <Button variant="ghost" onClick={() => setAnswer(null)}>Cancel</Button>
            </form>
          )}
          {act.error && <p role="alert" className="text-sm text-critical-ink">{errText(act.error)}</p>}
        </div>
      )}
    </article>
  );
}
