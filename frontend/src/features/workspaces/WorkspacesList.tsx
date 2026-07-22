import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { ApiError, api } from '../../api/client';
import type { RepositorySource } from '../../api/types';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

export function WorkspacesList() {
  const queryClient = useQueryClient();
  const workspaces = useQuery({
    queryKey: ['workspaces'],
    queryFn: api.listWorkspaces,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((w) => w.status === 'ingesting' || w.status === 'pending')
        ? 3000
        : false,
  });

  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [source, setSource] = useState<RepositorySource>('github');
  const [location, setLocation] = useState('');
  const [branch, setBranch] = useState('');
  const [token, setToken] = useState('');

  const create = useMutation({
    mutationFn: () =>
      api.createWorkspace({
        name: name.trim(),
        source,
        location: location.trim(),
        branch: branch.trim() || null,
        token: token.trim() || null,
      }),
    onSuccess: () => {
      setName('');
      setLocation('');
      setBranch('');
      setToken('');
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });

  const reingest = useMutation({
    mutationFn: (id: string) => api.reingestWorkspace(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && location.trim()) create.mutate();
  }

  const items = workspaces.data ?? [];

  return (
    <div>
      <div className="section-head">
        <h2>Workspaces</h2>
        <button className="primary" onClick={() => setOpen((v) => !v)}>
          {open ? 'Cancel' : '+ Connect a repository'}
        </button>
      </div>

      {open && (
        <form className="panel" onSubmit={onSubmit}>
          {create.isError && (
            <div className="banner">
              {create.error instanceof ApiError ? create.error.message : 'Could not create workspace'}
            </div>
          )}
          <div className="field">
            <label>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-project" />
          </div>
          <div className="field">
            <label>Source</label>
            <select value={source} onChange={(e) => setSource(e.target.value as RepositorySource)}>
              <option value="github">GitHub repository</option>
              <option value="local">Local path (on the server)</option>
            </select>
          </div>
          <div className="field">
            <label>{source === 'github' ? 'Clone URL' : 'Absolute path'}</label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder={source === 'github' ? 'https://github.com/owner/repo.git' : '/srv/repos/app'}
            />
          </div>
          {source === 'github' && (
            <>
              <div className="field">
                <label>Branch (optional)</label>
                <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
              </div>
              <div className="field">
                <label>Access token (optional — for private repos)</label>
                <input
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="ghp_…"
                />
                <div className="hint">Encrypted at rest; never shown again.</div>
              </div>
            </>
          )}
          <button
            className="primary"
            type="submit"
            disabled={create.isPending || !name.trim() || !location.trim()}
          >
            {create.isPending ? 'Connecting…' : 'Connect & ingest'}
          </button>
        </form>
      )}

      {workspaces.isLoading && (
        <p className="muted">
          <span className="spinner" /> Loading workspaces…
        </p>
      )}
      {workspaces.isError && <div className="banner">Could not load workspaces.</div>}

      {!workspaces.isLoading && items.length === 0 && (
        <div className="panel empty">
          <span className="ico">📁</span>
          No workspaces yet. Connect a repository to index it and run agents against it.
        </div>
      )}

      {items.length > 0 && (
        <div className="panel">
          {items.map((w) => (
            <div className="list-row" key={w.id}>
              <div>
                <div className="title">{w.name}</div>
                <div className="sub">
                  {w.source === 'github' ? 'GitHub' : 'Local'} · {w.location}
                  {w.branch ? ` · ${w.branch}` : ''}
                  {w.status === 'ready' && ` · ${w.file_count} files · ${formatBytes(w.size_bytes)}`}
                  {w.status === 'failed' && w.error ? ` · ${w.error}` : ''}
                </div>
              </div>
              <div className="row">
                <span className={`badge ${w.status}`}>{w.status}</span>
                <button
                  className="sm"
                  onClick={() => reingest.mutate(w.id)}
                  disabled={reingest.isPending || w.status === 'ingesting'}
                >
                  Re-ingest
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
