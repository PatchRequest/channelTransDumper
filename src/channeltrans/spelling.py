"""Transcription variants of a term, found in the vocabulary of the transcripts.

Automatic captions mangle names: "goshawk" also appears as "gosh hawk", "goss hawk" or
"goshock", "kestrel" as "kestral". This module suggests such spellings – words or word
pairs that are close to the term in spelling and sound – together with how many extra
passages each would add and an example, so the caller (a research agent) can decide
which ones really mean the term. Nothing is added to a search automatically: for short
words, sound-alikes are mostly different words ("hawk" – "hog" – "hook").
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from typing import Any

import jellyfish

from .search import MAX_LIMIT, QueryError, fts_phrase, resolve_channel

# Joined terms shorter than this have too many sound-alikes to suggest anything useful.
MIN_TERM_LENGTH = 5
# Shortest word that may form one half of a two-word variant ("gos hawk").
_MIN_PART_LENGTH = 2


def suggest_spellings(
    conn: sqlite3.Connection, term: str, *, channel: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Spellings of ``term`` in the transcripts that find passages the term itself misses.

    Each suggestion has the spelling, the number of passages it adds (those containing
    it but not the term) and an example with the match in «guillemets». Suggestions are
    sorted by closeness to the term, then by the number of passages added.
    """
    words = [word.lower() for word in re.findall(r"\w+", term)]
    joined = "".join(words)
    if not words:
        raise QueryError(f"Term {term!r} contains no words.")
    if len(joined) < MIN_TERM_LENGTH:
        raise QueryError(
            f"Term {term!r} is too short to suggest variants (at least {MIN_TERM_LENGTH} letters)."
        )
    channel_id = None if channel is None else resolve_channel(conn, channel)
    vocabulary = [
        word for (word,) in conn.execute("SELECT term FROM passages_vocabulary") if word.isalpha()
    ]
    candidates = sorted(
        (distance, spelling)
        for spelling, distance in _candidates(conn, joined, vocabulary)
        if spelling != " ".join(words)
    )
    suggestions = []
    seen: set[frozenset[int]] = set()
    for distance, spelling in candidates:
        added = _added_passages(conn, spelling, term, channel_id)
        # Spellings that stem alike ("gos hawk", "gos hawks") add the same passages; the
        # closest one stands for all of them.
        if added and frozenset(added) not in seen:
            seen.add(frozenset(added))
            suggestions.append(
                {
                    "spelling": spelling,
                    "passages": len(added),
                    "example": next(iter(added.values())),
                    "_distance": distance,
                }
            )
    suggestions.sort(key=lambda s: (s["_distance"], -s["passages"], s["spelling"]))
    return {
        "term": term,
        "suggestions": [
            {key: value for key, value in s.items() if key != "_distance"}
            for s in suggestions[: max(1, min(limit, MAX_LIMIT))]
        ],
    }


def _close(spelling: str, target: str) -> int | None:
    """Edit distance if ``spelling`` plausibly is a mistranscription of ``target``.

    Allowed: a single edit, or up to half of the target's letters if the two also sound
    alike (Metaphone codes at most one edit apart).
    """
    distance = jellyfish.damerau_levenshtein_distance(spelling, target)
    if distance <= 1:
        return distance
    sound_gap = jellyfish.damerau_levenshtein_distance(
        jellyfish.metaphone(spelling), jellyfish.metaphone(target)
    )
    if distance <= len(target) // 2 and sound_gap <= 1:
        return distance
    return None


def _candidates(
    conn: sqlite3.Connection, joined: str, vocabulary: list[str]
) -> Iterable[tuple[str, int]]:
    """Single words and word pairs from the vocabulary close to the joined term."""
    max_length_gap = len(joined) // 2
    for word in vocabulary:
        if word[0] == joined[0] and abs(len(word) - len(joined)) <= max_length_gap:
            distance = _close(word, joined)
            if distance is not None:
                yield word, distance

    # Word pairs: split the term, find words resembling each half, keep the pairs that
    # resemble the whole term and actually occur as a phrase.
    by_initial: dict[str, list[str]] = {}
    for word in vocabulary:
        if len(word) >= _MIN_PART_LENGTH:
            by_initial.setdefault(word[0], []).append(word)
    pairs: set[tuple[str, str]] = set()
    for split in range(_MIN_PART_LENGTH + 1, len(joined) - _MIN_PART_LENGTH):
        left, right = joined[:split], joined[split:]
        lefts = _resembling(left, by_initial.get(left[0], []))
        rights = _resembling(right, by_initial.get(right[0], []))
        pairs.update((a, b) for a in lefts for b in rights)
    for a, b in sorted(pairs):
        distance = _close(a + b, joined)
        if distance is not None and _phrase_occurs(conn, f"{a} {b}"):
            yield f"{a} {b}", distance


def _resembling(part: str, words: list[str]) -> list[str]:
    """Words that may stand for one half of a split term: loosely similar, same initial."""
    allowed = len(part) // 2 + 1
    return [
        word
        for word in words
        if abs(len(word) - len(part)) <= allowed
        and jellyfish.damerau_levenshtein_distance(word, part) <= allowed
    ]


def _phrase_occurs(conn: sqlite3.Connection, phrase: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM passages_words WHERE passages_words MATCH ? LIMIT 1",
            (f'"{phrase}"',),
        ).fetchone()
        is not None
    )


def _added_passages(
    conn: sqlite3.Connection, spelling: str, term: str, channel_id: str | None
) -> dict[int, str]:
    """Passages matching ``spelling`` but not ``term`` (as find_mentions matches them):
    passage ID → snippet with the match in «guillemets»."""
    sql = """SELECT p.id, snippet(passages_fts, 0, '«', '»', '…', 12)
             FROM passages_fts JOIN passages p ON p.id = passages_fts.rowid
             JOIN videos v ON v.id = p.video_id
             WHERE passages_fts MATCH ?"""
    params: list[Any] = [f'"{fts_phrase(spelling)}" NOT "{fts_phrase(term)}"']
    if channel_id is not None:
        sql += " AND v.channel_id = ?"
        params.append(channel_id)
    return dict(conn.execute(sql + " ORDER BY p.id", params).fetchall())
