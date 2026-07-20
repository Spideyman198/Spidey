import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { ApiError } from '../../api/client';
import { useAuth } from './AuthContext';

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate('/runs');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'login failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="main" style={{ maxWidth: 360, margin: '80px auto' }}>
      <h1>🕷️ Spidey</h1>
      <form className="panel" onSubmit={onSubmit}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label style={{ display: 'block', marginTop: 12 }}>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="muted" style={{ color: 'var(--red)' }} role="alert">
            {error}
          </p>
        )}
        <button className="primary" type="submit" disabled={busy} style={{ marginTop: 16 }}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
