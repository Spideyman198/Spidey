"""LLM bounded context: provider-neutral model access.

M4 delivers the embedding slice — dense semantic + sparse BM25 embeddings via
local fastembed models behind ports. The chat-model provider registry, native
tool-calling, streaming, retries, budgets, and metering (ADR-0009/0012) arrive
with M6; they layer onto the same context.
"""
