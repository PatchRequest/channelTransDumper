"""Read-only queries on the transcript database (shared by the CLI and the MCP server)."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from .embedding import Embedder

MAX_LIMIT = 50
MAX_QUERIES = 5
MAX_TERMS = 20
# Deepest position reachable by paging (offset + limit). Every search fuses this many
# candidates from each list, so the fused ranking does not depend on the page asked
# for and consecutive pages neither repeat nor skip passages.
MAX_DEPTH = 1000
# Customary damping constant of reciprocal rank fusion.
_RRF_K = 60

Match = Literal["all", "any"]

_TERM = re.compile(r'"([^"]*)"|(\S+)')

_PASSAGE_COLUMNS = """
    p.id AS passage_id, p.video_id, p.seq, p.start_ms, p.end_ms, p.text,
    v.title AS video_title, v.upload_date, c.title AS channel
"""
_PASSAGE_JOINS = """
    JOIN videos v ON v.id = p.video_id
    JOIN channels c ON c.id = v.channel_id
"""


class QueryError(Exception):
    """The request is invalid (empty search, unknown channel, unknown ID)."""


def build_fts_query(query: str, match: Match) -> str:
    """Translate a free-form search query into a safe FTS5 expression.

    Words are searched individually, ``"…"`` as an exact phrase, ``word*`` as a prefix.
    """
    terms = []
    for phrase, word in _TERM.findall(query):
        prefix = not phrase and word.endswith("*")
        text = phrase or word.rstrip("*")
        if not re.search(r"\w", text):
            continue
        terms.append('"' + text.replace('"', '""') + '"' + ("*" if prefix else ""))
    if not terms:
        raise QueryError("The search query contains no search terms.")
    return (" AND " if match == "all" else " OR ").join(terms)


def search_passages(
    conn: sqlite3.Connection,
    embedder: Embedder,
    queries: Sequence[str],
    *,
    channel: str | None = None,
    match: Match = "all",
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Hybrid search: full text and semantic similarity, fused into one ranking.

    Full-text search finds exact terms and names; semantic search finds hits by
    meaning – even with mistranscribed words or a query in another language.
    Several ``queries`` (e.g. the same question phrased in different languages) are
    searched separately and fused, so a passage found by several of them ranks higher.
    ``match`` only affects the full-text part. ``offset`` pages through the ranking.
    """
    queries = [query for query in queries if query.strip()]
    if not 1 <= len(queries) <= MAX_QUERIES:
        raise QueryError(f"Between 1 and {MAX_QUERIES} non-empty queries are required.")
    limit = _clamp(limit)
    if offset < 0 or offset + limit > MAX_DEPTH:
        raise QueryError(f"offset + limit must be between 1 and {MAX_DEPTH}.")
    channel_id = None if channel is None else resolve_channel(conn, channel)
    candidates = MAX_DEPTH

    rankings: list[list[int]] = []
    text_matches: set[int] = set()
    similarities: dict[int, float] = {}
    for query in queries:
        text_ids = text_candidates(conn, build_fts_query(query, match), channel_id, candidates)
        semantic = semantic_candidates(conn, embedder.embed_query(query), channel_id, candidates)
        rankings += [text_ids, list(semantic)]
        text_matches.update(text_ids)
        for passage_id, similarity in semantic.items():
            similarities[passage_id] = max(similarity, similarities.get(passage_id, 0.0))

    best = fuse_rankings(rankings)[offset : offset + limit]
    if not best:
        return []

    rows = conn.execute(
        f"""SELECT {_PASSAGE_COLUMNS} FROM passages p {_PASSAGE_JOINS}
            WHERE p.id IN ({",".join("?" * len(best))})""",
        best,
    )
    by_id = {row["passage_id"]: row for row in rows}
    return [
        _passage(by_id[passage_id])
        | {
            "text_match": passage_id in text_matches,
            "semantic_similarity": similarities.get(passage_id),
        }
        for passage_id in best
    ]


def fuse_rankings(rankings: Iterable[Sequence[int]]) -> list[int]:
    """Reciprocal rank fusion: passages ranked high in several lists come first."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, passage_id in enumerate(ranking):
            scores[passage_id] = scores.get(passage_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
    return sorted(scores, key=lambda passage_id: (-scores[passage_id], passage_id))


def text_candidates(
    conn: sqlite3.Connection, fts_query: str, channel_id: str | None, count: int
) -> list[int]:
    """Passage IDs matching an FTS5 expression, best BM25 score first."""
    sql = """SELECT p.id FROM passages_fts
             JOIN passages p ON p.id = passages_fts.rowid
             JOIN videos v ON v.id = p.video_id
             WHERE passages_fts MATCH ?"""
    params: list[Any] = [fts_query]
    if channel_id is not None:
        sql += " AND v.channel_id = ?"
        params.append(channel_id)
    sql += " ORDER BY bm25(passages_fts) LIMIT ?"
    return [row[0] for row in conn.execute(sql, [*params, count])]


def semantic_candidates(
    conn: sqlite3.Connection, query_vector: bytes, channel_id: str | None, count: int
) -> dict[int, float]:
    """Nearest neighbours of the query: passage ID → cosine similarity, best first."""
    sql = "SELECT passage_id, distance FROM passage_vectors WHERE embedding MATCH ? AND k = ?"
    params: list[Any] = [query_vector, count]
    if channel_id is not None:
        sql += " AND channel_id = ?"
        params.append(channel_id)
    sql += " ORDER BY distance"
    return {row[0]: round(1.0 - row[1], 3) for row in conn.execute(sql, params)}


def find_mentions(
    conn: sqlite3.Connection,
    terms: Sequence[str],
    *,
    channel: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Every passage containing one of the terms, grouped by video (most mentions first).

    Unlike :func:`search_passages` this is exhaustive: no ranking cut-off, so a
    researcher can see all videos that mention a name or term. Terms are matched as
    phrases (English stemming, so "hawk" also matches "hawks"); list transcription
    variants as separate terms. ``limit``/``offset`` page through the videos.
    """
    terms = [term for term in terms if term.strip()]
    if not 1 <= len(terms) <= MAX_TERMS:
        raise QueryError(f"Between 1 and {MAX_TERMS} non-empty terms are required.")
    fts_query = " OR ".join(f'"{fts_phrase(term)}"' for term in terms)
    sql = f"""SELECT p.id AS passage_id, p.video_id, p.start_ms,
                     v.title AS video_title, v.upload_date, c.title AS channel
              FROM passages_fts JOIN passages p ON p.id = passages_fts.rowid {_PASSAGE_JOINS}
              WHERE passages_fts MATCH ?"""
    params: list[Any] = [fts_query]
    if channel is not None:
        sql += " AND v.channel_id = ?"
        params.append(resolve_channel(conn, channel))
    videos: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql + " ORDER BY p.video_id, p.start_ms", params):
        video = videos.setdefault(
            row["video_id"],
            {
                "video_id": row["video_id"],
                "video_title": row["video_title"],
                "channel": row["channel"],
                "upload_date": row["upload_date"],
                "passages": [],
            },
        )
        video["passages"].append(
            {
                "passage_id": row["passage_id"],
                "start": _clock(row["start_ms"]),
                "url": _video_url(row["video_id"], row["start_ms"]),
            }
        )
    ordered = sorted(videos.values(), key=lambda v: (-len(v["passages"]), v["video_id"]))
    return {
        "total_passages": sum(len(v["passages"]) for v in ordered),
        "total_videos": len(ordered),
        "videos": ordered[max(offset, 0) : max(offset, 0) + _clamp(limit)],
    }


def fts_phrase(term: str) -> str:
    """A term as the body of an FTS5 phrase: punctuation becomes token separators."""
    words = re.findall(r"\w+", term)
    if not words:
        raise QueryError(f"Term {term!r} contains no words.")
    return " ".join(words)


def passage_context(
    conn: sqlite3.Connection, passage_id: int, *, before: int = 2, after: int = 2
) -> list[dict[str, Any]]:
    """Return a passage together with its neighbours in the same video."""
    anchor = conn.execute(
        "SELECT video_id, seq FROM passages WHERE id = ?", (passage_id,)
    ).fetchone()
    if anchor is None:
        raise QueryError(f"Passage {passage_id} does not exist.")
    rows = conn.execute(
        f"""SELECT {_PASSAGE_COLUMNS} FROM passages p {_PASSAGE_JOINS}
            WHERE p.video_id = ? AND p.seq BETWEEN ? AND ? ORDER BY p.seq""",
        (anchor["video_id"], anchor["seq"] - max(before, 0), anchor["seq"] + max(after, 0)),
    )
    return [_passage(row) for row in rows]


def video_transcript(
    conn: sqlite3.Connection, video_id: str, *, offset: int = 0, limit: int = 20
) -> dict[str, Any]:
    """Return a video's transcript page by page as passages."""
    video = conn.execute(
        """SELECT v.id, v.title, v.upload_date, v.duration_s, v.description, v.status,
                  c.title AS channel, t.language, t.kind
           FROM videos v JOIN channels c ON c.id = v.channel_id
           LEFT JOIN transcripts t ON t.video_id = v.id
           WHERE v.id = ?""",
        (video_id,),
    ).fetchone()
    if video is None:
        raise QueryError(f"Video {video_id} is not in the database.")
    total = conn.execute(
        "SELECT count(*) FROM passages WHERE video_id = ?", (video_id,)
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT {_PASSAGE_COLUMNS} FROM passages p {_PASSAGE_JOINS}
            WHERE p.video_id = ? ORDER BY p.seq LIMIT ? OFFSET ?""",
        (video_id, _clamp(limit), max(offset, 0)),
    )
    return {
        "video_id": video["id"],
        "title": video["title"],
        "channel": video["channel"],
        "upload_date": video["upload_date"],
        "duration_s": video["duration_s"],
        "description": video["description"],
        "status": video["status"],
        "transcript_language": video["language"],
        "transcript_kind": video["kind"],
        "url": _video_url(video["id"]),
        "total_passages": total,
        "passages": [
            {"passage_id": r["passage_id"], "seq": r["seq"], "start": _clock(r["start_ms"]),
             "text": r["text"]}
            for r in rows
        ],
    }


def list_videos(
    conn: sqlite3.Connection,
    *,
    channel: str | None = None,
    title_contains: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List videos (newest first), optionally filtered by channel and title."""
    sql = """SELECT v.id, v.title, v.upload_date, v.duration_s, v.status, c.title AS channel
             FROM videos v JOIN channels c ON c.id = v.channel_id WHERE 1 = 1"""
    params: list[Any] = []
    if channel is not None:
        sql += " AND v.channel_id = ?"
        params.append(resolve_channel(conn, channel))
    if title_contains:
        sql += " AND instr(lower(v.title), lower(?)) > 0"
        params.append(title_contains)
    sql += " ORDER BY v.channel_id, v.listing_rank LIMIT ? OFFSET ?"
    params += [_clamp(limit), max(offset, 0)]
    return [
        {
            "video_id": r["id"],
            "title": r["title"],
            "channel": r["channel"],
            "upload_date": r["upload_date"],
            "duration_s": r["duration_s"],
            "status": r["status"],
            "url": _video_url(r["id"]),
        }
        for r in conn.execute(sql, params)
    ]


def channel_stats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Overview of all channels with their synchronisation progress.

    ``transcript_languages`` counts transcripts per language as YouTube reports it.
    Single outliers are usually music-only clips whose language YouTube misdetected.
    """
    rows = conn.execute(
        """SELECT c.id, c.handle, c.title, c.url, c.last_discovered_at,
                  count(v.id) AS videos,
                  coalesce(sum(v.status = 'done'), 0) AS done,
                  coalesce(sum(v.status = 'pending'), 0) AS pending,
                  coalesce(sum(v.status = 'no_transcript'), 0) AS no_transcript,
                  coalesce(sum(v.status = 'failed'), 0) AS failed
           FROM channels c LEFT JOIN videos v ON v.channel_id = c.id
           GROUP BY c.id ORDER BY c.title"""
    ).fetchall()
    languages: dict[str, dict[str, int]] = {}
    for row in conn.execute(
        """SELECT v.channel_id, t.language, count(*) AS transcripts
           FROM transcripts t JOIN videos v ON v.id = t.video_id
           GROUP BY v.channel_id, t.language ORDER BY transcripts DESC, t.language"""
    ):
        languages.setdefault(row["channel_id"], {})[row["language"]] = row["transcripts"]
    return [dict(row) | {"transcript_languages": languages.get(row["id"], {})} for row in rows]


def resolve_channel(conn: sqlite3.Connection, channel: str) -> str:
    """Find the channel ID for an ID, an @handle or a title."""
    handle = channel if channel.startswith("@") else f"@{channel}"
    rows = conn.execute(
        """SELECT id FROM channels
           WHERE id = ? OR lower(handle) = lower(?) OR lower(title) = lower(?)""",
        (channel, handle, channel),
    ).fetchall()
    if len(rows) != 1:
        known = ", ".join(
            r["handle"] or r["id"] for r in conn.execute("SELECT id, handle FROM channels")
        )
        raise QueryError(f"Channel {channel!r} not found unambiguously. Known: {known or '–'}")
    return rows[0]["id"]


def _passage(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "passage_id": row["passage_id"],
        "video_id": row["video_id"],
        "video_title": row["video_title"],
        "channel": row["channel"],
        "upload_date": row["upload_date"],
        "seq": row["seq"],
        "start": _clock(row["start_ms"]),
        "url": _video_url(row["video_id"], row["start_ms"]),
        "text": row["text"],
    }


def _video_url(video_id: str, start_ms: int | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    return url if start_ms is None else f"{url}&t={start_ms // 1000}s"


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _clamp(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))
