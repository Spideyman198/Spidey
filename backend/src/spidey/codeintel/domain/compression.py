"""Context compression (M13, FR-2.7) — pure, deterministic, lossy-by-budget.

Retrieved chunks are the biggest, most variable consumer of the prompt token
budget. Compression trims each hit to the window most relevant to the query and
stops including hits once a character budget is spent, so a large result set
cannot blow the context window. It is deliberately *extractive* — it only
selects and slices existing lines, never rewrites them — so no model is involved
and provenance stays exact: a compressed hit's ``start_line``/``end_line`` are
recomputed to the lines actually kept, and the (still-attributed) content is
what the data frame renders (SEC-PI).

Compression is lossy, so it is applied only under budget pressure and its recall
cost is measured by the retrieval ablation (docs/perf/m13-retrieval-v2-eval).
The top hit is always kept in full-window form even if it alone exceeds the
budget — dropping the single best result would defeat retrieval entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.codeintel.domain.models import SearchHit

# Identifier-like query terms worth matching against source lines (mirrors the
# search-side term regex: skip 1-2 char noise words).
_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


@dataclass(frozen=True, slots=True)
class CompressionPolicy:
    """Budget for :func:`compress_hits`.

    ``char_budget`` caps the total kept content across all hits; ``per_hit_max_chars``
    caps any single hit; ``context_lines`` is how many lines of surrounding
    context to keep on each side of the most query-relevant line.
    """

    char_budget: int = 6000
    per_hit_max_chars: int = 1200
    context_lines: int = 8


@dataclass(frozen=True, slots=True)
class _Window:
    text: str
    line_offset: int


def _terms(query: str) -> frozenset[str]:
    return frozenset(t.lower() for t in _TERM_RE.findall(query))


def _best_window(content: str, terms: frozenset[str], context_lines: int) -> _Window:
    """The line window richest in query terms, plus context on each side.

    Falls back to the head of the content when no line matches any term, so a
    purely-semantic hit still contributes its opening (usually the signature).
    """
    lines = content.split("\n")
    span = 2 * context_lines + 1
    if not terms or len(lines) <= span:
        best_center = 0 if not terms else _densest_line(lines, terms)
    else:
        best_center = _densest_line(lines, terms)

    start = max(0, best_center - context_lines)
    end = min(len(lines), start + span)
    # Re-anchor the start if the window ran past the end, so we keep ``span`` lines.
    start = max(0, end - span)
    return _Window(text="\n".join(lines[start:end]), line_offset=start)


def _densest_line(lines: Sequence[str], terms: frozenset[str]) -> int:
    """Index of the first line matching the most query terms (0 if none match)."""
    best_index = 0
    best_hits = -1
    for index, line in enumerate(lines):
        tokens = {t.lower() for t in _TERM_RE.findall(line)}
        hits = len(tokens & terms)
        if hits > best_hits:
            best_hits = hits
            best_index = index
    return best_index


def compress_hits(
    hits: Sequence[SearchHit],
    *,
    policy: CompressionPolicy,
    query: str,
) -> list[SearchHit]:
    """Trim hits to their query-relevant windows within ``policy``'s budget.

    Returns copies with sliced ``content`` and provenance (``start_line``/
    ``end_line``) recomputed to the kept window. Order is preserved. Hits are
    included until the cumulative character budget is exhausted; the first hit is
    always included so the result is never empty when the input is not.
    """
    if not hits:
        return []

    terms = _terms(query)
    out: list[SearchHit] = []
    used = 0
    for hit in hits:
        window = _best_window(hit.content, terms, policy.context_lines)
        text = window.text[: policy.per_hit_max_chars]
        cost = len(text)
        if out and used + cost > policy.char_budget:
            break
        used += cost
        new_start = hit.start_line + window.line_offset
        new_end = new_start + text.count("\n")
        out.append(
            hit.model_copy(update={"content": text, "start_line": new_start, "end_line": new_end})
        )
    return out
