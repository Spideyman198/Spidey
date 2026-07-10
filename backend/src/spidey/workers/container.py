"""Per-worker-process composition.

The worker builds one container per process (lazily, on first task) and reuses
it for the process lifetime — engines and clients are expensive and safe to
share across tasks within a process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.composition import build_container
from spidey.platform.config import get_settings

if TYPE_CHECKING:
    from spidey.composition import Container

_container: Container | None = None


def get_worker_container() -> Container:
    global _container  # noqa: PLW0603 — process-lifetime singleton by design
    if _container is None:
        _container = build_container(get_settings())
    return _container
