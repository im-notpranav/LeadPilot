// Companies: every contact at the same web domain grouped into one account, with its deals and buying committee.
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type AccountRow } from "../lib/api";
import { ago, human, money, num } from "../lib/format";
import { useLive } from "../lib/live";
import { to } from "../lib/links";
import { Committee } from "../components/deals";
import { Icon } from "../components/icons";
import { Card, Empty, Loading, PageHeader, Segmented, StatTile } from "../components/ui";

type Sort = "pipeline" | "contacts" | "won" | "name";
const SORTS: { value: Sort; label: string }[] = [
  { value: "pipeline", label: "Pipeline" }, { value: "contacts", label: "Contacts" }, { value: "won", label: "Won" }, { value: "name", label: "Name" },
];
type AccountList = { total: number; items: AccountRow[]; totals: { pipeline_ev: number; open_deals: number; won_revenue: number } };

export default function Accounts() {
  const { clock } = useLive();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const sort = (params.get("sort") as Sort) || "pipeline";
  const [text, setText] = useState(q);
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };
  // Typing updates ?q= after a short pause, so the list follows the box and the URL stays shareable.
  useEffect(() => { const t = window.setTimeout(() => { if (text.trim() !== q) set("q", text.trim()); }, 250); return () => clearTimeout(t); }, [text]);
  useEffect(() => setText(q), [q]);

  const res = useQuery({
    queryKey: ["accounts", q, sort],
    queryFn: () => api.get<AccountList>(`/api/accounts?${new URLSearchParams({ ...(q && { q }), sort, limit: "300" })}`),
  });
  const t = res.data?.totals;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Accounts" subtitle="Contacts at the same company domain form one account. Each account shows its deals and which buying roles are involved." />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Accounts" icon="building" value={res.data ? num(res.data.total) : "-"} sub={q ? `matching “${q}”` : "with a lead you can see"} />
        <StatTile label="Open deals" icon="pipeline" value={t ? num(t.open_deals) : "-"} sub="open the deal board" to={to.deals()} />
        <StatTile label="Open pipeline" icon="analytics" value={t ? money(t.pipeline_ev) : "-"} sub="expected value of open deals" />
        <StatTile label="Won revenue" icon="check" tone="good" value={t ? money(t.won_revenue) : "-"} sub="value of won deals" />
      </div>
      <Card pad={false} title={`${res.data?.total ?? 0} accounts`} subtitle="Click an account for its people, buying committee and deals."
        right={<div className="flex flex-wrap items-center gap-2">
          <label className="flex h-9 items-center gap-2 rounded-xl border border-line bg-surface px-3 shadow-sm transition focus-within:border-brand focus-within:ring-4 focus-within:ring-brand/15">
            <Icon name="search" className="text-ink-3" size={14} />
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Company, domain or industry" aria-label="Search accounts"
              className="w-48 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3" />
          </label>
          <Segmented label="Sort accounts" value={sort} options={SORTS} onChange={(v) => set("sort", v === "pipeline" ? "" : v)} />
        </div>}>
        {res.isLoading ? <Loading rows={6} />
          : res.isError ? <Empty>Could not load accounts. <button onClick={() => res.refetch()} className="font-medium text-accent-ink hover:underline">Try again</button></Empty>
          : !res.data?.items.length ? <Empty>{q ? <>No account matches “{q}”.</> : "No accounts yet. They appear as leads arrive."}</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="text-left text-xs text-ink-3">
                <tr className="border-b border-line">
                  {["Account", "Industry", "Contacts", "Buying roles", "Open deals", "Pipeline", "Won", "Best score", "Owners", "Last activity"].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {res.data.items.map((a) => (
                  <tr key={a.account_id} className="border-b border-line transition last:border-0 hover:bg-surface-2/60">
                    <td className="max-w-[240px] px-4 py-2.5">
                      <Link to={to.account(a.account_id)} className="drill block truncate font-medium text-ink">{a.name ?? a.domain ?? a.account_id}</Link>
                      <div className="truncate text-xs text-ink-3">{a.domain ?? "no domain"}{a.country ? ` · ${a.country}` : ""}</div>
                    </td>
                    <td className="px-4 py-2.5 text-ink-2"><div className="capitalize">{human(a.industry)}</div><div className="text-xs capitalize text-ink-3">{a.segment ? human(a.segment) : ""}{a.employees ? ` · ${num(a.employees)} staff` : ""}</div></td>
                    <td className="px-4 py-2.5 tabular">{a.contacts}</td>
                    <td className="px-4 py-2.5"><Committee covered={a.committee_covered} /></td>
                    <td className="px-4 py-2.5 tabular">{a.open_deals}<span className="text-ink-3"> / {a.deals}</span></td>
                    <td className="px-4 py-2.5 tabular">{a.pipeline_ev ? money(a.pipeline_ev) : <span className="text-ink-3">-</span>}</td>
                    <td className="px-4 py-2.5 tabular">{a.won_revenue ? money(a.won_revenue) : <span className="text-ink-3">-</span>}</td>
                    <td className="px-4 py-2.5 tabular">{a.best_score.toFixed(0)}</td>
                    <td className="max-w-[180px] truncate px-4 py-2.5 text-ink-2">{a.owner_names.filter(Boolean).join(", ") || "Unassigned"}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-ink-3">{a.last_inbound_at ? ago(a.last_inbound_at, clock.now) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
