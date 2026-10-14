// One company: who we know there, which buying roles they cover, and every deal with them.
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type AccountDetail, type AccountPerson } from "../lib/api";
import { ago, human, money, num } from "../lib/format";
import { useLive } from "../lib/live";
import { to } from "../lib/links";
import { Committee, DealTable, ROLE_LABEL } from "../components/deals";
import { Icon } from "../components/icons";
import { Card, Chip, Empty, GradePill, Loading, StageBadge, Stat } from "../components/ui";

const ROLE_HINT: Record<string, string> = {
  decision_maker: "C-level or VP: signs off the budget",
  manager: "Director or manager: owns the problem day to day",
  practitioner: "Hands-on user: judges whether it works",
};

export default function Account() {
  const { id = "" } = useParams();
  const { clock } = useLive();
  const q = useQuery({ queryKey: ["account", id], queryFn: () => api.get<AccountDetail>(`/api/accounts/${encodeURIComponent(id)}`) });

  if (q.isLoading) return <Card><Loading rows={5} /></Card>;
  if (q.error || !q.data) return <Empty>Account not found, or none of its contacts are yours. <Link className="text-accent-ink underline" to={to.accounts()}>All accounts</Link></Empty>;
  const a = q.data;
  const open = a.opportunities.filter((d) => d.status === "open");
  const closed = a.opportunities.filter((d) => d.status !== "open");

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-ink-3">
        <Link to={to.accounts()} className="drill">Accounts</Link><Icon name="chevronRight" size={13} />
        <span className="font-medium text-ink">{a.name ?? a.domain ?? a.account_id}</span>
      </nav>

      <section className="card relative isolate overflow-hidden rounded-2xl p-5">
        <div className="pointer-events-none absolute -right-16 -top-24 -z-10 h-56 w-56 rounded-full bg-[var(--c-glow-1)] blur-3xl" aria-hidden />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent-soft text-accent-ink"><Icon name="building" /></span>
              <h1 className="font-display text-2xl font-extrabold tracking-tight">{a.name ?? a.domain ?? a.account_id}</h1>
              <Committee covered={a.committee_covered} />
            </div>
            <p className="mt-1 text-sm text-ink-2">
              {a.domain ?? "no domain"} · <span className="capitalize">{human(a.industry)}</span>{a.employees ? ` · ${num(a.employees)} employees` : ""}{a.segment ? <> · <span className="capitalize">{human(a.segment)}</span></> : ""} · {a.country ?? "-"}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {a.revenue_band && <Chip title="Revenue band">{a.revenue_band}</Chip>}
              {a.funding_stage && <Chip title="Funding stage"><span className="capitalize">{human(a.funding_stage)}</span></Chip>}
              {a.tech_stack.map((t) => <Chip key={t} tone="accent" title="Tech stack">{t}</Chip>)}
            </div>
          </div>
          <div className="text-sm"><span className="text-ink-3">Owners </span>
            {a.owner_rep_ids.length ? a.owner_rep_ids.map((r, i) => <span key={r}>{i > 0 && ", "}<Link to={to.queue(r)} className="drill font-medium">{a.owner_names[i] ?? r}</Link></span>) : <span className="font-medium">Unassigned</span>}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Contacts" value={a.contacts} sub={`best score ${a.best_score.toFixed(0)}`} />
          <Stat label="Open deals" value={a.open_deals} sub={`${a.deals} in total`} />
          <Stat label="Pipeline" value={money(a.pipeline_ev)} sub="expected value" />
          <Stat label="Pipeline ACV" value={money(a.pipeline_acv)} sub="if every open deal wins" />
          <Stat label="Won revenue" value={a.won_revenue ? money(a.won_revenue) : "-"} sub={`${closed.filter((d) => d.status === "won").length} won · ${closed.filter((d) => d.status === "lost").length} lost`} />
          <Stat label="Last activity" value={a.last_inbound_at ? ago(a.last_inbound_at, clock.now) : "-"} sub="latest inbound touch" />
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <Card pad={false} title="Deals" subtitle={`${open.length} open · ${closed.length} closed. New deals open on a buying signal from any contact here, or from a lead page.`}>
            <DealTable items={a.opportunities} empty="No deals with this company yet. One opens on a demo request, a sales enquiry or a meeting." />
          </Card>
          <People people={a.people} />
        </div>
        <BuyingCommittee people={a.people} covered={a.committee_covered} />
      </div>
    </div>
  );
}

function People({ people }: { people: AccountPerson[] }) {
  return (
    <Card pad={false} title="People" subtitle="Everyone we know at this company, best score first. Contacts owned by other reps show name and role only.">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr className="border-b border-line">{["Name", "Role", "Score", "Stage", "Owner"].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.lead_id} className="border-b border-line last:border-0">
                <td className="px-5 py-2.5">
                  {p.visible ? <Link to={to.lead(p.lead_id)} className="drill font-medium text-ink">{p.name ?? p.lead_id}</Link> : <span className="font-medium text-ink-2">{p.name ?? "Contact"}</span>}
                  <div className="text-xs text-ink-3">{p.title ?? "No title"}</div>
                </td>
                <td className="px-5 py-2.5 text-ink-2">{ROLE_LABEL[p.role] ?? human(p.role)}</td>
                <td className="px-5 py-2.5">{p.visible && p.grade ? <GradePill grade={p.grade} score={p.score} /> : <span className="text-ink-3">-</span>}</td>
                <td className="px-5 py-2.5"><StageBadge stage={p.stage} /></td>
                <td className="px-5 py-2.5 text-ink-2">{p.owner_name ?? "Unassigned"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function BuyingCommittee({ people, covered }: { people: AccountPerson[]; covered: string[] }) {
  const missing = Object.keys(ROLE_LABEL).filter((r) => !covered.includes(r));
  return (
    <Card title="Buying committee" subtitle={missing.length ? `Missing: ${missing.map((r) => ROLE_LABEL[r].toLowerCase()).join(", ")}. Deals with more roles involved are more likely to close.` : "Every buying role is involved."}>
      <div className="space-y-4">
        {Object.keys(ROLE_LABEL).map((role) => {
          const who = people.filter((p) => p.role === role);
          return (
            <div key={role}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-ink">{ROLE_LABEL[role]}</span>
                {who.length ? <span className="text-xs tabular text-ink-3">{who.length}</span> : <span className="text-xs font-medium text-critical-ink">Not involved yet</span>}
              </div>
              <div className="text-xs text-ink-3">{ROLE_HINT[role]}</div>
              {who.length > 0 && (
                <ul className="mt-1.5 space-y-1">
                  {who.map((p) => (
                    <li key={p.lead_id} className="flex items-center justify-between gap-2 text-sm">
                      {p.visible ? <Link to={to.lead(p.lead_id)} className="drill min-w-0 truncate text-ink">{p.name ?? p.lead_id}</Link> : <span className="min-w-0 truncate text-ink-2">{p.name ?? "Contact"}</span>}
                      <span className="shrink-0 truncate text-xs text-ink-3">{p.title ?? ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
