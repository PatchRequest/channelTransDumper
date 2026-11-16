"""Retrieval variants under test. Each returns passage IDs, best first."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .. import search, spelling
from ..embedding import MODEL_CACHE, Embedder
from . import metrics
from .dataset import Case

Variant = Callable[[sqlite3.Connection, Embedder, Case, int], list[int]]


def _hybrid(match: search.Match, with_keywords: bool = False) -> Variant:
    def run(conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int) -> list[int]:
        queries = case.queries + ([case.keywords] if with_keywords and case.keywords else [])
        ids: list[int] = []
        while len(ids) < depth:  # page through the ranking like an agent would
            page = search.search_passages(
                conn, embedder, queries, match=match, offset=len(ids),
                limit=min(search.MAX_LIMIT, depth - len(ids)),
            )
            ids += [hit["passage_id"] for hit in page]
            if len(page) < search.MAX_LIMIT:
                break
        return ids

    return run


def _all_mentions(conn: sqlite3.Connection, terms: list[str], depth: int) -> list[int]:
    """Every passage find_mentions returns for the terms, paging through all videos."""
    ids: list[int] = []
    offset = 0
    while True:
        page = search.find_mentions(conn, terms, limit=search.MAX_LIMIT, offset=offset)
        ids += [p["passage_id"] for video in page["videos"] for p in video["passages"]]
        offset += search.MAX_LIMIT
        if offset >= page["total_videos"]:
            return ids[:depth]


def _mentions(conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int) -> list[int]:
    """All passages naming the case's queries as terms, video by video."""
    return _all_mentions(conn, case.queries, depth)


def _mentions_spelled(
    conn: sqlite3.Connection, embedder: Embedder, case: Case, depth: int
) -> list[int]:
    """find_mentions with the queries plus the suggest_spellings results a perfect judge
    would accept (those the case lists as spellings of the term): the upper bound for an
    agent using both tools with the default number of suggestions."""
    known = metrics.mention_pattern(case.terms)
    terms = list(case.queries)
    for query in case.queries:
        terms += [
            s["spelling"]
            for s in spelling.suggest_spellings(conn, query)["suggestions"]
            if known.fullmatch(s["spelling"])
        ]
    return _all_mentions(conn, terms[: search.MAX_TERMS], depth)


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
    "hybrid_kw": _hybrid("all", with_keywords=True),
    "semantic": _semantic,
    "fts_any": _fts_any,
    "mentions": _mentions,
    "mentions_spelled": _mentions_spelled,
    "reranked": _Reranked(),
}

# Variants that only make sense for some case kinds (default: all kinds).
APPLIES_TO: dict[str, frozenset[str]] = {
    "mentions": frozenset({"mention"}),
    "mentions_spelled": frozenset({"mention"}),
    "hybrid_kw": frozenset({"fact", "sweep"}),
}


def applies(variant: str, kind: str) -> bool:
    return kind in APPLIES_TO.get(variant, frozenset({kind}))
