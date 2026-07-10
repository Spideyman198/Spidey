"""Workspace routes: create-and-ingest, list, get, manifest, re-ingest, delete.

Ingestion is asynchronous. Create/ingest endpoints commit the workspace row and
then enqueue the ingestion task, so the worker always sees a committed row. A
transactional outbox (M6) will later make the enqueue atomic with the commit;
until then the ordering is explicit here and a lost enqueue is recoverable via
the re-ingest endpoint.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from spidey.api.deps import CurrentUser, RequireDeveloper, SessionDep, WorkspaceServiceDep
from spidey.api.v1._request_meta import request_id
from spidey.api.v1.schemas import (
    CreateWorkspaceRequest,
    FileManifestEntryResponse,
    WorkspaceResponse,
)
from spidey.workspaces.domain.models import IngestionRequest, WorkspaceStatus

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_INGEST_TASK = "spidey.workspaces.ingest"


def _enqueue_ingest(request: Request, workspace_id: uuid.UUID) -> None:
    request.app.state.container.task_queue.enqueue(
        _INGEST_TASK, str(workspace_id), queue="ingestion"
    )


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a workspace and start ingestion",
)
async def create_workspace(
    request: Request,
    body: CreateWorkspaceRequest,
    developer: RequireDeveloper,
    workspaces: WorkspaceServiceDep,
    session: SessionDep,
) -> WorkspaceResponse:
    workspace = await workspaces.create(
        owner_id=developer.id,
        request=IngestionRequest(
            name=body.name,
            source=body.source,
            location=body.location,
            branch=body.branch,
            token=body.token,
        ),
        request_id=request_id(request),
    )
    # Commit before enqueue so the ingestion worker can see the row.
    await session.commit()
    _enqueue_ingest(request, workspace.id)
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=list[WorkspaceResponse], summary="List your workspaces")
async def list_workspaces(
    user: CurrentUser, workspaces: WorkspaceServiceDep
) -> list[WorkspaceResponse]:
    items = await workspaces.list(owner_id=user.id)
    return [WorkspaceResponse.model_validate(w) for w in items]


@router.get("/{workspace_id}", response_model=WorkspaceResponse, summary="Get a workspace")
async def get_workspace(
    workspace_id: uuid.UUID, user: CurrentUser, workspaces: WorkspaceServiceDep
) -> WorkspaceResponse:
    workspace = await workspaces.get(owner_id=user.id, workspace_id=workspace_id)
    return WorkspaceResponse.model_validate(workspace)


@router.get(
    "/{workspace_id}/files",
    response_model=list[FileManifestEntryResponse],
    summary="List the ingested file manifest",
)
async def list_workspace_files(
    workspace_id: uuid.UUID, user: CurrentUser, workspaces: WorkspaceServiceDep
) -> list[FileManifestEntryResponse]:
    entries = await workspaces.manifest(owner_id=user.id, workspace_id=workspace_id)
    return [FileManifestEntryResponse.model_validate(e) for e in entries]


@router.post(
    "/{workspace_id}/ingest",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run ingestion for a workspace",
)
async def reingest_workspace(
    request: Request,
    workspace_id: uuid.UUID,
    developer: RequireDeveloper,
    workspaces: WorkspaceServiceDep,
) -> WorkspaceResponse:
    workspace = await workspaces.get(owner_id=developer.id, workspace_id=workspace_id)
    _enqueue_ingest(request, workspace.id)
    return WorkspaceResponse.model_validate(
        workspace.model_copy(update={"status": WorkspaceStatus.INGESTING})
    )


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workspace and its files",
)
async def delete_workspace(
    request: Request,
    workspace_id: uuid.UUID,
    developer: RequireDeveloper,
    workspaces: WorkspaceServiceDep,
) -> None:
    await workspaces.delete(
        owner_id=developer.id, workspace_id=workspace_id, request_id=request_id(request)
    )
