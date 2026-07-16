"""Config-only model routing (ADR-0012).

A role maps to a primary (provider, model) plus an ordered fallback chain the
gateway walks on outage/429. "Switching providers requires configuration only"
is expressed here and proven by the conformance suite — not asserted in prose.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProviderName(StrEnum):
    ANTHROPIC = "anthropic"
    # One adapter, many targets: OpenAI, Ollama, vLLM, Azure OpenAI (ADR-0012).
    OPENAI_COMPATIBLE = "openai_compatible"
    GEMINI = "gemini"


class ModelRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str


class RouteConfig(BaseModel):
    """Where one role's calls go, and where they fall back to."""

    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str
    max_tokens: int = 1024
    temperature: float = 0.0
    fallbacks: list[ModelRef] = Field(default_factory=list[ModelRef])

    @property
    def primary(self) -> ModelRef:
        return ModelRef(provider=self.provider, model=self.model)

    @property
    def chain(self) -> list[ModelRef]:
        return [self.primary, *self.fallbacks]
