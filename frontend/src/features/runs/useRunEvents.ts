import { useEffect, useState } from 'react';

import { streamRunEvents } from '../../api/client';
import { emptyProjection, reduceEvent, type RunProjection } from '../../api/events';

// Subscribe to a run's live SSE stream and fold each event through the shared
// reducer into a projection. The dashboard and single-run view both use this;
// the replay view folds persisted events through the same reducer instead.
export function useRunEvents(runId: string): RunProjection {
  const [projection, setProjection] = useState<RunProjection>(emptyProjection);

  useEffect(() => {
    const controller = new AbortController();
    setProjection(emptyProjection());
    streamRunEvents(
      runId,
      (event) => setProjection((prev) => reduceEvent(prev, event)),
      controller.signal,
    ).catch(() => {
      // Aborted on unmount or the stream ended — either is fine.
    });
    return () => controller.abort();
  }, [runId]);

  return projection;
}
