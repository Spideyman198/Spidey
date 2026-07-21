"""Reranker adapters (M13, FR-2.7) — satisfy codeintel's ``Reranker`` port.

Two implementations, both scoring ``(query, document)`` pairs and returning one
score per document (higher = more relevant), aligned by index:

* :class:`LexicalOverlapReranker` — pure, deterministic, model-free. Scores a
  document by the fraction of query terms it covers. It needs no model, so it is
  the safe default and the deterministic subject of the retrieval ablation and
  the unit suite.
* :class:`CrossEncoderReranker` — a fastembed ONNX cross-encoder. Loading the
  model is expensive and reads weights from disk, so it happens lazily and the
  model is reused for the process lifetime (mirrors the embedders). The model
  artifact is **hash-pinned**: when a SHA-256 is configured it is verified
  against the on-disk ``.onnx`` before first use, so a swapped/corrupted model
  fails closed (supply-chain integrity for the retrieval path).

Both live in ``llm`` (not ``codeintel``) so codeintel stays free of model loading
and direct file IO (SEC invariant); codeintel depends only on the port shape.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from fastembed.rerank.cross_encoder import TextCrossEncoder

from spidey.platform.errors import ValidationFailedError
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

_logger = get_logger("spidey.llm.reranker")

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_HASH_CHUNK = 1 << 20  # 1 MiB


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t.lower() for t in _TOKEN_RE.findall(text))


class LexicalOverlapReranker:
    """Model-free reranker: score = fraction of query terms present in the doc.

    Deterministic and dependency-free — a genuine (if simple) lexical relevance
    signal that gives a stable reordering without any model, so it is the default
    and the ablation's control-vs-treatment subject.
    """

    def score(self, *, query: str, documents: Sequence[str]) -> list[float]:
        query_terms = _tokens(query)
        if not query_terms:
            return [0.0] * len(documents)
        denom = len(query_terms)
        return [len(query_terms & _tokens(doc)) / denom for doc in documents]


def locate_model_onnx(cache_dir: Path, model_name: str) -> Path | None:
    """The largest ``.onnx`` under ``cache_dir`` belonging to ``model_name``.

    fastembed lays a model out under ``models--<org>--<name>/…/*.onnx``; matching
    on that path fragment scopes the hash to the intended model even when the
    cache holds several. The largest file is the weights (vs. any external-data
    shards), which is what we pin.
    """
    fragment = model_name.replace("/", "--").lower()
    candidates = [p for p in cache_dir.rglob("*.onnx") if fragment in str(p).lower()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model_integrity(
    *, cache_dir: str | None, model_name: str, expected_sha: str | None
) -> None:
    """Verify a pinned ONNX artifact, or fail closed. No pin → warn and allow.

    Raises :class:`ValidationFailedError` when a SHA-256 is required but cannot be
    verified (no cache path, artifact absent) or does not match — so a swapped or
    corrupted model never silently enters the retrieval path.
    """
    if expected_sha is None:
        _logger.warning(
            "reranker model is not hash-pinned; set rerank_model_sha256 to enforce integrity",
            model=model_name,
        )
        return
    if cache_dir is None:
        msg = "rerank_model_sha256 is set but no fastembed_cache_path is configured to verify it"
        raise ValidationFailedError(msg, model=model_name)
    onnx = locate_model_onnx(Path(cache_dir), model_name)
    if onnx is None:
        msg = "reranker model artifact not found under the cache path for hash verification"
        raise ValidationFailedError(msg, model=model_name, cache_dir=cache_dir)
    actual = sha256_file(onnx)
    if actual != expected_sha:
        msg = "reranker model hash mismatch — refusing to load an unpinned model artifact"
        raise ValidationFailedError(msg, model=model_name, expected=expected_sha, actual=actual)
    _logger.info("reranker model hash verified", model=model_name)


class CrossEncoderReranker:
    """fastembed ONNX cross-encoder reranker, hash-pinned and lazily loaded."""

    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: str | None,
        model_sha256: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._expected_sha = (model_sha256 or "").strip().lower() or None
        self._model: TextCrossEncoder | None = None

    def _get_model(self) -> TextCrossEncoder:
        if self._model is None:
            self._model = TextCrossEncoder(model_name=self._model_name, cache_dir=self._cache_dir)
            self._verify_integrity()
        return self._model

    def _verify_integrity(self) -> None:
        verify_model_integrity(
            cache_dir=self._cache_dir,
            model_name=self._model_name,
            expected_sha=self._expected_sha,
        )

    def score(self, *, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        model = self._get_model()
        return [float(s) for s in model.rerank(query, list(documents))]
