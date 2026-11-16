from __future__ import annotations

import json
import math

import pytest
from fakes import EMBEDDER, OPTIONS, FakeClient, video

from channeltrans import ingest
from channeltrans.bench import dataset, metrics, runner, snapshot
from channeltrans.bench.dataset import Case, Judgment
from channeltrans.bench.metrics import Retrieved
from channeltrans.db import connect, connect_read_only


def _p(video_id: str, start_s: float, end_s: float, pid: int = 0) -> Retrieved:
    return Retrieved(pid, video_id, int(start_s * 1000), int(end_s * 1000), "")


def _j(video_id: str, start_s: float, end_s: float, grade: int) -> Judgment:
    return Judgment(video_id, int(start_s * 1000), int(end_s * 1000), grade)


# --- Matching passages to judged spans ---------------------------------------------------


def test_match_requires_same_video_and_enough_overlap():
    judged = [_j("a", 296.48, 357.2, 2)]
    # The bug that once reported 3 % instead of 71 %: second-truncated start times.
    assert metrics.match_judgment(_p("a", 296.48, 357.2), judged) == judged[0]
    assert metrics.match_judgment(_p("a", 300, 350), judged) == judged[0]  # rechunked inside
    assert metrics.match_judgment(_p("a", 340, 400), judged) is None  # overlap below half
    assert metrics.match_judgment(_p("b", 296.48, 357.2), judged) is None


def test_match_picks_the_best_overlapping_span():
    judged = [_j("a", 0, 60, 0), _j("a", 60, 120, 2)]
    assert metrics.match_judgment(_p("a", 50, 115), judged) == judged[1]


# --- Metrics ----------------------------------------------------------------------------


def test_ndcg_counts_each_judged_span_once_and_unjudged_as_zero():
    judged = [_j("a", 0, 60, 2), _j("b", 0, 60, 1), _j("c", 0, 60, 0)]
    perfect = [_p("a", 0, 60), _p("b", 0, 60)]
    assert metrics.ndcg(perfect, judged, 10) == pytest.approx(1.0)
    duplicated = [_p("a", 0, 60), _p("a", 0, 60), _p("b", 0, 60)]
    expected = (3 + 1 / math.log2(4)) / (3 + 1 / math.log2(3))
    assert metrics.ndcg(duplicated, judged, 10) == pytest.approx(expected)
    assert metrics.ndcg([_p("x", 0, 60)], judged, 10) == 0.0


def test_recall_and_unjudged():
    judged = [_j("a", 0, 60, 2), _j("b", 0, 60, 1), _j("c", 0, 60, 0)]
    ranked = [_p("x", 0, 60), _p("c", 0, 60), _p("b", 0, 60), _p("a", 0, 60)]
    assert metrics.recall(ranked, judged, 3) == 0.5
    assert metrics.recall(ranked, judged, 4) == 1.0
    assert metrics.recall(ranked, judged, 4, min_grade=2) == 1.0
    assert metrics.unjudged(ranked, judged, 2) == 0.5


def test_mention_pattern_matches_whole_words_and_variants():
    pattern = metrics.mention_pattern(["harris hawk", "harris hog"])
    assert pattern.search("my Harris\nhog Peggy")
    assert pattern.search("a harris hawk.")
    assert not pattern.search("harrishawk")
    assert not pattern.search("harris hogs")


# --- Dataset ----------------------------------------------------------------------------


def test_cases_validate_terms_and_ids(tmp_path):
    with pytest.raises(ValueError):
        Case("m", ["harris"], "mention", "en", "g", "dev")
    with pytest.raises(ValueError):
        Case("f", ["q"], "fact", "en", "g", "dev", terms=["x"])
    path = tmp_path / "cases.json"
    case = {"id": "a", "queries": ["q"], "kind": "fact", "lang": "en", "group": "g", "split": "dev"}
    path.write_text(json.dumps([case, case]))
    with pytest.raises(ValueError):
        dataset.load_cases(path)  # duplicate IDs
    path.write_text(json.dumps([case, case | {"id": "b", "split": "test"}]))
    with pytest.raises(ValueError):
        dataset.load_cases(path)  # one group in both splits


def test_judgments_round_trip(tmp_path):
    path = tmp_path / "j.json"
    judgments = {"c": [_j("b", 0, 60, 1), _j("a", 5, 9, 2)]}
    dataset.save_judgments(path, judgments)
    assert dataset.load_judgments(path) == {"c": [_j("a", 5, 9, 2), _j("b", 0, 60, 1)]}
    assert dataset.load_judgments(tmp_path / "missing.json") == {}


# --- Snapshot and runner ----------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "live.db"
    conn = connect(path)
    client = FakeClient(
        {
            "a": video("a", "Hooding calms the falcon before the flight."),
            "b": video("b", "My harris hog Peggy hunts rabbits.", "Cold weather is hard."),
        }
    )
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    conn.close()
    return path


def test_snapshot_is_consistent_and_never_overwritten(db, tmp_path):
    target = tmp_path / "snap.db"
    manifest = snapshot.create_snapshot(db, target)
    assert manifest["passages"] == manifest["vectors"] == 2
    assert snapshot.load_manifest(target)["transcripts_per_channel"] == {"@falconer": 2}
    with pytest.raises(snapshot.SnapshotError):
        snapshot.create_snapshot(db, target)


def test_snapshot_rejects_a_sync_caught_mid_embedding(db, tmp_path):
    conn = connect(db)
    conn.execute("DELETE FROM passage_vectors WHERE passage_id = 1")
    conn.commit()
    conn.close()
    with pytest.raises(snapshot.SnapshotError):
        snapshot.create_snapshot(db, tmp_path / "snap.db")
    assert not (tmp_path / "snap.db").exists()


def test_pool_merge_and_evaluate(db, tmp_path):
    snap = tmp_path / "snap.db"
    snapshot.create_snapshot(db, snap)
    cases = [
        Case("hood", ["hooding falcon"], "fact", "en", "hood", "dev"),
        Case("cold", ["cold weather"], "fact", "en", "cold", "dev"),
        Case("harris", ["harris hawk"], "mention", "en", "harris", "dev",
             terms=["harris hawk", "harris hog"]),
    ]
    conn = connect_read_only(snap)
    judgments: dataset.Judgments = {}
    pool = runner.build_pool(conn, EMBEDDER, cases, judgments, ["hybrid", "fts_any"], 5)
    assert [entry["case_id"] for entry in pool] == ["hood", "cold"]  # mentions need no judging
    pool = pool[:1]
    keys = [c["key"] for c in pool[0]["candidates"]]
    hood_key = next(c["key"] for c in pool[0]["candidates"] if "Hooding" in c["text"])
    grades = {"hood": {key: 2 if key == hood_key else 0 for key in keys}}
    assert runner.merge_grades(judgments, grades) == len(keys)
    with pytest.raises(ValueError):
        runner.merge_grades(judgments, grades)  # judging a span twice is an error
    assert [e["case_id"] for e in runner.build_pool(conn, EMBEDDER, cases, judgments, ["hybrid"], 5)] == ["cold"]

    evaluation = runner.evaluate(conn, EMBEDDER, cases, judgments, ["hybrid"])
    assert evaluation.unjudged_cases == ["cold"]
    rows = evaluation.rows
    by_group = {row.group: row.values for row in rows}
    assert by_group["fact"]["nDCG@10"] == pytest.approx(1.0)
    assert by_group["fact"]["unjudged@10"] == 0.0
    assert by_group["mention"]["mention_R@50"] == 1.0
    assert "| hybrid | fact | 1 |" in runner.format_table(rows)
    conn.close()


def test_judging_round_packs_controls_and_merges_twins(db, tmp_path):
    from channeltrans.bench import judging

    snap = tmp_path / "snap.db"
    snapshot.create_snapshot(db, snap)
    conn = connect_read_only(snap)
    cases = [
        Case("hood", ["hooding falcon"], "fact", "en", "hood", "dev"),
        Case("haube", ["Haube Falke"], "fact", "de", "hood", "dev", same_as="hood"),
        Case("cold", ["cold weather"], "fact", "en", "cold", "dev"),
    ]
    rows = conn.execute("SELECT video_id, start_ms, end_ms FROM passages ORDER BY id").fetchall()
    known = {"cold": [Judgment(rows[1][0], rows[1][1], rows[1][2], 2)]}
    pool = runner.build_pool(conn, EMBEDDER, cases, known, ["fts_any", "semantic"], 5)
    assert {item["case_id"] for item in pool} == {"hood", "haube", "cold"}

    packed = judging.pack(conn, pool, cases, known, size=2, seed=1)
    graded_cases = {c["case_id"] for package in packed.packages for c in package}
    assert "haube" not in graded_cases  # judged together with "hood"
    hood = next(c for p in packed.packages for c in p if c["case_id"] == "hood")
    assert hood["queries"] == ["hooding falcon", "Haube Falke"]
    assert any(c["expect"] == "2" and c["case_id"] == "cold" for c in packed.manifest["controls"])

    # A judge who grades everything 1, except controls as expected
    expected = {(c["package"], c["key"]): (2 if c["expect"] == "2" else 0) for c in packed.manifest["controls"]}
    grades = [
        {c["case_id"]: {x["key"]: expected.get((n, x["key"]), 1) for x in c["candidates"]} for c in package}
        for n, package in enumerate(packed.packages)
    ]
    collected = judging.collect(packed.packages, grades, packed.manifest, pool, known)
    assert collected.failed_controls == []
    assert collected.agreement[0] == collected.agreement[1]
    assert set(collected.grades) == {"hood", "haube", "cold"}
    assert collected.grades["haube"].keys() == {c["key"] for i in pool if i["case_id"] == "haube" for c in i["candidates"]}
    for key in collected.grades.get("cold", {}):  # the known answer is not imported again
        assert runner.parse_span_key(key)[1] != rows[1][1] or runner.parse_span_key(key)[0] != rows[1][0]

    grades[0][next(iter(grades[0]))].popitem()
    with pytest.raises(ValueError):
        judging.collect(packed.packages, grades, packed.manifest, pool, known)
    conn.close()
