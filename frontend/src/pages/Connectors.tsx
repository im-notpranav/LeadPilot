// Admin: the connectors that feed LeadPilot — signed webhooks, website forms, CRMs, inbound email and the website tracker.
import { Fragment, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Connector, type ConnectorKind, type ConnectorList, type Delivery } from "../lib/api";
import { dateTime, human } from "../lib/format";
import { Button, Card, Empty, Loading, PageHeader, StatusTag } from "../components/ui";

const KINDS: Record<ConnectorKind, { label: string; help: string }> = {
  webhook: { label: "Webhook (signed)", help: "Your own systems send LeadPilot events, signed with HMAC-SHA256." },
  form: { label: "Website form", help: "Form tools (Webflow, Typeform, WordPress, Zapier…) post each submission; it becomes a lead." },
  crm: { label: "CRM", help: "HubSpot, Pipedrive or Salesforce workflows send contact records, signed." },
  email: { label: "Inbound email", help: "Postmark, SendGrid or Mailgun forward prospects' replies and bounces." },
  tracker: { label: "Website tracker", help: "A script on your site records page views and links them to the lead once they fill in a form." },
  call: { label: "Phone calls", help: "Retell (or any phone system) sends each call; it is summarised and attached to the lead with that number." },
};
const DELIVERY_TONE: Record<string, "good" | "warn" | "serious" | "critical"> = {
  accepted: "good", duplicate: "warn", partial: "warn", ignored: "warn", unresolved: "serious", rejected: "critical",
};
const input = "h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/30";
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Connectors() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["connectors"], queryFn: () => api.get<ConnectorList>("/api/connectors") });
  const [shown, setShown] = useState<Connector | null>(null);      // a connector whose full secret is on screen
  const [open, setOpen] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["connectors"] });
  const items = list.data?.items ?? [];

  return (
    <div className="mx-auto max-w-[1200px] space-y-5">
      <PageHeader title="Connectors" subtitle="Bring leads and activity in from your website, forms, CRM and inbox. Each connector has its own secret." />
      <CreateConnector onCreated={(c) => { setShown(c); setOpen(c.id); refresh(); }} />
      {shown && <Setup con={shown} onClose={() => setShown(null)} tolerance={list.data?.signature_tolerance_s ?? 300} />}
      <Card pad={false} title="Your connectors" subtitle={items.length ? `${items.filter((c) => c.status === "active").length} active` : undefined}>
        {list.isLoading ? <Loading /> : list.isError ? <Empty>{errText(list.error)}</Empty> : !items.length ? <Empty>No connectors yet. Create one above.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-left text-xs text-ink-3">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">Name</th><th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Received</th>
                  <th className="px-4 py-2 font-medium">Last received</th><th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <Fragment key={c.id}>
                    <tr className={`border-b border-line ${c.status === "disabled" ? "text-ink-3" : ""}`}>
                      <td className="px-4 py-2.5 font-medium">{c.name}<div className="text-xs font-normal text-ink-3">source: {c.source ?? "from each event"}</div></td>
                      <td className="px-4 py-2.5">{KINDS[c.kind].label}</td>
                      <td className="px-4 py-2.5">{c.status === "active" ? <StatusTag status="good">Active</StatusTag> : <StatusTag status="critical">Disabled</StatusTag>}</td>
                      <td className="px-4 py-2.5 tabular">{c.kind === "tracker" && c.stats ? `${c.stats.page_views} views · ${c.stats.identified}/${c.stats.visitors} visitors known` : c.received_count}</td>
                      <td className="px-4 py-2.5 text-xs tabular">{c.last_received_at ? dateTime(c.last_received_at) : "Never"}</td>
                      <td className="px-4 py-2.5 text-right">
                        <Button size="sm" variant="ghost" onClick={() => setOpen(open === c.id ? null : c.id)}>{open === c.id ? "Close" : "Manage"}</Button>
                      </td>
                    </tr>
                    {open === c.id && (
                      <tr className="border-b border-line bg-surface-2/40">
                        <td colSpan={6} className="px-4 py-4">
                          <Manage con={c} meta={list.data!} onSecret={setShown} onChanged={refresh} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function CreateConnector({ onCreated }: { onCreated: (c: Connector) => void }) {
  const [kind, setKind] = useState<ConnectorKind>("form");
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<Connector>("/api/connectors", { kind, name: name.trim() }),
    onSuccess: (c) => { setName(""); onCreated(c); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) create.mutate(); };
  return (
    <Card title="Add a connector" subtitle={KINDS[kind].help}>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <label className="w-56">
          <span className="mb-1 block text-xs font-medium text-ink-2">Type</span>
          <select aria-label="Connector type" value={kind} onChange={(e) => setKind(e.target.value as ConnectorKind)} className={input}>
            {(Object.keys(KINDS) as ConnectorKind[]).map((k) => <option key={k} value={k}>{KINDS[k].label}</option>)}
          </select>
        </label>
        <label className="min-w-[220px] flex-1">
          <span className="mb-1 block text-xs font-medium text-ink-2">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Website demo form" className={input} />
        </label>
        <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>Create connector</Button>
      </form>
      {create.isError && <p role="alert" className="mt-2 text-sm text-critical-ink">{errText(create.error)}</p>}
    </Card>
  );
}

function Code({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { await navigator.clipboard.writeText(children); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md border border-line bg-surface px-3 py-2 pr-16 text-[11px] leading-relaxed text-ink-2">{children}</pre>
      <button onClick={copy} className="absolute right-1.5 top-1.5 rounded px-1.5 py-0.5 text-[11px] text-ink-3 hover:bg-surface-2 hover:text-ink">{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}

// How to connect: shown with the full secret right after creating, rotating or revealing.
function Setup({ con, onClose, tolerance }: { con: Connector; onClose: () => void; tolerance: number }) {
  const url = `${location.origin}${con.endpoint}`;
  const secret = con.secret ?? "";
  const sample = con.kind === "crm"
    ? `{"records":[{"id":"123","email":"jane@acme.io","firstname":"Jane","company":"Acme"}]}`
    : `{"type":"page_view","lead_ref":{"email":"jane@acme.io"},"payload":{"page_category":"pricing"}}`;
  const signed = `// Node 18+: sign the exact body you send
const body = JSON.stringify(${sample});
const ts = Math.floor(Date.now() / 1000);
const sig = require("crypto").createHmac("sha256", process.env.LEADPILOT_SECRET).update(\`\${ts}.\${body}\`).digest("hex");
await fetch("${url}", { method: "POST", body, headers: {
  "Content-Type": "application/json", "X-LeadPilot-Timestamp": String(ts), "X-LeadPilot-Signature": \`v1=\${sig}\` } });`;
  return (
    <section aria-label="Connector setup" className="space-y-3 rounded-xl border border-accent/40 bg-accent-soft/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">Set up “{con.name}”</h2>
          <p className="mt-0.5 text-xs text-ink-2">{con.kind === "tracker" ? "The site key is public: it only ever records page views and form leads." : "Keep this secret private. Anyone holding it can send data to LeadPilot."}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>Done</Button>
      </div>
      {con.kind === "tracker" ? (<>
        <p className="text-sm text-ink">Paste this before <code>&lt;/body&gt;</code> on every page of your site:</p>
        <Code>{`<script async src="${location.origin}/api/t.js" data-key="${con.site_key}"></script>`}</Code>
        <p className="text-xs text-ink-2">Forms with an email field are captured automatically (passwords and card fields are never read). Name a form with <code>data-leadpilot="Demo request"</code>, skip one with <code>data-leadpilot-ignore</code>, or call <code>window.leadpilot.identify({"{"}email{"}"})</code> from your code. Visitors who ask not to be tracked are not tracked.</p>
      </>) : (<>
        <div className="flex flex-wrap items-center gap-2 text-sm"><span className="font-medium text-ink">Secret</span><code className="break-all rounded-md border border-line bg-surface px-2 py-1 text-xs">{secret}</code></div>
        {(con.kind === "form" || con.kind === "email") && (<>
          <p className="text-sm text-ink">{con.kind === "form" ? "Point your form tool's webhook (JSON or form-encoded POST) at:" : "Set your mail provider's inbound route (Postmark, SendGrid Inbound Parse, Mailgun) to POST to:"}</p>
          <Code>{`${url}?token=${secret}`}</Code>
          <p className="text-xs text-ink-2">Tools that can sign requests may use the signature headers below instead of the token.</p>
        </>)}
        {con.kind === "call" && (<>
          <p className="text-sm text-ink">In Retell, open your agent (or the account's webhook settings) and set the webhook URL to:</p>
          <Code>{url}</Code>
          <p className="text-xs text-ink-2">Retell signs every webhook with your Retell API key: put that key in <code>RETELL_API_KEY</code> in <code>backend/.env</code> and restart. A call is matched to the lead with the number you called (or that called you); pass <code>lead_id</code> or <code>lead_email</code> in the call's metadata to match it exactly. Calls with no matching lead wait on the Calls page.</p>
          <p className="text-xs text-ink-2">Another phone system? Switch the provider to “Generic” and POST one call per request to <code className="text-xs">{`${url}?token=${secret}`}</code>:</p>
          <Code>{`{"call_id":"abc-1","direction":"outbound","to":"+14155552671","started_at":"2026-10-15T14:00:00Z","duration_s":312,
 "transcript":"Agent: Hi…\nCustomer: …","recording_url":"https://…/abc-1.mp3"}`}</Code>
        </>)}
        {(con.kind === "webhook" || con.kind === "crm") && (<>
          <p className="text-sm text-ink">POST JSON to <code className="text-xs">{url}</code> with two headers: <code className="text-xs">X-LeadPilot-Timestamp</code> (unix seconds, within {tolerance / 60} minutes of now) and <code className="text-xs">X-LeadPilot-Signature: v1=</code> hex HMAC-SHA256 of <code className="text-xs">"{"{timestamp}.{raw body}"}"</code> keyed with the secret.</p>
          <Code>{signed}</Code>
          <p className="text-xs text-ink-2">{con.kind === "crm" ? "Send one record, a list, or {\"records\": [...]}. HubSpot, Pipedrive and plain JSON shapes are understood; resending the same record id is ignored." : "Send one event, a list, or {\"events\": [...]}. Give each an event_id so retries are ignored."}</p>
        </>)}
      </>)}
    </section>
  );
}

function Manage({ con, meta, onSecret, onChanged }: { con: Connector; meta: ConnectorList; onSecret: (c: Connector) => void; onChanged: () => void }) {
  const s = con.settings as Record<string, unknown>;
  const [name, setName] = useState(con.name);
  const [source, setSource] = useState(con.source ?? "");
  const [formKind, setFormKind] = useState(String(s.form_kind ?? "auto"));
  const [capture, setCapture] = useState(String(s.capture_method ?? "form_submit"));
  const [origins, setOrigins] = useState(((s.allowed_origins as string[]) ?? []).join(", "));
  const [provider, setProvider] = useState(String(s.provider ?? "retell"));
  const [processOn, setProcessOn] = useState(String(s.process_on ?? "auto"));
  const [error, setError] = useState<string | null>(null);
  const done = { onSuccess: () => { setError(null); onChanged(); }, onError: (e: unknown) => setError(errText(e)) };
  const save = useMutation({
    mutationFn: () => {
      const settings: Record<string, unknown> = {};
      if (con.kind === "form") Object.assign(settings, { form_kind: formKind, capture_method: capture });
      if (con.kind === "crm") settings.capture_method = capture;
      if (con.kind === "tracker") settings.allowed_origins = origins;
      if (con.kind === "call") Object.assign(settings, { provider, process_on: processOn });
      return api.patch<Connector>(`/api/connectors/${con.id}`, { name, source, settings });
    }, ...done,
  });
  const rotate = useMutation({ mutationFn: () => api.post<Connector>(`/api/connectors/${con.id}/rotate`), ...done, onSuccess: (c: Connector) => { onSecret(c); done.onSuccess(); } });
  const reveal = useMutation({ mutationFn: () => api.post<{ secret: string }>(`/api/connectors/${con.id}/reveal`), onSuccess: (r) => onSecret({ ...con, secret: r.secret }), onError: done.onError });
  const disable = useMutation({ mutationFn: () => api.del<Connector>(`/api/connectors/${con.id}`), ...done });
  const active = con.status === "active";

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,340px)_1fr]">
      <div className="space-y-3">
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Name</span><input value={name} onChange={(e) => setName(e.target.value)} className={input} /></label>
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Lead source</span>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder={con.kind === "webhook" ? "taken from each event" : "e.g. website"} className={input} /></label>
        {con.kind === "form" && (
          <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">What a submission means</span>
            <select aria-label="Form intent" value={formKind} onChange={(e) => setFormKind(e.target.value)} className={input}>
              {meta.form_kinds.map((k) => <option key={k} value={k}>{k === "auto" ? "Work it out from the form name" : k === "none" ? "Just a lead (no buying signal)" : human(k)}</option>)}
            </select></label>
        )}
        {(con.kind === "form" || con.kind === "crm") && (
          <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">How these leads were captured</span>
            <select aria-label="Capture method" value={capture} onChange={(e) => setCapture(e.target.value)} className={input}>
              {meta.capture_methods.map((m) => <option key={m} value={m}>{human(m)}</option>)}
            </select></label>
        )}
        {con.kind === "call" && (<>
          <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Phone system</span>
            <select aria-label="Phone system" value={provider} onChange={(e) => setProvider(e.target.value)} className={input}>
              <option value="retell">Retell</option><option value="generic">Generic (LeadPilot call format)</option>
            </select></label>
          {provider === "retell" && (
            <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Take each call from</span>
              <select aria-label="Take each call from" value={processOn} onChange={(e) => setProcessOn(e.target.value)} className={input}>
                <option value="auto">Automatic: call_ended with Gemini, otherwise call_analyzed</option>
                <option value="call_ended">call_ended (as soon as the call ends)</option>
                <option value="call_analyzed">call_analyzed (after Retell's own analysis)</option>
              </select></label>
          )}
        </>)}
        {con.kind === "tracker" && (
          <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Allowed sites (blank = any)</span>
            <input value={origins} onChange={(e) => setOrigins(e.target.value)} placeholder="example.com, shop.example.com" className={input} /></label>
        )}
        {error && <p role="alert" className="text-sm text-critical-ink">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" size="sm" disabled={save.isPending || !name.trim()} onClick={() => save.mutate()}>Save</Button>
          {active && con.kind !== "tracker" && <Button size="sm" disabled={reveal.isPending} onClick={() => reveal.mutate()}>Show setup</Button>}
          {active && con.kind === "tracker" && <Button size="sm" onClick={() => onSecret(con)}>Show snippet</Button>}
          {active && <Button size="sm" disabled={rotate.isPending} onClick={() => { if (confirm(`Rotate the secret for “${con.name}”? The old one stops working at once.`)) rotate.mutate(); }}>Rotate secret</Button>}
          {active && <Button size="sm" variant="danger" disabled={disable.isPending} onClick={() => { if (confirm(`Disable “${con.name}”? Anything sending to it will be refused.`)) disable.mutate(); }}>Disable</Button>}
        </div>
        <p className="text-xs text-ink-3">Created {dateTime(con.created_at)}{con.created_by ? ` by ${con.created_by}` : ""} · {con.kind === "tracker" ? `site key ${con.site_key}` : `secret ${con.secret_hint}`}</p>
      </div>
      <Deliveries id={con.id} />
    </div>
  );
}

function Deliveries({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["connectors", id, "deliveries"], queryFn: () => api.get<{ items: Delivery[] }>(`/api/connectors/${id}/deliveries?limit=50`), refetchInterval: 5000 });
  const items = q.data?.items ?? [];
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold text-ink-2">Recent deliveries</h3>
      {q.isLoading ? <Loading /> : !items.length ? <p className="text-sm text-ink-3">Nothing received yet.</p> : (
        <ul className="max-h-[320px] space-y-1.5 overflow-y-auto pr-1">
          {items.map((d) => {
            const leads = [...new Set(d.results.map((r) => r.lead_id).filter(Boolean))] as string[];
            return (
              <li key={d.id} className="rounded-lg border border-line bg-surface px-3 py-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusTag status={DELIVERY_TONE[d.status] ?? "warn"}>{human(d.status)}</StatusTag>
                  <span className="tabular text-ink-3">HTTP {d.http_status}</span>
                  <span className="tabular text-ink-2">{dateTime(d.received_at)}</span>
                  {d.events > 0 && <span className="text-ink-2">{d.events} event{d.events === 1 ? "" : "s"}</span>}
                  {leads.slice(0, 3).map((l) => <Link key={l} to={`/leads/${l}`} className="text-accent-ink hover:underline">{l}</Link>)}
                </div>
                {d.reason && <div className="mt-1 text-ink-2">{d.reason}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
