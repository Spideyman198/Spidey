"""Workspace routes: create-and-ingest, list, get, manifest, re-ingest, delete.

Ingestion is asynchronous. Create/ingest endpoints commit the workspace row and
then enqueue the ingestion task, so the worker always sees a committed row. A
transactional outbox (M6) will later make the enqueue atomic with the commit;
until then the ordering is explicit here and a lost enqueue is recoverable via
the re-ingest endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from spidey.api.deps import (
    CurrentUser,
    GraphStoreDep,
    RequireDeveloper,
    SearchServiceDep,
    SessionDep,
    SymbolStoreDep,
    WorkspaceServiceDep,
)
from spidey.api.v1._request_meta import request_id
from spidey.api.v1.schemas import (
    CreateWorkspaceRequest,
    FileManifestEntryResponse,
    GraphNeighborResponse,
    GraphQueryResponse,
    IndexStateResponse,
    SearchHitResponse,
    SearchResponse,
    SymbolResponse,
    WorkspaceResponse,
)
from spidey.codeintel.domain.models import GraphNeighbor, IndexStatus
from spidey.platform.errors import NotFoundError
from spidey.workspaces.domain.models import IngestionRequest, WorkspaceStatus

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_INGEST_TASK = "spidey.workspaces.ingest"
_INDEX_TASK = "spidey.codeintel.index"


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


@router.get(
    "/{workspace_id}/index",
    response_model=IndexStateResponse,
    summary="Code-index status for a workspace",
)
async def get_index_state(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    symbols: SymbolStoreDep,
) -> IndexStateResponse:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    state = await symbols.get_state(workspace_id)
    if state is None:
        raise NotFoundError("workspace has not been indexed")
    return IndexStateResponse.model_validate(state)


@router.get(
    "/{workspace_id}/symbols",
    response_model=list[SymbolResponse],
    summary="Extracted symbols for a workspace",
)
async def list_symbols(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    symbols: SymbolStoreDep,
    path: str | None = None,
) -> list[SymbolResponse]:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    found = await symbols.list_symbols(workspace_id=workspace_id, path=path)
    return [SymbolResponse.model_validate(s) for s in found]


@router.get(
    "/{workspace_id}/search",
    response_model=SearchResponse,
    summary="Hybrid (semantic + lexical) code search",
)
async def search_code(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    search: SearchServiceDep,
    q: Annotated[str, Query(min_length=1, max_length=1024, description="Search query")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> SearchResponse:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    result = await search.search(workspace_id=workspace_id, query=q, limit=limit)
    return SearchResponse(
        query=q,
        hits=[SearchHitResponse.model_validate(hit) for hit in result.hits],
        graph_facts=result.graph_facts,
    )


def _neighbor_response(neighbor: GraphNeighbor) -> GraphNeighborResponse:
    return GraphNeighborResponse(
        node=neighbor.node,  # type: ignore[arg-type]
        edge_kind=neighbor.edge_kind,
        distance=neighbor.distance,
        via_qualified_name=neighbor.via_qualified_name,
        via_path=neighbor.via_path,
        line=neighbor.line,
        fact=neighbor.as_fact(),
    )


async def _resolve_seed(
    graph: GraphStoreDep, workspace_id: uuid.UUID, symbol: str
) -> tuple[str, str]:
    """Resolve a symbol name/qualified-name to a concrete graph node, or 404."""
    nodes = await graph.find_nodes_by_name(workspace_id=workspace_id, name=symbol)
    if not nodes:
        raise NotFoundError("no graph node matches that symbol")
    return nodes[0].path, nodes[0].qualified_name


def _clamp_depth(request: Request, depth: int | None) -> int:
    settings = request.app.state.container.settings
    if depth is None:
        return settings.graph_query_default_depth
    return max(1, min(depth, settings.graph_query_max_depth))


def _row_limit(request: Request) -> int:
    return int(request.app.state.container.settings.graph_query_max_results)


@router.get(
    "/{workspace_id}/graph/callers",
    response_model=GraphQueryResponse,
    summary="Transitive callers of a symbol (what calls X)",
)
async def graph_callers(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    graph: GraphStoreDep,
    request: Request,
    symbol: Annotated[str, Query(min_length=1, max_length=1024)],
    depth: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> GraphQueryResponse:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    path, qn = await _resolve_seed(graph, workspace_id, symbol)
    neighbors = await graph.callers(
        workspace_id=workspace_id,
        path=path,
        qualified_name=qn,
        depth=_clamp_depth(request, depth),
        limit=_row_limit(request),
    )
    return GraphQueryResponse(
        symbol=symbol, relation="callers", neighbors=[_neighbor_response(n) for n in neighbors]
    )


@router.get(
    "/{workspace_id}/graph/callees",
    response_model=GraphQueryResponse,
    summary="Transitive callees of a symbol (what X calls)",
)
async def graph_callees(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    graph: GraphStoreDep,
    request: Request,
    symbol: Annotated[str, Query(min_length=1, max_length=1024)],
    depth: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> GraphQueryResponse:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    path, qn = await _resolve_seed(graph, workspace_id, symbol)
    neighbors = await graph.callees(
        workspace_id=workspace_id,
        path=path,
        qualified_name=qn,
        depth=_clamp_depth(request, depth),
        limit=_row_limit(request),
    )
    return GraphQueryResponse(
        symbol=symbol, relation="callees", neighbors=[_neighbor_response(n) for n in neighbors]
    )


@router.get(
    "/{workspace_id}/graph/impact",
    response_model=GraphQueryResponse,
    summary="Impact set of a symbol (what changing X affects)",
)
async def graph_impact(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    graph: GraphStoreDep,
    request: Request,
    symbol: Annotated[str, Query(min_length=1, max_length=1024)],
    depth: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> GraphQueryResponse:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    path, qn = await _resolve_seed(graph, workspace_id, symbol)
    neighbors = await graph.impact_set(
        workspace_id=workspace_id,
        path=path,
        qualified_name=qn,
        depth=_clamp_depth(request, depth),
        limit=_row_limit(request),
    )
    return GraphQueryResponse(
        symbol=symbol, relation="impact", neighbors=[_neighbor_response(n) for n in neighbors]
    )


@router.get(
    "/{workspace_id}/graph/neighborhood",
    response_model=GraphQueryResponse,
    summary="Graph neighborhood of a symbol (any edge, either direction)",
)
async def graph_neighborhood(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    workspaces: WorkspaceServiceDep,
    graph: GraphStoreDep,
    request: Request,
    symbol: Annotated[str, Query(min_length=1, max_length=1024)],
    depth: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> GraphQueryResponse:
    await workspaces.get(owner_id=user.id, workspace_id=workspace_id)  # ownership check
    path, qn = await _resolve_seed(graph, workspace_id, symbol)
    neighbors = await graph.neighborhood(
        workspace_id=workspace_id,
        path=path,
        qualified_name=qn,
        depth=_clamp_depth(request, depth),
        limit=_row_limit(request),
    )
    return GraphQueryResponse(
        symbol=symbol,
        relation="neighborhood",
        neighbors=[_neighbor_response(n) for n in neighbors],
    )


@router.post(
    "/{workspace_id}/index",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run code indexing for a workspace",
)
async def reindex_code(
    request: Request,
    workspace_id: uuid.UUID,
    developer: RequireDeveloper,
    workspaces: WorkspaceServiceDep,
) -> IndexStateResponse:
    await workspaces.get(owner_id=developer.id, workspace_id=workspace_id)  # ownership check
    request.app.state.container.task_queue.enqueue(
        _INDEX_TASK, str(workspace_id), queue="ingestion"
    )
    return IndexStateResponse(
        status=IndexStatus.BUILDING,
        file_count=0,
        symbol_count=0,
        chunk_count=0,
        updated_at=datetime.now(tz=UTC),
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
