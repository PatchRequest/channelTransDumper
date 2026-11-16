"""Passages that repeat speech from another video (compilations, re-uploads, clips).

Two passages of different videos are duplicates when at least half of the shorter one's
word 5-grams also occur in the other – i.e. the same recording was reused, not merely
the same topic discussed. Embedding similarity alone cannot tell these apart: two
different explanations of the same thing can be as close as a reused clip. Candidates
come from the nearest neighbours in vector space; the text decides.

Search folds duplicates into the best-ranked passage of their group (see
``search.search_passages``), so a page of hits shows more distinct statements.
"""

from __future__ import annotations

import re
import sqlite3

# Share of the shorter passage's 5-grams that must recur for a duplicate.
MIN_OVERLAP = 0.5
# Nearest neighbours checked per passage.
_NEIGHBOURS = 10
_N = 5
_BATCH = 256


def shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i : i + _N]) for i in range(len(words) - _N + 1)}


def overlap(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def link_missing(conn: sqlite3.Connection) -> int:
    """Find the duplicates of every embedded passage not yet scanned; returns the count.

    Links are stored in both directions, so a passage scanned before its duplicate
    existed is linked when the duplicate is scanned.
    """
    pending = [
        row[0]
        for row in conn.execute(
            """SELECT passage_id FROM passage_vectors
               WHERE passage_id NOT IN (SELECT passage_id FROM duplicate_scans)
               ORDER BY passage_id"""
        )
    ]
    for start in range(0, len(pending), _BATCH):
        batch = pending[start : start + _BATCH]
        links = [pair for passage_id in batch for pair in _find(conn, passage_id)]
        with conn:  # stored per batch so an interruption loses little work
            conn.executemany(
                "INSERT OR IGNORE INTO passage_duplicates (passage_id, duplicate_id) VALUES (?, ?)",
                links,
            )
            conn.executemany(
                "INSERT INTO duplicate_scans (passage_id) VALUES (?)", [(p,) for p in batch]
            )
    return len(pending)


def _find(conn: sqlite3.Connection, passage_id: int) -> list[tuple[int, int]]:
    """Duplicate links of one passage, in both directions."""
    video_id, text, embedding = conn.execute(
        """SELECT p.video_id, p.text, v.embedding
           FROM passages p JOIN passage_vectors v ON v.passage_id = p.id
           WHERE p.id = ?""",
        (passage_id,),
    ).fetchone()
    own = shingles(text)
    neighbours = conn.execute(
        """SELECT p.id, p.text
           FROM (SELECT passage_id FROM passage_vectors WHERE embedding MATCH ? AND k = ?) n
           JOIN passages p ON p.id = n.passage_id
           WHERE p.video_id != ?""",
        (embedding, _NEIGHBOURS + 1, video_id),
    ).fetchall()
    return [
        pair
        for other, other_text in neighbours
        if overlap(own, shingles(other_text)) >= MIN_OVERLAP
        for pair in ((passage_id, other), (other, passage_id))
    ]
