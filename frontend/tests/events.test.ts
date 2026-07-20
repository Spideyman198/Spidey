import { describe, expect, it } from 'vitest';

import { emptyProjection, reduceEvent, reduceEvents } from '../src/api/events';
import type { RunEvent } from '../src/api/types';

function ev(type: string, payload: Record<string, unknown>, id = String(Math.random())): RunEvent {
  return { event_id: id, event_type: type, occurred_at: '2026-07-20T00:00:00Z', actor: null, payload };
}

describe('reduceEvent', () => {
  it('starts from an empty, unknown projection', () => {
    const p = emptyProjection();
    expect(p.status).toBe('unknown');
    expect(p.timeline).toHaveLength(0);
    expect(p.testsPassed).toBeNull();
  });

  it('folds a full run into a projection the dashboard and replay share', () => {
    const events: RunEvent[] = [
      ev('agents.run_status_changed', { status: 'planning' }),
      ev('agents.plan_created', { version: 1, step_count: 2 }),
      ev('agents.run_status_changed', { status: 'running' }),
      ev('agents.step_committed', { step_index: 0, commit_sha: 'abcdef123456', branch: 'spidey/run-x' }),
      ev('execution.tests_completed', { framework: 'pytest', passed: true }),
      ev('llm.call_completed', { prompt_tokens: 100, completion_tokens: 50, cost_usd: 0.002 }),
      ev('agents.pull_request_opened', { number: 7, url: 'https://github.com/o/r/pull/7', branch: 'spidey/run-x' }),
      ev('agents.run_status_changed', { status: 'completed' }),
    ];
    const p = reduceEvents(events);
    expect(p.status).toBe('completed');
    expect(p.planSteps).toBe(2);
    expect(p.commits).toEqual(['abcdef123456']);
    expect(p.testsPassed).toBe(true);
    expect(p.tokens).toBe(150);
    expect(p.costUsd).toBe(0.002);
    expect(p.pullRequestUrl).toBe('https://github.com/o/r/pull/7');
    expect(p.timeline.length).toBeGreaterThan(0);
  });

  it('counts approvals requested and resolved', () => {
    const p = reduceEvents([
      ev('agents.approval_requested', { approval_id: 'a', tool: 'workspace.apply_edit', side_effect: 'write' }),
      ev('agents.approval_resolved', { approval_id: 'a', approved: true }),
    ]);
    expect(p.approvalsRequested).toBe(1);
    expect(p.approvalsResolved).toBe(1);
  });

  it('is pure — reduceEvent never mutates its input', () => {
    const before = emptyProjection();
    const after = reduceEvent(before, ev('agents.plan_created', { version: 1, step_count: 3 }));
    expect(before.planSteps).toBe(0);
    expect(after.planSteps).toBe(3);
    expect(after).not.toBe(before);
  });

  it('marks failing tests', () => {
    const p = reduceEvents([ev('execution.tests_completed', { framework: 'pytest', passed: false })]);
    expect(p.testsPassed).toBe(false);
  });
});
