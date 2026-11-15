"""Retrieval variants under test. Each returns passage IDs, best first."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .. import search
from ..embedding import Embedder
from .dataset import Case

Variant = Callable[[sqlite3.Connection, Embedder, Case, int], list[int]]


def _hybrid(match: search.Match) -> Variant:
    def run(conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int) -> list[int]:
        hits = search.search_passages(conn, embedder, case.queries, match=match, limit=depth)
        return [hit["passage_id"] for hit in hits]

    return run


def _semantic(conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int) -> list[int]:
    return search.fuse_rankings(
        list(search.semantic_candidates(conn, embedder.embed_query(query), None, depth))
        for query in case.queries
    )[:depth]


def _fts_any(conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int) -> list[int]:
    return search.fuse_rankings(
        search.text_candidates(conn, search.build_fts_query(query, "any"), None, depth)
        for query in case.queries
    )[:depth]


VARIANTS: dict[str, Variant] = {
    "hybrid": _hybrid("all"),
    "hybrid_any": _hybrid("any"),
    "semantic": _semantic,
    "fts_any": _fts_any,
}
