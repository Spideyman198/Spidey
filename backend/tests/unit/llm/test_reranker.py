"""Reranker adapters: deterministic lexical scoring + cross-encoder hash pin."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from spidey.llm.infrastructure.reranker import (
    CrossEncoderReranker,
    LexicalOverlapReranker,
    locate_model_onnx,
    sha256_file,
    verify_model_integrity,
)
from spidey.platform.errors import ValidationFailedError

if TYPE_CHECKING:
    from pathlib import Path


class TestLexicalOverlapReranker:
    def test_scores_by_query_term_coverage(self) -> None:
        reranker = LexicalOverlapReranker()
        scores = reranker.score(query="foo bar", documents=["foo baz", "bar foo", "nothing"])
        assert scores == [0.5, 1.0, 0.0]

    def test_empty_query_scores_zero(self) -> None:
        reranker = LexicalOverlapReranker()
        assert reranker.score(query="  ", documents=["anything", "here"]) == [0.0, 0.0]

    def test_is_deterministic(self) -> None:
        reranker = LexicalOverlapReranker()
        docs = ["config parser", "unrelated"]
        first = reranker.score(query="parse config loader", documents=docs)
        second = reranker.score(query="parse config loader", documents=docs)
        assert first == second


def _plant_model(cache_dir: Path, model_name: str, payload: bytes) -> Path:
    model_dir = cache_dir / f"models--{model_name.replace('/', '--')}"
    model_dir.mkdir(parents=True)
    onnx = model_dir / "model.onnx"
    onnx.write_bytes(payload)
    return onnx


class TestCrossEncoderHashPin:
    def test_locate_and_hash_roundtrip(self, tmp_path: Path) -> None:
        payload = b"onnx-weights"
        onnx = _plant_model(tmp_path, "Xenova/reranker", payload)
        located = locate_model_onnx(tmp_path, "Xenova/reranker")
        assert located == onnx
        assert sha256_file(onnx) == hashlib.sha256(payload).hexdigest()

    def test_matching_hash_verifies(self, tmp_path: Path) -> None:
        payload = b"trusted"
        _plant_model(tmp_path, "Xenova/reranker", payload)
        verify_model_integrity(
            cache_dir=str(tmp_path),
            model_name="Xenova/reranker",
            expected_sha=hashlib.sha256(payload).hexdigest(),
        )  # no raise

    def test_hash_mismatch_fails_closed(self, tmp_path: Path) -> None:
        _plant_model(tmp_path, "Xenova/reranker", b"swapped")
        with pytest.raises(ValidationFailedError):
            verify_model_integrity(
                cache_dir=str(tmp_path),
                model_name="Xenova/reranker",
                expected_sha="deadbeef" * 8,
            )

    def test_pin_without_cache_dir_fails_closed(self) -> None:
        with pytest.raises(ValidationFailedError):
            verify_model_integrity(
                cache_dir=None, model_name="Xenova/reranker", expected_sha="ab" * 32
            )

    def test_missing_artifact_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationFailedError):
            verify_model_integrity(
                cache_dir=str(tmp_path), model_name="Xenova/reranker", expected_sha="ab" * 32
            )

    def test_unpinned_is_allowed_with_warning(self, tmp_path: Path) -> None:
        # No pin → warn and allow (no raise).
        verify_model_integrity(
            cache_dir=str(tmp_path), model_name="Xenova/reranker", expected_sha=None
        )

    def test_empty_documents_short_circuit(self) -> None:
        reranker = CrossEncoderReranker(model_name="Xenova/reranker", cache_dir=None)
        # No documents → no model load, so this never touches disk or fastembed.
        assert reranker.score(query="q", documents=[]) == []
