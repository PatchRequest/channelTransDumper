"""MCP server: exposes the transcript database to AI agents as search tools."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import search
from .db import DatabaseError, connect_read_only
from .embedding import LocalEmbedder


def build_server(db_path: Path) -> MCPServer:
    server = MCPServer(
        "channeltrans",
        instructions=(
            "Searchable transcripts of YouTube channels. Each passage is a roughly "
            "one-minute excerpt of what was said, with video, timestamp and link. "
            "Typical flow: list_channels → search_transcripts → get_passage_context for "
            "the surroundings of a hit. Search is hybrid (full text plus semantic "
            "similarity) and understands questions in languages other than the video's. "
            "Most transcripts are auto-generated: proper names and technical terms may "
            "be misspelled. For exhaustive research, search several phrasings and raise "
            "the limit."
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
        """List all captured channels with their video counts and capture progress."""
        with connection() as conn:
            return search.channel_stats(conn)

    @server.tool()
    def search_transcripts(
        query: str,
        channel: str | None = None,
        match: Literal["all", "any"] = "all",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Hybrid search over the transcripts; returns the most relevant passages.

        Combines full-text search (exact terms, names) with semantic search (hits by
        meaning, even with mistranscribed words or a query in another language).

        query: question or search terms. For the full-text part: words are stemmed
            (English), "…" searches an exact phrase, word* searches by prefix.
        channel: optionally restrict to one channel (ID, @handle or title).
        match: full-text part – "all" = every term must occur, "any" = one is enough.
        limit: number of hits (at most 50).

        For each hit, text_match tells whether the terms occur literally, and
        semantic_similarity (0–1, null if not among the semantically nearest) how
        close it is in meaning.
        """
        with connection() as conn:
            return search.search_passages(
                conn, embedder, query, channel=channel, match=match, limit=limit
            )

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
