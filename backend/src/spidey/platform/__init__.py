"""Shared kernel: configuration, errors, logging, telemetry, security primitives.

This package must never import from any bounded context or interface layer
(enforced by import-linter). Everything here is context-free infrastructure
that the rest of the system builds on.
"""
