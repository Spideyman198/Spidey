"""IndexService incremental logic: only changed files are re-parsed."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from spidey.codeintel.application import IndexService
from spidey.codeintel.domain.errors import ParseError
from spidey.codeintel.domain.models import (
    CodeChunk,
    IndexOutcome,
    IndexStatus,
    Language,
    ManifestEntry,
    ParsedUnit,
    Symbol,
    SymbolKind,
)

if TYPE_CHECKING:
    from spidey.codeintel.domain.models import IndexState as _IndexState

WS = uuid.uuid4()


class FakeReader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.reads: list[str] = []

    def read_bytes(self, path: str) -> bytes:
        self.reads.append(path)
        return self.files[path]


class FakeParser:
    """One symbol per file; raises ParseError for a source of b'BAD'."""

    def __init__(self) -> None:
        self.parsed: list[str] = []

    def parse(self, *, path: str, language: Language, source: bytes) -> ParsedUnit:
        self.parsed.append(path)
        if source == b"BAD":
            raise ParseError("bad", path=path)
        sym = Symbol(
            kind=SymbolKind.FUNCTION,
            name="f",
            qualified_name="f",
            parent=None,
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=len(source),
        )
        chunk = CodeChunk(
            header_path="f",
            kind=SymbolKind.FUNCTION,
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=len(source),
        )
        return ParsedUnit(path=path, language=language, symbols=[sym], chunks=[chunk])


class FakeStore:
    def __init__(self) -> None:
        self.hashes: dict[str, str] = {}
        self.symbols: dict[str, list[Symbol]] = {}
        self.chunks: dict[str, list[CodeChunk]] = {}
        self.status: IndexStatus = IndexStatus.PENDING

    async def indexed_hashes(self, workspace_id: uuid.UUID) -> dict[str, str]:
        return dict(self.hashes)

    async def replace_file(
        self,
        *,
        workspace_id: uuid.UUID,
        path: str,
        sha256: str,
        language: Language,
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> None:
        self.hashes[path] = sha256
        self.symbols[path] = symbols
        self.chunks[path] = chunks

    async def remove_files(self, *, workspace_id: uuid.UUID, paths: list[str]) -> None:
        for path in paths:
            self.hashes.pop(path, None)
            self.symbols.pop(path, None)
            self.chunks.pop(path, None)

    async def set_status(
        self,
        *,
        workspace_id: uuid.UUID,
        status: IndexStatus,
        symbol_count: int | None = None,
        chunk_count: int | None = None,
        file_count: int | None = None,
    ) -> None:
        self.status = status

    async def counts(self, workspace_id: uuid.UUID) -> tuple[int, int, int]:
        return (
            len(self.hashes),
            sum(len(v) for v in self.symbols.values()),
            sum(len(v) for v in self.chunks.values()),
        )

    async def get_state(self, workspace_id: uuid.UUID) -> _IndexState | None:
        return None

    async def list_symbols(
        self, *, workspace_id: uuid.UUID, path: str | None = None
    ) -> list[Symbol]:
        return []


async def _reindex(
    store: FakeStore, parser: FakeParser, reader: FakeReader, manifest: list[ManifestEntry]
) -> IndexOutcome:
    service = IndexService(store=store, parser=parser)
    return await service.reindex(workspace_id=WS, manifest=manifest, reader=reader)


class TestIncremental:
    async def test_first_pass_indexes_all_supported(self) -> None:
        store, parser = FakeStore(), FakeParser()
        reader = FakeReader({"a.py": b"aaa", "b.go": b"bbb", "readme.md": b"x"})
        manifest = [
            ManifestEntry(path="a.py", sha256="h1"),
            ManifestEntry(path="b.go", sha256="h2"),
            ManifestEntry(path="readme.md", sha256="h3"),  # unsupported → ignored
        ]
        outcome = await _reindex(store, parser, reader, manifest)
        assert outcome.status is IndexStatus.READY
        assert outcome.files_indexed == 2
        assert set(parser.parsed) == {"a.py", "b.go"}  # readme skipped

    async def test_unchanged_file_is_not_reparsed(self) -> None:
        store, parser = FakeStore(), FakeParser()
        reader = FakeReader({"a.py": b"aaa"})
        manifest = [ManifestEntry(path="a.py", sha256="h1")]
        await _reindex(store, parser, reader, manifest)
        parser.parsed.clear()
        reader.reads.clear()
        # Second pass with identical hash → nothing re-parsed.
        outcome = await _reindex(store, parser, reader, manifest)
        assert parser.parsed == []
        assert outcome.files_indexed == 0

    async def test_changed_file_only_is_reparsed(self) -> None:
        store, parser = FakeStore(), FakeParser()
        reader = FakeReader({"a.py": b"aaa", "b.py": b"bbb"})
        m1 = [ManifestEntry(path="a.py", sha256="h1"), ManifestEntry(path="b.py", sha256="h2")]
        await _reindex(store, parser, reader, m1)
        parser.parsed.clear()
        # a.py changes hash; b.py unchanged.
        m2 = [ManifestEntry(path="a.py", sha256="CHANGED"), ManifestEntry(path="b.py", sha256="h2")]
        outcome = await _reindex(store, parser, reader, m2)
        assert parser.parsed == ["a.py"]  # exactly one file re-indexed
        assert outcome.files_indexed == 1

    async def test_deleted_file_symbols_removed(self) -> None:
        store, parser = FakeStore(), FakeParser()
        reader = FakeReader({"a.py": b"aaa", "b.py": b"bbb"})
        m1 = [ManifestEntry(path="a.py", sha256="h1"), ManifestEntry(path="b.py", sha256="h2")]
        await _reindex(store, parser, reader, m1)
        # b.py gone from manifest.
        outcome = await _reindex(store, parser, reader, [ManifestEntry(path="a.py", sha256="h1")])
        assert "b.py" not in store.symbols
        assert outcome.files_removed == 1

    async def test_unparseable_file_recorded_empty_not_retried(self) -> None:
        store, parser = FakeStore(), FakeParser()
        reader = FakeReader({"bad.py": b"BAD"})
        manifest = [ManifestEntry(path="bad.py", sha256="h1")]
        outcome = await _reindex(store, parser, reader, manifest)
        assert outcome.files_skipped == 1
        assert store.symbols["bad.py"] == []  # indexed-but-empty
        assert store.hashes["bad.py"] == "h1"  # hash recorded → not retried
        parser.parsed.clear()
        await _reindex(store, parser, reader, manifest)
        assert parser.parsed == []  # same hash, not re-attempted
