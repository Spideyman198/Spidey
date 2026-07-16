"""Event contracts + consumer projection (pure, no I/O)."""

from __future__ import annotations

import uuid

import pytest
from prometheus_client import REGISTRY

from spidey.platform.events import (
    EventEnvelope,
    LlmCallCompleted,
    MetricsProjector,
    ToolInvocationCompleted,
    stream_key_for,
)


class TestEnvelope:
    def test_of_derives_type_and_version(self) -> None:
        env = EventEnvelope.of(
            LlmCallCompleted(
                provider="anthropic",
                model="claude-sonnet-5",
                role="planner",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=42,
                cost_usd=0.01,
            ),
            run_id=uuid.uuid4(),
            actor="user-1",
        )
        assert env.event_type == "llm.call_completed"
        assert env.schema_version == 1
        assert len(env.event_id) == 26  # ULID
        assert env.payload["model"] == "claude-sonnet-5"

    def test_validated_payload_roundtrips(self) -> None:
        env = EventEnvelope.of(
            ToolInvocationCompleted(
                tool="codeintel.search", side_effect="read", outcome="ok", latency_ms=12
            )
        )
        payload = env.validated_payload()
        assert isinstance(payload, ToolInvocationCompleted)
        assert payload.tool == "codeintel.search"

    def test_unknown_event_type_rejected(self) -> None:
        env = EventEnvelope(event_type="does.not_exist", schema_version=1, payload={})
        with pytest.raises(ValueError, match="unknown event_type"):
            env.validated_payload()

    def test_stream_key_is_per_run_or_firehose(self) -> None:
        rid = uuid.uuid4()
        assert stream_key_for(rid) == f"run:{rid}:events"
        assert stream_key_for(None) == "events:all"


class FakeBus:
    """Serves preset firehose messages once (satisfies the consumer's bus use)."""

    def __init__(self, messages: list[tuple[str, str]]) -> None:
        self._messages = messages
        self.acked: list[str] = []
        self.groups: list[str] = []

    async def ensure_group(self, stream_key: str, group: str) -> None:
        self.groups.append(group)

    async def read_group(
        self, stream_key: str, *, group: str, consumer: str, count: int, block_ms: int
    ) -> list[tuple[str, str]]:
        msgs, self._messages = self._messages, []
        return msgs

    async def ack(self, stream_key: str, *, group: str, message_id: str) -> None:
        self.acked.append(message_id)


class TestMetricsProjector:
    async def test_projects_llm_and_tool_events(self) -> None:
        env_llm = EventEnvelope.of(
            LlmCallCompleted(
                provider="prov-x",
                model="model-x",
                role="role-x",
                prompt_tokens=7,
                completion_tokens=3,
                latency_ms=5,
                cost_usd=0.25,
            )
        )
        env_tool = EventEnvelope.of(
            ToolInvocationCompleted(tool="tool-x", side_effect="read", outcome="ok", latency_ms=1)
        )
        bus = FakeBus([("1-0", env_llm.model_dump_json()), ("2-0", env_tool.model_dump_json())])
        projected = await MetricsProjector(bus).pump()  # type: ignore[arg-type]

        assert projected == 2
        assert bus.acked == ["1-0", "2-0"]
        assert (
            REGISTRY.get_sample_value(
                "spidey_llm_tokens_total",
                {"provider": "prov-x", "model": "model-x", "role": "role-x", "direction": "prompt"},
            )
            == 7
        )
        assert (
            REGISTRY.get_sample_value(
                "spidey_llm_cost_usd_total",
                {"provider": "prov-x", "model": "model-x", "role": "role-x"},
            )
            == 0.25
        )
        assert (
            REGISTRY.get_sample_value(
                "spidey_tool_invocations_total",
                {"tool": "tool-x", "side_effect": "read", "outcome": "ok"},
            )
            == 1
        )
