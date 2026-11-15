from __future__ import annotations

import json

import pytest
from fakes import EMBEDDER, OPTIONS, FakeClient, video as _video

from channeltrans import ingest, search
from channeltrans.db import DatabaseError, connect, connect_read_only
from channeltrans.transcript import Cue, build_passages, parse_json3
from channeltrans.youtube import FetchError, VideoNotReady, select_track


def _json3(*events: dict) -> bytes:
    return json.dumps({"events": list(events)}).encode()


# --- Transcript -------------------------------------------------------------------------


def test_parse_json3_joins_segments_and_skips_empty_events():
    cues = parse_json3(
        _json3(
            {"tStartMs": 0, "dDurationMs": 5000, "segs": [{"utf8": "Hello"}, {"utf8": " there"}]},
            {"tStartMs": 2000, "dDurationMs": 100, "aAppend": 1, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 3000, "dDurationMs": 4000, "segs": [{"utf8": "second\nline"}]},
            {"tStartMs": 9000, "dDurationMs": 1000},
        )
    )
    # The end of the first line is capped at the start of the next one.
    assert cues == [Cue(0, 3000, "Hello there"), Cue(3000, 7000, "second line")]


def test_parse_json3_rejects_other_formats():
    from channeltrans.transcript import TranscriptFormatError

    with pytest.raises(TranscriptFormatError):
        parse_json3(b"WEBVTT\n")


def test_build_passages_groups_cues_up_to_target_size():
    cues = [Cue(i * 1000, (i + 1) * 1000, "word " * 4) for i in range(10)]
    passages = build_passages(cues, target_chars=50)
    assert [(p.start_ms, p.end_ms) for p in passages] == [
        (0, 3000), (3000, 6000), (6000, 9000), (9000, 10000),
    ]
    assert " ".join(p.text for p in passages) == " ".join(c.text for c in cues)


# --- Track selection --------------------------------------------------------------------


def test_select_track_prefers_manual_subtitles_in_original_language():
    info = {
        "language": "en-US",
        "subtitles": {"de": [], "en-GB": [], "en": []},
        "automatic_captions": {"en-orig": [], "en": []},
    }
    assert select_track(info).key == "en"
    assert select_track(info).kind == "manual"


def test_select_track_falls_back_to_original_automatic_captions():
    info = {
        "language": "en-US",
        "subtitles": {"de": []},
        "automatic_captions": {"de-orig": [], "en": [], "en-orig": []},
    }
    track = select_track(info)
    assert (track.key, track.kind, track.language) == ("en-orig", "auto", "en-US")


def test_select_track_never_picks_a_translation():
    assert select_track({"language": "en", "automatic_captions": {"de": []}}) is None
    assert select_track({"language": None, "automatic_captions": {"en": []}}) is None


# --- Search -----------------------------------------------------------------------------


def test_build_fts_query_quotes_terms_and_supports_phrases_and_prefixes():
    assert search.build_fts_query('hawk* "weight control" AND', "all") == (
        '"hawk"* AND "weight control" AND "AND"'
    )
    assert search.build_fts_query("a - b", "any") == '"a" OR "b"'
    with pytest.raises(search.QueryError):
        search.build_fts_query(' - "" ', "all")


# --- Ingest and queries -----------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "t.db")
    yield connection
    connection.close()


def test_sync_stores_transcripts_and_is_resumable(conn):
    client = FakeClient(
        {
            "new": _video("new", "Always weigh your hawk before flying."),
            "mute": _video("mute"),
            "broken": FetchError("HTTP 429"),
            "live": VideoNotReady("live"),
        }
    )
    channel_id = ingest.discover(conn, client, "https://youtube.test/@falconer")
    result = ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    assert (result.done, result.no_transcript, result.failed, result.not_ready) == (1, 1, 1, 1)
    assert client.fetched == ["new", "mute", "broken", "live"]  # listing order
    statuses = dict(conn.execute("SELECT id, status FROM videos"))
    assert statuses == {
        "new": "done", "mute": "no_transcript", "broken": "failed", "live": "pending",
    }

    # Second run: finished videos are skipped, failed and open ones are tried again.
    client.fetched.clear()
    client.videos["broken"] = _video("broken", "Recovered transcript.")
    ingest.discover(conn, client, "https://youtube.test/@falconer")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    assert client.fetched == ["broken", "live"]
    row = conn.execute("SELECT status, last_error FROM videos WHERE id = 'broken'").fetchone()
    assert tuple(row) == ("done", None)


def test_sync_aborts_after_consecutive_failures_and_gives_up_after_max_attempts(conn):
    client = FakeClient({str(i): FetchError("blocked") for i in range(5)})
    channel_id = ingest.discover(conn, client, "u")
    options = ingest.SyncOptions(delay_s=0, max_attempts=2, max_consecutive_failures=3)

    result = ingest.process_queue(conn, client, EMBEDDER, channel_id, options)
    assert result.aborted and client.fetched == ["0", "1", "2"]

    ingest.process_queue(conn, client, EMBEDDER, channel_id, options)  # 0, 1, 2 for the second time
    client.fetched.clear()
    ingest.process_queue(conn, client, EMBEDDER, channel_id, options)
    assert client.fetched == ["3", "4"]  # 0–2 have reached max_attempts


def test_requeue_missing_and_limit(conn):
    client = FakeClient({"a": _video("a"), "b": _video("b", "text")})
    channel_id = ingest.discover(conn, client, "u")
    result = ingest.process_queue(conn, client, EMBEDDER, channel_id, ingest.SyncOptions(limit=1, delay_s=0))
    assert result.no_transcript == 1 and client.fetched == ["a"]

    assert ingest.requeue_missing(conn, channel_id) == 1
    client.videos["a"] = _video("a", "Captions arrived late.")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    assert dict(conn.execute("SELECT id, status FROM videos")) == {"a": "done", "b": "done"}


def test_search_context_and_transcript_queries(conn):
    lines = [f"Passage {i} about hawks. " + "filler " * 150 for i in range(4)]
    client = FakeClient(
        {
            "v1": _video("v1", *lines),
            "v2": _video("v2", "The falcon needs weight control every day."),
        }
    )
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    def text_hits(query, **kwargs):
        hits = search.search_passages(conn, EMBEDDER, [query], **kwargs)
        return [h["video_id"] for h in hits if h["text_match"]]

    hits = search.search_passages(conn, EMBEDDER, ["falcons weight"], channel="@falconer")
    assert hits[0]["video_id"] == "v2" and hits[0]["text_match"]  # stemming: falcons → falcon
    assert hits[0]["url"] == "https://www.youtube.com/watch?v=v2&t=0s"
    assert hits[0]["semantic_similarity"] > 0
    assert text_hits("falcon nonexistentword") == []
    assert text_hits("falcon nonexistentword", match="any") == ["v2"]
    assert text_hits('"weight control"') == ["v2"]

    # A semantic hit without a literal match of all terms still ranks first.
    semantic = search.search_passages(conn, EMBEDDER, ["falcon weight control daily routine"])
    assert semantic[0]["video_id"] == "v2" and not semantic[0]["text_match"]

    third = search.search_passages(conn, EMBEDDER, ['"Passage 2"'])[0]
    context = search.passage_context(conn, third["passage_id"], before=1, after=5)
    assert [p["seq"] for p in context] == [1, 2, 3]
    assert third["start"] == "0:00:10"

    page = search.video_transcript(conn, "v1", offset=1, limit=2)
    assert page["total_passages"] == 4 and [p["seq"] for p in page["passages"]] == [1, 2]
    assert page["transcript_kind"] == "auto"

    assert [v["video_id"] for v in search.list_videos(conn, title_contains="TITLE V2")] == ["v2"]
    stats = search.channel_stats(conn)
    assert (stats[0]["videos"], stats[0]["done"]) == (2, 2)

    assert stats[0]["transcript_languages"] == {"en": 2}

    with pytest.raises(search.QueryError):
        search.search_passages(conn, EMBEDDER, ["hawk"], channel="unknown")
    with pytest.raises(search.QueryError):
        search.search_passages(conn, EMBEDDER, [" "])
    with pytest.raises(search.QueryError):
        search.search_passages(conn, EMBEDDER, ["hawk"] * (search.MAX_QUERIES + 1))
    with pytest.raises(search.QueryError):
        search.passage_context(conn, 9999)


def test_several_queries_are_fused(conn):
    client = FakeClient(
        {
            "a": _video("a", "Hooding calms the falcon before the flight."),
            "b": _video("b", "Haube beruhigt den Falken vor dem Flug."),
        }
    )
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    def found(queries):
        return {
            h["video_id"]
            for h in search.search_passages(conn, EMBEDDER, queries)
            if h["text_match"]
        }

    assert found(["hooding falcon"]) == {"a"}
    assert found(["Haube Falken"]) == {"b"}
    assert found(["hooding falcon", "Haube Falken"]) == {"a", "b"}


def test_refetch_and_reindex_replace_passages_without_stale_search_hits(conn):
    client = FakeClient({"v": _video("v", "old wording about jesses")})
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    conn.execute("UPDATE videos SET status = 'pending'")
    client.videos["v"] = _video("v", "new wording about bells")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    def hits(query):
        return [(h["text"], h["text_match"]) for h in search.search_passages(conn, EMBEDDER, [query])]

    # The old passage is gone from both the full-text index and the vector table.
    assert hits("jesses") == [("new wording about bells", False)]
    assert hits("bells") == [("new wording about bells", True)]

    assert ingest.reindex(conn, EMBEDDER) == 1
    assert hits("bells") == [("new wording about bells", True)]
    counts = conn.execute(
        "SELECT (SELECT count(*) FROM passages), (SELECT count(*) FROM passage_vectors)"
    ).fetchone()
    assert tuple(counts) == (1, 1)


def test_interrupted_embedding_is_completed_on_next_sync(conn):
    client = FakeClient({"v": _video("v", "hooding a falcon")})
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    conn.execute("DELETE FROM passage_vectors")
    conn.commit()

    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    assert client.fetched == ["v"]  # no refetch, only the vectors are caught up
    assert conn.execute("SELECT count(*) FROM passage_vectors").fetchone()[0] == 1


def test_version_1_database_is_upgraded(tmp_path):
    import sqlite3

    from channeltrans import db

    legacy = sqlite3.connect(tmp_path / "old.db")
    legacy.executescript(f"{db._SCHEMA_STEPS[0]}PRAGMA user_version = 1;")
    legacy.close()
    with pytest.raises(DatabaseError):
        connect_read_only(tmp_path / "old.db")  # read-only access does not migrate
    upgraded = connect(tmp_path / "old.db")
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    upgraded.execute("SELECT count(*) FROM passage_vectors")
    upgraded.close()


def test_read_only_connection_requires_existing_database(tmp_path):
    with pytest.raises(DatabaseError):
        connect_read_only(tmp_path / "missing.db")
    connect(tmp_path / "t.db").close()
    read_only = connect_read_only(tmp_path / "t.db")
    with pytest.raises(Exception):
        read_only.execute("DELETE FROM channels")
    read_only.close()
