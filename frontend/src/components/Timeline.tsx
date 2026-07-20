import type { TimelineEntry } from '../api/events';

// Renders the reduced event timeline. Agent-authored detail is rendered as plain
// text only (React escapes it) — never as HTML — so run output can't inject markup.
export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) return <p className="muted">No events yet.</p>;
  return (
    <div>
      {entries.map((entry) => (
        <div className="timeline-item" key={entry.id}>
          <span className="muted">{entry.label}</span>
          <span>{entry.detail}</span>
        </div>
      ))}
    </div>
  );
}
