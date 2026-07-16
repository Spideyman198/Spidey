"""Agents context — the orchestrator.

Unlike the leaf contexts (which stay independent of one another), agents composes
their capabilities: it owns the tool plane (the single invocation choke point,
M6), and — from M7 — run lifecycle, the planner/coder/reviewer graph, and
context assembly. It may depend on the leaf contexts; they never depend on it.
"""
