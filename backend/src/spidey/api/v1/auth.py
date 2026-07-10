"""Authentication routes: login, refresh, logout, change password."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Request, status

from spidey.api.deps import AuthServiceDep, CurrentUser
from spidey.api.v1._request_meta import client_ip, request_id
from spidey.api.v1.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for tokens")
async def login(request: Request, body: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    pair = await auth.login(
        body.email,
        body.password,
        source_ip=client_ip(request),
        request_id=request_id(request),
    )
    return TokenResponse(**pair.model_dump())


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the refresh token")
async def refresh(request: Request, body: RefreshRequest, auth: AuthServiceDep) -> TokenResponse:
    pair = await auth.refresh(
        body.refresh_token,
        source_ip=client_ip(request),
        request_id=request_id(request),
    )
    return TokenResponse(**pair.model_dump())


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a token family")
async def logout(
    request: Request,
    body: RefreshRequest,
    auth: AuthServiceDep,
    user: CurrentUser,
) -> None:
    await auth.logout(
        body.refresh_token,
        actor=user,
        source_ip=client_ip(request),
        request_id=request_id(request),
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password and revoke all sessions",
)
async def change_password(
    request: Request,
    body: Annotated[ChangePasswordRequest, Body()],
    auth: AuthServiceDep,
    user: CurrentUser,
) -> None:
    await auth.change_password(
        actor=user,
        current_password=body.current_password,
        new_password=body.new_password,
        source_ip=client_ip(request),
        request_id=request_id(request),
    )
