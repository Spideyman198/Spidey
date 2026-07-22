import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../../api/client';
import { StatusBadge } from '../../components/StatusBadge';

export function RunsList() {
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.listRuns });
  const workspaces = useQuery({ queryKey: ['workspaces'], queryFn: api.listWorkspaces });
  const [goal, setGoal] = useState('');
  const [workspaceId, setWorkspaceId] = useState('');

  const create = useMutation({
    mutationFn: () => api.createRun(goal, workspaceId || undefined),
    onSuccess: () => {
      setGoal('');
      void queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (goal.trim()) create.mutate();
  }

  const ready = (workspaces.data ?? []).filter((w) => w.status === 'ready');
  const items = runs.data ?? [];

  return (
    <div>
      <div className="section-head">
        <h2>Runs</h2>
      </div>

      <form className="panel stack" onSubmit={onSubmit}>
        <textarea
          rows={2}
          placeholder="Describe a goal for a new run…"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <div className="row between wrap">
          <select
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
            style={{ maxWidth: 280 }}
          >
            <option value="">No workspace (freeform)</option>
            {ready.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <button className="primary" type="submit" disabled={create.isPending || !goal.trim()}>
            {create.isPending ? 'Starting…' : 'Start run'}
          </button>
        </div>
        {ready.length === 0 && !workspaces.isLoading && (
          <div className="hint">
            No indexed workspaces yet — <Link to="/workspaces">connect a repository</Link> to run
            against real code.
          </div>
        )}
      </form>

      {runs.isLoading && (
        <p className="muted">
          <span className="spinner" /> Loading runs…
        </p>
      )}
      {!runs.isLoading && items.length === 0 && (
        <div className="panel empty">
          <span className="ico">▶</span>
          No runs yet. Describe a goal above to start one.
        </div>
      )}
      {items.length > 0 && (
        <div className="panel">
          {items.map((run) => (
            <div className="list-row" key={run.id}>
              <Link className="title" to={`/runs/${run.id}`}>
                {run.goal}
              </Link>
              <StatusBadge status={run.status} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
