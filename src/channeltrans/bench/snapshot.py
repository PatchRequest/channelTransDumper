"""Consistent, frozen copies of the database, so measurements are comparable."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import duplicates
from ..db import SCHEMA_VERSION, connect, connect_read_only


class SnapshotError(Exception):
    """The snapshot could not be created or is incomplete."""


def manifest_path(snapshot: Path) -> Path:
    return snapshot.with_suffix(".json")


def create_snapshot(source: Path, destination: Path) -> dict[str, Any]:
    """Copy ``source`` with SQLite's backup API (safe while a sync writes) and verify it.

    A plain file copy is not safe: the database runs in WAL mode, so recent commits
    may only exist in the ``-wal`` file. The copy is upgraded to the current schema, so
    an older snapshot can be carried forward by snapshotting it again; upgrades only add
    derived structures (indexes), never change passages.
    """
    if destination.exists():
        raise SnapshotError(f"{destination} already exists; snapshots are never overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    with closing(connect(destination)) as dst:  # applies pending schema steps
        # Derived links a newer schema adds; computed from the copied vectors and text.
        duplicates.link_missing(dst)
        dst.execute("PRAGMA journal_mode = DELETE")

    manifest = describe(destination) | {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": str(source),
        "schema_version": SCHEMA_VERSION,
    }
    if manifest["passages"] != manifest["vectors"]:
        destination.unlink()
        raise SnapshotError(
            f"Snapshot caught a sync mid-embedding ({manifest['passages']} passages, "
            f"{manifest['vectors']} vectors); try again in a moment."
        )
    manifest_path(destination).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def describe(snapshot: Path) -> dict[str, Any]:
    """Counts that identify the state of a database."""
    with closing(connect_read_only(snapshot)) as conn:
        counts = conn.execute(
            """SELECT (SELECT count(*) FROM passages) AS passages,
                      (SELECT count(*) FROM passage_vectors) AS vectors,
                      (SELECT count(*) FROM passage_duplicates) / 2 AS duplicate_pairs,
                      (SELECT count(*) FROM transcripts) AS transcripts"""
        ).fetchone()
        channels = {
            row["name"]: row["done"]
            for row in conn.execute(
                """SELECT coalesce(c.handle, c.id) AS name, sum(v.status = 'done') AS done
                   FROM channels c JOIN videos v ON v.channel_id = c.id GROUP BY c.id"""
            )
        }
    return dict(counts) | {"transcripts_per_channel": channels}


def load_manifest(snapshot: Path) -> dict[str, Any]:
    path = manifest_path(snapshot)
    if not path.is_file():
        raise SnapshotError(f"{snapshot} has no manifest; create it with `snapshot`.")
    return json.loads(path.read_text())
