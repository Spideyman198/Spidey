"""Postgres adapter for the code knowledge graph (ADR-0003).

Traversals are recursive CTEs with three hard safety rails: a ``depth`` cap, a
visited-node accumulator that makes cycles terminate (a code graph is full of
them — mutual recursion, inheritance diamonds), and a final ``LIMIT``. No query
can walk an unbounded path, which is exactly the constraint ADR-0003 accepts in
exchange for keeping the graph in Postgres.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select, text

from spidey.codeintel.domain.models import (
    EdgeKind,
    GraphNeighbor,
    GraphNode,
    SymbolKind,
)
from spidey.codeintel.infrastructure.orm import GraphEdgeRecord, GraphNodeRecord

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession

    from spidey.codeintel.domain.models import GraphEdge

# The traversals are four concrete, fully static queries. They are written out
# in full — no string building of any kind — so no value ever reaches SQL except
# as a bound parameter (:ws/:path/:qn/:depth/:limit). This is deliberately not
# DRY: it makes SQL-injection impossibility obvious to a human and to every SAST
# scanner, which a dynamically assembled query cannot. Each projects the reached
# node, the edge, the hop distance, and the predecessor (for directional facts).
#
# Directions: callees walk src→dst over `calls` (outgoing); callers/impact walk
# dst→src (incoming); impact also follows `inherits` (subtype is affected);
# neighborhood walks either direction over any edge. Every walk is bounded by
# :depth, a visited-node array (cycle termination), and :limit.

_CALLEES_SQL = """
    WITH RECURSIVE seed AS (
        SELECT id FROM graph_nodes
         WHERE workspace_id = :ws AND path = :path AND qualified_name = :qn
    ),
    walk (node_id, via_id, edge_kind, depth, line, outgoing, visited) AS (
        SELECT e.dst_id, e.src_id, e.kind, 1, e.line, true, ARRAY[e.src_id, e.dst_id]
          FROM graph_edges e JOIN seed s ON e.src_id = s.id
         WHERE e.workspace_id = :ws AND e.kind = 'calls'
        UNION ALL
        SELECT e.dst_id, e.src_id, e.kind, w.depth + 1, e.line, true, w.visited || e.dst_id
          FROM graph_edges e JOIN walk w ON e.src_id = w.node_id
         WHERE e.workspace_id = :ws AND e.kind = 'calls'
           AND w.depth < :depth AND e.dst_id <> ALL(w.visited)
    )
    SELECT DISTINCT ON (w.node_id)
           n.path AS path, n.qualified_name AS qualified_name, n.name AS name,
           n.kind AS kind, n.start_line AS start_line,
           w.edge_kind AS edge_kind, w.depth AS depth, w.line AS line,
           w.outgoing AS outgoing, v.path AS via_path, v.qualified_name AS via_qn
      FROM walk w
      JOIN graph_nodes n ON n.id = w.node_id
      JOIN graph_nodes v ON v.id = w.via_id
     ORDER BY w.node_id, w.depth
     LIMIT :limit
"""

_CALLERS_SQL = """
    WITH RECURSIVE seed AS (
        SELECT id FROM graph_nodes
         WHERE workspace_id = :ws AND path = :path AND qualified_name = :qn
    ),
    walk (node_id, via_id, edge_kind, depth, line, outgoing, visited) AS (
        SELECT e.src_id, e.dst_id, e.kind, 1, e.line, false, ARRAY[e.dst_id, e.src_id]
          FROM graph_edges e JOIN seed s ON e.dst_id = s.id
         WHERE e.workspace_id = :ws AND e.kind = 'calls'
        UNION ALL
        SELECT e.src_id, e.dst_id, e.kind, w.depth + 1, e.line, false, w.visited || e.src_id
          FROM graph_edges e JOIN walk w ON e.dst_id = w.node_id
         WHERE e.workspace_id = :ws AND e.kind = 'calls'
           AND w.depth < :depth AND e.src_id <> ALL(w.visited)
    )
    SELECT DISTINCT ON (w.node_id)
           n.path AS path, n.qualified_name AS qualified_name, n.name AS name,
           n.kind AS kind, n.start_line AS start_line,
           w.edge_kind AS edge_kind, w.depth AS depth, w.line AS line,
           w.outgoing AS outgoing, v.path AS via_path, v.qualified_name AS via_qn
      FROM walk w
      JOIN graph_nodes n ON n.id = w.node_id
      JOIN graph_nodes v ON v.id = w.via_id
     ORDER BY w.node_id, w.depth
     LIMIT :limit
"""

_IMPACT_SQL = """
    WITH RECURSIVE seed AS (
        SELECT id FROM graph_nodes
         WHERE workspace_id = :ws AND path = :path AND qualified_name = :qn
    ),
    walk (node_id, via_id, edge_kind, depth, line, outgoing, visited) AS (
        SELECT e.src_id, e.dst_id, e.kind, 1, e.line, false, ARRAY[e.dst_id, e.src_id]
          FROM graph_edges e JOIN seed s ON e.dst_id = s.id
         WHERE e.workspace_id = :ws AND e.kind IN ('calls', 'inherits')
        UNION ALL
        SELECT e.src_id, e.dst_id, e.kind, w.depth + 1, e.line, false, w.visited || e.src_id
          FROM graph_edges e JOIN walk w ON e.dst_id = w.node_id
         WHERE e.workspace_id = :ws AND e.kind IN ('calls', 'inherits')
           AND w.depth < :depth AND e.src_id <> ALL(w.visited)
    )
    SELECT DISTINCT ON (w.node_id)
           n.path AS path, n.qualified_name AS qualified_name, n.name AS name,
           n.kind AS kind, n.start_line AS start_line,
           w.edge_kind AS edge_kind, w.depth AS depth, w.line AS line,
           w.outgoing AS outgoing, v.path AS via_path, v.qualified_name AS via_qn
      FROM walk w
      JOIN graph_nodes n ON n.id = w.node_id
      JOIN graph_nodes v ON v.id = w.via_id
     ORDER BY w.node_id, w.depth
     LIMIT :limit
"""

_NEIGHBORHOOD_SQL = """
    WITH RECURSIVE seed AS (
        SELECT id FROM graph_nodes
         WHERE workspace_id = :ws AND path = :path AND qualified_name = :qn
    ),
    walk (node_id, via_id, edge_kind, depth, line, outgoing, visited) AS (
        SELECT CASE WHEN e.src_id = s.id THEN e.dst_id ELSE e.src_id END,
               s.id, e.kind, 1, e.line, (e.src_id = s.id),
               ARRAY[s.id, CASE WHEN e.src_id = s.id THEN e.dst_id ELSE e.src_id END]
          FROM graph_edges e JOIN seed s ON (e.src_id = s.id OR e.dst_id = s.id)
         WHERE e.workspace_id = :ws
        UNION ALL
        SELECT CASE WHEN e.src_id = w.node_id THEN e.dst_id ELSE e.src_id END,
               w.node_id, e.kind, w.depth + 1, e.line, (e.src_id = w.node_id),
               w.visited || CASE WHEN e.src_id = w.node_id THEN e.dst_id ELSE e.src_id END
          FROM graph_edges e JOIN walk w ON (e.src_id = w.node_id OR e.dst_id = w.node_id)
         WHERE e.workspace_id = :ws AND w.depth < :depth
           AND (CASE WHEN e.src_id = w.node_id THEN e.dst_id ELSE e.src_id END) <> ALL(w.visited)
    )
    SELECT DISTINCT ON (w.node_id)
           n.path AS path, n.qualified_name AS qualified_name, n.name AS name,
           n.kind AS kind, n.start_line AS start_line,
           w.edge_kind AS edge_kind, w.depth AS depth, w.line AS line,
           w.outgoing AS outgoing, v.path AS via_path, v.qualified_name AS via_qn
      FROM walk w
      JOIN graph_nodes n ON n.id = w.node_id
      JOIN graph_nodes v ON v.id = w.via_id
     ORDER BY w.node_id, w.depth
     LIMIT :limit
"""


class PostgresGraphStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rebuild(
        self,
        *,
        workspace_id: uuid.UUID,
        nodes: Sequence[GraphNode],
        edges: Sequence[GraphEdge],
    ) -> None:
        # Edges first (they FK the nodes), then a clean node set, then re-insert.
        await self._session.execute(
            delete(GraphEdgeRecord).where(GraphEdgeRecord.workspace_id == workspace_id)
        )
        await self._session.execute(
            delete(GraphNodeRecord).where(GraphNodeRecord.workspace_id == workspace_id)
        )
        await self._session.flush()

        ids: dict[tuple[str, str], uuid.UUID] = {}
        node_rows: list[GraphNodeRecord] = []
        for node in nodes:
            node_id = uuid.uuid4()
            ids[(node.path, node.qualified_name)] = node_id
            node_rows.append(
                GraphNodeRecord(
                    id=node_id,
                    workspace_id=workspace_id,
                    path=node.path,
                    qualified_name=node.qualified_name,
                    name=node.name,
                    kind=node.kind.value,
                    start_line=node.start_line,
                )
            )
        self._session.add_all(node_rows)
        # Persist nodes before edges reference them: the FK targets are inserted
        # with explicit ids and no ORM relationship, so we order the flush here.
        await self._session.flush()

        edge_rows: list[GraphEdgeRecord] = []
        for edge in edges:
            src = ids.get((edge.src_path, edge.src_qualified_name))
            dst = ids.get((edge.dst_path, edge.dst_qualified_name))
            if src is None or dst is None:
                continue  # builder only emits resolved edges; defensive skip
            edge_rows.append(
                GraphEdgeRecord(
                    workspace_id=workspace_id,
                    src_id=src,
                    dst_id=dst,
                    kind=edge.kind.value,
                    line=edge.line,
                )
            )
        self._session.add_all(edge_rows)
        await self._session.flush()

    async def counts(self, workspace_id: uuid.UUID) -> tuple[int, int]:
        nodes = await self._session.scalar(
            select(func.count())
            .select_from(GraphNodeRecord)
            .where(GraphNodeRecord.workspace_id == workspace_id)
        )
        edges = await self._session.scalar(
            select(func.count())
            .select_from(GraphEdgeRecord)
            .where(GraphEdgeRecord.workspace_id == workspace_id)
        )
        return int(nodes or 0), int(edges or 0)

    async def find_nodes_by_name(
        self, *, workspace_id: uuid.UUID, name: str, limit: int = 20
    ) -> list[GraphNode]:
        records = await self._session.scalars(
            select(GraphNodeRecord)
            .where(
                GraphNodeRecord.workspace_id == workspace_id,
                or_(
                    func.lower(GraphNodeRecord.name) == name.lower(),
                    func.lower(GraphNodeRecord.qualified_name) == name.lower(),
                ),
            )
            .order_by(GraphNodeRecord.path, GraphNodeRecord.start_line)
            .limit(limit)
        )
        return [
            GraphNode(
                path=r.path,
                qualified_name=r.qualified_name,
                name=r.name,
                kind=SymbolKind(r.kind),
                start_line=r.start_line,
            )
            for r in records
        ]

    async def callers(
        self, *, workspace_id: uuid.UUID, path: str, qualified_name: str, depth: int, limit: int
    ) -> list[GraphNeighbor]:
        return await self._run(_CALLERS_SQL, workspace_id, path, qualified_name, depth, limit)

    async def callees(
        self, *, workspace_id: uuid.UUID, path: str, qualified_name: str, depth: int, limit: int
    ) -> list[GraphNeighbor]:
        return await self._run(_CALLEES_SQL, workspace_id, path, qualified_name, depth, limit)

    async def impact_set(
        self, *, workspace_id: uuid.UUID, path: str, qualified_name: str, depth: int, limit: int
    ) -> list[GraphNeighbor]:
        return await self._run(_IMPACT_SQL, workspace_id, path, qualified_name, depth, limit)

    async def neighborhood(
        self, *, workspace_id: uuid.UUID, path: str, qualified_name: str, depth: int, limit: int
    ) -> list[GraphNeighbor]:
        return await self._run(_NEIGHBORHOOD_SQL, workspace_id, path, qualified_name, depth, limit)

    async def _run(
        self,
        sql: str,
        workspace_id: uuid.UUID,
        path: str,
        qualified_name: str,
        depth: int,
        limit: int,
    ) -> list[GraphNeighbor]:
        result = await self._session.execute(
            text(sql),
            {
                "ws": workspace_id,
                "path": path,
                "qn": qualified_name,
                "depth": depth,
                "limit": limit,
            },
        )
        return [self._to_neighbor(row) for row in result.mappings()]

    @staticmethod
    def _to_neighbor(row: RowMapping) -> GraphNeighbor:
        return GraphNeighbor(
            node=GraphNode(
                path=str(row["path"]),
                qualified_name=str(row["qualified_name"]),
                name=str(row["name"]),
                kind=SymbolKind(str(row["kind"])),
                start_line=int(row["start_line"]),  # type: ignore[arg-type]
            ),
            edge_kind=EdgeKind(str(row["edge_kind"])),
            distance=int(row["depth"]),  # type: ignore[arg-type]
            via_qualified_name=str(row["via_qn"]),
            via_path=str(row["via_path"]),
            line=int(row["line"]) if row["line"] is not None else None,  # type: ignore[arg-type]
            outgoing=bool(row["outgoing"]),
        )
