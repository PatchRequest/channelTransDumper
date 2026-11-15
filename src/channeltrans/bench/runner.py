"""Running variants over cases: candidate pools for judging and metric tables."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

from ..embedding import Embedder
from . import metrics
from .dataset import Case, Judgment, Judgments
from .metrics import Retrieved
from .variants import VARIANTS, applies


# Hits requested per variant and case: four pages of 50.
DEPTH = 200


@dataclass(frozen=True)
class Row:
    variant: str
    group: str
    cases: int
    values: dict[str, float]


def retrieve(conn: sqlite3.Connection, passage_ids: list[int]) -> list[Retrieved]:
    if not passage_ids:
        return []
    rows = conn.execute(
        f"""SELECT id, video_id, start_ms, end_ms, text FROM passages
            WHERE id IN ({",".join("?" * len(passage_ids))})""",
        passage_ids,
    )
    by_id = {row["id"]: Retrieved(*row) for row in rows}
    return [by_id[passage_id] for passage_id in passage_ids]


def run_variant(
    conn: sqlite3.Connection, embedder: Embedder, variant: str, case: Case, depth: int
) -> list[Retrieved]:
    return retrieve(conn, VARIANTS[variant](conn, embedder, case, depth))


def build_pool(
    conn: sqlite3.Connection,
    embedder: Embedder,
    cases: list[Case],
    judgments: Judgments,
    variants: list[str],
    depth: int,
) -> list[dict[str, Any]]:
    """Unjudged passages that any of the variants returns in its first ``depth`` hits."""
    pool = []
    for case in cases:
        if case.kind == "mention":
            continue  # mentions are measured objectively, without judgments
        known = judgments.get(case.id, [])
        candidates: dict[str, dict[str, Any]] = {}
        for variant in (v for v in variants if applies(v, case.kind)):
            for passage in run_variant(conn, embedder, variant, case, depth):
                key = span_key(passage)
                if key not in candidates and metrics.match_judgment(passage, known) is None:
                    title = conn.execute(
                        "SELECT title FROM videos WHERE id = ?", (passage.video_id,)
                    ).fetchone()[0]
                    candidates[key] = {"key": key, "video_title": title, "text": passage.text}
        if candidates:
            pool.append(
                {
                    "case_id": case.id,
                    "kind": case.kind,
                    "queries": case.queries,
                    "candidates": list(candidates.values()),
                }
            )
    return pool


def merge_grades(judgments: Judgments, grades: dict[str, dict[str, int]]) -> int:
    """Adds graded pool entries (case ID → span key → grade); returns the number added."""
    added = 0
    for case_id, by_key in grades.items():
        spans = judgments.setdefault(case_id, [])
        for key, grade in by_key.items():
            video_id, start_ms, end_ms = parse_span_key(key)
            judgment = Judgment(video_id, start_ms, end_ms, grade)
            if any((j.video_id, j.start_ms, j.end_ms) == (video_id, start_ms, end_ms) for j in spans):
                raise ValueError(f"Span {key} of case {case_id} is already judged.")
            spans.append(judgment)
            added += 1
    return added


@dataclass(frozen=True)
class Evaluation:
    rows: list[Row]
    unjudged_cases: list[str]  # fact/sweep cases skipped for lack of a relevant judgment


def evaluate(
    conn: sqlite3.Connection,
    embedder: Embedder,
    cases: list[Case],
    judgments: Judgments,
    variants: list[str],
) -> Evaluation:
    """Metrics per variant and case group (kind, and kind/language).

    Variants are asked for up to ``DEPTH`` hits, so completeness beyond the first 50
    is measurable once a variant can deliver it (e.g. through paging).
    """
    scored = [
        case
        for case in cases
        if case.kind == "mention" or any(j.grade > 0 for j in judgments.get(case.id, []))
    ]
    unjudged_cases = [case.id for case in cases if case not in scored]
    mention_truth = {case.id: _mentions(conn, case) for case in scored if case.kind == "mention"}
    rows = []
    for variant in variants:
        per_group: dict[str, list[dict[str, float]]] = defaultdict(list)
        for case in scored:
            if not applies(variant, case.kind):
                continue
            ranked = run_variant(conn, embedder, variant, case, DEPTH)
            if case.kind == "mention":
                truth = mention_truth[case.id]
                values = {
                    f"mention_R@{k}": len({p.passage_id for p in ranked[:k]} & truth) / len(truth)
                    if truth
                    else 0.0
                    for k in (50, DEPTH)
                }
            else:
                judged = judgments[case.id]
                values = {
                    "nDCG@10": metrics.ndcg(ranked, judged, 10),
                    "R@10": metrics.recall(ranked, judged, 10),
                    "R@50": metrics.recall(ranked, judged, 50),
                    f"R@{DEPTH}": metrics.recall(ranked, judged, DEPTH),
                    "unjudged@10": metrics.unjudged(ranked, judged, 10),
                }
            per_group[f"{case.kind}/{case.lang}"].append(values)
            per_group[case.kind].append(values)
        for group in sorted(per_group):
            results = per_group[group]
            rows.append(
                Row(variant, group, len(results), {m: mean(r[m] for r in results) for m in results[0]})
            )
    return Evaluation(rows, unjudged_cases)


def format_table(rows: list[Row]) -> str:
    columns = [
        "nDCG@10", "R@10", "R@50", f"R@{DEPTH}", "unjudged@10", "mention_R@50", f"mention_R@{DEPTH}",
    ]
    lines = [
        "| variant | group | cases | " + " | ".join(columns) + " |",
        "|---|---|---|" + "---|" * len(columns),
    ]
    for row in rows:
        cells = [f"{row.values[c]:.3f}" if c in row.values else "" for c in columns]
        lines.append(f"| {row.variant} | {row.group} | {row.cases} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def span_key(passage: Retrieved) -> str:
    return f"{passage.video_id}|{passage.start_ms}|{passage.end_ms}"


def parse_span_key(key: str) -> tuple[str, int, int]:
    video_id, start_ms, end_ms = key.rsplit("|", 2)
    return video_id, int(start_ms), int(end_ms)


def _mentions(conn: sqlite3.Connection, case: Case) -> set[int]:
    pattern = metrics.mention_pattern(case.terms)
    return {
        passage_id
        for passage_id, text in conn.execute("SELECT id, text FROM passages")
        if pattern.search(text)
    }
