from __future__ import annotations

import dataclasses
import json

import pytest
from fakes import EMBEDDER, OPTIONS, FakeClient, video as _video

from channeltrans import ingest, search
from channeltrans.db import DatabaseError, connect, connect_read_only, writer_lock
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

    # Second run: finished videos are skipped; failed, open and transcript-less ones are
    # tried again.
    client.fetched.clear()
    client.videos["broken"] = _video("broken", "Recovered transcript.")
    ingest.discover(conn, client, "https://youtube.test/@falconer")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    assert client.fetched == ["mute", "broken", "live"]
    row = conn.execute("SELECT status, last_error FROM videos WHERE id = 'broken'").fetchone()
    assert tuple(row) == ("done", None)


def test_missing_transcripts_are_checked_in_later_runs_until_confirmed(conn):
    members = dataclasses.replace(_video("members"), availability="subscriber_only")
    client = FakeClient({"late": _video("late"), "mute": _video("mute"), "members": members})
    channel_id = ingest.discover(conn, client, "u")
    options = dataclasses.replace(OPTIONS, missing_checks=2)

    ingest.process_queue(conn, client, EMBEDDER, channel_id, options)
    client.videos["late"] = _video("late", "Captions that YouTube withheld the first time.")
    client.fetched.clear()
    ingest.process_queue(conn, client, EMBEDDER, channel_id, options)
    assert client.fetched == ["late", "mute"]  # members-only videos are not checked again
    client.fetched.clear()
    ingest.process_queue(conn, client, EMBEDDER, channel_id, options)
    assert client.fetched == []  # "mute" was checked twice: final
    rows = {r["id"]: (r["status"], r["missing_checks"]) for r in conn.execute("SELECT * FROM videos")}
    assert rows == {"late": ("done", 0), "mute": ("no_transcript", 2), "members": ("no_transcript", 1)}

    # --recheck-missing checks everything without transcript again, members-only included
    assert ingest.requeue_missing(conn, channel_id) == 2
    ingest.process_queue(conn, client, EMBEDDER, channel_id, options)
    assert sorted(client.fetched) == ["members", "mute"]


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


def test_pages_continue_the_same_ranking(conn):
    client = FakeClient({f"v{i}": _video(f"v{i}", f"hawk number {i} " + "word " * i) for i in range(12)})
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    def ids(**kwargs):
        return [h["passage_id"] for h in search.search_passages(conn, EMBEDDER, ["hawk"], **kwargs)]

    everything = ids(limit=12)
    assert len(everything) == 12
    assert ids(limit=5) + ids(limit=5, offset=5) + ids(limit=5, offset=10) == everything
    assert ids(offset=12) == []
    with pytest.raises(search.QueryError):
        ids(limit=10, offset=search.MAX_DEPTH)
    with pytest.raises(search.QueryError):
        ids(offset=-1)


def test_find_mentions_is_exhaustive_and_grouped_by_video(conn):
    client = FakeClient(
        {
            # each line fills a passage of its own (about 1000 characters)
            "a": _video("a", "My Harris hawk. " + "x " * 500, "Harris hawks again. " + "y " * 500, "goshawk"),
            "b": _video("b", "a harris hog, the transcript says"),
            "c": _video("c", "nothing relevant"),
        }
    )
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    result = search.find_mentions(conn, ["Harris hawk", "harris hog"])
    assert (result["total_passages"], result["total_videos"]) == (3, 2)
    assert [v["video_id"] for v in result["videos"]] == ["a", "b"]  # most mentions first
    assert [p["start"] for p in result["videos"][0]["passages"]] == ["0:00:00", "0:00:05"]
    assert search.find_mentions(conn, ["Harris hawk"], offset=1, limit=1)["videos"] == []
    assert search.find_mentions(conn, ["harris-hawk!"])["total_videos"] == 1  # punctuation
    with pytest.raises(search.QueryError):
        search.find_mentions(conn, ["  ", "!!"])


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


def test_writer_lock_rejects_a_second_writer(tmp_path):
    import subprocess
    import sys

    db = tmp_path / "db.sqlite"
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; from pathlib import Path; from channeltrans.db import writer_lock\n"
         f"with writer_lock(Path({str(db)!r})):\n    print('locked', flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(DatabaseError, match="Another sync"):
            with writer_lock(db):
                pass
    finally:
        holder.kill()
        holder.wait()
    with writer_lock(db):  # released when the holder died
        pass


def test_date_range_narrows_search_and_mentions(conn):
    dated = {
        "old": dataclasses.replace(_video("old", "Weigh the hawk every morning."), upload_date="2019-05-01"),
        "new": dataclasses.replace(_video("new", "Weigh the hawk before flying."), upload_date="2025-05-01"),
        "undated": dataclasses.replace(_video("undated", "Weigh the hawk daily."), upload_date=None),
    }
    client = FakeClient(dated)
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)

    def videos(**scope):
        return {h["video_id"] for h in search.search_passages(conn, EMBEDDER, ["weigh hawk"], **scope)}

    assert videos() == {"old", "new", "undated"}
    assert videos(since="2020-01-01") == {"new"}
    assert videos(until="2020-01-01") == {"old"}  # unknown dates fall outside any range
    assert videos(since="2019-05-01", until="2019-05-01") == {"old"}
    mentions = search.find_mentions(conn, ["hawk"], since="2025-01-01")
    assert [v["video_id"] for v in mentions["videos"]] == ["new"]
    for bad in ({"since": "May 2020"}, {"since": "2025-01-01", "until": "2024-01-01"}):
        with pytest.raises(search.QueryError):
            videos(**bad)


def test_upgrade_moves_vectors_into_the_dated_table(tmp_path):
    import sqlite3

    import sqlite_vec

    from channeltrans import db as schema

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.enable_load_extension(True)
    sqlite_vec.load(old)
    for step, script in enumerate(schema._SCHEMA_STEPS[:5]):
        old.executescript(f"BEGIN;{script}PRAGMA user_version = {step + 1};COMMIT;")
    old.executescript(
        """INSERT INTO channels (id, title, url, added_at, last_discovered_at) VALUES ('c', 'C', 'u', 'now', 'now');
           INSERT INTO videos (id, channel_id, title, listing_rank, upload_date, status)
               VALUES ('v', 'c', 'T', 0, '2024-02-03', 'done');
           INSERT INTO passages (video_id, seq, start_ms, end_ms, text) VALUES ('v', 0, 0, 1, 'x');"""
    )
    vector = EMBEDDER.embed_documents([("T", "x")])[0]
    old.execute("INSERT INTO passage_vectors (passage_id, channel_id, embedding) VALUES (1, 'c', ?)", (vector,))
    old.commit()
    old.close()

    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    row = conn.execute("SELECT passage_id, upload_date, embedding FROM passage_vectors").fetchone()
    assert (row[0], row[1], row[2]) == (1, "2024-02-03", vector)
    conn.execute("DELETE FROM passages")  # the delete trigger is back
    assert conn.execute("SELECT count(*) FROM passage_vectors").fetchone()[0] == 0
