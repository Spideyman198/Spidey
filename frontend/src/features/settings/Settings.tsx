import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { ApiError, api } from '../../api/client';
import type { Role } from '../../api/types';
import { useTheme, type ThemePref } from '../theme/ThemeContext';

const THEME_OPTIONS: { value: ThemePref; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

export function Settings() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });

  return (
    <div>
      <h2>Settings</h2>
      <Appearance />
      <Account email={me.data?.email} role={me.data?.role} />
      {me.data?.role === 'admin' && <Users />}
    </div>
  );
}

function Appearance() {
  const { pref, setPref } = useTheme();
  return (
    <div className="panel">
      <h3>Appearance</h3>
      <div className="row between">
        <span className="muted">Theme</span>
        <div className="seg">
          {THEME_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              className={pref === opt.value ? 'on' : ''}
              onClick={() => setPref(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Account({ email, role }: { email: string | undefined; role: Role | undefined }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');

  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent('');
      setNext('');
      setConfirm('');
    },
  });

  const mismatch = next.length > 0 && next !== confirm;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (current && next && next === confirm) change.mutate();
  }

  return (
    <div className="panel">
      <h3>Account</h3>
      <div className="row between" style={{ marginBottom: 16 }}>
        <div>
          <div className="title">{email ?? '—'}</div>
          <div className="sub">Role: {role ?? '—'}</div>
        </div>
      </div>

      <form onSubmit={onSubmit}>
        <h3 style={{ fontSize: 13 }}>Change password</h3>
        {change.isSuccess && <div className="notice">Password changed. Other sessions were signed out.</div>}
        {change.isError && (
          <div className="banner">
            {change.error instanceof ApiError ? change.error.message : 'Could not change password'}
          </div>
        )}
        <div className="field">
          <label>Current password</label>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="field">
          <label>New password</label>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <div className="field">
          <label>Confirm new password</label>
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {mismatch && <div className="hint" style={{ color: 'var(--red)' }}>Passwords do not match.</div>}
        </div>
        <button
          className="primary"
          type="submit"
          disabled={change.isPending || !current || !next || mismatch}
        >
          {change.isPending ? 'Saving…' : 'Update password'}
        </button>
      </form>
    </div>
  );
}

function Users() {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ['users'], queryFn: api.listUsers });

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<Role>('developer');

  const create = useMutation({
    mutationFn: () => api.createUser(email.trim(), password, role),
    onSuccess: () => {
      setEmail('');
      setPassword('');
      void queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (email.trim() && password) create.mutate();
  }

  return (
    <div className="panel">
      <h3>Users</h3>
      {create.isError && (
        <div className="banner">
          {create.error instanceof ApiError ? create.error.message : 'Could not create user'}
        </div>
      )}
      <form className="row wrap" onSubmit={onSubmit} style={{ alignItems: 'flex-end', marginBottom: 16 }}>
        <div className="field grow" style={{ marginBottom: 0, minWidth: 180 }}>
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="dev@example.com" />
        </div>
        <div className="field" style={{ marginBottom: 0, minWidth: 140 }}>
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Role</label>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="viewer">viewer</option>
            <option value="developer">developer</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <button className="primary" type="submit" disabled={create.isPending || !email.trim() || !password}>
          Add user
        </button>
      </form>

      {users.isLoading && <p className="muted"><span className="spinner" /> Loading…</p>}
      {(users.data ?? []).map((u) => (
        <div className="list-row" key={u.id}>
          <div>
            <div className="title">{u.email}</div>
            <div className="sub">
              {u.role}
              {u.is_active ? '' : ' · inactive'}
            </div>
          </div>
          <button className="danger sm" onClick={() => remove.mutate(u.id)} disabled={remove.isPending}>
            Remove
          </button>
        </div>
      ))}
    </div>
  );
}
