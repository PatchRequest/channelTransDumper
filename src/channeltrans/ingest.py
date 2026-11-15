"""Synchronisation: list a channel and pull its transcripts into the database bit by bit."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from .embedding import Embedder
from .transcript import Cue, build_passages, cues_from_json, cues_to_json
from .youtube import FetchedVideo, FetchError, VideoNotReady, YouTubeClient

log = logging.getLogger("channeltrans.ingest")


@dataclass(frozen=True)
class SyncOptions:
    limit: int | None = None  # fetch at most this many videos in this run
    delay_s: float = 3.0  # pause between two videos
    max_attempts: int = 5  # a failed video is not retried beyond this
    # Several failures in a row suggest we are being blocked; the run then stops.
    max_consecutive_failures: int = 3


@dataclass
class SyncResult:
    done: int = 0
    no_transcript: int = 0
    failed: int = 0
    not_ready: int = 0
    aborted: bool = False


_EMBED_BATCH = 64


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def discover(conn: sqlite3.Connection, client: YouTubeClient, channel_url: str) -> str:
    """Reconcile the channel's video list with the database and return the channel ID."""
    listing = client.list_channel(channel_url)
    now = _now()
    with conn:
        conn.execute(
            """INSERT INTO channels (id, handle, title, url, added_at, last_discovered_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                   handle = excluded.handle, title = excluded.title, url = excluded.url,
                   last_discovered_at = excluded.last_discovered_at""",
            (listing.channel_id, listing.handle, listing.title, listing.url, now, now),
        )
        conn.executemany(
            """INSERT INTO videos (id, channel_id, title, listing_rank) VALUES (?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                   title = excluded.title, listing_rank = excluded.listing_rank""",
            [
                (video.id, listing.channel_id, video.title, rank)
                for rank, video in enumerate(listing.videos)
            ],
        )
    log.info("%s: %d videos listed", listing.title, len(listing.videos))
    return listing.channel_id


def requeue_missing(conn: sqlite3.Connection, channel_id: str) -> int:
    """Put videos without a transcript back into the queue (captions often appear late)."""
    with conn:
        cursor = conn.execute(
            "UPDATE videos SET status = 'pending' WHERE channel_id = ? AND status = 'no_transcript'",
            (channel_id,),
        )
    return cursor.rowcount


def process_queue(
    conn: sqlite3.Connection,
    client: YouTubeClient,
    embedder: Embedder,
    channel_id: str,
    options: SyncOptions,
) -> SyncResult:
    """Work through a channel's open videos, newest first."""
    # Catch up on vectors an interrupted run or an older database still owes.
    embed_missing(conn, embedder)
    queue = conn.execute(
        """SELECT id, title FROM videos
           WHERE channel_id = ?
             AND (status = 'pending' OR (status = 'failed' AND attempts < ?))
           ORDER BY listing_rank
           LIMIT ?""",
        (channel_id, options.max_attempts, -1 if options.limit is None else options.limit),
    ).fetchall()

    result = SyncResult()
    consecutive_failures = 0
    for index, row in enumerate(queue):
        if index:
            time.sleep(options.delay_s)
        prefix = f"[{index + 1}/{len(queue)}] {row['id']} {row['title']!r}"
        try:
            video = client.fetch_video(row["id"])
        except VideoNotReady:
            result.not_ready += 1
            log.info("%s: live stream is running or scheduled, will retry later", prefix)
            continue
        except FetchError as exc:
            _mark_failed(conn, row["id"], str(exc))
            result.failed += 1
            consecutive_failures += 1
            log.warning("%s: fetch failed: %s", prefix, exc)
            if consecutive_failures >= options.max_consecutive_failures:
                result.aborted = True
                log.error(
                    "%d failures in a row – run aborted. Start it again later.",
                    consecutive_failures,
                )
                break
            continue

        consecutive_failures = 0
        passages = _store(conn, video)
        embed_missing(conn, embedder)
        if video.transcript is None:
            result.no_transcript += 1
            log.info("%s: no transcript available", prefix)
        else:
            result.done += 1
            log.info("%s: %d passages (%s)", prefix, passages, video.transcript.kind)
    return result


def reindex(conn: sqlite3.Connection, embedder: Embedder) -> int:
    """Rebuild all passages and their vectors from the stored transcripts."""
    rows = conn.execute("SELECT video_id, cues FROM transcripts").fetchall()
    with conn:
        for row in rows:
            _replace_passages(conn, row["video_id"], cues_from_json(row["cues"]))
    embed_missing(conn, embedder)
    return len(rows)


def embed_missing(conn: sqlite3.Connection, embedder: Embedder) -> int:
    """Compute the vectors of all passages that do not have one yet."""
    rows = conn.execute(
        """SELECT p.id, p.text, v.title, v.channel_id
           FROM passages p JOIN videos v ON v.id = p.video_id
           WHERE p.id NOT IN (SELECT passage_id FROM passage_vectors)
           ORDER BY p.id"""
    ).fetchall()
    if len(rows) > _EMBED_BATCH:
        log.info("Computing vectors for %d passages …", len(rows))
    for start in range(0, len(rows), _EMBED_BATCH):
        batch = rows[start : start + _EMBED_BATCH]
        vectors = embedder.embed_documents([(row["title"], row["text"]) for row in batch])
        with conn:  # stored per batch so an interruption loses little work
            conn.executemany(
                "INSERT INTO passage_vectors (passage_id, channel_id, embedding) VALUES (?, ?, ?)",
                [(row["id"], row["channel_id"], vector) for row, vector in zip(batch, vectors)],
            )
    return len(rows)


def _store(conn: sqlite3.Connection, video: FetchedVideo) -> int:
    transcript = video.transcript
    # A transcript without text (e.g. music only) counts as not available.
    has_text = transcript is not None and bool(transcript.cues)
    passages = 0
    with conn:
        conn.execute(
            """UPDATE videos SET title = ?, upload_date = ?, duration_s = ?, description = ?,
                   status = ?, last_error = NULL, processed_at = ?
               WHERE id = ?""",
            (
                video.title,
                video.upload_date,
                video.duration_s,
                video.description,
                "done" if has_text else "no_transcript",
                _now(),
                video.id,
            ),
        )
        if has_text:
            conn.execute(
                """INSERT INTO transcripts (video_id, language, kind, cues) VALUES (?, ?, ?, ?)
                   ON CONFLICT (video_id) DO UPDATE SET
                       language = excluded.language, kind = excluded.kind, cues = excluded.cues""",
                (video.id, transcript.language, transcript.kind, cues_to_json(transcript.cues)),
            )
            passages = _replace_passages(conn, video.id, transcript.cues)
    return passages


def _replace_passages(conn: sqlite3.Connection, video_id: str, cues: list[Cue]) -> int:
    passages = build_passages(cues)
    conn.execute("DELETE FROM passages WHERE video_id = ?", (video_id,))
    conn.executemany(
        "INSERT INTO passages (video_id, seq, start_ms, end_ms, text) VALUES (?, ?, ?, ?, ?)",
        [(video_id, seq, p.start_ms, p.end_ms, p.text) for seq, p in enumerate(passages)],
    )
    return len(passages)


def _mark_failed(conn: sqlite3.Connection, video_id: str, error: str) -> None:
    with conn:
        conn.execute(
            """UPDATE videos SET status = 'failed', attempts = attempts + 1,
                   last_error = ?, processed_at = ?
               WHERE id = ?""",
            (error, _now(), video_id),
        )
