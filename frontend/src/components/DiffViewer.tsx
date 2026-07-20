// Lightweight unified-diff renderer (added/removed lines colored). Content is
// rendered as text only — never HTML — so a hostile diff cannot inject markup.
export function DiffViewer({ diff }: { diff: string }) {
  if (!diff.trim()) return <p className="muted">No changes.</p>;
  const lines = diff.split('\n');
  return (
    <pre className="diff">
      {lines.map((line, i) => {
        const cls =
          line.startsWith('+') && !line.startsWith('+++')
            ? 'add'
            : line.startsWith('-') && !line.startsWith('---')
              ? 'del'
              : undefined;
        return (
          <div className={cls} key={i}>
            {line || ' '}
          </div>
        );
      })}
    </pre>
  );
}
