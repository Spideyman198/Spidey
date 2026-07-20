// Typed API client. JWT is held in memory + localStorage and sent as a bearer on
// every request. SSE is consumed via a fetch stream (not EventSource) so the
// token travels in the Authorization header, never in the URL (docs/11 privacy).

import type { Approval, Memory, Plan, Run, RunEvent, RunReport } from './types';

const BASE = '/api/v1';
const TOKEN_KEY = 'spidey.token';

let token: string | null = localStorage.getItem(TOKEN_KEY);

export function getToken(): string | null {
  return token;
}

export function setToken(value: string | null): void {
  token = value;
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!response.ok) {
    const detail = data?.detail ?? data?.message ?? response.statusText;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : 'request failed');
  }
  return data as T;
}

export interface TokenPair {
  access_token: string;
}

export const api = {
  async login(email: string, password: string): Promise<void> {
    const pair = await request<TokenPair>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    setToken(pair.access_token);
  },
  logout(): void {
    setToken(null);
  },

  listRuns: () => request<Run[]>('/runs'),
  getRun: (id: string) => request<Run>(`/runs/${id}`),
  createRun: (goal: string, workspaceId?: string) =>
    request<Run>('/runs', {
      method: 'POST',
      body: JSON.stringify({ goal, workspace_id: workspaceId ?? null }),
    }),
  cancelRun: (id: string) => request<Run>(`/runs/${id}/cancel`, { method: 'POST' }),
  resumeRun: (id: string) => request<Run>(`/runs/${id}/resume`, { method: 'POST' }),
  getPlan: (id: string) => request<Plan>(`/runs/${id}/plan`),
  listApprovals: (id: string) => request<Approval[]>(`/runs/${id}/approvals`),
  resolveApproval: (runId: string, approvalId: string, approved: boolean) =>
    request<void>(`/runs/${runId}/approvals/${approvalId}`, {
      method: 'POST',
      body: JSON.stringify({ approved }),
    }),
  getReport: (id: string) => request<RunReport>(`/runs/${id}/report`),
  getTimeline: (id: string) => request<RunEvent[]>(`/runs/${id}/timeline`),
  getDiff: (id: string) => request<{ diff: string }>(`/runs/${id}/diff`),

  listMemories: () => request<Memory[]>('/memories'),
  deleteMemory: (id: string) => request<void>(`/memories/${id}`, { method: 'DELETE' }),
  remember: (content: string) =>
    request<Memory>('/memories', { method: 'POST', body: JSON.stringify({ content }) }),
};

// Stream a run's SSE events with the bearer in the header. Calls `onEvent` per
// `data:` frame and resolves when the stream ends or `signal` aborts.
export async function streamRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const headers = new Headers({ Accept: 'text/event-stream' });
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${BASE}/runs/${runId}/events`, { headers, signal });
  if (!response.ok || !response.body) throw new ApiError(response.status, 'stream failed');

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(5).trim()) as RunEvent);
      } catch {
        // A keep-alive or malformed frame — ignore.
      }
    }
  }
}
