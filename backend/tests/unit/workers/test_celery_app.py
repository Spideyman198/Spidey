"""Celery configuration contract: bounded tasks, JSON-only, heartbeat scheduled."""

from __future__ import annotations

from datetime import datetime

from spidey.workers.celery_app import HEARTBEAT_INTERVAL_SECONDS, create_celery_app
from spidey.workers.tasks.maintenance import heartbeat
from tests.conftest import make_settings


class TestCeleryConfiguration:
    def test_broker_and_backend_from_settings(self) -> None:
        settings = make_settings()
        app = create_celery_app(settings)
        assert app.conf.broker_url == settings.redis_dsn
        assert app.conf.result_backend == settings.redis_dsn

    def test_every_task_is_time_bounded(self) -> None:
        conf = create_celery_app(make_settings()).conf
        assert conf.task_soft_time_limit == 300
        assert conf.task_time_limit == 360
        assert conf.task_acks_late is True

    def test_json_only_serialization(self) -> None:
        conf = create_celery_app(make_settings()).conf
        assert conf.task_serializer == "json"
        assert conf.accept_content == ["json"]

    def test_heartbeat_registered_and_scheduled(self) -> None:
        app = create_celery_app(make_settings())
        app.loader.import_default_modules()
        app.finalize()
        assert "spidey.maintenance.heartbeat" in app.tasks
        entry = app.conf.beat_schedule["platform-heartbeat"]
        assert entry["task"] == "spidey.maintenance.heartbeat"
        assert entry["schedule"] == HEARTBEAT_INTERVAL_SECONDS


class TestHeartbeatTask:
    def test_returns_utc_iso_timestamp(self) -> None:
        stamp = heartbeat()
        parsed = datetime.fromisoformat(stamp)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0  # pyright: ignore[reportOptionalMemberAccess]
