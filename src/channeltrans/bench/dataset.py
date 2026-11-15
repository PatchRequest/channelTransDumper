"""Test cases and relevance judgments.

Judgments refer to time spans of a video rather than passage IDs, so they stay valid
when the database is rebuilt; see :func:`metrics.match_judgment`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Kind = Literal["fact", "sweep", "mention"]
Split = Literal["dev", "test"]

# Grades: 0 = not relevant, 1 = touches the topic, 2 = answers the question.
GRADES = (0, 1, 2)


@dataclass(frozen=True)
class Case:
    id: str
    queries: list[str]
    kind: Kind  # fact: one specific answer; sweep: everything on a topic; mention: a term
    lang: str  # language of the queries
    # Cases on the same topic (e.g. one fact asked in two languages) share a group, and a
    # group lies entirely in one split, so tuning on dev cannot leak into test results.
    group: str
    split: Split
    # mention cases only: spellings that count as a mention, incl. transcription errors
    terms: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.queries:
            raise ValueError(f"Case {self.id} has no queries.")
        if (self.kind == "mention") != bool(self.terms):
            raise ValueError(f"Case {self.id}: terms are required for, and only for, mentions.")


@dataclass(frozen=True)
class Judgment:
    video_id: str
    start_ms: int
    end_ms: int
    grade: int

    def __post_init__(self) -> None:
        if self.grade not in GRADES:
            raise ValueError(f"Invalid grade {self.grade}.")
        if self.end_ms < self.start_ms:
            raise ValueError("A judged span must not end before it starts.")


Judgments = dict[str, list[Judgment]]  # case ID → judged spans


def load_cases(path: Path) -> list[Case]:
    cases = [Case(**raw) for raw in json.loads(path.read_text())]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path} contains duplicate case IDs.")
    split_of: dict[str, str] = {}
    for case in cases:
        if split_of.setdefault(case.group, case.split) != case.split:
            raise ValueError(f"Group {case.group} spans both splits.")
    return cases


def fingerprint(*paths: Path) -> str:
    """Short hash of the given files, recorded with results to make runs reproducible."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:12]


def load_judgments(path: Path) -> Judgments:
    if not path.is_file():
        return {}
    return {
        case_id: [Judgment(**raw) for raw in spans]
        for case_id, spans in json.loads(path.read_text()).items()
    }


def save_judgments(path: Path, judgments: Judgments) -> None:
    data = {
        case_id: [asdict(j) for j in sorted(spans, key=lambda j: (j.video_id, j.start_ms))]
        for case_id, spans in sorted(judgments.items())
    }
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
