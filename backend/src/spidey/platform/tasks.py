"""Task-dispatch seam.

Producers (the API) enqueue work by task *name* through this port, so they
never import the worker package — preserving the api/workers independence
contract. The Celery adapter holds only a broker connection for publishing;
task definitions live entirely in the worker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from celery import Celery

if TYPE_CHECKING:
    from spidey.platform.config import Settings


class TaskQueue(Protocol):
    def enqueue(self, task_name: str, *args: str, queue: str | None = None) -> None:
        """Publish a task by name. Arguments are JSON-serializable scalars."""
        ...


class CeleryTaskQueue:
    """Publish-only Celery client. Shares the broker with the worker but knows
    nothing of its task implementations."""

    def __init__(self, settings: Settings) -> None:
        self._app = Celery("spidey-producer", broker=settings.redis_dsn)
        self._app.conf.update(task_serializer="json", accept_content=["json"])

    def enqueue(self, task_name: str, *args: str, queue: str | None = None) -> None:
        self._app.send_task(task_name, args=list(args), queue=queue)
