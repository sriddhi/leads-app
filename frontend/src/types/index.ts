export type LeadStatus = 'PENDING' | 'REACHED_OUT';

export type Role = 'ADMIN' | 'ATTORNEY';

export type LeadState = 'QUEUED' | 'ASSIGNED' | 'REACHED_OUT';

export interface Lead {
  id: string;
  lead_number: string;
  first_name: string;
  last_name: string;
  email: string;
  phone?: string | null;
  message?: string | null;
  resume_filename: string;
  resume_original_filename: string;
  status: LeadStatus;
  assignee_id: string | null;
  assignee_name?: string | null;
  version: number;
  is_potential_duplicate: boolean;
  duplicate_of: string | null;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
  full_name: string;
  role: Role;
}

export interface CaseHistoryItem {
  id: string;
  lead_number: string | null;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  status: LeadStatus;
  created_at: string;
  matched_on: string[];
}

export interface RelatedLeadItem {
  id: string;
  lead_number: string | null;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  status: LeadStatus;
  assignee_id: string | null;
  version: number;
  created_at: string;
}

export interface RelatedTransitionResult {
  id: string;
  lead_number: string | null;
  ok: boolean;
  detail: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
}

export interface PaginatedLeads {
  items: Lead[];
  total: number;
  page: number;
  pages: number;
}

export interface QueueItem extends Lead {
  age_seconds: number;
}

export interface StatePeriod {
  state: LeadState;
  assignee_id: string | null;
  assignee_name?: string | null;
  entered_at: string;
  exited_at: string | null;
  duration_seconds: number | null;
}

export interface LeadDetail extends Lead {
  timeline: StatePeriod[];
}

export interface AuditEvent {
  id: string;
  lead_id: string;
  actor_kind: string;
  action: string;
  reason: string | null;
  created_at: string;
  ip: string | null;
}

export interface MetricsAttorney {
  id: string;
  name: string;
  open: number;
  cap: number;
  utilization: number;
}

export interface Metrics {
  queue_depth: number;
  oldest_queued_age_seconds: number;
  in_progress: number;
  reached_out: number;
  reached_out_last_hour: number;
  attorneys: MetricsAttorney[];
}

export interface AttorneyTimeRow {
  attorney_id: string;
  name: string;
  total_holding_seconds: number;
  cases_handled: number;
  avg_time_to_reached_out_seconds: number | null;
  current_open_load: number;
  oldest_open_age_seconds: number | null;
}

export interface AttorneyCapacity {
  id: string;
  name: string;
  max_open_cases: number;
  open: number;
}
