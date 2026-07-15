"""Code-intelligence domain errors."""

from __future__ import annotations

from spidey.platform.errors import SpideyError


class ParseError(SpideyError):
    """A source file could not be parsed (size limit, timeout, or bad input).

    Raised across the :class:`Parser` port; the indexer catches it to record
    the file as indexed-but-empty rather than failing the whole index pass.
    """

    status = 422
    title = "Source could not be parsed"
