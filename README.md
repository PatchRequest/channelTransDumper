# channeltrans

Pulls the transcripts of every video of a YouTube channel into a SQLite database with
hybrid search (full text plus semantic similarity), so AI agents can look up what was
said on the channel.

## Setup

Requirements: Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/PatchRequest/channelTransDumper.git
cd channelTransDumper
uv sync
```

yt-dlp needs a JavaScript runtime for YouTube: `node` or `deno` on the `PATH`.

The first `sync` or `search` downloads the embedding model `google/embeddinggemma-300m`
(about 1.2 GB) once into `~/.channeltrans/models`. After that it runs locally;
transcripts and search queries never leave the machine.

## Capturing a channel

```bash
uv run channeltrans sync https://www.youtube.com/@somechannel
```

- Lists the channel's videos, live streams and shorts and works through them from the
  top (newest first). Running it again continues where the last run stopped and picks
  up newly published videos.
- `--limit N` caps a run, `--delay S` sets the pause between videos (default 3 s).
- Failed videos are retried in later runs, up to five times. After three failures in a
  row the run stops (exit code 1), because that suggests YouTube is blocking requests.
- A video without transcript is checked again in the next two runs: YouTube now and
  then answers without captions for a video that has them (in one full re-check, 41 of
  283 such videos turned out to have a transcript). Members-only videos are not
  checked again. `--recheck-missing` checks every video without a transcript once
  more, e.g. long after publication, when automatic captions may have been added.
- Only one `sync` or `reindex` runs at a time per database; a second one stops with an
  error. Capture several channels one after the other.
- Only the subtitle track in the video's original language is stored (manually
  maintained subtitles win over automatic captions), never a translation.

### Proxy (e.g. thermoptic)

```bash
uv run channeltrans sync <channel-url> --proxy http://127.0.0.1:1234 --proxy-insecure-tls
```

`--proxy-insecure-tls` turns off certificate verification. That is needed for proxies
that intercept TLS with their own CA; the proxy then verifies YouTube's certificate.
Both can also be set through `CHANNELTRANS_PROXY` and `CHANNELTRANS_PROXY_INSECURE_TLS=1`.

## Database

Default path `~/.channeltrans/transcripts.db`, changeable with `--db` or `CHANNELTRANS_DB`.

| Table             | Content                                                              |
| ----------------- | -------------------------------------------------------------------- |
| `channels`        | captured channels                                                    |
| `videos`          | all videos with status `pending`/`done`/`no_transcript`/`failed`     |
| `transcripts`     | raw transcript per video as timestamped lines (JSON)                 |
| `passages`        | sections of about 1000 characters (roughly one minute), timestamped  |
| `passages_fts`    | FTS5 full-text index over `passages` (stemmed)                       |
| `passages_words`  | unstemmed FTS5 index; its vocabulary feeds spelling suggestions      |
| `passage_duplicates` | passages repeating speech of another video (compilations, clips)  |
| `passage_vectors` | embedding per passage (sqlite-vec), computed from video title + text |

`channeltrans reindex` rebuilds passages and vectors from the raw transcripts (after
changing `PASSAGE_TARGET_CHARS`) without querying YouTube again. Querying
`passage_vectors` directly with SQL requires the sqlite-vec extension.

## Searching

```bash
uv run channeltrans search 'hawk* "weight control"' --channel @somechannel
uv run channeltrans search "how do I stop my hawk screaming" "hawk screaming at home"
uv run channeltrans spellings goshawk
uv run channeltrans mentions goshawk "gosh hawk" "goss hawk" gossock
uv run channeltrans status
```

Several queries in one call (alternative wordings, or the same question in each
language the channel's transcripts are in) are searched separately and fused into one
ranking; passages found by several of them rank higher.

Every search runs twice and is fused into one ranking (reciprocal rank fusion):

- **Full text** finds exact terms and names. Words are searched individually (English
  stemming), `"…"` is an exact phrase, `word*` a prefix. `--any` requires only one of
  the terms instead of all.
- **Semantic** finds hits by meaning, even when a word was mistranscribed. It also
  works across languages, but clearly better when the query is in the transcript's
  language: in a test with German questions on English transcripts, translating the
  question first raised the share of correct first hits from 5 of 12 to 9 of 12.

Output is JSON. For each hit, `text_match` tells whether the terms occur literally and
`semantic_similarity` (0–1) how close it is in meaning. A passage that repeats speech
from a better hit of another video (compilations, re-uploaded clips: at least half of
its word 5-grams recur) is folded into that hit and listed under `duplicates`, so a
page shows distinct statements. `--offset` pages through the same ranking;
`--since`/`--until` (upload dates, `YYYY-MM-DD`, inclusive) restrict it to a period. For research that must not miss anything on a topic, add a short keyword
query next to the question and keep paging: in the benchmark this raised the share of
relevant passages within 200 hits from 0.88 to 0.96, at a small cost to the first ten.

**Everything about a named thing.** `mentions` returns every passage naming one of the
terms, grouped by video – exhaustive, not ranked. Automatic captions misspell names
("goshawk" also appears as "gosh hawk", "goss hawk", "gossock"), so `spellings` lists
the variants that occur in the transcripts, each with the number of passages it adds
and an example; many are sound-alikes of other words, so pick the real ones and pass
them to `mentions`. In the benchmark, an agent doing so found 99–100 % of the mentions
of eight bird names and terms, against 7–99 % with the plain term.

## Search quality

Measured with the benchmark in `benchmark/` (65 cases on two falconry channels, 4,100
relevance-judged passages; held-out test split, repeated speech counted once):

| | first 10 hits (nDCG@10) | relevant passages within 50 / 200 hits |
|---|---|---|
| Specific questions | 0.71 | 81 % / 92 % |
| "Everything on a topic" | 0.88 | 65 % / 89 % |
| … plus a keyword query | 0.90 | 77 % / 99 % |

For named things (species, people, equipment), `find_mentions` with the spellings an
agent picked from `suggest_spellings` found 99–100 % of all mentions in each of eight
test terms. See `benchmark/RESULTS.md` for every run, including ideas that were
measured and dropped (a cross-encoder reranker, weighted keyword fusion).

## MCP server for agents

```bash
claude mcp add channeltrans -- uv run --directory /path/to/channelTransDumper channeltrans mcp
```

Tools: `list_channels`, `search_transcripts`, `find_mentions`, `suggest_spellings`,
`get_passage_context`, `get_video_transcript`, `list_videos`. The server opens the
database read-only; after an update that changes the schema, run `channeltrans sync`
or `channeltrans reindex` once to upgrade the database.

## Tests

```bash
uv run pytest
```

## License

MIT, see [LICENSE](LICENSE).
