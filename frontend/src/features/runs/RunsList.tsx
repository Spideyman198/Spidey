import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../../api/client';
import { StatusBadge } from '../../components/StatusBadge';

export function RunsList() {
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.listRuns });
  const [goal, setGoal] = useState('');

  const create = useMutation({
    mutationFn: () => api.createRun(goal),
    onSuccess: () => {
      setGoal('');
      void queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (goal.trim()) create.mutate();
  }

  return (
    <div>
      <h2>Runs</h2>
      <form className="panel" onSubmit={onSubmit}>
        <div className="row">
          <input
            placeholder="Describe a goal for a new run…"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <button className="primary" type="submit" disabled={create.isPending || !goal.trim()}>
            Start run
          </button>
        </div>
      </form>

      {runs.isLoading && <p className="muted">Loading…</p>}
      {runs.data?.length === 0 && <p className="muted">No runs yet.</p>}
      {runs.data?.map((run) => (
        <div className="panel row" key={run.id} style={{ justifyContent: 'space-between' }}>
          <Link to={`/runs/${run.id}`}>{run.goal}</Link>
          <StatusBadge status={run.status} />
        </div>
      ))}
    </div>
  );
}
