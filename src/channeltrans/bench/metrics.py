"""Retrieval metrics over judged time spans."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .dataset import Judgment

# A retrieved passage counts as a judged span if they overlap by at least this share
# of the shorter of the two. With unchanged chunking, spans and passages coincide.
MIN_OVERLAP = 0.5


@dataclass(frozen=True)
class Retrieved:
    passage_id: int
    video_id: str
    start_ms: int
    end_ms: int
    text: str


def match_judgment(passage: Retrieved, judgments: list[Judgment]) -> Judgment | None:
    """The judged span a passage corresponds to, or None if it is unjudged."""
    best, best_share = None, 0.0
    for judgment in judgments:
        if judgment.video_id != passage.video_id:
            continue
        overlap = min(passage.end_ms, judgment.end_ms) - max(passage.start_ms, judgment.start_ms)
        shorter = min(passage.end_ms - passage.start_ms, judgment.end_ms - judgment.start_ms)
        share = overlap / shorter if shorter > 0 else float(overlap >= 0)
        if share >= MIN_OVERLAP and share > best_share:
            best, best_share = judgment, share
    return best


def ndcg(ranked: list[Retrieved], judgments: list[Judgment], k: int) -> float:
    """Normalised discounted cumulative gain; unjudged passages count as grade 0.

    A judged span counts once, even if several retrieved passages match it.
    """
    seen: set[Judgment] = set()
    gains = []
    for passage in ranked[:k]:
        judgment = match_judgment(passage, judgments)
        if judgment is None or judgment in seen:
            gains.append(0)
        else:
            seen.add(judgment)
            gains.append(judgment.grade)
    ideal = sorted((j.grade for j in judgments), reverse=True)[:k]
    ideal_dcg = _dcg(ideal)
    return _dcg(gains) / ideal_dcg if ideal_dcg else 0.0


def recall(ranked: list[Retrieved], judgments: list[Judgment], k: int, min_grade: int = 1) -> float:
    """Share of relevant judged spans found among the first ``k`` passages."""
    relevant = {j for j in judgments if j.grade >= min_grade}
    if not relevant:
        return 0.0
    found = {match_judgment(p, judgments) for p in ranked[:k]}
    return len(relevant & found) / len(relevant)


def unjudged(ranked: list[Retrieved], judgments: list[Judgment], k: int) -> float:
    """Share of the first ``k`` passages without a judgment (high values make scores unreliable)."""
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(match_judgment(p, judgments) is None for p in top) / len(top)


def mention_pattern(terms: list[str]) -> re.Pattern[str]:
    """Matches any of the terms as whole words, case-insensitively, with flexible spacing."""
    alternatives = (r"\s+".join(map(re.escape, term.split())) for term in terms)
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


def _dcg(gains: list[int]) -> float:
    return sum((2**gain - 1) / math.log2(rank + 2) for rank, gain in enumerate(gains))
