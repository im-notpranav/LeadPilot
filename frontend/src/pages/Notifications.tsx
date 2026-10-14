// Notifications: everything sent to you (and, for managers and admins, to your reps), your own channel settings,
// and for admins the state of each delivery channel with a test button. Rules live in backend/config/notifications.yaml.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Notice, type NoticeList, type NoticeMe, type NoticeSettings } from "../lib/api";
import { can, useAuth } from "../lib/auth";
import { useLive } from "../lib/live";
import { errText, inputCls } from "../components/deals";
import { CHANNEL_LABEL, DeliveryChips, NoticeRow, RULE_LABEL, TO_LABEL, useMarkRead } from "../components/notices";
import { Button, Card, Chip, Empty, Loading, PageHeader, Segmented, Select, StatusTag } from "../components/ui";

const PAGE = 50;

export default function Notifications() {
  const { me } = useAuth();
  const manage = can.manage(me);
  const [show, setShow] = useState<"all" | "unread">("all");
  const [whose, setWhose] = useState<"mine" | "team">("mine");
  const [rule, setRule] = useState("");
  const settings = useQuery({ queryKey: ["notifications", "settings"], queryFn: () => api.get<NoticeSettings>("/api/notifications/settings") });
  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <PageHeader title="Notifications" subtitle="New leads, replies, reassignments, stalls and deal results, as they happen. Email, Slack and SMS follow the same rules once they are set up." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Inbox show={show} setShow={setShow} whose={manage ? whose : "mine"} setWhose={manage ? setWhose : undefined} rule={rule} setRule={setRule} admin={can.admin(me)} />
        <div className="space-y-4">
          {settings.isLoading ? <Card><Loading rows={3} /></Card>
            : settings.error || !settings.data ? <Card><Empty>Could not load the settings. {errText(settings.error)}</Empty></Card>
            : <>
              <MySettings s={settings.data} />
              {can.admin(me) && <ChannelsCard s={settings.data} />}
              {manage && settings.data.rules.length > 0 && <RulesCard s={settings.data} />}
            </>}
        </div>
      </div>
    </div>
  );
}

function Inbox({ show, setShow, whose, setWhose, rule, setRule, admin }: {
  show: "all" | "unread"; setShow: (v: "all" | "unread") => void; whose: "mine" | "team"; setWhose?: (v: "mine" | "team") => void;
  rule: string; setRule: (v: string) => void; admin: boolean;
}) {
  const { clock } = useLive();
  const nav = useNavigate();
  const read = useMarkRead();
  const params = (before?: number) => {
    const p = new URLSearchParams({ limit: String(PAGE), mine: String(whose === "mine"), unread: String(show === "unread") });
    if (rule) p.set("rule", rule);
    if (before) p.set("before", String(before));
    return p.toString();
  };
  const q = useInfiniteQuery({
    queryKey: ["notifications", "list", show, whose, rule],
    queryFn: ({ pageParam }) => api.get<NoticeList>(`/api/notifications?${params(pageParam)}`),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.items.length === PAGE ? last.items[last.items.length - 1].id : undefined),
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const unread = q.data?.pages[0]?.unread ?? 0;
  const open = (n: Notice) => { if (!n.read) read.mutate({ ids: [n.id] }); if (n.link) nav(n.link); };
  return (
    <Card pad={false} title={`Inbox${unread ? ` · ${unread} unread` : ""}`}
      subtitle={whose === "team" ? "Everything sent to you and to the reps you oversee." : "Everything sent to you."}
      right={unread > 0 ? <Button size="sm" variant="ghost" disabled={read.isPending} onClick={() => read.mutate({ all: true })}>Mark all read</Button> : undefined}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        <Segmented label="Show" value={show} onChange={setShow} options={[{ value: "all", label: "All" }, { value: "unread", label: "Unread" }]} />
        {setWhose && <Segmented label="Whose" value={whose} onChange={setWhose} options={[{ value: "mine", label: "Sent to me" }, { value: "team", label: "My reps' too" }]} />}
        <Select label="Kind" value={rule} onChange={setRule}>
          <option value="">Every kind</option>
          {Object.entries(RULE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </div>
      {q.isLoading ? <div className="p-5"><Loading rows={5} /></div>
        : q.error ? <Empty>Could not load notifications. {errText(q.error)}</Empty>
        : !items.length ? <Empty>{show === "unread" ? "You are all caught up." : "No notifications yet. They start as soon as leads, replies and deals come in."}</Empty>
        : (
          <ul className="divide-y divide-[var(--c-line)] p-1.5">
            {items.map((n) => (
              <li key={n.id}>
                <NoticeRow n={n} now={clock.now} showRep={whose === "team"} onOpen={() => open(n)} />
                {admin && n.deliveries && n.deliveries.length > 0 && <div className="px-3 pb-2 pl-[3.25rem]"><DeliveryChips items={n.deliveries} /></div>}
              </li>
            ))}
          </ul>
        )}
      {q.hasNextPage && <div className="border-t border-line p-3 text-center"><Button size="sm" variant="ghost" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>{q.isFetchingNextPage ? "Loading…" : "Show older"}</Button></div>}
    </Card>
  );
}

function MySettings({ s }: { s: NoticeSettings }) {
  const qc = useQueryClient();
  const configured = (c: string) => s.channels.find((x) => x.channel === c)?.configured ?? false;
  const [form, setForm] = useState<NoticeMe | null>(s.me);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(s.me), [s.me]);
  const save = useMutation({
    mutationFn: (f: NoticeMe) => api.put<NoticeMe>("/api/notifications/settings", { phone: f.phone, email: f.email, sms: f.sms }),
    onSuccess: () => { setSaved(true); qc.invalidateQueries({ queryKey: ["notifications", "settings"] }); },
  });
  if (!s.me || !form) {
    return <Card title="Your settings"><p className="text-sm text-ink-3">Sign-in is off on this server, so there is no personal profile to keep settings on. Everything still shows here and in the bell.</p></Card>;
  }
  const set = (patch: Partial<NoticeMe>) => { setForm({ ...form, ...patch }); setSaved(false); };
  return (
    <Card title="Your settings" subtitle="How you hear about things outside the app. In-app notifications are always on.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
        <label className="flex items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--c-brand)]" checked={form.email} onChange={(e) => set({ email: e.target.checked })} />
          <span><span className="font-medium text-ink">Email me</span><span className="block text-xs text-ink-3">{form.email_address ?? "Your account has no email address."}{!configured("email") && " Email is not set up on this server yet."}</span></span>
        </label>
        <label className="flex items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--c-brand)]" checked={form.sms} onChange={(e) => set({ sms: e.target.checked })} />
          <span><span className="font-medium text-ink">Text me</span><span className="block text-xs text-ink-3">Only for urgent ones, like a hot lead assigned to you.{!configured("sms") && " SMS is not set up on this server yet."}</span></span>
        </label>
        <label className="block"><span className="mb-1 block text-xs font-medium text-ink-2">Mobile number</span>
          <input type="tel" value={form.phone ?? ""} onChange={(e) => set({ phone: e.target.value || null })} placeholder="+44 7911 123456" className={inputCls} /></label>
        {save.error && <p role="alert" className="text-sm text-critical-ink">{errText(save.error)}</p>}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
          {saved && <span role="status" className="text-sm text-good-ink">Saved</span>}
        </div>
      </form>
    </Card>
  );
}

function ChannelsCard({ s }: { s: NoticeSettings }) {
  const [result, setResult] = useState<Record<string, string>>({});
  const test = useMutation({
    mutationFn: (channel: string) => api.post<{ channel: string; status: string; target?: string; detail: string | null }>("/api/notifications/test", { channel }),
    onSuccess: (r) => setResult((x) => ({ ...x, [r.channel]: r.status === "sent" ? `Sent${r.target ? ` to ${r.target}` : ""}.` : `Failed: ${r.detail}` })),
    onError: (e, channel) => setResult((x) => ({ ...x, [channel]: `Failed: ${errText(e)}` })),
  });
  return (
    <Card title="Channels" subtitle="A channel delivers once its keys are in backend/.env (restart to apply).">
      {!s.delivers && <p className="mb-3 rounded-xl border border-line bg-surface-2/50 px-3 py-2 text-xs text-ink-2">Demo mode: simulated leads only notify in the app, so nobody gets real emails or texts about fake leads. Set <code className="font-mono">LEADPILOT_NOTIFY_IN_DEMO=1</code> to deliver anyway. Tests always send.</p>}
      <ul className="space-y-3">
        {s.channels.map((c) => (
          <li key={c.channel} className="text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-ink">{c.label}</span>
              <span className="flex items-center gap-2">
                {c.configured ? <StatusTag status="good">Ready</StatusTag> : <StatusTag status="warn">Not set up</StatusTag>}
                {c.channel !== "in_app" && <Button size="sm" variant="ghost" disabled={!c.configured || test.isPending} onClick={() => test.mutate(c.channel)}>Send test</Button>}
              </span>
            </div>
            {!c.configured && c.needs.length > 0 && <div className="mt-1 text-xs text-ink-3">Needs {c.needs.map((n, i) => <span key={n}>{i > 0 && ", "}<code className="font-mono">{n}</code></span>)}</div>}
            {result[c.channel] && <div role="status" className={`mt-1 text-xs ${result[c.channel].startsWith("Sent") ? "text-good-ink" : "text-critical-ink"}`}>{result[c.channel]}</div>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function RulesCard({ s }: { s: NoticeSettings }) {
  return (
    <Card pad={false} title="Rules" subtitle={<>Who hears about what. Edit <code className="font-mono">backend/config/notifications.yaml</code> and restart to change them.</>}>
      <ul className="divide-y divide-[var(--c-line)]">
        {s.rules.map((r) => (
          <li key={r.name} className={`px-5 py-2.5 text-sm ${r.enabled ? "" : "opacity-60"}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-ink">{RULE_LABEL[r.name] ?? r.name}</span>
              {r.enabled ? (r.severity === "urgent" ? <StatusTag status="critical">Urgent</StatusTag> : null) : <Chip>Off</Chip>}
            </div>
            <div className="mt-0.5 text-xs text-ink-3">To {r.to.map((t) => TO_LABEL[t] ?? t).join(", ").toLowerCase()} · {r.channels.map((c) => CHANNEL_LABEL[c] ?? c).join(", ")}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
