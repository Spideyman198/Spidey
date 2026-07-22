import { useQuery } from '@tanstack/react-query';
import { Component, type ReactNode } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';

import { api } from '../api/client';
import { useAuth } from '../features/auth/AuthContext';
import { LoginPage } from '../features/auth/LoginPage';
import { Dashboard } from '../features/dashboard/Dashboard';
import { MemoryManager } from '../features/memory/MemoryManager';
import { Replay } from '../features/replay/Replay';
import { RunView } from '../features/runs/RunView';
import { RunsList } from '../features/runs/RunsList';
import { Settings } from '../features/settings/Settings';
import { useTheme } from '../features/theme/ThemeContext';
import { WorkspacesList } from '../features/workspaces/WorkspacesList';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="main">
          <div className="panel">
            <h2>Something went wrong</h2>
            <p className="muted">{this.state.error.message}</p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const NAV = [
  { to: '/runs', label: 'Runs', ico: '▶' },
  { to: '/workspaces', label: 'Workspaces', ico: '📁' },
  { to: '/dashboard', label: 'Dashboard', ico: '📊' },
  { to: '/memory', label: 'Memory', ico: '🧠' },
  { to: '/settings', label: 'Settings', ico: '⚙' },
];

function Shell({ children }: { children: ReactNode }) {
  const { logout } = useAuth();
  const { theme, toggle } = useTheme();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: 60_000 });

  return (
    <div className="layout">
      <nav className="nav">
        <div className="brand">🕷️ Spidey</div>
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to}>
            <span className="ico">{item.ico}</span>
            {item.label}
          </NavLink>
        ))}
        <div className="spacer" />
        <div className="footer">
          {me.data && <div className="who">{me.data.email}</div>}
          <div className="row between">
            <button
              className="ghost sm"
              onClick={toggle}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
            </button>
            <button className="ghost sm" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </nav>
      <main className="main">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  );
}

export function App() {
  const { authenticated } = useAuth();

  if (!authenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Shell>
      <Routes>
        <Route path="/runs" element={<RunsList />} />
        <Route path="/runs/:runId" element={<RunView />} />
        <Route path="/runs/:runId/replay" element={<Replay />} />
        <Route path="/workspaces" element={<WorkspacesList />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/memory" element={<MemoryManager />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/runs" replace />} />
      </Routes>
    </Shell>
  );
}
