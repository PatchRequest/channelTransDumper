from __future__ import annotations

import pytest
from fakes import EMBEDDER, OPTIONS, FakeClient, video

from channeltrans import ingest, search, spelling
from channeltrans.db import connect

FILLER = "x " * 500  # each line fills a passage of its own (about 1000 characters)


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    client = FakeClient(
        {
            "a": video("a", "My goshawk caught a rabbit. " + FILLER, "The gosh hawk again. " + FILLER),
            "b": video("b", "A gossock, as the captions say. " + FILLER, "Gosh hawks are fast. " + FILLER),
            "c": video("c", "Oh my gosh, what a day. " + FILLER, "A goshawk, also called gosok, and a kestral. " + FILLER),
        }
    )
    channel_id = ingest.discover(conn, client, "u")
    ingest.process_queue(conn, client, EMBEDDER, channel_id, OPTIONS)
    return conn


def _suggested(conn, term, **kwargs):
    return {s["spelling"]: s for s in spelling.suggest_spellings(conn, term, **kwargs)["suggestions"]}


def test_suggests_split_and_misspelled_forms_with_the_passages_they_add(conn):
    suggested = _suggested(conn, "goshawk")
    assert {"gosh hawk", "gossock"} <= set(suggested)
    assert "goshawk" not in suggested
    # "gosh hawk" and "gosh hawks" stem alike and add the same two passages: listed once
    assert suggested["gosh hawk"]["passages"] == 2
    assert "gosh hawks" not in suggested
    assert "«gossock»" in suggested["gossock"]["example"].lower()


def test_suggestions_only_list_spellings_that_add_passages(conn):
    # "gosok" only occurs next to "goshawk", so find_mentions would gain nothing from it
    suggested = _suggested(conn, "goshawk")
    assert "gosok" not in suggested
    assert all(s["passages"] > 0 for s in suggested.values())
    assert _suggested(conn, "kestrel")["kestral"]["passages"] == 1


def test_suggestions_respect_limit_and_reject_short_terms(conn):
    assert len(spelling.suggest_spellings(conn, "goshawk", limit=1)["suggestions"]) == 1
    with pytest.raises(search.QueryError):
        spelling.suggest_spellings(conn, "owl")
    with pytest.raises(search.QueryError):
        spelling.suggest_spellings(conn, "!!!")
