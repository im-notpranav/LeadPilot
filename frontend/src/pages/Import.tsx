// Managers: load a spreadsheet or CRM export as leads. Preview the column mapping, fix it, then import.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type ImportPreview, type ImportResult, type ImportRow } from "../lib/api";
import { day, human, num } from "../lib/format";
import { Button, Card, Empty, PageHeader, Stat } from "../components/ui";

const CAPTURE = ["cold_import", "form_submit", "badge_scan", "referral", "partner_lead", "ad_lead"];
const MAX_BYTES = 5 * 1024 * 1024;
const input = "h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/30";
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Import() {
  const qc = useQueryClient();
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [source, setSource] = useState("csv_import");
  const [capture, setCapture] = useState("cold_import");
  const [useRecordSource, setUseRecordSource] = useState(true);
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ImportResult | null>(null);

  const body = (map = columnMap) => ({ csv: file?.text, source, capture_method: capture, column_map: map, use_record_source: useRecordSource });
  const preview = useMutation({ mutationFn: (map: Record<string, string>) => api.post<ImportPreview>("/api/import/preview", body(map)) });
  const commit = useMutation({
    mutationFn: () => api.post<ImportResult>("/api/import/commit", body()),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries(); },
  });

  const pick = async (f: File | undefined) => {
    setResult(null); setColumnMap({}); preview.reset(); commit.reset(); setFileError(null);
    if (!f) { setFile(null); return; }
    if (f.size > MAX_BYTES) { setFile(null); setFileError("That file is larger than 5 MB. Split it and import the parts."); return; }
    setFile({ name: f.name, text: await f.text() });
  };
  const remap = (header: string, target: string) => {
    const next = { ...columnMap, [header]: target };
    setColumnMap(next);
    preview.mutate(next);
  };
  const p = preview.data;

  return (
    <div className="mx-auto max-w-[1200px] space-y-5">
      <PageHeader title="Import leads" subtitle="Load a spreadsheet or a CRM export (HubSpot, Salesforce, Pipedrive, Zoho…). Columns are matched by name; you can change any of them." />
      <Card title="1. Choose a file" subtitle="CSV with a header row, up to 5,000 rows. Each row needs an email or a phone number.">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_200px_200px]">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-ink-2">CSV file</span>
            <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => pick(e.target.files?.[0])}
              className="block w-full text-sm text-ink-2 file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:bg-surface-2" />
          </label>
          <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Lead source</span>
            <input value={source} onChange={(e) => setSource(e.target.value)} aria-label="Lead source" className={input} /></label>
          <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">How they were captured</span>
            <select value={capture} onChange={(e) => setCapture(e.target.value)} aria-label="Capture method" className={input}>
              {CAPTURE.map((c) => <option key={c} value={c}>{human(c)}</option>)}
            </select></label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" checked={useRecordSource} onChange={(e) => setUseRecordSource(e.target.checked)} />
          Use the file's own “Lead source” column when a row has one
        </label>
        {fileError && <p role="alert" className="mt-2 text-sm text-critical-ink">{fileError}</p>}
        <div className="mt-3 flex items-center gap-3">
          <Button variant="primary" disabled={!file || preview.isPending} onClick={() => { setResult(null); preview.mutate(columnMap); }}>Preview</Button>
          {file && <span className="text-xs text-ink-3">{file.name}</span>}
        </div>
        {preview.isError && <p role="alert" className="mt-2 text-sm text-critical-ink">{errText(preview.error)}</p>}
      </Card>

      {p && !result && (<>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Rows" value={num(p.counts.rows)} />
          <Stat label="Ready to import" value={num(p.counts.ok)} />
          <Stat label="Skipped" value={num(p.counts.skipped)} sub={p.counts.skipped ? "see below" : undefined} />
          <Stat label="Events" value={num(p.events)} sub="leads + form intent" />
        </div>
        <Card pad={false} title="2. Check the columns" subtitle="Change a column to fix the mapping, or ignore it.">
          <div className="grid gap-x-6 gap-y-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {p.headers.map((h) => (
              <label key={h} className="flex items-center gap-2 text-sm">
                <span className="w-40 shrink-0 truncate font-medium text-ink" title={h}>{h}</span>
                <select aria-label={`Column ${h}`} value={columnMap[h] ?? p.columns[h] ?? ""} onChange={(e) => remap(h, e.target.value)}
                  className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 text-sm text-ink">
                  <option value="">Ignore</option>
                  {p.targets.map((t) => <option key={t} value={t}>{human(t)}</option>)}
                </select>
              </label>
            ))}
          </div>
        </Card>
        <Card pad={false} title="3. Preview" subtitle={`First ${p.sample.length} of ${p.counts.ok} leads`}
          right={<Button variant="primary" disabled={!p.counts.ok || commit.isPending || preview.isPending} onClick={() => commit.mutate()}>{commit.isPending ? "Importing…" : `Import ${num(p.counts.ok)} leads`}</Button>}>
          {commit.isError && <p role="alert" className="border-b border-line px-4 py-2 text-sm text-critical-ink">{errText(commit.error)}</p>}
          {!p.sample.length ? <Empty>No importable rows.</Empty> : <Rows rows={p.sample} />}
        </Card>
        {p.errors.length > 0 && <Skipped rows={p.errors} />}
      </>)}

      {result && (
        <Card title="Import finished" subtitle={`Batch ${result.batch_id} · ${result.seconds}s`}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="New leads" value={num(result.leads.processed ?? 0)} />
            <Stat label="Already imported" value={num(result.leads.duplicate ?? 0)} sub="same file imported before" />
            <Stat label="Skipped rows" value={num(result.counts.skipped)} />
            <Stat label="Events" value={num(result.events)} />
          </div>
          {result.lead_ids.length > 0 && (
            <p className="mt-3 text-sm text-ink-2">Open: {result.lead_ids.slice(0, 8).map((id, i) => <span key={id}>{i > 0 && ", "}<Link to={`/leads/${id}`} className="text-accent-ink hover:underline">{id}</Link></span>)}{result.lead_ids.length > 8 && ` and ${result.lead_ids.length - 8} more`}</p>
          )}
          <div className="mt-3"><Button onClick={() => { setResult(null); preview.reset(); }}>Import another file</Button></div>
        </Card>
      )}
    </div>
  );
}

function Rows({ rows }: { rows: ImportRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <thead className="text-left text-xs text-ink-3">
          <tr className="border-b border-line">
            {["Line", "Name", "Email / phone", "Company", "Title", "Country", "Source", "Intent", "Created"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.line} className="border-b border-line last:border-0">
              <td className="px-4 py-2 tabular text-ink-3">{r.line}</td>
              <td className="px-4 py-2 font-medium">{r.name ?? "—"}</td>
              <td className="px-4 py-2">{r.email ?? r.phone}</td>
              <td className="px-4 py-2">{r.company ?? "—"}</td>
              <td className="px-4 py-2 text-ink-2">{r.title ?? "—"}</td>
              <td className="px-4 py-2">{r.country ?? "—"}</td>
              <td className="px-4 py-2 text-ink-2">{r.source}</td>
              <td className="px-4 py-2 text-ink-2">{r.intent ? human(r.intent) : "—"}</td>
              <td className="px-4 py-2 tabular text-ink-2">{r.created_at ? day(r.created_at) : "on import"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Skipped({ rows }: { rows: ImportRow[] }) {
  return (
    <Card pad={false} title="Skipped rows" subtitle="These rows will not be imported.">
      <ul className="max-h-[240px] overflow-y-auto px-4 py-2 text-sm">
        {rows.map((r) => <li key={r.line} className="py-0.5"><span className="tabular text-ink-3">Line {r.line}:</span> <span className="text-ink-2">{r.error}</span></li>)}
      </ul>
    </Card>
  );
}
