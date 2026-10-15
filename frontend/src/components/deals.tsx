// Deal (opportunity) building blocks shared by the deal board, the account and deal pages, and the lead page.
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type DealStage as Stage, type LeadDetail, type Opportunity, type OpportunityDetail } from "../lib/api";
import { day, human, money, pct } from "../lib/format";
import { to } from "../lib/links";
import { Button, Card, Empty, StallFlag, StatusTag } from "./ui";

export const DEAL_STAGES: Stage[] = ["qualified", "meeting", "proposal", "negotiation", "won", "lost"];
export const ROLE_LABEL: Record<string, string> = { decision_maker: "Decision maker", manager: "Manager", practitioner: "User" };
export const KIND_LABEL: Record<string, string> = { new_business: "New business", expansion: "Expansion", renewal: "Renewal" };
export const inputCls = "h-10 w-full rounded-xl border border-line bg-surface px-3 text-sm text-ink shadow-sm outline-none transition placeholder:text-ink-3 focus:border-brand focus:ring-4 focus:ring-brand/15";
export const errText = (e: unknown) => (e instanceof Error ? e.message.replace(/^\d+: /, "") : String(e));

export function DealStage({ d }: { d: Pick<Opportunity, "stage" | "status"> }) {
  if (d.status === "won") return <StatusTag status="good">Won</StatusTag>;
  if (d.status === "lost") return <StatusTag status="critical">Lost</StatusTag>;
  return <span className="inline-flex items-center rounded-full border border-accent/30 bg-accent-soft/60 px-2 py-0.5 text-xs font-medium capitalize text-accent-ink">{human(d.stage)}</span>;
}

/** Three dots: decision maker, manager, user. Filled when someone in that role is involved. */
export function Committee({ covered }: { covered: string[] }) {
  const names = covered.map((r) => ROLE_LABEL[r] ?? r).join(", ");
  return (
    <span className="inline-flex items-center gap-1" title={`Buying committee: ${names || "nobody yet"}`}>
      {Object.keys(ROLE_LABEL).map((r) => (
        <span key={r} aria-hidden className={`h-1.5 w-3 rounded-full ${covered.includes(r) ? "bg-brand" : "bg-[var(--c-line)]"}`} />
      ))}
      <span className="sr-only">{covered.length} of 3 buying roles involved</span>
    </span>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-2 text-xs font-medium text-ink-2">{label}{hint && <span className="font-normal text-ink-3">{hint}</span>}</span>
      {children}
    </label>
  );
}

const QUOTE_WORD: Record<string, string> = { draft: "drafted", needs_approval: "awaiting approval", sent: "sent", expired: "expired", declined: "declined" };

export function DealCard({ d }: { d: Opportunity }) {
  const open = d.status === "open";
  return (
    <Link to={to.deal(d.opp_id)} className={`block rounded-xl border bg-surface p-3 text-sm shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-card ${d.is_stalled ? "border-[var(--c-critical)]" : "border-line hover:border-brand/40"}`}>
      <div className="truncate font-medium text-ink">{d.name}</div>
      <div className="truncate text-xs text-ink-3">{KIND_LABEL[d.kind]} · {d.contacts} contact{d.contacts === 1 ? "" : "s"}{open && d.quote ? ` · quote ${QUOTE_WORD[d.quote.status] ?? human(d.quote.status)}` : ""}</div>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs tabular text-ink-2">
        <span>{open ? `${money(d.expected_value)} · ${pct(d.close_prob)}` : money(d.acv)}</span>
        <Committee covered={d.committee_covered} />
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-ink-3">
        <span className="truncate">{d.owner_name ?? "Unassigned"}</span>
        {d.is_stalled && d.stall ? <StallFlag rules={d.stall.rules} risk={d.stall.risk} /> : <span className="shrink-0 tabular">{open ? `${d.days_in_stage.toFixed(1)}d` : day(d.closed_at)}</span>}
      </div>
    </Link>
  );
}

export function DealTable({ items, empty = "No deals yet." }: { items: Opportunity[]; empty?: ReactNode }) {
  if (!items.length) return <Empty>{empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="text-left text-xs text-ink-3">
          <tr className="border-b border-line">
            {["Deal", "Stage", "Value", "Chance", "Owner", "Opened"].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.opp_id} className="border-b border-line transition last:border-0 hover:bg-surface-2/60">
              <td className="px-5 py-2.5">
                <Link to={to.deal(d.opp_id)} className="drill font-medium text-ink">{d.name}</Link>
                <div className="text-xs text-ink-3">{KIND_LABEL[d.kind]} · {d.contacts} contact{d.contacts === 1 ? "" : "s"}</div>
              </td>
              <td className="px-5 py-2.5"><span className="inline-flex items-center gap-1.5"><DealStage d={d} />{d.is_stalled && d.stall && <StallFlag rules={d.stall.rules} />}</span></td>
              <td className="px-5 py-2.5 tabular">{money(d.acv)}</td>
              <td className="px-5 py-2.5 tabular">{d.status === "open" ? pct(d.close_prob) : "-"}</td>
              <td className="px-5 py-2.5">{d.owner_name ?? "Unassigned"}</td>
              <td className="px-5 py-2.5 tabular text-ink-2">{day(d.opened_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function NewDealForm({ leadId, onCancel }: { leadId: string; onCancel?: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [closeDate, setCloseDate] = useState("");
  const [kind, setKind] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<OpportunityDetail>("/api/opportunities", {
      lead_id: leadId, ...(name.trim() && { name: name.trim() }), ...(amount && { amount: Number(amount) }),
      ...(closeDate && { close_date: closeDate }), ...(kind && { kind }) }),
    onSuccess: (d) => { qc.invalidateQueries(); nav(to.deal(d.opp_id)); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Deal name" hint="optional"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Platform, EU rollout" className={inputCls} /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Amount ($)" hint="optional"><input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Predicted if empty" className={inputCls} /></Field>
        <Field label="Expected close"><input type="date" value={closeDate} onChange={(e) => setCloseDate(e.target.value)} className={inputCls} /></Field>
      </div>
      <Field label="Type">
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={inputCls}>
          <option value="">Automatic (expansion after a win)</option>
          {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      {create.isError && <p role="alert" className="text-sm text-critical-ink">{errText(create.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create deal"}</Button>
        {onCancel && <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}

// Lead page: the company this person belongs to and the deals they take part in.
export function LeadDealsCard({ l }: { l: LeadDetail }) {
  const [adding, setAdding] = useState(false);
  const deals = l.opportunities ?? [];
  return (
    <Card id="deals" title="Account & deals"
      subtitle={l.account_id ? <>Part of <Link className="drill font-medium text-ink" to={to.account(l.account_id)}>{l.company ?? l.account_id}</Link></> : "No company domain, so this lead is its own account"}
      right={l.status === "active" && !adding ? <Button size="sm" onClick={() => setAdding(true)}>New deal</Button> : undefined}>
      {adding && <div className="mb-4 rounded-xl border border-line bg-surface-2/40 p-3"><NewDealForm leadId={l.lead_id} onCancel={() => setAdding(false)} /></div>}
      {!deals.length ? <p className="text-sm text-ink-3">No deal yet. One opens automatically on a demo request, a sales enquiry or a meeting.</p> : (
        <ul className="space-y-2">
          {deals.map((d) => (
            <li key={d.opp_id} className="flex items-center justify-between gap-2 text-sm">
              <Link to={to.deal(d.opp_id)} className="drill min-w-0 truncate font-medium text-ink">{d.name}</Link>
              <span className="flex shrink-0 items-center gap-2"><span className="tabular text-xs text-ink-2">{money(d.acv)}</span><DealStage d={d} /></span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
