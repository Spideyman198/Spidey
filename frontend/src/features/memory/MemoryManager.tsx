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

  const items = memories.data ?? [];

  return (
    <div>
      <div className="section-head">
        <h2>Memory</h2>
      </div>
      <form className="panel stack" onSubmit={onSubmit}>
        {error && (
          <div className="banner" role="alert">
            {error}
          </div>
        )}
        <div className="row">
          <input
            placeholder="Teach a fact (screened by the write gate)…"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <button className="primary" type="submit" disabled={remember.isPending || !content.trim()}>
            Remember
          </button>
        </div>
      </form>

      {memories.isLoading && (
        <p className="muted">
          <span className="spinner" /> Loading…
        </p>
      )}
      {!memories.isLoading && items.length === 0 && (
        <div className="panel empty">
          <span className="ico">🧠</span>
          No memories yet. Teach a durable fact, or let runs distill their own.
        </div>
      )}
      {items.length > 0 && (
        <div className="panel">
          {items.map((memory) => (
            <div className="list-row" key={memory.id}>
              <div>
                <div className="title">{memory.content}</div>
                <div className="sub">
                  <span className="badge">{memory.kind}</span> confidence{' '}
                  {memory.confidence.toFixed(2)} · used {memory.use_count}×
                </div>
              </div>
              <button className="danger sm" onClick={() => remove.mutate(memory.id)}>
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
