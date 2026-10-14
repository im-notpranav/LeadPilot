// Deal (opportunity) building blocks shared by the deals board, the account page and the lead page.
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type LeadDetail, type Opportunity, type OpportunityDetail } from "../lib/api";
import { day, human, money, pct } from "../lib/format";
import { Button, Card, Empty, StallFlag, StatusTag } from "./ui";

export const ROLE_LABEL: Record<string, string> = { decision_maker: "Decision maker", manager: "Manager", practitioner: "User" };
export const KIND_LABEL: Record<string, string> = { new_business: "New business", expansion: "Expansion", renewal: "Renewal" };
const input = "h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/30";
export const errText = (e: unknown) => (e instanceof Error ? e.message.replace(/^\d+: /, "") : String(e));

export function DealStage({ d }: { d: Pick<Opportunity, "stage" | "status"> }) {
  if (d.status === "won") return <StatusTag status="good">Won</StatusTag>;
  if (d.status === "lost") return <StatusTag status="critical">Lost</StatusTag>;
  return <span className="inline-flex items-center rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs font-medium capitalize text-ink">{human(d.stage)}</span>;
}

export function Committee({ covered }: { covered: string[] }) {
  return (
    <span className="inline-flex items-center gap-1" title={`Buying committee: ${covered.map((r) => ROLE_LABEL[r] ?? r).join(", ") || "nobody yet"}`}>
      {Object.keys(ROLE_LABEL).map((r) => (
        <span key={r} aria-hidden className={`h-1.5 w-3 rounded-full ${covered.includes(r) ? "bg-accent" : "bg-line"}`} />
      ))}
      <span className="sr-only">{covered.length} of 3 buying roles engaged</span>
    </span>
  );
}

export function DealCard({ d }: { d: Opportunity }) {
  return (
    <Link to={`/deals/${d.opp_id}`} className={`block rounded-lg border bg-surface p-2.5 text-sm transition hover:shadow-sm ${d.is_stalled ? "border-[var(--c-critical)]" : "border-line"}`}>
      <div className="truncate font-medium">{d.name}</div>
      <div className="truncate text-xs text-ink-3">{KIND_LABEL[d.kind]} · {d.contacts} contact{d.contacts === 1 ? "" : "s"}</div>
      <div className="mt-2 flex items-center justify-between text-xs tabular text-ink-2">
        <span>{d.status === "open" ? `${money(d.expected_value)} · ${pct(d.close_prob)}` : money(d.acv)}</span>
        <Committee covered={d.committee_covered} />
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-ink-3">
        <span className="truncate">{d.owner_name ?? "Unassigned"}</span>
        {d.is_stalled && d.stall ? <StallFlag rules={d.stall.rules} risk={d.stall.risk} /> : <span className="tabular">{d.status === "open" ? `${d.days_in_stage.toFixed(1)}d` : day(d.closed_at)}</span>}
      </div>
    </Link>
  );
}

export function DealTable({ items, empty = "No deals yet." }: { items: Opportunity[]; empty?: string }) {
  if (!items.length) return <Empty>{empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="text-left text-xs text-ink-3">
          <tr className="border-b border-line">
            {["Deal", "Stage", "Value", "Chance", "Owner", "Opened"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.opp_id} className="border-b border-line last:border-0">
              <td className="px-4 py-2.5"><Link to={`/deals/${d.opp_id}`} className="font-medium text-ink hover:underline">{d.name}</Link>
                <div className="text-xs text-ink-3">{KIND_LABEL[d.kind]} · {d.contacts} contact{d.contacts === 1 ? "" : "s"}</div></td>
              <td className="px-4 py-2.5"><DealStage d={d} /></td>
              <td className="px-4 py-2.5 tabular">{money(d.acv)}</td>
              <td className="px-4 py-2.5 tabular">{d.status === "open" ? pct(d.close_prob) : "—"}</td>
              <td className="px-4 py-2.5">{d.owner_name ?? "Unassigned"}</td>
              <td className="px-4 py-2.5 tabular text-ink-2">{day(d.opened_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function NewDealForm({ leadId, onDone }: { leadId: string; onDone?: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [closeDate, setCloseDate] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<OpportunityDetail>("/api/opportunities", {
      lead_id: leadId, ...(name.trim() && { name: name.trim() }), ...(amount && { amount: Number(amount) }),
      ...(closeDate && { close_date: closeDate }) }),
    onSuccess: (d) => { qc.invalidateQueries(); onDone?.(); nav(`/deals/${d.opp_id}`); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-2">
      <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Deal name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Platform, EU rollout" className={input} /></label>
      <div className="grid grid-cols-2 gap-2">
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Amount ($)</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="optional" className={input} /></label>
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Expected close</span>
          <input type="date" value={closeDate} onChange={(e) => setCloseDate(e.target.value)} className={input} /></label>
      </div>
      {create.isError && <p role="alert" className="text-sm text-critical-ink">{errText(create.error)}</p>}
      <Button type="submit" variant="primary" size="sm" disabled={create.isPending}>Create deal</Button>
    </form>
  );
}

// Lead page: the company this person belongs to and the deals they take part in.
export function LeadDealsCard({ l }: { l: LeadDetail }) {
  const [adding, setAdding] = useState(false);
  const deals = l.opportunities ?? [];
  return (
    <Card title="Account & deals" subtitle={l.account_id ? <>Part of <Link className="text-accent-ink hover:underline" to={`/accounts/${l.account_id}`}>{l.company ?? l.account_id}</Link></> : "No company domain: this lead is its own account"}
      right={l.status === "active" && !adding ? <Button size="sm" onClick={() => setAdding(true)}>New deal</Button> : undefined}>
      {adding && <div className="mb-3 rounded-lg border border-line p-3"><NewDealForm leadId={l.lead_id} onDone={() => setAdding(false)} /></div>}
      {!deals.length ? <p className="text-sm text-ink-3">No deal yet. One opens automatically on a demo request, a sales enquiry or a meeting.</p> : (
        <ul className="space-y-2">
          {deals.map((d) => (
            <li key={d.opp_id} className="flex items-center justify-between gap-2 text-sm">
              <Link to={`/deals/${d.opp_id}`} className="min-w-0 truncate font-medium text-ink hover:underline">{d.name}</Link>
              <span className="flex shrink-0 items-center gap-2"><span className="tabular text-xs text-ink-2">{money(d.acv)}</span><DealStage d={d} /></span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
