// One deal: where it stands, how it got there (every move with its rule), who is involved, what it is worth, and edits.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DealStage as Stage, type OpportunityDetail } from "../lib/api";
import { useLive } from "../lib/live";
import { ago, dateTime, day, human, money, pct, signed } from "../lib/format";
import { to } from "../lib/links";
import { DEAL_STAGES, DealStage, Field, KIND_LABEL, ROLE_LABEL, errText, inputCls } from "../components/deals";
import { Icon } from "../components/icons";
import { Button, Card, Chip, Empty, GradePill, Loading, StageBadge, StallFlag, Stat } from "../components/ui";

const OPEN: Stage[] = ["qualified", "meeting", "proposal", "negotiation"];

export default function Deal() {
  const { id = "" } = useParams();
  const { clock } = useLive();
  const q = useQuery({ queryKey: ["deal", id], queryFn: () => api.get<OpportunityDetail>(`/api/opportunities/${id}`) });

  if (q.isLoading) return <Card><Loading rows={5} /></Card>;
  if (q.error || !q.data) return <Empty>Deal not found, or none of its contacts are yours. <Link className="text-accent-ink underline" to={to.deals()}>Deal board</Link></Empty>;
  const d = q.data;
  const open = d.status === "open";
  const primary = d.contacts_detail.find((c) => c.primary);

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-sm text-ink-3">
        <Link to={to.deals()} className="drill">Deals</Link><Icon name="chevronRight" size={13} />
        {d.account_id && <><Link to={to.account(d.account_id)} className="drill">{d.company ?? d.account_id}</Link><Icon name="chevronRight" size={13} /></>}
        <span className="font-medium text-ink">{d.name}</span>
      </nav>

      <section className="card relative isolate overflow-hidden rounded-2xl p-5">
        <div className="pointer-events-none absolute -right-16 -top-24 -z-10 h-56 w-56 rounded-full bg-[var(--c-glow-1)] blur-3xl" aria-hidden />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-display text-2xl font-extrabold tracking-tight">{d.name}</h1>
              <DealStage d={d} />
              <Chip>{KIND_LABEL[d.kind]}</Chip>
              {d.is_stalled && d.stall && <StallFlag rules={d.stall.rules} risk={d.stall.risk} />}
            </div>
            <p className="mt-1 text-sm text-ink-2">
              {d.account_id ? <Link to={to.account(d.account_id)} className="drill">{d.company ?? d.account_id}</Link> : d.company ?? "No company"} · opened {day(d.opened_at)}
              {d.created_by ? ` by ${d.created_by}` : " on a buying signal"}{primary && <> · main contact <Link to={to.lead(primary.lead_id)} className="drill">{primary.name ?? primary.lead_id}</Link></>}
            </p>
            <p className="mt-0.5 text-xs text-ink-3">{d.opp_id} · {d.events} events · opened by rule {d.open_rule}</p>
          </div>
          <div className="flex items-center gap-2 text-sm"><span className="text-ink-3">Owner</span>{d.owner_rep_id ? <Link to={to.queue(d.owner_rep_id)} className="drill font-medium">{d.owner_name}</Link> : <span className="font-medium">Unassigned</span>}</div>
        </div>
        <StagePath d={d} />
        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Value" value={money(d.acv)} sub={d.amount ? "set on the deal" : "predicted ACV"} />
          <Stat label="Chance to win" value={open ? pct(d.close_prob, 1) : d.status === "won" ? "Won" : "Lost"} sub={open ? "from fit, intent and stage" : day(d.closed_at)} />
          <Stat label="Expected value" value={open ? money(d.expected_value) : "-"} sub="value × chance" />
          <Stat label="In this stage" value={open ? `${d.days_in_stage.toFixed(1)}d` : "-"} sub={d.stall?.sla_days ? `stage time limit ${d.stall.sla_days}d` : human(d.stage)} />
          <Stat label="Expected close" value={d.close_date ? day(d.close_date) : "-"} sub={d.close_date ? "set by the rep" : "not set"} />
          <Stat label="Last activity" value={d.last_activity_at ? ago(d.last_activity_at, clock.now) : "-"} sub={`${d.contacts} contact${d.contacts === 1 ? "" : "s"}`} />
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <History d={d} />
          <Contacts d={d} />
        </div>
        <div className="min-w-0 space-y-4">
          <EditDeal d={d} />
          <Committee d={d} />
          <Worth d={d} />
          {d.is_stalled && d.stall && (
            <Card title="Stall watch">
              <ul className="space-y-1 text-sm text-ink-2">{d.stall.details.map((x) => <li key={x}>{x}</li>)}</ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

/** qualified → meeting → proposal → negotiation → won/lost, with the current step lit. */
function StagePath({ d }: { d: OpportunityDetail }) {
  const at = d.status === "open" ? OPEN.indexOf(d.stage) : OPEN.length;
  const last = d.status === "lost" ? "Lost" : "Won";
  return (
    <ol className="mt-4 grid grid-cols-5 gap-1.5" aria-label="Deal stages">
      {[...OPEN, last].map((s, i) => {
        const done = i < at || (i === at && d.status !== "open");
        const now = i === at && d.status === "open";
        const tone = i === OPEN.length && d.status === "lost" ? "bg-critical" : done || now ? "bg-brand" : "bg-[var(--c-line)]";
        return (
          <li key={s} aria-current={now ? "step" : undefined} className="min-w-0">
            <div className={`h-1.5 rounded-full ${tone} ${now ? "animate-pulse" : ""}`} />
            <div className={`mt-1 truncate text-xs capitalize ${now || (done && i === OPEN.length) ? "font-semibold text-ink" : "text-ink-3"}`}>{human(s)}</div>
          </li>
        );
      })}
    </ol>
  );
}

function History({ d }: { d: OpportunityDetail }) {
  const items = d.transitions.slice().reverse();
  return (
    <Card title="Stage history" subtitle="Every move, newest first, with the rule that made it and the evidence behind it.">
      {!items.length ? <p className="text-sm text-ink-3">No moves yet.</p> : (
        <ol className="space-y-0">
          {items.map((t, i) => (
            <li key={i} className="grid grid-cols-[120px_1fr] gap-3 border-b border-line py-2.5 text-sm last:border-0">
              <div className="text-xs tabular text-ink-3">{dateTime(t.ts)}</div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  {t.from ? <><span className="capitalize text-ink-2">{human(t.from)}</span><Icon name="arrowRight" size={12} className="text-ink-3" /></> : <span className="text-ink-2">Opened in</span>}
                  <span className="font-medium capitalize text-ink">{human(t.to)}</span>
                  <Chip title="Rule">{t.rule_id}</Chip>
                  {t.mode === "manual" && <Chip tone="accent">by hand</Chip>}
                </div>
                <div className="mt-0.5 text-xs text-ink-3">{t.reason}{t.evidence.length ? ` · ${t.evidence.length} event${t.evidence.length === 1 ? "" : "s"} as evidence` : ""}</div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function Contacts({ d }: { d: OpportunityDetail }) {
  return (
    <Card pad={false} title="People on this deal" subtitle="Contacts at the company who took part. The main contact is the one the deal opened with.">
      {!d.contacts_detail.length ? <Empty>No contacts you can see.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-xs text-ink-3"><tr className="border-b border-line">{["Name", "Role", "Score", "Stage"].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {d.contacts_detail.map((c) => (
                <tr key={c.lead_id} className="border-b border-line last:border-0">
                  <td className="px-5 py-2.5">
                    <Link to={to.lead(c.lead_id)} className="drill font-medium text-ink">{c.name ?? c.lead_id}</Link>{c.primary && <span className="ml-1.5"><Chip tone="accent">main contact</Chip></span>}
                    <div className="text-xs text-ink-3">{c.title ?? "No title"}</div>
                  </td>
                  <td className="px-5 py-2.5 text-ink-2">{ROLE_LABEL[roleOf(d, c.lead_id)] ?? "-"}</td>
                  <td className="px-5 py-2.5"><GradePill grade={c.grade} score={c.score} /></td>
                  <td className="px-5 py-2.5"><StageBadge stage={c.stage} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const roleOf = (d: OpportunityDetail, leadId: string) => Object.entries(d.committee?.roles ?? {}).find(([, ids]) => ids.includes(leadId))?.[0] ?? "";

function Committee({ d }: { d: OpportunityDetail }) {
  const c = d.committee;
  if (!c) return null;
  return (
    <Card title="Buying committee" subtitle={c.missing.length ? "Bring in the missing roles: each one involved raises the chance to win." : "Every buying role is involved."}>
      <ul className="space-y-2 text-sm">
        {Object.keys(ROLE_LABEL).map((r) => {
          const ids = c.roles[r] ?? [];
          const names = ids.map((id) => d.contacts_detail.find((p) => p.lead_id === id)?.name ?? id);
          return (
            <li key={r} className="flex items-start justify-between gap-3">
              <span className="font-medium text-ink">{ROLE_LABEL[r]}</span>
              {ids.length ? <span className="min-w-0 truncate text-right text-ink-2">{names.join(", ")}</span> : <span className="text-xs font-medium text-critical-ink">Missing</span>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Worth({ d }: { d: OpportunityDetail }) {
  const maxAbs = Math.max(1, ...d.close_factors.map((f) => Math.abs(f.logit ?? 0)).filter((_, i) => i > 0));
  return (
    <Card title="Value and chance" subtitle={d.status === "open" ? `${money(d.acv)} × ${pct(d.close_prob, 1)} = ${money(d.expected_value)} expected` : undefined}>
      <div className="space-y-1 text-sm">
        {d.acv_factors.map((f) => (
          <div key={f.key} className="flex justify-between gap-2"><span className="text-ink-2">{f.label}</span><span className="tabular">{f.kind === "multiplier" ? `×${f.value}` : money(f.value)}</span></div>
        ))}
      </div>
      {d.status === "open" && (
        <div className="mt-3 border-t border-line pt-3">
          <div className="mb-1.5 text-xs text-ink-3">What moves the chance (log-odds)</div>
          {d.close_factors.map((f, i) => (
            <div key={f.key} className="grid grid-cols-[1fr_90px_44px] items-center gap-2 py-0.5 text-xs">
              <span className="truncate text-ink-2">{f.label}</span>
              {i === 0 || f.logit == null ? <span /> : (
                <span className="relative h-2 rounded bg-surface-2">
                  <span className="absolute top-0 h-2 rounded" style={{ left: f.logit >= 0 ? "50%" : `${50 - (Math.abs(f.logit) / maxAbs) * 50}%`, width: `${(Math.abs(f.logit) / maxAbs) * 50}%`, background: f.logit >= 0 ? "var(--series-1)" : "var(--series-2)" }} />
                </span>
              )}
              <span className="text-right tabular">{f.logit == null ? "" : signed(f.logit, 2)}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function EditDeal({ d }: { d: OpportunityDetail }) {
  const qc = useQueryClient();
  const [name, setName] = useState(d.name);
  const [amount, setAmount] = useState(d.amount != null ? String(d.amount) : "");
  const [closeDate, setCloseDate] = useState(d.close_date ?? "");
  const [stage, setStage] = useState<Stage>(d.stage);
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState(false);
  // A save, or a live update from the engine, refreshes the form.
  useEffect(() => { setName(d.name); setAmount(d.amount != null ? String(d.amount) : ""); setCloseDate(d.close_date ?? ""); setStage(d.stage); setReason(""); }, [d.name, d.amount, d.close_date, d.stage]);

  const changes = {
    ...(name.trim() && name.trim() !== d.name && { name: name.trim() }),
    ...(amount !== "" && Number(amount) !== d.amount && { amount: Number(amount) }),
    ...(closeDate && closeDate !== d.close_date && { close_date: closeDate }),
    ...(stage !== d.stage && { stage, ...(reason.trim() && (stage === "lost" ? { lost_reason: reason.trim() } : { reason: reason.trim() })) }),
  };
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch<OpportunityDetail>(`/api/opportunities/${d.opp_id}`, body),
    onSuccess: (fresh) => { qc.setQueryData(["deal", d.opp_id], fresh); qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "deal" }); setSaved(true); window.setTimeout(() => setSaved(false), 2500); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (Object.keys(changes).length) save.mutate(changes); };
  const moving = stage !== d.stage;

  return (
    <Card id="edit" title="Update deal" subtitle={d.status === "open" ? "Changes are saved as events, so they show in the history and survive a replay." : "This deal is closed. Pick an open stage to reopen it."}>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Deal name"><input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Amount ($)" hint={d.amount ? undefined : "predicted if empty"}><input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder={d.acv ? String(Math.round(d.acv)) : ""} className={inputCls} /></Field>
          <Field label="Expected close"><input type="date" value={closeDate} onChange={(e) => setCloseDate(e.target.value)} className={inputCls} /></Field>
        </div>
        <Field label="Stage">
          <select value={stage} onChange={(e) => setStage(e.target.value as Stage)} className={`${inputCls} capitalize`}>
            {DEAL_STAGES.map((s) => <option key={s} value={s}>{human(s)}</option>)}
          </select>
        </Field>
        {moving && (
          <Field label={stage === "lost" ? "Why was it lost?" : "Reason for the move"} hint="optional">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={stage === "lost" ? "e.g. went with a competitor" : "e.g. verbal yes on the call"} className={inputCls} />
          </Field>
        )}
        {d.lost_reason && d.status === "lost" && !moving && <p className="text-sm text-ink-2">Lost because: <span className="text-ink">{d.lost_reason}</span></p>}
        {save.isError && <p role="alert" className="text-sm text-critical-ink">{errText(save.error)}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={save.isPending || !Object.keys(changes).length}>{save.isPending ? "Saving…" : "Save changes"}</Button>
          {d.status === "open" && !moving && <>
            <Button size="sm" onClick={() => setStage("won")}>Mark won</Button>
            <Button size="sm" variant="danger" onClick={() => setStage("lost")}>Mark lost</Button>
          </>}
          {saved && <span role="status" className="text-xs font-medium text-good-ink">Saved</span>}
        </div>
      </form>
    </Card>
  );
}
