import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { api } from '../../api/client';
import { StatusBadge } from '../../components/StatusBadge';
import { useRunEvents } from '../runs/useRunEvents';
import type { Run } from '../../api/types';

const ACTIVE = new Set(['pending', 'planning', 'awaiting_approval', 'running', 'needs_human']);

export function Dashboard() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.listRuns, refetchInterval: 5000 });
  const active = (runs.data ?? []).filter((r) => ACTIVE.has(r.status));

  return (
    <div>
      <h2>Dashboard</h2>
      {active.length === 0 && <p className="muted">No active runs.</p>}
      {active[0] && <LiveRun run={active[0]} />}

      <div className="panel">
        <h3>Active runs</h3>
        {active.map((run) => (
          <div className="row" key={run.id} style={{ justifyContent: 'space-between' }}>
            <Link to={`/runs/${run.id}`}>{run.goal}</Link>
            <StatusBadge status={run.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

// The live tiles are folded from the same event reducer as the run view/replay.
function LiveRun({ run }: { run: Run }) {
  const p = useRunEvents(run.id);
  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3>{run.goal}</h3>
        <StatusBadge status={p.status !== 'unknown' ? p.status : run.status} />
      </div>
      <div className="row" style={{ gap: 24, flexWrap: 'wrap' }}>
        <span className="stat">
          <b>{p.planSteps}</b>plan steps
        </span>
        <span className="stat">
          <b>{p.commits.length}</b>commits
        </span>
        <span className="stat">
          <b>{p.toolCalls}</b>tool calls
        </span>
        <span className="stat">
          <b>{p.tokens.toLocaleString()}</b>tokens
        </span>
        <span className="stat">
          <b>${p.costUsd.toFixed(4)}</b>cost
        </span>
        <span className="stat">
          <b>{p.testsPassed === null ? '—' : p.testsPassed ? '✓' : '✗'}</b>tests
        </span>
      </div>
    </div>
  );
}
