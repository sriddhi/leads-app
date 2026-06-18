import type {
  Lead,
  PaginatedLeads,
  AuthToken,
  User,
  QueueItem,
  LeadDetail,
  AuditEvent,
  Metrics,
  AttorneyTimeRow,
  AttorneyCapacity,
  CaseHistoryItem,
  RelatedLeadItem,
  RelatedTransitionResult,
} from '@/types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function isConflictError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status >= 400) {
    let message = `Request failed with status ${res.status}`;
    try {
      const json = await res.json();
      if (json.detail) {
        message = typeof json.detail === 'string' ? json.detail : JSON.stringify(json.detail);
      } else if (json.message) {
        message = json.message;
      }
    } catch {
      // ignore parse errors
    }
    if (res.status === 409 && message === `Request failed with status ${res.status}`) {
      message = 'This lead changed since you loaded it. Please refresh.';
    }
    throw new ApiError(message, res.status);
  }
  return res.json() as Promise<T>;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

function jsonAuthHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

// The public endpoint returns only a minimal receipt (no internal fields).
export interface LeadReceipt {
  lead_number: string | null;
  status: string;
  message: string;
}

export async function submitLead(formData: FormData): Promise<LeadReceipt> {
  const res = await fetch(`${BASE_URL}/api/v1/leads`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<LeadReceipt>(res);
}

export async function getLeads(token: string, page = 1): Promise<PaginatedLeads> {
  const res = await fetch(`${BASE_URL}/api/v1/leads?page=${page}&page_size=20`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return handleResponse<PaginatedLeads>(res);
}

export async function getLead(token: string, id: string): Promise<Lead> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return handleResponse<Lead>(res);
}

export async function updateLeadStatus(token: string, id: string): Promise<Lead> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/status`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ status: 'REACHED_OUT' }),
  });
  return handleResponse<Lead>(res);
}

export async function login(email: string, password: string): Promise<AuthToken> {
  const body = new URLSearchParams();
  body.append('username', email);
  body.append('password', password);

  const res = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: body.toString(),
  });
  return handleResponse<AuthToken>(res);
}

export async function getMe(token: string): Promise<User> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/me`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return handleResponse<User>(res);
}

// ---------------------------------------------------------------------------
// Attorney workflow
// ---------------------------------------------------------------------------

export async function getQueue(token: string): Promise<QueueItem[]> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/queue`, {
    headers: authHeaders(token),
  });
  return handleResponse<QueueItem[]>(res);
}

export async function getMyCases(token: string): Promise<Lead[]> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/my-cases`, {
    headers: authHeaders(token),
  });
  return handleResponse<Lead[]>(res);
}

export async function getLeadByNumber(token: string, num: string): Promise<LeadDetail> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/by-number/${encodeURIComponent(num)}`, {
    headers: authHeaders(token),
  });
  return handleResponse<LeadDetail>(res);
}

export async function getLeadDetail(token: string, id: string): Promise<LeadDetail> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}`, {
    headers: authHeaders(token),
  });
  return handleResponse<LeadDetail>(res);
}

export async function getCaseHistory(
  token: string,
  id: string,
  dims: string[] = ['phone', 'email'],
): Promise<CaseHistoryItem[]> {
  const qs = dims.length ? `?dims=${encodeURIComponent(dims.join(','))}` : '';
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/history${qs}`, {
    headers: authHeaders(token),
  });
  return handleResponse<CaseHistoryItem[]>(res);
}

export async function getRelatedLeads(token: string, id: string): Promise<RelatedLeadItem[]> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/related`, {
    headers: authHeaders(token),
  });
  return handleResponse<RelatedLeadItem[]>(res);
}

export async function transitionRelated(
  token: string,
  id: string,
  action: 'assign' | 'reached_out',
  leadIds: string[],
  note?: string,
): Promise<RelatedTransitionResult[]> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/related/transition`, {
    method: 'POST',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ action, lead_ids: leadIds, note }),
  });
  return handleResponse<RelatedTransitionResult[]>(res);
}

export async function assignToMe(token: string, id: string, version: number): Promise<Lead> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/assign`, {
    method: 'POST',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ version }),
  });
  return handleResponse<Lead>(res);
}

export async function reassign(
  token: string,
  id: string,
  version: number,
  assignee_id: string | null,
  reason?: string
): Promise<Lead> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/reassign`, {
    method: 'POST',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ version, assignee_id, reason }),
  });
  return handleResponse<Lead>(res);
}

export async function markReachedOut(token: string, id: string, version: number): Promise<Lead> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/status`, {
    method: 'PATCH',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ status: 'REACHED_OUT', version }),
  });
  return handleResponse<Lead>(res);
}

export async function reverse(
  token: string,
  id: string,
  version: number,
  reason: string
): Promise<Lead> {
  const res = await fetch(`${BASE_URL}/api/v1/leads/${id}/reverse`, {
    method: 'POST',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ version, reason }),
  });
  return handleResponse<Lead>(res);
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export async function adminGetAttorneys(token: string): Promise<AttorneyCapacity[]> {
  const res = await fetch(`${BASE_URL}/api/v1/admin/attorneys`, {
    headers: authHeaders(token),
  });
  return handleResponse<AttorneyCapacity[]>(res);
}

export async function adminSetCapacity(
  token: string,
  id: string,
  max_open_cases: number
): Promise<AttorneyCapacity> {
  const res = await fetch(`${BASE_URL}/api/v1/admin/attorneys/${id}/capacity`, {
    method: 'PUT',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ max_open_cases }),
  });
  return handleResponse<AttorneyCapacity>(res);
}

export async function adminToggleAutoAssign(
  token: string,
  enabled: boolean
): Promise<{ enabled: boolean }> {
  const res = await fetch(`${BASE_URL}/api/v1/admin/settings/auto-assign`, {
    method: 'PUT',
    headers: jsonAuthHeaders(token),
    body: JSON.stringify({ enabled }),
  });
  return handleResponse<{ enabled: boolean }>(res);
}

export async function adminGetAudit(token: string): Promise<{ items: AuditEvent[] }> {
  const res = await fetch(`${BASE_URL}/api/v1/admin/audit`, {
    headers: authHeaders(token),
  });
  return handleResponse<{ items: AuditEvent[] }>(res);
}

export async function adminGetMetrics(token: string): Promise<Metrics> {
  const res = await fetch(`${BASE_URL}/api/v1/admin/metrics`, {
    headers: authHeaders(token),
  });
  return handleResponse<Metrics>(res);
}

export async function adminGetAttorneyTime(token: string): Promise<AttorneyTimeRow[]> {
  const res = await fetch(`${BASE_URL}/api/v1/admin/attorney-time`, {
    headers: authHeaders(token),
  });
  return handleResponse<AttorneyTimeRow[]>(res);
}

/**
 * Opens an SSE stream of audit events. EventSource cannot set headers, so the
 * token is passed via query string. Returns the EventSource so the caller can
 * close it. onEvent receives the parsed JSON payload of each message.
 */
export function openAuditStream(
  token: string,
  onEvent: (event: AuditEvent) => void
): EventSource {
  const url = `${BASE_URL}/api/v1/admin/audit/stream?token=${encodeURIComponent(token)}`;
  const source = new EventSource(url);
  source.onmessage = (e: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(e.data) as AuditEvent;
      onEvent(parsed);
    } catch {
      // ignore malformed messages
    }
  };
  return source;
}
