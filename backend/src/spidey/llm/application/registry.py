"""Provider registry: resolves a role to its ordered chain of chat models.

Holds one factory per configured provider (a factory owns that provider's client
+ credentials + model catalog) and the routing table. ``chain(role)`` returns the
primary model followed by any configured fallbacks whose provider is actually
configured — the gateway walks that list on failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from spidey.platform.errors import SpideyError

if TYPE_CHECKING:
    from spidey.llm.domain.chat import Role
    from spidey.llm.domain.ports import ChatModel
    from spidey.llm.domain.routing import ProviderName, RouteConfig


class ChatModelFactory(Protocol):
    """Builds a :class:`ChatModel` bound to one model (manifest resolved by the
    provider's catalog)."""

    def build(self, model: str) -> ChatModel: ...


class RoutingError(SpideyError):
    """A role has no configured, usable route."""

    status = 500
    title = "LLM routing error"


class ProviderRegistry:
    def __init__(
        self,
        *,
        factories: dict[ProviderName, ChatModelFactory],
        routes: dict[Role, RouteConfig],
    ) -> None:
        self._factories = factories
        self._routes = routes

    def route(self, role: Role) -> RouteConfig:
        route = self._routes.get(role)
        if route is None:
            msg = f"no route configured for role {role.value!r}"
            raise RoutingError(msg, role=role.value)
        return route

    def chain(self, role: Role) -> list[ChatModel]:
        """Primary + fallbacks, skipping any provider that is not configured."""
        route = self.route(role)
        models = [
            self._factories[ref.provider].build(ref.model)
            for ref in route.chain
            if ref.provider in self._factories
        ]
        if not models:
            msg = f"no configured provider for role {role.value!r}"
            raise RoutingError(msg, role=role.value)
        return models
