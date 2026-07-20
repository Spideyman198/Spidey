import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, ApiError } from '../../api/client';

// User sovereignty over long-term memory (FR-5.3): inspect, teach, and delete.
export function MemoryManager() {
  const queryClient = useQueryClient();
  const memories = useQuery({ queryKey: ['memories'], queryFn: api.listMemories });
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['memories'] });
  const remember = useMutation({
    mutationFn: () => api.remember(content),
    onSuccess: () => {
      setContent('');
      setError(null);
      invalidate();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'rejected'),
  });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteMemory(id), onSuccess: invalidate });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (content.trim()) remember.mutate();
  }

  return (
    <div>
      <h2>Memory</h2>
      <form className="panel" onSubmit={onSubmit}>
        <div className="row">
          <input
            placeholder="Teach a fact (screened by the write gate)…"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <button className="primary" type="submit" disabled={remember.isPending}>
            Remember
          </button>
        </div>
        {error && (
          <p style={{ color: 'var(--red)' }} role="alert">
            {error}
          </p>
        )}
      </form>

      {memories.data?.length === 0 && <p className="muted">No memories yet.</p>}
      {memories.data?.map((memory) => (
        <div className="panel row" key={memory.id} style={{ justifyContent: 'space-between' }}>
          <span>
            <span className="badge">{memory.kind}</span> {memory.content}{' '}
            <span className="muted">· confidence {memory.confidence.toFixed(2)}</span>
          </span>
          <button onClick={() => remove.mutate(memory.id)}>Delete</button>
        </div>
      ))}
    </div>
  );
}
