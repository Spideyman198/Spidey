"""Per-model capability manifest (ADR-0012).

Each adapter declares, per model, what it can do and what it costs. The gateway
reads it to price usage and to fail fast on an unsupported feature (e.g. tools
against a model that lacks them) rather than silently degrading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from spidey.llm.domain.chat import Usage

_PER_MILLION = 1_000_000


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    max_context_tokens: int = 128_000
    # USD per million tokens, input and output.
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0

    def cost(self, usage: Usage) -> float:
        return (
            usage.prompt_tokens * self.input_price_per_mtok
            + usage.completion_tokens * self.output_price_per_mtok
        ) / _PER_MILLION
