"""Relevance judging rounds: split a pool into judge packages and check the grades.

A judge (an LLM agent or a person) grades one package per run, following
``benchmark/judge-prompt.md``. To measure rather than assume the judges' reliability,
packages carry hidden controls – a known answer of the case (expected grade 2) and a
known answer of another case (expected at most 1) – and about 5 % of each package's
candidates are graded a second time in the next package. Cases asking the same
question in two languages (``Case.same_as``) are judged once and graded for both.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import metrics
from .dataset import Case, Judgments
from .metrics import Retrieved
from .runner import parse_span_key

PACKAGE_SIZE = 220  # candidates per judge run
OVERLAP = 0.05


@dataclass
class Packed:
    packages: list[list[dict[str, Any]]]  # per package: cases with their candidates
    manifest: dict[str, Any]


def pack(
    conn: sqlite3.Connection,
    pool: list[dict[str, Any]],
    cases: list[Case],
    judgments: Judgments,
    *,
    size: int = PACKAGE_SIZE,
    seed: int = 0,
) -> Packed:
    rng = random.Random(seed)
    by_id = {case.id: case for case in cases}
    target = {case.id: case.same_as or case.id for case in cases}

    # One entry per question: twins are merged into the case they point to.
    entries: dict[str, dict[str, Any]] = {}
    for item in pool:
        case = by_id[target[item["case_id"]]]
        entry = entries.setdefault(
            case.id, {"case_id": case.id, "kind": case.kind, "queries": [], "candidates": {}}
        )
        for candidate in item["candidates"]:
            entry["candidates"].setdefault(candidate["key"], candidate)
    for entry in entries.values():
        entry["queries"] = [
            query
            for case in cases
            if target[case.id] == entry["case_id"]
            for query in case.queries
        ]

    # Whole cases per package, largest first, each into the first package with room.
    packages: list[list[dict[str, Any]]] = []
    for entry in sorted(entries.values(), key=lambda e: (-len(e["candidates"]), e["case_id"])):
        item = entry | {"candidates": list(entry["candidates"].values())}
        for package in packages:
            if sum(len(c["candidates"]) for c in package) + len(item["candidates"]) <= size:
                package.append(item)
                break
        else:
            packages.append([item])

    answers = {
        case_id: [j for j in spans if j.grade == 2]
        for case_id, spans in judgments.items()
        if any(j.grade == 2 for j in spans)
    }
    controls: list[dict[str, Any]] = []
    for number, package in enumerate(packages):
        facts = [c for c in package if c["kind"] == "fact"]
        known = [c for c in facts if c["case_id"] in answers]
        if known:
            case = rng.choice(known)
            control = _add_control(conn, rng, number, case, case["case_id"], answers, "2")
            if control:
                controls.append(control)
        if facts:
            case = rng.choice(facts)
            sources = sorted(cid for cid in answers if target.get(cid, cid) != case["case_id"])
            if sources:
                control = _add_control(conn, rng, number, case, rng.choice(sources), answers, "<=1")
                if control:
                    controls.append(control)

    overlap: list[dict[str, Any]] = []
    if len(packages) > 1:
        originals = [[dict(c) for c in package] for package in packages]
        control_keys = {(c["package"], c["key"]) for c in controls}
        for number, package in enumerate(originals):
            follower = (number + 1) % len(packages)
            for case in package:
                eligible = [c for c in case["candidates"] if (number, c["key"]) not in control_keys]
                picks = rng.sample(eligible, min(len(eligible), max(1, round(len(eligible) * OVERLAP))))
                packages[follower].append(case | {"candidates": picks})
                overlap += [
                    {"case_id": case["case_id"], "key": p["key"], "packages": [number, follower]}
                    for p in picks
                ]

    final = []
    for package in packages:
        merged: dict[str, dict[str, Any]] = {}
        for case in package:
            entry = merged.setdefault(case["case_id"], case | {"candidates": []})
            seen = {c["key"] for c in entry["candidates"]}
            entry["candidates"] += [c for c in case["candidates"] if c["key"] not in seen]
        for entry in merged.values():
            rng.shuffle(entry["candidates"])
        final.append(list(merged.values()))
    return Packed(final, {"same_as": {c.id: c.same_as for c in cases if c.same_as},
                          "controls": controls, "overlap": overlap})


def _add_control(
    conn: sqlite3.Connection,
    rng: random.Random,
    number: int,
    case: dict[str, Any],
    source: str,
    answers: Judgments,
    expect: str,
) -> dict[str, Any] | None:
    span = rng.choice(answers[source])
    row = conn.execute(
        """SELECT p.start_ms, p.end_ms, p.text, v.title FROM passages p
           JOIN videos v ON v.id = p.video_id
           WHERE p.video_id = ? AND p.end_ms > ? AND p.start_ms < ? ORDER BY p.start_ms""",
        (span.video_id, span.start_ms, span.end_ms),
    ).fetchone()
    key = f"{span.video_id}|{row[0]}|{row[1]}"
    if any(c["key"] == key for c in case["candidates"]):
        return None
    case["candidates"].append({"key": key, "video_title": row[3], "text": row[2]})
    return {"package": number, "case_id": case["case_id"], "key": key, "expect": expect, "from": source}


@dataclass
class Collected:
    grades: dict[str, dict[str, int]]  # importable: case ID → span key → grade
    failed_controls: list[dict[str, Any]] = field(default_factory=list)
    controls: int = 0
    agreement: tuple[int, int] = (0, 0)  # equal grades, overlap pairs
    two_apart: int = 0  # overlap pairs graded 0 by one judge and 2 by the other


def collect(
    packages: list[list[dict[str, Any]]],
    grades: list[dict[str, dict[str, int]]],
    manifest: dict[str, Any],
    pool: list[dict[str, Any]],
    judgments: Judgments,
) -> Collected:
    """Check the judges' grades against controls and overlap; merge them for import.

    Where two judges disagree, the lower grade is kept (the rubric's rule for doubt).
    Controls and spans judged before are left out of the import.
    """
    for number, (package, graded) in enumerate(zip(packages, grades, strict=True)):
        for case in package:
            keys = {c["key"] for c in case["candidates"]}
            given = graded.get(case["case_id"], {})
            if set(given) != keys or any(g not in (0, 1, 2) for g in given.values()):
                raise ValueError(
                    f"Package {number}, case {case['case_id']}: grades do not match the candidates."
                )

    failed = []
    for control in manifest["controls"]:
        grade = grades[control["package"]][control["case_id"]][control["key"]]
        if not (grade == 2 if control["expect"] == "2" else grade <= 1):
            failed.append(control | {"grade": grade})
    pairs = [
        (grades[a][o["case_id"]][o["key"]], grades[b][o["case_id"]][o["key"]])
        for o in manifest["overlap"]
        for a, b in [o["packages"]]
    ]

    combined: dict[str, dict[str, int]] = {}
    for graded in grades:
        for case_id, by_key in graded.items():
            target = combined.setdefault(case_id, {})
            for key, grade in by_key.items():
                target[key] = min(grade, target.get(key, grade))

    result: dict[str, dict[str, int]] = {}
    for item in pool:
        case_id = item["case_id"]
        source = combined[manifest["same_as"].get(case_id, case_id)]
        known = judgments.get(case_id, [])
        for candidate in item["candidates"]:
            video_id, start_ms, end_ms = parse_span_key(candidate["key"])
            passage = Retrieved(0, video_id, start_ms, end_ms, "")
            if metrics.match_judgment(passage, known) is None:
                result.setdefault(case_id, {})[candidate["key"]] = source[candidate["key"]]
    return Collected(
        grades=result,
        failed_controls=failed,
        controls=len(manifest["controls"]),
        agreement=(sum(a == b for a, b in pairs), len(pairs)),
        two_apart=sum({a, b} == {0, 2} for a, b in pairs),
    )
