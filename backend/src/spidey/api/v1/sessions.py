"""Session and message routes. Every operation is scoped to the caller."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from spidey.api.deps import ConversationServiceDep, CurrentUser
from spidey.api.v1._request_meta import request_id
from spidey.api.v1.schemas import (
    CreateMessageRequest,
    CreateSessionRequest,
    MessageResponse,
    RenameSessionRequest,
    SessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a session",
)
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    user: CurrentUser,
    conversations: ConversationServiceDep,
) -> SessionResponse:
    session = await conversations.create_session(
        owner_id=user.id, title=body.title, request_id=request_id(request)
    )
    return SessionResponse.model_validate(session)


@router.get("", response_model=list[SessionResponse], summary="List your sessions")
async def list_sessions(
    user: CurrentUser, conversations: ConversationServiceDep
) -> list[SessionResponse]:
    sessions = await conversations.list_sessions(owner_id=user.id)
    return [SessionResponse.model_validate(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse, summary="Get a session")
async def get_session(
    session_id: uuid.UUID, user: CurrentUser, conversations: ConversationServiceDep
) -> SessionResponse:
    session = await conversations.get_session(owner_id=user.id, session_id=session_id)
    return SessionResponse.model_validate(session)


@router.patch("/{session_id}", response_model=SessionResponse, summary="Rename a session")
async def rename_session(
    session_id: uuid.UUID,
    body: RenameSessionRequest,
    user: CurrentUser,
    conversations: ConversationServiceDep,
) -> SessionResponse:
    session = await conversations.rename_session(
        owner_id=user.id, session_id=session_id, title=body.title
    )
    return SessionResponse.model_validate(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a session")
async def delete_session(
    request: Request,
    session_id: uuid.UUID,
    user: CurrentUser,
    conversations: ConversationServiceDep,
) -> None:
    await conversations.delete_session(
        owner_id=user.id, session_id=session_id, request_id=request_id(request)
    )


@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append a user message",
)
async def add_message(
    session_id: uuid.UUID,
    body: CreateMessageRequest,
    user: CurrentUser,
    conversations: ConversationServiceDep,
) -> MessageResponse:
    message = await conversations.add_user_message(
        owner_id=user.id, session_id=session_id, content=body.content
    )
    return MessageResponse.model_validate(message)


@router.get(
    "/{session_id}/messages",
    response_model=list[MessageResponse],
    summary="List messages in a session",
)
async def list_messages(
    session_id: uuid.UUID,
    user: CurrentUser,
    conversations: ConversationServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: uuid.UUID | None = None,
) -> list[MessageResponse]:
    messages = await conversations.list_messages(
        owner_id=user.id, session_id=session_id, limit=limit, before=before
    )
    return [MessageResponse.model_validate(m) for m in messages]
