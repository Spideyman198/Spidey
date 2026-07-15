"""Local embedding adapters (fastembed / ONNX).

Chosen for the self-hosted posture (ADR-0009): no API key, no per-call cost,
deterministic, and — once models are baked into the image — no runtime download
and read-only-rootfs safe.

Model construction loads ONNX weights and is the expensive part, so it happens
lazily on first use and the model is reused for the process lifetime. That keeps
process startup — and any code path that builds a container without ever
embedding — free of the load cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastembed import SparseTextEmbedding, TextEmbedding

from spidey.llm.domain.models import SparseVector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.llm.domain.models import DenseVector


class FastembedDenseEmbedder:
    def __init__(self, *, model_name: str, dimension: int, cache_dir: str | None) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._cache_dir = cache_dir
        self._model: TextEmbedding | None = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(model_name=self._model_name, cache_dir=self._cache_dir)
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[DenseVector]:
        if not texts:
            return []
        return [vector.tolist() for vector in self._get_model().embed(list(texts))]

    def embed_query(self, text: str) -> DenseVector:
        return next(iter(self._get_model().query_embed(text))).tolist()


class FastembedSparseEmbedder:
    def __init__(self, *, model_name: str, cache_dir: str | None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: SparseTextEmbedding | None = None

    def _get_model(self) -> SparseTextEmbedding:
        if self._model is None:
            self._model = SparseTextEmbedding(
                model_name=self._model_name, cache_dir=self._cache_dir
            )
        return self._model

    @staticmethod
    def _to_sparse(embedding: object) -> SparseVector:
        # fastembed returns objects exposing .indices/.values as numpy arrays;
        # .tolist() erases to Any, so pin the element types explicitly.
        indices = cast("list[int]", embedding.indices.tolist())  # type: ignore[attr-defined]
        values = cast("list[float]", embedding.values.tolist())  # type: ignore[attr-defined]
        return SparseVector(indices=indices, values=values)

    def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        if not texts:
            return []
        return [self._to_sparse(e) for e in self._get_model().embed(list(texts))]

    def embed_query(self, text: str) -> SparseVector:
        return self._to_sparse(next(iter(self._get_model().query_embed(text))))
