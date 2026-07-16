"""Redacted interaction capture (InteractionCapture adapter).

Writes the request/response to ``llm_interactions`` for replay, scrubbing secrets
from every message body at capture time (docs/08 §5): a leaked key in a prompt or
completion never reaches disk.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from spidey.llm.infrastructure.orm import LlmInteractionRecord
from spidey.platform.security import scrub_text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from spidey.llm.domain.chat import ChatMessage, ChatRequest, ChatResponse


class PostgresInteractionCapture:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        provider: str,
        model: str,
        role: str,
        request: ChatRequest,
        response: ChatResponse,
        run_id: uuid.UUID | None,
    ) -> uuid.UUID:
        interaction_id = uuid.uuid4()
        self._session.add(
            LlmInteractionRecord(
                id=interaction_id,
                run_id=run_id,
                provider=provider,
                model=model,
                role=role,
                request={
                    "messages": [_redact_message(m) for m in request.messages],
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "tools": [t.name for t in request.tools],
                },
                response={
                    "content": scrub_text(response.message.content),
                    "tool_calls": [tc.name for tc in response.message.tool_calls],
                    "finish_reason": response.finish_reason.value,
                },
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        )
        await self._session.flush()
        return interaction_id


def _redact_message(message: ChatMessage) -> dict[str, Any]:
    return {
        "role": message.role.value,
        "content": scrub_text(message.content),
        "tool_calls": [tc.name for tc in message.tool_calls],
    }
