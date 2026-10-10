// Admin: who can use LeadPilot (roles, rep links, manager teams) and the API keys that may ingest events.
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ApiKey, type Profile, type Rep, type Role } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";
import { Button, Card, Empty, Loading, PageHeader } from "../components/ui";

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything, plus people and API keys",
  manager: "Their team's leads and unassigned leads, analytics, quality, reassignment",
  rep: "Only their own leads, queue and pipeline",
  pending: "Signed up, no access yet",
};

export default function Access() {
  return (
    <div className="mx-auto max-w-[1200px] space-y-5">
      <PageHeader title="Access" subtitle="Approve people, set what they can see, and issue keys for sending events in." />
      <People />
      <ApiKeys />
    </div>
  );
}

function People() {
  const qc = useQueryClient();
  const { me } = useAuth();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api.get<{ items: Profile[]; admin_emails: string[] }>("/api/admin/users") });
  const reps = useQuery({ queryKey: ["reps"], queryFn: () => api.get<{ items: Rep[] }>("/api/reps") });
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<Profile> }) => api.patch<Profile>(`/api/admin/users/${id}`, changes),
    onSuccess: () => { setError(null); qc.invalidateQueries({ queryKey: ["admin", "users"] }); },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const repList = reps.data?.items ?? [];
  const bootstrap = new Set(users.data?.admin_emails ?? []);
  const items = users.data?.items ?? [];
  const pending = items.filter((u) => u.role === "pending").length;

  return (
    <Card pad={false} title="People" subtitle={pending ? `${pending} waiting for approval` : "Everyone who has signed in"}>
      {error && <p role="alert" className="border-b border-line px-4 py-2 text-sm text-critical-ink">{error}</p>}
      {users.isLoading ? <Loading /> : !items.length ? <Empty>No one has signed in yet.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-ink-3">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">Person</th>
                <th className="px-4 py-2 font-medium">Role</th>
                <th className="px-4 py-2 font-medium">Works as / oversees</th>
                <th className="px-4 py-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => {
                const locked = bootstrap.has(u.email ?? "") || u.user_id === me?.user_id;
                const set = (changes: Partial<Profile>) => save.mutate({ id: u.user_id, changes });
                return (
                  <tr key={u.user_id} className={`border-b border-line align-top last:border-0 ${u.role === "pending" ? "bg-accent-soft/40" : ""}`}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-ink">{u.name || u.email}</div>
                      {u.name && <div className="text-xs text-ink-3">{u.email}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <select aria-label={`Role for ${u.email}`} value={u.role} disabled={locked || save.isPending}
                        onChange={(e) => set({ role: e.target.value as Role })}
                        className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink disabled:opacity-60">
                        {(["pending", "rep", "manager", "admin"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                      <div className="mt-1 max-w-[220px] text-xs text-ink-3">{locked && bootstrap.has(u.email ?? "") ? "Admin via LEADPILOT_ADMIN_EMAILS" : ROLE_HELP[u.role]}</div>
                    </td>
                    <td className="px-4 py-3">
                      {u.role === "rep" && (
                        <select aria-label={`Rep for ${u.email}`} value={u.rep_id ?? ""} onChange={(e) => set({ rep_id: e.target.value || null })}
                          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
                          <option value="">Choose a rep…</option>
                          {repList.map((r) => <option key={r.rep_id} value={r.rep_id}>{r.name}</option>)}
                        </select>
                      )}
                      {u.role === "rep" && !u.rep_id && <div className="mt-1 text-xs text-critical-ink">Link a rep, or this person sees no leads.</div>}
                      {u.role === "manager" && <TeamPicker reps={repList} value={u.team_rep_ids} onChange={(team) => set({ team_rep_ids: team })} />}
                      {(u.role === "admin" || u.role === "pending") && <span className="text-xs text-ink-3">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs tabular text-ink-2">{u.last_seen_at ? dateTime(u.last_seen_at) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function TeamPicker({ reps, value, onChange }: { reps: Rep[]; value: string[] | null; onChange: (v: string[] | null) => void }) {
  const all = value === null;
  const chosen = new Set(value ?? []);
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange([...next].sort());
  };
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.target.checked ? null : [])} /> All reps
      </label>
      {!all && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          {reps.map((r) => (
            <label key={r.rep_id} className="flex items-center gap-2 text-xs text-ink-2">
              <input type="checkbox" checked={chosen.has(r.rep_id)} onChange={() => toggle(r.rep_id)} /> {r.name}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function ApiKeys() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["admin", "keys"], queryFn: () => api.get<{ items: ApiKey[] }>("/api/admin/api-keys") });
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<ApiKey | null>(null);
  const [copied, setCopied] = useState(false);
  const create = useMutation({
    mutationFn: (n: string) => api.post<ApiKey>("/api/admin/api-keys", { name: n }),
    onSuccess: (k) => { setFresh(k); setCopied(false); setName(""); qc.invalidateQueries({ queryKey: ["admin", "keys"] }); },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.del<ApiKey>(`/api/admin/api-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "keys"] }),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) create.mutate(name.trim()); };
  const copy = async () => { if (fresh?.secret) { await navigator.clipboard.writeText(fresh.secret); setCopied(true); } };
  const items = keys.data?.items ?? [];

  return (
    <Card pad={false} title="API keys" subtitle="For websites, forms, CRMs and other systems that send events to POST /api/events">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2 border-b border-line px-4 py-3">
        <label className="min-w-[220px] flex-1">
          <span className="mb-1 block text-xs font-medium text-ink-2">New key name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Website forms"
            className="h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/30" />
        </label>
        <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>Create key</Button>
      </form>
      {fresh?.secret && (
        <div className="border-b border-line bg-accent-soft/50 px-4 py-3">
          <div className="text-sm font-medium text-ink">Copy “{fresh.name}” now. It won't be shown again.</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-md border border-line bg-surface px-2 py-1.5 text-xs">{fresh.secret}</code>
            <Button size="sm" onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
            <Button size="sm" variant="ghost" onClick={() => setFresh(null)}>Done</Button>
          </div>
          <pre className="mt-2 overflow-x-auto rounded-md bg-surface px-2 py-1.5 text-[11px] text-ink-2">{`curl -X POST ${location.origin}/api/events \\
  -H "X-API-Key: ${fresh.prefix}…" -H "Content-Type: application/json" \\
  -d '{"type":"page_view","lead_ref":{"email":"jane@acme.io"},"payload":{"page_category":"pricing"}}'`}</pre>
        </div>
      )}
      {keys.isLoading ? <Loading /> : !items.length ? <Empty>No API keys yet.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs text-ink-3">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">Name</th><th className="px-4 py-2 font-medium">Key</th>
                <th className="px-4 py-2 font-medium">Created</th><th className="px-4 py-2 font-medium">Last used</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((k) => (
                <tr key={k.id} className={`border-b border-line last:border-0 ${k.revoked_at ? "text-ink-3" : ""}`}>
                  <td className="px-4 py-2.5 font-medium">{k.name}<div className="text-xs font-normal text-ink-3">{k.created_by}</div></td>
                  <td className="px-4 py-2.5"><code className="text-xs">{k.prefix}…</code></td>
                  <td className="px-4 py-2.5 text-xs tabular">{dateTime(k.created_at)}</td>
                  <td className="px-4 py-2.5 text-xs tabular">{k.last_used_at ? dateTime(k.last_used_at) : "Never"}</td>
                  <td className="px-4 py-2.5 text-right">
                    {k.revoked_at ? <span className="text-xs">Revoked</span> : (
                      <Button size="sm" variant="danger" disabled={revoke.isPending}
                        onClick={() => { if (confirm(`Revoke “${k.name}”? Anything using it will stop sending events.`)) revoke.mutate(k.id); }}>
                        Revoke
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
