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
  const projection = useRunEvents(runId);

  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.getRun(runId) });
  const plan = useQuery({ queryKey: ['plan', runId], queryFn: () => api.getPlan(runId), retry: false });
  const approvals = useQuery({
    queryKey: ['approvals', runId, projection.approvalsRequested],
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

  const status = projection.status !== 'unknown' ? projection.status : (run.data?.status ?? 'pending');

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>{run.data?.goal ?? 'Run'}</h2>
        <StatusBadge status={status} />
      </div>
      <div className="row" style={{ marginBottom: 16 }}>
        <button onClick={() => resume.mutate()}>Resume / approve plan</button>
        <button onClick={() => cancel.mutate()}>Cancel</button>
        <Link to={`/runs/${runId}/replay`}>Replay ↻</Link>
      </div>

      {approvals.data && approvals.data.length > 0 && (
        <div className="panel">
          <h3>Approval inbox</h3>
          {approvals.data.map((a) => (
            <div className="row" key={a.id} style={{ justifyContent: 'space-between' }}>
              <span>
                <code>{a.tool}</code> <span className="muted">({a.side_effect})</span>
              </span>
              <span className="row">
                <button className="primary" onClick={() => resolve.mutate({ id: a.id, approved: true })}>
                  Approve
                </button>
                <button onClick={() => resolve.mutate({ id: a.id, approved: false })}>Reject</button>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="panel">
        <h3>Plan</h3>
        {plan.data?.steps.map((step) => (
          <div className="timeline-item" key={step.index}>
            <span className="muted">step {step.index + 1}</span>
            <span>{step.title}</span>
          </div>
        )) ?? <p className="muted">No plan yet.</p>}
      </div>

      <div className="panel">
        <h3>Timeline (live)</h3>
        <Timeline entries={projection.timeline} />
      </div>

      <div className="panel">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>Diff</h3>
          <button onClick={() => void diff.refetch()}>Load diff</button>
        </div>
        {diff.data && <DiffViewer diff={diff.data.diff} />}
      </div>
    </div>
  );
}
