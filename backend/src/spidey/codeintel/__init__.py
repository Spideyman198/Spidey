"""Code-intelligence bounded context: Tree-sitter parsing, symbol extraction,
syntax-aware chunking, and incremental indexing.

M3 delivers parsing, the symbol index, and the chunker. Embedding and vector
search (M4), and the knowledge graph (M5), build on the symbols and chunks
produced here.
"""
