"""User management use cases (admin) and first-run bootstrap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.identity.domain.models import Role, User, normalize_email, validate_new_password
from spidey.platform.audit import AuditAction
from spidey.platform.errors import ConflictError, ForbiddenError, NotFoundError

if TYPE_CHECKING:
    import uuid

    from spidey.identity.domain.ports import (
        PasswordHasher,
        RefreshTokenRepository,
        UserRepository,
    )
    from spidey.platform.audit import AuditSink


class UserService:
    def __init__(
        self,
        *,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        hasher: PasswordHasher,
        audit: AuditSink,
    ) -> None:
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._hasher = hasher
        self._audit = audit

    async def create_user(
        self,
        *,
        actor: User,
        email: str,
        password: str,
        role: Role,
        request_id: str | None,
    ) -> User:
        email = normalize_email(email)
        validate_new_password(password, email=email)
        created = await self._users.create(
            email=email, password_hash=self._hasher.hash(password), role=role
        )
        await self._audit.record(
            AuditAction.USER_CREATED,
            outcome="success",
            actor_user_id=actor.id,
            target=email,
            request_id=request_id,
            role=role.value,
        )
        return created

    async def list_users(self) -> list[User]:
        return await self._users.list_all()

    async def delete_user(self, *, actor: User, user_id: uuid.UUID, request_id: str | None) -> None:
        if user_id == actor.id:
            raise ForbiddenError("an administrator cannot delete their own account")
        await self._refresh_tokens.revoke_all_for_user(user_id)
        deleted = await self._users.delete(user_id)
        if not deleted:
            raise NotFoundError("user does not exist")
        await self._audit.record(
            AuditAction.USER_DELETED,
            outcome="success",
            actor_user_id=actor.id,
            target=str(user_id),
            request_id=request_id,
        )

    async def bootstrap_admin(self, *, email: str, password: str) -> User:
        """First-run only: creates the initial admin when no users exist.

        Refuses on a populated instance — there is deliberately no path to
        (re)create an admin through configuration once the system is live.
        """
        if await self._users.count() > 0:
            raise ConflictError("bootstrap refused: users already exist")
        email = normalize_email(email)
        validate_new_password(password, email=email)
        created = await self._users.create(
            email=email, password_hash=self._hasher.hash(password), role=Role.ADMIN
        )
        await self._audit.record(
            AuditAction.USER_CREATED,
            outcome="success",
            actor_user_id=created.id,
            target=email,
            role=Role.ADMIN.value,
            bootstrap=True,
        )
        return created
