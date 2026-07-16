"""Run graph topology (ADR-0002): plan → execute* → finalize.

Explicit and diagrammable by design. ``plan`` drafts and pauses for approval;
``execute`` loops over plan steps (pausing before any write tool); ``finalize``
completes the run. Compiled with a checkpointer so pauses are durable and a run
resumes across an API restart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from spidey.agents.graph.state import RunState

if TYPE_CHECKING:
    from spidey.agents.graph.nodes import GraphNodes


def build_run_graph(nodes: GraphNodes, *, checkpointer: Any) -> Any:
    graph: StateGraph[RunState, None, RunState, RunState] = StateGraph(RunState)
    graph.add_node("plan", nodes.plan)
    graph.add_node("approve", nodes.approve)
    graph.add_node("execute", nodes.execute)
    graph.add_node("budget_gate", nodes.budget_gate)
    graph.add_node("finalize", nodes.finalize)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "approve")  # plan drafted once, then the approval gate
    graph.add_edge("approve", "execute")
    graph.add_conditional_edges(
        "execute",
        nodes.route_after_execute,
        {"execute": "execute", "budget_gate": "budget_gate", "finalize": "finalize"},
    )
    graph.add_edge("budget_gate", "execute")  # a granted window resumes execution
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
