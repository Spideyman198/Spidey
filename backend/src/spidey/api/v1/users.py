"""User administration routes (admin only) and self-inspection."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from spidey.api.deps import CurrentUser, RequireAdmin, UserServiceDep
from spidey.api.v1._request_meta import request_id
from spidey.api.v1.schemas import CreateUserRequest, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, summary="The authenticated user")
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("", response_model=list[UserResponse], summary="List users (admin)")
async def list_users(_admin: RequireAdmin, users: UserServiceDep) -> list[UserResponse]:
    return [UserResponse.model_validate(u) for u in await users.list_users()]


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (admin)",
)
async def create_user(
    request: Request,
    body: CreateUserRequest,
    admin: RequireAdmin,
    users: UserServiceDep,
) -> UserResponse:
    created = await users.create_user(
        actor=admin,
        email=body.email,
        password=body.password,
        role=body.role,
        request_id=request_id(request),
    )
    return UserResponse.model_validate(created)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user (admin)",
)
async def delete_user(
    request: Request,
    user_id: uuid.UUID,
    admin: RequireAdmin,
    users: UserServiceDep,
) -> None:
    await users.delete_user(actor=admin, user_id=user_id, request_id=request_id(request))
