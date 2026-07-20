// The one event reducer (docs/04 M12): the live dashboard and the replay timeline
// are both projections of the same run-event stream folded through this pure
// function. Keeping it pure and framework-free makes it unit-testable and keeps
// "what happened" identical whether events arrive live over SSE or are replayed.

import type { RunEvent, RunStatus } from './types';

export interface TimelineEntry {
  id: string;
  at: string;
  label: string;
  detail: string;
  kind: 'status' | 'plan' | 'approval' | 'edit' | 'test' | 'commit' | 'pr' | 'info';
}

export interface RunProjection {
  status: RunStatus | 'unknown';
  planSteps: number;
  reviewRounds: number;
  commits: string[];
  approvalsRequested: number;
  approvalsResolved: number;
  testsPassed: boolean | null;
  pullRequestUrl: string | null;
  tokens: number;
  costUsd: number;
  toolCalls: number;
  timeline: TimelineEntry[];
}

export function emptyProjection(): RunProjection {
  return {
    status: 'unknown',
    planSteps: 0,
    reviewRounds: 0,
    commits: [],
    approvalsRequested: 0,
    approvalsResolved: 0,
    testsPassed: null,
    pullRequestUrl: null,
    tokens: 0,
    costUsd: 0,
    toolCalls: 0,
    timeline: [],
  };
}

function str(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value : '';
}

function num(payload: Record<string, unknown>, key: string): number {
  const value = payload[key];
  return typeof value === 'number' ? value : 0;
}

// Fold one event into the projection. Returns a new object (never mutates), so
// React state updates stay referentially honest.
export function reduceEvent(state: RunProjection, event: RunEvent): RunProjection {
  const next: RunProjection = { ...state, commits: [...state.commits], timeline: state.timeline };
  const p = event.payload;
  let entry: TimelineEntry | null = null;

  switch (event.event_type) {
    case 'agents.run_status_changed':
      next.status = (str(p, 'status') || state.status) as RunStatus;
      entry = mk(event, 'status', 'Status', str(p, 'status'));
      break;
    case 'agents.plan_created':
      next.planSteps = num(p, 'step_count');
      entry = mk(event, 'plan', 'Plan drafted', `${num(p, 'step_count')} steps (v${num(p, 'version')})`);
      break;
    case 'agents.approval_requested':
      next.approvalsRequested += 1;
      entry = mk(event, 'approval', 'Approval requested', str(p, 'tool'));
      break;
    case 'agents.approval_resolved':
      next.approvalsResolved += 1;
      entry = mk(event, 'approval', 'Approval resolved', p['approved'] ? 'approved' : 'rejected');
      break;
    case 'agents.code_generated':
      entry = mk(event, 'edit', 'Edit applied', filesLabel(p));
      break;
    case 'agents.review_completed':
      next.reviewRounds = Math.max(next.reviewRounds, num(p, 'iteration'));
      entry = mk(event, 'edit', 'Review', str(p, 'verdict'));
      break;
    case 'agents.step_committed': {
      const sha = str(p, 'commit_sha');
      next.commits = [...next.commits, sha];
      entry = mk(event, 'commit', 'Committed', sha.slice(0, 12));
      break;
    }
    case 'agents.commit_blocked':
      entry = mk(event, 'commit', 'Commit blocked', str(p, 'reason'));
      break;
    case 'agents.fix_generated':
      entry = mk(event, 'edit', 'Debugger fix', `attempt ${num(p, 'attempt')}`);
      break;
    case 'execution.tests_completed':
      next.testsPassed = p['passed'] === true;
      entry = mk(event, 'test', 'Tests', p['passed'] ? 'passed' : 'failed');
      break;
    case 'execution.command_executed':
      next.toolCalls += 1;
      entry = mk(event, 'test', 'Command', str(p, 'argv0'));
      break;
    case 'agents.docs_generated':
      entry = mk(event, 'info', 'Documented', `${num(p, 'summary_chars')} chars`);
      break;
    case 'agents.pull_request_opened':
      next.pullRequestUrl = str(p, 'url');
      entry = mk(event, 'pr', 'Pull request', `#${num(p, 'number')}`);
      break;
    case 'tools.invocation_completed':
      next.toolCalls += 1;
      break;
    case 'llm.call_completed':
      next.tokens += num(p, 'prompt_tokens') + num(p, 'completion_tokens');
      next.costUsd = round(next.costUsd + num(p, 'cost_usd'));
      break;
    case 'agents.run_reported':
      entry = mk(event, 'info', 'Run reported', str(p, 'outcome'));
      break;
    default:
      break;
  }

  if (entry) next.timeline = [...state.timeline, entry];
  return next;
}

export function reduceEvents(events: RunEvent[]): RunProjection {
  return events.reduce(reduceEvent, emptyProjection());
}

function mk(event: RunEvent, kind: TimelineEntry['kind'], label: string, detail: string): TimelineEntry {
  return { id: event.event_id, at: event.occurred_at, label, kind, detail };
}

function filesLabel(p: Record<string, unknown>): string {
  const files = p['files'];
  return Array.isArray(files) ? `${files.length} file(s)` : '';
}

function round(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}
