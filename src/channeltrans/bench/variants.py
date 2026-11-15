"""Retrieval variants under test. Each returns passage IDs, best first."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .. import search
from ..embedding import MODEL_CACHE, Embedder
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


class _Reranked:
    """Hybrid candidates re-sorted by a cross-encoder (re-measured on judged cases)."""

    MODEL = "jinaai/jina-reranker-v2-base-multilingual"
    CANDIDATES = 50

    def __init__(self) -> None:
        self._encoder = None

    def __call__(
        self, conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int
    ) -> list[int]:
        if self._encoder is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._encoder = TextCrossEncoder(self.MODEL, cache_dir=str(MODEL_CACHE))
        hits = search.search_passages(conn, embedder, case.queries, limit=self.CANDIDATES)
        documents = [f"{hit['video_title']}\n{hit['text']}" for hit in hits]
        scores = [0.0] * len(hits)
        for query in case.queries:
            for index, score in enumerate(self._encoder.rerank(query, documents)):
                scores[index] = max(scores[index], score)
        order = sorted(range(len(hits)), key=lambda index: -scores[index])
        return [hits[index]["passage_id"] for index in order][:depth]


VARIANTS: dict[str, Variant] = {
    "hybrid": _hybrid("all"),
    "hybrid_any": _hybrid("any"),
    "semantic": _semantic,
    "fts_any": _fts_any,
    "reranked": _Reranked(),
}
