"""Request-scoped dependency wiring and auth/authz guards.

The unit of work: one DB session per request, committed on success and rolled
back on any exception, so an action and its audit record land atomically or
not at all. Use cases are assembled here from the container's singletons and
that per-request session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from spidey.agents.application import RunService
from spidey.agents.infrastructure.run_store import PostgresRunStore
from spidey.codeintel.application import GraphExpander, SearchService
from spidey.codeintel.infrastructure import PostgresGraphStore, PostgresSymbolStore
from spidey.identity.application import AuthService, UserService
from spidey.identity.domain.models import Role, User
from spidey.identity.infrastructure import (
    PostgresRefreshTokenRepository,
    PostgresUserRepository,
)
from spidey.identity.infrastructure.security_sink import IndependentSecurityEventSink
from spidey.memory.application import ConversationService
from spidey.memory.infrastructure import PostgresConversationStore
from spidey.platform.audit import AuditAction, AuditLogger, IndependentAuditLogger
from spidey.platform.errors import ForbiddenError, UnauthorizedError
from spidey.platform.events import OutboxWriter
from spidey.workspaces.application import WorkspaceService
from spidey.workspaces.infrastructure import PostgresWorkspaceStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from spidey.composition import Container

_bearer = HTTPBearer(auto_error=False)


def _container(request: Request) -> Container:
    return request.app.state.container


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One transactional unit of work per request."""
    container = _container(request)
    async with container.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


ContainerDep = Annotated["Container", Depends(_container)]
SessionDep = Annotated["AsyncSession", Depends(get_session)]


def get_auth_service(container: ContainerDep, session: SessionDep) -> AuthService:
    return AuthService(
        users=PostgresUserRepository(session),
        refresh_tokens=PostgresRefreshTokenRepository(session),
        hasher=container.hasher,
        issuer=container.token_issuer,
        rate_limiter=container.rate_limiter,
        lockouts=container.lockouts,
        audit=AuditLogger(session),
        security=IndependentSecurityEventSink(container.session_factory),
        refresh_ttl_days=container.settings.refresh_token_ttl_days,
    )


def get_user_service(container: ContainerDep, session: SessionDep) -> UserService:
    return UserService(
        users=PostgresUserRepository(session),
        refresh_tokens=PostgresRefreshTokenRepository(session),
        hasher=container.hasher,
        audit=AuditLogger(session),
    )


def get_conversation_service(session: SessionDep) -> ConversationService:
    return ConversationService(
        store=PostgresConversationStore(session),
        audit=AuditLogger(session),
    )


def get_workspace_service(container: ContainerDep, session: SessionDep) -> WorkspaceService:
    return WorkspaceService(
        store=PostgresWorkspaceStore(session),
        storage=container.workspace_storage,
        cipher=container.cipher,
        audit=AuditLogger(session),
    )


def get_symbol_store(session: SessionDep) -> PostgresSymbolStore:
    return PostgresSymbolStore(session)


def get_graph_store(session: SessionDep) -> PostgresGraphStore:
    return PostgresGraphStore(session)


def get_search_service(container: ContainerDep, session: SessionDep) -> SearchService:
    settings = container.settings
    expander: GraphExpander | None = None
    if settings.graph_expansion_enabled:
        expander = GraphExpander(
            graph=PostgresGraphStore(session),
            hops=settings.graph_expansion_hops,
            seeds=settings.graph_expansion_seeds,
            max_facts=settings.graph_expansion_max_facts,
        )
    return SearchService(
        store=PostgresSymbolStore(session),
        dense_embedder=container.dense_embedder,
        sparse_embedder=container.sparse_embedder,
        vector_index=container.vector_index,
        graph_expander=expander,
    )


def get_run_service(container: ContainerDep, session: SessionDep) -> RunService:
    return RunService(
        store=PostgresRunStore(session),
        events=OutboxWriter(session),
        task_queue=container.task_queue,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
SymbolStoreDep = Annotated[PostgresSymbolStore, Depends(get_symbol_store)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
GraphStoreDep = Annotated[PostgresGraphStore, Depends(get_graph_store)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


async def get_current_user(
    container: ContainerDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve and validate the bearer token into an active user.

    The token is cryptographically sufficient, but we re-load the user so that
    a deactivated or deleted account cannot keep acting until its short-lived
    access token expires.
    """
    if credentials is None:
        raise UnauthorizedError("authentication required")
    claims = container.token_issuer.decode(credentials.credentials)
    stored = await PostgresUserRepository(session).get_by_id(claims.user_id)
    if stored is None or not stored.user.is_active:
        raise UnauthorizedError("account is no longer active")
    return stored.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: Role) -> object:
    """Dependency factory enforcing a minimum RBAC role, with an audit trail
    on denial (docs/11 layer 2)."""

    async def _guard(request: Request, user: CurrentUser, container: ContainerDep) -> User:
        if not user.role.satisfies(minimum):
            # Independent commit: the denial rolls the request back, but the
            # evidence must remain (docs/11 layer 2).
            await IndependentAuditLogger(container.session_factory).record(
                AuditAction.AUTHZ_DENIED,
                outcome="denied",
                actor_user_id=user.id,
                target=f"{request.method} {request.url.path}",
                request_id=request.headers.get("x-request-id"),
                required_role=minimum.value,
                actual_role=user.role.value,
            )
            raise ForbiddenError("insufficient role for this operation")
        return user

    return Depends(_guard)


RequireAdmin = Annotated[User, require_role(Role.ADMIN)]
RequireDeveloper = Annotated[User, require_role(Role.DEVELOPER)]
