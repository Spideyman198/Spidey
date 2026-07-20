// Hand-authored types for the API surface the UI drives. Kept in sync with the
// backend OpenAPI (docs/api/openapi.json); a codegen step can replace this later.

export type RunStatus =
  | 'pending'
  | 'planning'
  | 'awaiting_approval'
  | 'running'
  | 'needs_human'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface Run {
  id: string;
  owner_id: string;
  workspace_id: string | null;
  session_id: string | null;
  goal: string;
  status: RunStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlanStep {
  index: number;
  title: string;
  detail: string;
  status: string;
}

export interface Plan {
  version: number;
  steps: PlanStep[];
}

export interface Approval {
  id: string;
  run_id: string;
  tool: string;
  side_effect: string;
  arguments_preview: string;
  status: string;
  requested_at: string;
}

export interface RunReport {
  run_id: string;
  goal: string;
  status: RunStatus;
  outcome: string;
  steps: { index: number; title: string; status: string }[];
  commits: string[];
  tests_passed: boolean | null;
  pull_request_url: string | null;
  event_count: number;
}

export interface Memory {
  id: string;
  kind: string;
  content: string;
  confidence: number;
  use_count: number;
  created_at: string;
}

// A domain event as delivered over SSE or read from the timeline endpoint. The
// payload is untyped-per-event JSON; the reducer narrows it by `event_type`.
export interface RunEvent {
  event_id: string;
  event_type: string;
  occurred_at: string;
  actor: string | null;
  payload: Record<string, unknown>;
}
