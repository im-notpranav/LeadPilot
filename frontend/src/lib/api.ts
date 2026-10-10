// Thin typed client for the LeadPilot REST API.

export type Driver = { key: string; points: number; label: string };
export type Action = {
  id: string; rule_id: string; action: string; channel: string; due_at: string; urgency: string; reason: string;
  template: string; completion?: { type: string; payload: Record<string, unknown> } | null; rep_id?: string | null;
  created_at?: string; status?: string; closed_at?: string | null; ts?: string;
  alternates?: { rule_id: string; action: string; reason: string; due_minutes: number; urgency: string }[];
};
export type Stall = { is_stalled: boolean; rules: string[]; details: string[]; risk: number; days_over_sla: number; sla_days: number | null };
export type LeadView = {
  lead_id: string; name: string; company: string | null; title: string | null; email: string | null; phone: string | null;
  country: string | null; region: string | null; industry: string | null; employees: number | null; segment: string | null;
  source: string; sources: string[]; status: string; merged_into: string | null; owner_rep_id: string | null;
  owner_name: string | null; stage: string; stage_entered_at: string | null; days_in_stage: number; is_stalled: boolean;
  stall: Stall; score: number; grade: string; intent_level: string; active_signals: string[];
  parts: { fit: number; engagement: number; intent: number; penalties: number }; fake_score: number; fake_status: string;
  predicted_acv: number; acv_p10: number; acv_p90: number; close_prob: number; expected_value: number; priority: number;
  priority_drivers: Driver[]; created_at: string | null; last_inbound_at: string | null; last_outbound_at: string | null;
  first_response_at: string | null; first_response_minutes: number | null; primary_action: Action | null;
  sla_deadline: string | null; auto_reassign_count: number; sparkline: number[];
  action_due_minutes?: number | null; sla_minutes_left?: number | null;
};
export type Factor = { key: string; category: string; value: number; reason: string; evidence: string[]; label: string; raw: number; count: number; half_life: number | null };
export type Contribution = { key: string; category: string; delta: number; reason: string; text?: string; evidence: string[] };
export type Transition = { ts: string; from_stage: string; to_stage: string; rule_id: string; evidence_event_ids: string[]; mode: string; reason: string };
export type LeadDetail = LeadView & {
  alternates: Action["alternates"]; factors: Record<string, Factor>;
  acv_factors: { key: string; label: string; value: number; kind: string }[];
  close_factors: { key: string; label: string; logit: number | null }[];
  metrics: Record<string, unknown>; quality: { fake_score: number; signals: { key: string; weight: number; detail: string }[]; status: string; reviewed_by: string | null } | null;
  merged_ids: string[]; emails: string[]; seniority: string; revenue_band: string | null; tech_stack: string[];
  funding_stage: string | null; account_id: string | null; disqualifier: string | null; budget: number | null; seats: number | null;
  fake_signals: { key: string; weight: number; detail: string }[];
  transitions: Transition[]; assignments: any[]; actions: Action[]; stall_flags: any[]; merges: any[];
  redirect?: string;
};
export type ScorePoint = { id: number; ts: string; score: number; old: number; delta: number; event_id: string; event_type: string; summary: string; grade: string; intent_level: string; parts: LeadView["parts"]; contributions: Contribution[] };
export type FeedItem = { ts: string; event_id: string; type: string; lead_id: string; name: string | null; company: string | null; actor: string; rep_id: string | null; source: string | null; delta: number; score: number | null; grade: string | null; stage: string | null; summary: string };
export type Rep = { rep_id: string; name: string; profile: string; territories: string[]; industries: string[]; segments: string[]; tags: string[]; open_leads: number; load: number; capacity: number; pipeline_ev: number; stalled: number; won_live: number; lost_live: number; wins_total: number; closed_total: number; win_rate: number | null; revenue: number; median_first_response_min: number | null; sla_attainment: number | null; neglect_count: number; reassigned_away: number; assigned: number };
export type SimStatus = { status: string; seed: number; clock: { now: string; speed: number; paused: boolean }; events: number; raw_events: number; leads: number; open_leads: number; stalled: number; quarantined: number; merged: number; won: number; lost: number; scheduled: number; latency: { count: number; p50_ms?: number; p95_ms?: number; max_ms?: number }; background: boolean; rep_actions: boolean; historical_deals: number; sim_counts: Record<string, number> };

// Session hooks, set by AuthProvider: the current access token, and what to do when the server rejects it.
let tokenSource: () => string | null = () => null;
let onUnauthorized: () => void = () => {};
export function configureAuth(getToken: () => string | null, unauthorized: () => void) {
  tokenSource = getToken;
  onUnauthorized = unauthorized;
}
export const currentToken = () => tokenSource();

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(`${status}: ${detail}`); }
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not json */ }
    if (r.status === 401) onUnauthorized();
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenSource();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => handle<T>(r));
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

export type Role = "admin" | "manager" | "rep" | "pending";
export type Me = { kind: string; role: Role; user_id: string | null; email: string | null; name: string | null; rep_id: string | null; rep_name: string | null; team_rep_ids: string[] | null; auth: boolean };
export type AuthConfig = { enabled: boolean; supabase_url: string | null; anon_key: string | null; login_ready: boolean };
export type Profile = { user_id: string; email: string | null; name: string | null; role: Role; rep_id: string | null; team_rep_ids: string[] | null; created_at: string | null; updated_at: string | null; last_seen_at: string | null };
export type ApiKey = { id: string; name: string; prefix: string; created_by: string | null; created_at: string; last_used_at: string | null; revoked_at: string | null; secret?: string; note?: string };

export const STAGES = ["new", "contacted", "engaged", "qualified", "meeting", "proposal", "negotiation", "won", "lost", "nurture", "disqualified"];
export const EVENT_TYPES = ["page_view", "content_download", "webinar_registered", "webinar_attended", "demo_request", "contact_sales", "trial_signup", "proposal_viewed", "email_sent", "email_opened", "email_clicked", "email_replied", "email_bounced", "unsubscribed", "call_logged", "meeting_scheduled", "meeting_held", "meeting_no_show", "proposal_sent", "contract_sent", "deal_won", "deal_lost", "task_created", "task_completed", "bant_qualified"];
export const REP_EVENTS = new Set(["email_sent", "call_logged", "meeting_scheduled", "meeting_held", "meeting_no_show", "proposal_sent", "contract_sent", "deal_won", "deal_lost", "task_created", "task_completed", "bant_qualified"]);
