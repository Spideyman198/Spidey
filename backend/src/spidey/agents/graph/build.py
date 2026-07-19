"""Run graph topology (ADR-0002): plan → (coder → review → commit)* → finalize.

Explicit and diagrammable by design (docs/02 §5). ``plan`` drafts and pauses for
approval; ``branch`` isolates the run on its own git branch; each step flows
``coder`` → (edit-approval gate → ``apply_edits``) → ``reviewer`` (bounded
critique loop) → ``commit`` (secret-scanned, atomic). Compiled with a
checkpointer so every pause is durable and a run resumes across an API restart.
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
    graph.add_node("branch", nodes.branch)
    graph.add_node("coder", nodes.coder)
    graph.add_node("gate_edits", nodes.gate_edits)
    graph.add_node("apply_edits", nodes.apply_edits)
    graph.add_node("reviewer", nodes.reviewer)
    graph.add_node("commit", nodes.commit)
    graph.add_node("budget_gate", nodes.budget_gate)
    # M10 tail: test → (debug loop | document) → PR gate → open PR → finalize.
    graph.add_node("test", nodes.test)
    graph.add_node("debug", nodes.debug)
    graph.add_node("document", nodes.document)
    graph.add_node("pr_gate", nodes.pr_gate)
    graph.add_node("open_pr", nodes.open_pr)
    graph.add_node("escalate", nodes.escalate)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "approve")  # plan drafted once, then the approval gate
    graph.add_edge("approve", "branch")  # isolated run branch before any edit
    graph.add_edge("branch", "coder")
    graph.add_conditional_edges(
        "coder",
        nodes.route_after_coder,
        {"gate_edits": "gate_edits", "reviewer": "reviewer", "commit": "commit"},
    )
    graph.add_edge("gate_edits", "apply_edits")  # resume ⇒ approvals resolved
    graph.add_edge("apply_edits", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        nodes.route_after_reviewer,
        {"coder": "coder", "commit": "commit"},
    )
    graph.add_conditional_edges(
        "commit",
        nodes.route_after_commit,
        {"coder": "coder", "budget_gate": "budget_gate", "test": "test"},
    )
    graph.add_edge("budget_gate", "coder")  # a granted window resumes execution
    graph.add_conditional_edges(
        "test",
        nodes.route_after_test,
        {"debug": "debug", "document": "document", "escalate": "escalate"},
    )
    graph.add_edge("debug", "coder")  # the fix step rides the coder/commit path
    graph.add_conditional_edges(
        "document",
        nodes.route_after_document,
        {"pr_gate": "pr_gate", "finalize": "finalize"},
    )
    graph.add_edge("pr_gate", "open_pr")  # resume ⇒ PR approved
    graph.add_edge("open_pr", "finalize")
    graph.add_edge("escalate", END)
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
