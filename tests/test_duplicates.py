from __future__ import annotations

import pytest
from fakes import EMBEDDER, OPTIONS, FakeClient, video

from channeltrans import ingest, search
from channeltrans.bench import metrics, runner
from channeltrans.bench.dataset import Judgment
from channeltrans.db import connect

REUSED = (
    "Hooding calms the falcon because darkness tells the bird to hold still and wait "
    "for the flight while the falconer carries it across the field to the quarry."
)


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    client = FakeClient(
        {
            "orig": video("orig", REUSED),
            "compilation": video("compilation", "Best of the channel. " + REUSED),
            "other": video("other", "Hooding a falcon for the first time takes patience and a calm room."),
        }
    )
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    return conn


def _pairs(conn):
    return {tuple(row) for row in conn.execute("SELECT passage_id, duplicate_id FROM passage_duplicates")}


def test_reused_speech_is_linked_both_ways_but_similar_topics_are_not(conn):
    ids = dict(conn.execute("SELECT video_id, id FROM passages"))
    assert _pairs(conn) == {(ids["orig"], ids["compilation"]), (ids["compilation"], ids["orig"])}
    assert conn.execute("SELECT count(*) FROM duplicate_scans").fetchone()[0] == 3


def test_search_folds_duplicates_into_the_better_hit(conn):
    hits = search.search_passages(conn, EMBEDDER, ["hooding falcon darkness"], limit=10)
    assert len(hits) == 2  # three passages, two of them the same speech
    folded = next(hit for hit in hits if hit["duplicates"])
    assert len(folded["duplicates"]) == 1
    assert {folded["video_id"], folded["duplicates"][0]["video_id"]} == {"orig", "compilation"}
    assert folded["duplicates"][0]["url"].startswith("https://www.youtube.com/watch?v=")
    # paging runs over the folded ranking
    assert [h["passage_id"] for h in search.search_passages(conn, EMBEDDER, ["hooding falcon darkness"], limit=1, offset=1)] == [hits[1]["passage_id"]]


def test_reindex_relinks_duplicates(conn):
    before = len(_pairs(conn))
    ingest.reindex(conn, EMBEDDER)
    assert len(_pairs(conn)) == before
    assert conn.execute("SELECT count(*) FROM duplicate_scans").fetchone()[0] == 3


def test_metrics_count_an_information_unit_once(conn):
    rows = conn.execute("SELECT id, video_id, start_ms, end_ms, text FROM passages ORDER BY video_id").fetchall()
    passages = {row[1]: metrics.Retrieved(*row) for row in rows}
    judged = [Judgment(p.video_id, p.start_ms, p.end_ms, 2) for p in passages.values()]
    units = runner.information_units(conn, judged)
    assert units[judged[0]] == units[judged[1]] != units[judged[2]]  # compilation = orig
    both_copies = [passages["compilation"], passages["orig"]]
    assert metrics.recall(both_copies, judged, 2, units=units) == pytest.approx(1 / 2)
    assert metrics.recall(both_copies, judged, 2) == pytest.approx(2 / 3)
