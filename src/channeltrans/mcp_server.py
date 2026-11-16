"""MCP server: exposes the transcript database to AI agents as search tools."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import search, spelling
from .db import DatabaseError, connect_read_only
from .embedding import LocalEmbedder


def build_server(db_path: Path) -> MCPServer:
    server = MCPServer(
        "channeltrans",
        instructions=(
            "Searchable transcripts of YouTube channels. Each passage is a roughly "
            "one-minute excerpt of what was said, with video, timestamp and link. "
            "Typical flow: list_channels → search_transcripts → get_passage_context for "
            "the surroundings of a hit. For everything said about a named thing, call "
            "suggest_spellings for its distinctive word (\"peregrine\", not \"peregrine "
            "falcon\"), then find_mentions with the term plus the suggestions that really "
            "mean it; find_mentions is exhaustive. Page through search_transcripts with "
            "offset for everything on a topic. Search is hybrid (full text plus semantic "
            "similarity). It works across languages, but hits are clearly better when "
            "the query is in the transcript's language, so translate the question into "
            "it rather than searching in the user's language. list_channels reports how "
            "many transcripts each channel has per language (transcript_languages); a "
            "single outlier is usually a misdetected music clip and can be ignored. Pass "
            "one query per relevant language, or rephrasings of the question, as several "
            "queries in one call. Most transcripts are auto-generated: proper names and "
            "technical terms may be misspelled. For exhaustive research on a topic, add a "
            "short keyword query (e.g. \"goshawk molt weight\") next to the question and "
            "keep paging: that reaches clearly more of the relevant passages, at a small "
            "cost to the first hits."
        ),
    )
    embedder = LocalEmbedder()

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        """Read-only connection; expected errors reach the agent in plain text."""
        try:
            conn = connect_read_only(db_path)
            try:
                yield conn
            finally:
                conn.close()
        except (DatabaseError, search.QueryError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def list_channels() -> list[dict[str, Any]]:
        """List all captured channels with video counts, progress and transcript languages."""
        with connection() as conn:
            return search.channel_stats(conn)

    @server.tool()
    def search_transcripts(
        queries: list[str],
        channel: str | None = None,
        match: Literal["all", "any"] = "all",
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Hybrid search over the transcripts; returns the most relevant passages.

        Combines full-text search (exact terms, names) with semantic search (hits by
        meaning, even with mistranscribed words). Each query is searched separately and
        all results are fused into one ranking; passages found by several queries rank
        higher.

        queries: 1–5 phrasings of the same question, each in a language the transcripts
            are in (see list_channels → transcript_languages) – a query in another
            language finds less and dilutes the ranking. Use several queries for
            channels with several languages or for alternative wordings and synonyms.
            For the full-text part: words are stemmed (English), "…" searches an exact
            phrase, word* a prefix.
        channel: optionally restrict to one channel (ID, @handle or title).
        match: full-text part – "all" = every term must occur, "any" = one is enough.
        limit: number of hits per call (at most 50).
        offset: skip this many hits to read further pages of the same ranking
            (offset + limit at most 1000). Keep paging while hits stay relevant.

        For each hit, text_match tells whether the terms of some query occur literally,
        and semantic_similarity (0–1, the best over all queries; null if not among the
        semantically nearest) how close it is in meaning.
        """
        with connection() as conn:
            return search.search_passages(
                conn, embedder, queries, channel=channel, match=match, limit=limit, offset=offset
            )

    @server.tool()
    def find_mentions(
        terms: list[str], channel: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Every passage that names one of the terms, grouped by video, most mentions first.

        Exhaustive, unlike search_transcripts: use it to see all videos that mention a
        species, person, place or piece of equipment, then read passages with
        get_passage_context. Terms match as phrases with English stemming ("hawk" also
        matches "hawks"). Transcripts misspell names, so add the transcription variants
        as extra terms (up to 20): get them from suggest_spellings, e.g.
        ["goshawk", "gosh hawk", "goss hawk", "gossock"].
        limit/offset page through the videos (at most 50 per call); total_passages and
        total_videos give the full counts.
        """
        with connection() as conn:
            return search.find_mentions(conn, terms, channel=channel, limit=limit, offset=offset)

    @server.tool()
    def suggest_spellings(term: str, channel: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Transcription variants of a term that occur in the transcripts.

        Automatic captions mangle names ("goshawk" → "gosh hawk", "gossock"; "kestrel" →
        "kestral"). Returns spellings close to the term in letters and sound that find
        passages the term itself misses: each with the number of passages it adds and an
        example (match in «guillemets»). Closest spellings come first. Many suggestions
        are different words that merely sound alike – judge each by its example and
        pass only the real variants to find_mentions. Use the distinctive word of a name
        (at least 5 letters): "peregrine" rather than "peregrine falcon".
        limit: number of suggestions (at most 50).
        """
        with connection() as conn:
            return spelling.suggest_spellings(conn, term, channel=channel, limit=limit)

    @server.tool()
    def get_passage_context(
        passage_id: int, before: int = 2, after: int = 2
    ) -> list[dict[str, Any]]:
        """Return a passage with the passages before and after it from the same video."""
        with connection() as conn:
            return search.passage_context(conn, passage_id, before=before, after=after)

    @server.tool()
    def get_video_transcript(video_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        """Return a video's metadata and transcript, page by page as passages.

        offset/limit page through the passages (at most 50 per call);
        total_passages gives the total count.
        """
        with connection() as conn:
            return search.video_transcript(conn, video_id, offset=offset, limit=limit)

    @server.tool()
    def list_videos(
        channel: str | None = None,
        title_contains: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List videos, newest first; optionally filtered by channel and title substring.

        status tells whether a transcript exists: done, pending, no_transcript or failed.
        """
        with connection() as conn:
            return search.list_videos(
                conn, channel=channel, title_contains=title_contains, limit=limit, offset=offset
            )

    return server
