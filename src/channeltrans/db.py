"""SQLite schema and connection setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from .embedding import DIMENSIONS

_SCHEMA_V1 = """
CREATE TABLE channels (
    id                 TEXT PRIMARY KEY,          -- YouTube channel ID (UC…)
    handle             TEXT,                      -- @handle, if the channel has one
    title              TEXT NOT NULL,
    url                TEXT NOT NULL,
    added_at           TEXT NOT NULL,
    last_discovered_at TEXT NOT NULL
);

CREATE TABLE videos (
    id            TEXT PRIMARY KEY,               -- YouTube video ID
    channel_id    TEXT NOT NULL REFERENCES channels(id),
    title         TEXT NOT NULL,
    -- Position in the channel listing (0 = top = newest video).
    listing_rank  INTEGER NOT NULL,
    upload_date   TEXT,                           -- ISO date, only known after fetching
    duration_s    INTEGER,
    description   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'done', 'no_transcript', 'failed')),
    attempts      INTEGER NOT NULL DEFAULT 0,     -- number of failed fetches
    last_error    TEXT,
    processed_at  TEXT
);
CREATE INDEX videos_queue ON videos (channel_id, status, listing_rank);

-- Unmodified transcript as timestamped lines; the source the passages are built from.
CREATE TABLE transcripts (
    video_id  TEXT PRIMARY KEY REFERENCES videos(id),
    language  TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('manual', 'auto')),
    cues      TEXT NOT NULL                       -- JSON: [[start_ms, end_ms, text], …]
);

-- Searchable sections of a transcript.
CREATE TABLE passages (
    id        INTEGER PRIMARY KEY,
    video_id  TEXT NOT NULL REFERENCES videos(id),
    seq       INTEGER NOT NULL,                   -- running number within the video, from 0
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER NOT NULL,
    text      TEXT NOT NULL,
    UNIQUE (video_id, seq)
);

CREATE VIRTUAL TABLE passages_fts USING fts5(
    text,
    content = 'passages',
    content_rowid = 'id',
    tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER passages_fts_insert AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER passages_fts_delete AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts (passages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

# One vector per passage for semantic search (model: embedding.MODEL).
_SCHEMA_V2 = f"""
CREATE VIRTUAL TABLE passage_vectors USING vec0(
    passage_id INTEGER PRIMARY KEY,
    channel_id TEXT PARTITION KEY,
    embedding  FLOAT[{DIMENSIONS}] distance_metric=cosine
);

CREATE TRIGGER passages_vectors_delete AFTER DELETE ON passages BEGIN
    DELETE FROM passage_vectors WHERE passage_id = old.id;
END;
"""

# Unstemmed word index and its vocabulary, for finding transcription variants of a term
# (see spelling.py). passages_fts stems words, so its vocabulary cannot serve this.
_SCHEMA_V3 = """
CREATE VIRTUAL TABLE passages_words USING fts5(
    text,
    content = 'passages',
    content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
INSERT INTO passages_words (passages_words) VALUES ('rebuild');

CREATE TRIGGER passages_words_insert AFTER INSERT ON passages BEGIN
    INSERT INTO passages_words (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER passages_words_delete AFTER DELETE ON passages BEGIN
    INSERT INTO passages_words (passages_words, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE VIRTUAL TABLE passages_vocabulary USING fts5vocab(passages_words, 'row');
"""

# Schema steps in order; the schema version is the number of steps applied.
_SCHEMA_STEPS = [_SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3]
SCHEMA_VERSION = len(_SCHEMA_STEPS)


class DatabaseError(Exception):
    """The database is missing or does not match this version of the program."""


def connect(path: Path) -> sqlite3.Connection:
    """Open the database for writing, creating or upgrading it as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    _configure(conn)
    conn.execute("PRAGMA journal_mode = WAL")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0 and conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
        conn.close()
        raise DatabaseError(f"{path} is not a channeltrans database.")
    if version > SCHEMA_VERSION:
        _check_version(conn, path, version)
    for step in range(version, SCHEMA_VERSION):
        conn.executescript(
            f"BEGIN;{_SCHEMA_STEPS[step]}PRAGMA user_version = {step + 1};COMMIT;"
        )
    return conn


def connect_read_only(path: Path) -> sqlite3.Connection:
    """Open an existing database read-only."""
    if not path.is_file():
        raise DatabaseError(
            f"Database {path} does not exist. Run `channeltrans sync <channel-url>` first."
        )
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    _configure(conn)
    _check_version(conn, path, conn.execute("PRAGMA user_version").fetchone()[0])
    return conn


def _configure(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")


def _check_version(conn: sqlite3.Connection, path: Path, version: int) -> None:
    if version != SCHEMA_VERSION:
        conn.close()
        raise DatabaseError(
            f"{path} has schema version {version}, expected {SCHEMA_VERSION}. "
            "Running `channeltrans sync` or `channeltrans reindex` upgrades older databases."
        )
