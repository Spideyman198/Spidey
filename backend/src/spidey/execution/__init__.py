"""Execution context (M9): the sandboxed command/test capability.

The most dangerous capability in the system — running untrusted code — behind a
narrow ``Sandbox`` port and a fail-closed ``CommandPolicy``. The security
property defended is the container boundary (B4), engineered as if the sandbox
interior is routinely hostile (docs/11 §1).
"""
