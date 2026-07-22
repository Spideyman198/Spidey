import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';

import { api } from '../../api/client';
import { DiffViewer } from '../../components/DiffViewer';
import { StatusBadge } from '../../components/StatusBadge';
import { Timeline } from '../../components/Timeline';
import { useRunEvents } from './useRunEvents';

export function RunView() {
  const { runId = '' } = useParams();
  const queryClient = useQueryClient();
  const p = useRunEvents(runId);

  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.getRun(runId) });
  const plan = useQuery({ queryKey: ['plan', runId], queryFn: () => api.getPlan(runId), retry: false });
  const approvals = useQuery({
    queryKey: ['approvals', runId, p.approvalsRequested],
    queryFn: () => api.listApprovals(runId),
  });
  const diff = useQuery({ queryKey: ['diff', runId], queryFn: () => api.getDiff(runId), enabled: false });

  const resolve = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      api.resolveApproval(runId, id, approved),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['approvals', runId] }),
  });
  const resume = useMutation({ mutationFn: () => api.resumeRun(runId) });
  const cancel = useMutation({ mutationFn: () => api.cancelRun(runId) });

  const status = p.status !== 'unknown' ? p.status : (run.data?.status ?? 'pending');
  const pending = (approvals.data ?? []).filter((a) => a.status === 'pending');

  return (
    <div>
      <div className="section-head">
        <h2>{run.data?.goal ?? 'Run'}</h2>
        <StatusBadge status={status} />
      </div>

      <div className="row wrap" style={{ marginBottom: 16 }}>
        <button className="primary" onClick={() => resume.mutate()}>
          Resume / approve plan
        </button>
        <button onClick={() => cancel.mutate()}>Cancel</button>
        <Link className="btn" to={`/runs/${runId}/replay`}>
          Replay ↻
        </Link>
        {p.pullRequestUrl && (
          <a className="btn primary" href={p.pullRequestUrl} target="_blank" rel="noreferrer">
            View pull request ↗
          </a>
        )}
      </div>

      <div className="stats" style={{ marginBottom: 16 }}>
        <div className="stat">
          <b>{p.planSteps}</b>
          <span>plan steps</span>
        </div>
        <div className="stat">
          <b>{p.reviewRounds}</b>
          <span>review rounds</span>
        </div>
        <div className="stat">
          <b>{p.commits.length}</b>
          <span>commits</span>
        </div>
        <div className="stat">
          <b>{p.toolCalls}</b>
          <span>tool calls</span>
        </div>
        <div className="stat">
          <b>{p.tokens.toLocaleString()}</b>
          <span>tokens</span>
        </div>
        <div className="stat">
          <b>${p.costUsd.toFixed(4)}</b>
          <span>cost</span>
        </div>
        <div className="stat">
          <b>{p.testsPassed === null ? '—' : p.testsPassed ? '✓' : '✗'}</b>
          <span>tests</span>
        </div>
      </div>

      {pending.length > 0 && (
        <div className="panel">
          <h3>Approval inbox</h3>
          {pending.map((a) => (
            <div className="list-row" key={a.id}>
              <div>
                <div className="title">
                  <code>{a.tool}</code> <span className="muted">({a.side_effect})</span>
                </div>
                {a.arguments_preview && <div className="sub">{a.arguments_preview}</div>}
              </div>
              <div className="row">
                <button className="primary sm" onClick={() => resolve.mutate({ id: a.id, approved: true })}>
                  Approve
                </button>
                <button className="danger sm" onClick={() => resolve.mutate({ id: a.id, approved: false })}>
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="panel">
        <h3>Plan</h3>
        {plan.data && plan.data.steps.length > 0 ? (
          plan.data.steps.map((step) => (
            <div className="list-row" key={step.index}>
              <div>
                <div className="title">
                  <span className="muted">{step.index + 1}.</span> {step.title}
                </div>
                {step.detail && <div className="sub">{step.detail}</div>}
              </div>
              <span className={`badge ${step.status}`}>{step.status}</span>
            </div>
          ))
        ) : (
          <p className="muted">No plan yet.</p>
        )}
      </div>

      <div className="panel">
        <h3>Timeline (live)</h3>
        {p.timeline.length === 0 ? (
          <p className="muted">Waiting for events…</p>
        ) : (
          <Timeline entries={p.timeline} />
        )}
      </div>

      <div className="panel">
        <div className="section-head" style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Diff</h3>
          <button className="sm" onClick={() => void diff.refetch()}>
            {diff.isFetching ? 'Loading…' : 'Load diff'}
          </button>
        </div>
        {diff.data ? <DiffViewer diff={diff.data.diff} /> : <p className="muted">No diff loaded.</p>}
      </div>
    </div>
  );
}
