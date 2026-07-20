import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';

import { api } from '../../api/client';
import { reduceEvents } from '../../api/events';
import { StatusBadge } from '../../components/StatusBadge';
import { Timeline } from '../../components/Timeline';

// Replay folds the *persisted* event timeline through the same reducer the live
// dashboard uses — so a completed run reconstructs identically to how it ran.
export function Replay() {
  const { runId = '' } = useParams();
  const events = useQuery({ queryKey: ['timeline', runId], queryFn: () => api.getTimeline(runId) });
  const report = useQuery({ queryKey: ['report', runId], queryFn: () => api.getReport(runId) });

  if (events.isLoading) return <p className="muted">Loading timeline…</p>;
  const projection = reduceEvents(events.data ?? []);

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>Replay</h2>
        <StatusBadge status={projection.status !== 'unknown' ? projection.status : 'pending'} />
      </div>

      {report.data && (
        <div className="panel">
          <p>
            <strong>Goal:</strong> {report.data.goal}
          </p>
          <p className="muted">
            outcome: {report.data.outcome} · {report.data.commits.length} commits · tests:{' '}
            {report.data.tests_passed === null ? 'n/a' : report.data.tests_passed ? 'passed' : 'failed'}
            {report.data.pull_request_url && (
              <>
                {' · '}
                <a href={report.data.pull_request_url} target="_blank" rel="noreferrer noopener">
                  pull request
                </a>
              </>
            )}
          </p>
        </div>
      )}

      <div className="panel">
        <h3>Reconstructed timeline</h3>
        <Timeline entries={projection.timeline} />
      </div>
    </div>
  );
}
