import { Component, type ReactNode } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from '../features/auth/AuthContext';
import { LoginPage } from '../features/auth/LoginPage';
import { Dashboard } from '../features/dashboard/Dashboard';
import { MemoryManager } from '../features/memory/MemoryManager';
import { Replay } from '../features/replay/Replay';
import { RunView } from '../features/runs/RunView';
import { RunsList } from '../features/runs/RunsList';

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

function Shell({ children }: { children: ReactNode }) {
  const { logout } = useAuth();
  return (
    <div className="layout">
      <nav className="nav">
        <h1>🕷️ Spidey</h1>
        <NavLink to="/runs">Runs</NavLink>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <NavLink to="/memory">Memory</NavLink>
        <button onClick={logout} style={{ marginTop: 24, width: '100%' }}>
          Sign out
        </button>
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
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/memory" element={<MemoryManager />} />
        <Route path="*" element={<Navigate to="/runs" replace />} />
      </Routes>
    </Shell>
  );
}
