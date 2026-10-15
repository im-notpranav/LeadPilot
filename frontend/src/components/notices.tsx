// Shared pieces for notifications: labels and icons per rule, the row used by the bell and the page.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Notice, type NoticeDelivery } from "../lib/api";
import { ago } from "../lib/format";
import { Icon, type IconName } from "./icons";

export const RULE_LABEL: Record<string, string> = {
  hot_lead: "Hot lead", lead_assigned: "New lead", reply_received: "Reply", meeting_booked: "Meeting or demo",
  lead_reassigned: "Reassigned", escalated: "Escalated", stalled: "Stalled", deal_won: "Deal won", deal_lost: "Deal lost",
  review_needed: "Review needed", source_flagged: "Source flagged", call_analyzed: "Call summary",
};
const RULE_ICON: Record<string, IconName> = {
  hot_lead: "zap", lead_assigned: "user", reply_received: "mail", meeting_booked: "clock", lead_reassigned: "users",
  escalated: "alert", stalled: "alert", deal_won: "trophy", deal_lost: "wallet", review_needed: "quality", source_flagged: "quality", call_analyzed: "phone",
};
export const TO_LABEL: Record<string, string> = { owner: "Owner", previous_owner: "Previous owner", managers: "Managers" };
export const CHANNEL_LABEL: Record<string, string> = { in_app: "In app", email: "Email", slack: "Slack", sms: "SMS" };

export function NoticeIcon({ n }: { n: Pick<Notice, "rule" | "severity"> }) {
  const bad = n.severity === "urgent" || n.rule === "stalled" || n.rule === "escalated" || n.rule === "source_flagged";
  return (
    <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${bad ? "bg-[color-mix(in_srgb,var(--c-critical)_14%,transparent)] text-critical-ink" : "bg-accent-soft text-accent-ink"}`}>
      <Icon name={RULE_ICON[n.rule] ?? "bell"} size={14} />
    </span>
  );
}

/** Mark notifications read (or all of them) and refresh every notifications query. */
export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { ids: number[] } | { all: true }) => api.post<{ unread: number }>("/api/notifications/read", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function NoticeRow({ n, now, onOpen, showRep = false, compact = false }: { n: Notice; now: string | null; onOpen: () => void; showRep?: boolean; compact?: boolean }) {
  return (
    <button type="button" onClick={onOpen} className={`group flex w-full items-start gap-2.5 rounded-xl text-left transition hover:bg-surface-2 ${compact ? "px-2.5 py-2" : "px-3 py-2.5"}`}>
      <NoticeIcon n={n} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className={`min-w-0 flex-1 truncate text-sm ${n.read ? "text-ink-2" : "font-semibold text-ink"}`}>{n.title}</span>
          <span className="shrink-0 text-[11px] tabular text-ink-3">{ago(n.ts, now)}</span>
        </span>
        <span className={`block text-xs text-ink-3 ${compact ? "line-clamp-2" : ""}`}>{n.body}</span>
        {showRep && n.audience === "rep" && n.rep_name && <span className="mt-1 inline-block rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-ink-2">For {n.rep_name}</span>}
      </span>
      {!n.read && <span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-brand" aria-label="Unread" />}
    </button>
  );
}

export function DeliveryChips({ items }: { items: NoticeDelivery[] }) {
  if (!items.length) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((d, i) => (
        <span key={i} title={[d.target, d.detail].filter(Boolean).join(": ") || undefined}
          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${d.status === "sent" ? "border-[color-mix(in_srgb,var(--c-good)_40%,transparent)] text-good-ink" : d.status === "failed" ? "border-[color-mix(in_srgb,var(--c-critical)_40%,transparent)] text-critical-ink" : "border-line text-ink-3"}`}>
          {CHANNEL_LABEL[d.channel] ?? d.channel} {d.status === "sent" ? "sent" : d.status === "failed" ? "failed" : "skipped"}
        </span>
      ))}
    </span>
  );
}
