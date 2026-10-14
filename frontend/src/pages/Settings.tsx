// Settings console: the rules behind every score, stage, assignment and next action, kept as versions.
// Edit a section, check it (validated and dry-run on real events), test it (what-if: every event re-run under it and
// compared with the rules in force), save it as a version, then activate it: activation re-runs every event under the
// new rules. Older versions can be rolled back to at any time.
import { Fragment, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ConfigActivated, type ConfigChange, type ConfigCheck, type ConfigCurrent, type ConfigVersion, type ConfigVersionDetail, type WhatIfRun } from "../lib/api";
import { dateTime } from "../lib/format";
import { jumpTo } from "../lib/links";
import { WhatIfPanel } from "../components/whatif";
import { errText, inputCls } from "../components/deals";
import { Button, Card, Chip, Empty, Loading, PageHeader, Segmented, StatusTag } from "../components/ui";

const show = (v: unknown) => (v === null || v === undefined ? "-" : typeof v === "object" ? JSON.stringify(v) : String(v));

export default function Settings() {
  const qc = useQueryClient();
  const cur = useQuery({ queryKey: ["config"], queryFn: () => api.get<ConfigCurrent>("/api/config") });
  const versions = useQuery({ queryKey: ["config", "versions"], queryFn: () => api.get<{ items: ConfigVersion[] }>("/api/config/versions") });
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const refresh = () => qc.invalidateQueries();
  useEffect(() => { if (runId !== null) requestAnimationFrame(() => jumpTo("whatif")); }, [runId]);

  // Activation re-runs every event, so the whole dashboard changes: refresh everything afterwards.
  const activated = (r: ConfigActivated) => { setBusy(null); setDone(`Version ${r.version.id} is in force: ${r.replayed_events.toLocaleString()} events re-run in ${r.seconds}s.`); refresh(); };
  const failed = () => setBusy(null);

  if (cur.isLoading) return <Card><Loading rows={6} /></Card>;
  if (cur.error || !cur.data) return <Empty>Could not load the settings. {errText(cur.error)}</Empty>;
  const c = cur.data;

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <PageHeader title="Settings" subtitle="The rules behind every score, stage, assignment and next action. Changes are saved as versions. Activating a version re-runs every event under its rules, so the whole dashboard reflects it." />
      {busy && (
        <div role="status" className="pop flex items-center gap-3 rounded-2xl border border-brand/30 bg-accent-soft/60 px-4 py-3 text-sm text-ink-2">
          <span className="h-4 w-4 shrink-0 rounded-full border-2 border-brand/30 border-t-brand" style={{ animation: "spin 700ms linear infinite" }} />{busy}
        </div>
      )}
      {done && !busy && <div role="status" className="pop rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-good-ink">{done}</div>}
      <InForce v={c.active} />
      <Editor c={c} onBusy={setBusy} onActivated={activated} onFailed={failed} onSaved={(msg) => { setDone(msg); refresh(); }} onWhatIf={setRunId} />
      {runId !== null && <WhatIfPanel key={runId} runId={runId} onClose={() => setRunId(null)} />}
      <History items={versions.data?.items ?? []} canEdit={c.can_edit} onBusy={setBusy} onActivated={activated} onFailed={failed} onWhatIf={setRunId} />
    </div>
  );
}

function InForce({ v }: { v: ConfigVersion }) {
  return (
    <section className="card relative isolate overflow-hidden rounded-2xl p-5">
      <div className="pointer-events-none absolute -right-16 -top-24 -z-10 h-56 w-56 rounded-full bg-[var(--c-glow-1)] blur-3xl" aria-hidden />
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-xl font-extrabold tracking-tight">Version {v.id} is in force</span>
        <StatusTag status="good">Active</StatusTag>
      </div>
      <p className="mt-1 text-sm text-ink-2">{v.note ?? "No note"}</p>
      <p className="mt-0.5 text-xs text-ink-3">
        Activated {dateTime(v.activated_at)}{v.activated_by ? ` by ${v.activated_by}` : ""} ·{" "}
        {v.changes_from_defaults ? `${v.changes_from_defaults} ${v.changes_from_defaults === 1 ? "setting differs" : "settings differ"} from the YAML files` : "same as the YAML files"}
        {v.sections_changed.length ? ` (${v.sections_changed.join(", ")})` : ""}
      </p>
    </section>
  );
}

function Changes({ items, empty = "No differences." }: { items: ConfigChange[]; empty?: string }) {
  if (!items.length) return <p className="text-sm text-ink-3">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead className="text-left text-xs text-ink-3"><tr className="border-b border-line"><th className="py-2 pr-4 font-medium">Setting</th><th className="py-2 pr-4 font-medium">Before</th><th className="py-2 font-medium">After</th></tr></thead>
        <tbody>
          {items.map((ch) => (
            <tr key={ch.path} className="border-b border-line align-top last:border-0">
              <td className="py-1.5 pr-4 font-mono text-xs text-ink">{ch.path}</td>
              <td className="py-1.5 pr-4 font-mono text-xs text-critical-ink line-through decoration-1">{show(ch.before)}</td>
              <td className="py-1.5 font-mono text-xs text-good-ink">{show(ch.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Acts = { onBusy: (m: string | null) => void; onActivated: (r: ConfigActivated) => void; onFailed: () => void; onWhatIf: (runId: number) => void };

function Editor({ c, onBusy, onActivated, onFailed, onSaved, onWhatIf }: { c: ConfigCurrent; onSaved: (msg: string) => void } & Acts) {
  const [tab, setTab] = useState(c.sections[0].name);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [showFile, setShowFile] = useState(false);
  const [checked, setChecked] = useState<ConfigCheck | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const section = c.sections.find((s) => s.name === tab)!;
  const edited = Object.fromEntries(Object.entries(drafts).filter(([k, v]) => v !== c.sections.find((s) => s.name === k)?.yaml));
  const dirty = Object.keys(edited).length > 0;
  const fail = (e: unknown) => { setChecked(null); setErrors(errText(e).split("\n")); };
  const reset = () => { setDrafts({}); setNote(""); setChecked(null); setErrors([]); };

  const check = useMutation({
    mutationFn: () => api.post<ConfigCheck>("/api/config/check", { sections: edited }),
    onSuccess: (r) => { setErrors([]); setChecked(r); }, onError: fail,
  });
  const whatIf = useMutation({
    mutationFn: () => api.post<WhatIfRun>("/api/config/whatif", { sections: edited }),
    onSuccess: (r) => { setErrors([]); onWhatIf(r.id); }, onError: fail,
  });
  const save = useMutation({
    mutationFn: (activate: boolean) => {
      if (activate) onBusy("Saving and re-running every event under the new rules. The dashboard waits until this finishes.");
      return api.post<{ version: ConfigVersion } & Partial<ConfigActivated>>("/api/config/versions", { sections: edited, note, activate });
    },
    onSuccess: (r, activate) => {
      reset();
      if (activate && r.replayed_events !== undefined) onActivated(r as ConfigActivated);
      else onSaved(`Saved as version ${r.version.id} (draft). Activate it from the history below when you are ready.`);
    },
    onError: (e) => { onFailed(); fail(e); },
  });

  return (
    <Card title="Rules" subtitle={c.can_edit ? "Edit a section as YAML. Check runs your changes on real events in a scratch copy before anything is saved; What if re-runs every event under them and shows what would change." : "Read-only: only admins can change the rules."}>
      <div className="scroll-thin -mx-1 mb-3 overflow-x-auto px-1 pb-1">
        <Segmented label="Section" value={tab} onChange={(v) => { setTab(v); setShowFile(false); }}
          options={c.sections.map((s) => ({ value: s.name, label: `${s.label}${edited[s.name] !== undefined ? " •" : ""}` }))} />
      </div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
        <span className="flex items-center gap-2">{section.changed ? <Chip tone="accent">Changed from the YAML file</Chip> : <Chip>Same as the YAML file</Chip>}
          {edited[tab] !== undefined && <Chip tone="accent">Edited, not saved</Chip>}</span>
        <button type="button" onClick={() => setShowFile((s) => !s)} className="drill font-medium text-accent-ink">{showFile ? "Back to the editor" : "Show the documented defaults"}</button>
      </div>
      {showFile ? (
        <pre aria-label={`backend/config/${tab}.yaml`} className="scroll-thin max-h-[520px] overflow-auto rounded-xl border border-line bg-surface-2/50 p-3 font-mono text-xs leading-relaxed text-ink-2">{section.file}</pre>
      ) : (
        <textarea aria-label={`${section.label} settings`} value={drafts[tab] ?? section.yaml} readOnly={!c.can_edit} spellCheck={false}
          onChange={(e) => { setDrafts((d) => ({ ...d, [tab]: e.target.value })); setChecked(null); setErrors([]); }}
          className="scroll-thin h-[520px] w-full resize-y rounded-xl border border-line bg-surface px-3 py-2.5 font-mono text-xs leading-relaxed text-ink shadow-sm outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/15" />
      )}
      {errors.length > 0 && (
        <div role="alert" className="mt-3 rounded-xl border px-3 py-2.5 text-sm text-critical-ink" style={{ borderColor: "color-mix(in srgb, var(--c-critical) 40%, transparent)", background: "color-mix(in srgb, var(--c-critical) 8%, transparent)" }}>
          <div className="mb-1 font-semibold">These changes cannot be used yet:</div>
          <ul className="list-disc space-y-0.5 pl-5">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      {checked && (
        <div className="mt-3 rounded-xl border border-line p-3">
          <div className="mb-2 text-sm font-medium text-good-ink">Checks passed on {checked.events_checked.toLocaleString()} events. {checked.changes.length} setting{checked.changes.length === 1 ? "" : "s"} would change:</div>
          <Changes items={checked.changes} empty="Nothing differs from the version in force." />
        </div>
      )}
      {c.can_edit && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="min-w-[240px] flex-1"><span className="mb-1 block text-xs font-medium text-ink-2">Note for this version</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Faster first touch for A leads" className={inputCls} /></label>
          <Button disabled={!dirty || check.isPending} onClick={() => check.mutate()}>{check.isPending ? "Checking…" : "Check changes"}</Button>
          <Button disabled={!dirty || whatIf.isPending} onClick={() => whatIf.mutate()} title="Re-run every event under these rules and compare with the rules in force">{whatIf.isPending ? "Starting…" : "What if?"}</Button>
          <Button disabled={!dirty || save.isPending} onClick={() => save.mutate(false)}>Save as draft</Button>
          <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(true)}>Save and activate</Button>
          {dirty && <Button variant="ghost" onClick={reset}>Discard edits</Button>}
        </div>
      )}
    </Card>
  );
}

function History({ items, canEdit, onBusy, onActivated, onFailed, onWhatIf }: { items: ConfigVersion[]; canEdit: boolean } & Acts) {
  const [open, setOpen] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["config", "version", open], enabled: open !== null, queryFn: () => api.get<ConfigVersionDetail>(`/api/config/versions/${open}`) });
  const run = useMutation({
    mutationFn: (v: ConfigVersion) => {
      onBusy(v.status === "draft" ? `Activating version ${v.id}: re-running every event under its rules.` : `Rolling back to version ${v.id}: re-running every event under its rules.`);
      return api.post<ConfigActivated>(v.status === "draft" ? `/api/config/versions/${v.id}/activate` : `/api/config/versions/${v.id}/restore`, {});
    },
    onSuccess: (r) => { setConfirm(null); setError(null); onActivated(r); },
    onError: (e) => { onFailed(); setError(errText(e)); },
  });
  const whatIf = useMutation({
    mutationFn: (v: ConfigVersion) => api.post<WhatIfRun>("/api/config/whatif", { version_id: v.id }),
    onSuccess: (r) => { setError(null); onWhatIf(r.id); }, onError: (e) => setError(errText(e)),
  });

  return (
    <Card pad={false} title="Version history" subtitle="Newest first. A rollback saves the old rules as a new version, so the history is never rewritten.">
      {error && <p role="alert" className="px-5 pt-3 text-sm text-critical-ink">{error}</p>}
      {!items.length ? <Loading /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs text-ink-3">
              <tr className="border-b border-line">{["Version", "Note", "Status", "Created", "Changes", ""].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <Fragment key={v.id}>
                  <tr className="border-b border-line last:border-0">
                    <td className="px-5 py-2.5 font-semibold tabular">v{v.id}</td>
                    <td className="max-w-[280px] px-5 py-2.5"><div className="truncate text-ink">{v.note ?? "No note"}</div>{v.restored_from && <div className="text-xs text-ink-3">copy of v{v.restored_from}</div>}</td>
                    <td className="px-5 py-2.5">{v.status === "active" ? <StatusTag status="good">Active</StatusTag> : v.status === "draft" ? <StatusTag status="warn">Draft</StatusTag> : <Chip>Retired</Chip>}</td>
                    <td className="px-5 py-2.5 text-xs text-ink-2">{dateTime(v.created_at)}<div className="text-ink-3">{v.created_by ?? ""}</div></td>
                    <td className="px-5 py-2.5 text-xs text-ink-2">{v.changes_from_previous === null ? "first version" : `${v.changes_from_previous} vs v${v.id - 1}`}<div className="text-ink-3">{v.changes_from_defaults} vs YAML</div></td>
                    <td className="px-5 py-2.5 text-right">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <Button size="sm" variant="ghost" onClick={() => setOpen(open === v.id ? null : v.id)}>{open === v.id ? "Hide changes" : "Changes"}</Button>
                        {canEdit && v.status !== "active" && <Button size="sm" variant="ghost" disabled={whatIf.isPending} onClick={() => whatIf.mutate(v)} title={`Re-run every event under version ${v.id} and compare with the rules in force`}>What if?</Button>}
                        {canEdit && v.status !== "active" && (confirm === v.id ? <>
                          <Button size="sm" variant="primary" disabled={run.isPending} onClick={() => run.mutate(v)}>{v.status === "draft" ? "Yes, activate" : "Yes, roll back"}</Button>
                          <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
                        </> : <Button size="sm" onClick={() => setConfirm(v.id)}>{v.status === "draft" ? "Activate" : "Roll back to this"}</Button>)}
                      </div>
                    </td>
                  </tr>
                  {confirm === v.id && (
                    <tr className="border-b border-line bg-surface-2/40"><td colSpan={6} className="px-5 py-2 text-xs text-ink-2">
                      Every event is processed again under {v.status === "draft" ? "this version" : `version ${v.id}'s rules (saved as a new version)`}. Scores, stages, assignments and deals may change, and the dashboard waits until it finishes.
                    </td></tr>
                  )}
                  {open === v.id && (
                    <tr className="border-b border-line bg-surface-2/40"><td colSpan={6} className="px-5 py-3">
                      {detail.isLoading || !detail.data ? <Loading rows={2} /> : <>
                        <div className="mb-1.5 text-xs font-medium text-ink-2">{detail.data.previous_id ? `Compared with v${detail.data.previous_id}` : "Compared with the YAML files"}</div>
                        <Changes items={detail.data.changes} empty={detail.data.previous_id ? "Same rules as the version before." : "Same as the YAML files."} />
                      </>}
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
