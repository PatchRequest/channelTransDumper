# Retrieval benchmark

Measures how well search serves research agents: not only whether the best passage
ranks first, but how much of everything relevant an agent gets to see.

## Files

- `cases.json`: test cases. `kind` is `fact` (one specific answer), `sweep` (everything
  said on a topic) or `mention` (all passages naming a term, incl. transcription errors
  listed in `terms`). `split` separates `dev` cases, used for tuning, from `test` cases,
  used for reporting.
- `judgments.json`: graded time spans per case (0 = not relevant, 1 = touches the topic,
  2 = answers it). Spans instead of passage IDs keep judgments valid across rebuilds.
- `RESULTS.md`: one entry per recorded run.

## Workflow

Always measure on a frozen snapshot, never on the live database: a growing corpus
changes rankings without any code change.

```bash
uv run channeltrans-bench snapshot ~/.channeltrans/transcripts.db ~/.channeltrans/snapshots/NAME.db
uv run channeltrans-bench pool --db ~/.channeltrans/snapshots/NAME.db --out pool.json
# grade pool.json → grades.json: {"case-id": {"video|start_ms|end_ms": 0|1|2, ...}, ...}
uv run channeltrans-bench import-judgments grades.json
uv run channeltrans-bench evaluate --db ~/.channeltrans/snapshots/NAME.db --split dev --record "note"
```

`pool` collects the unjudged passages that any variant returns, so a new variant is
not penalised for finding passages nobody judged; `unjudged@10` shows how much of a
ranking is still unjudged.

## Metrics

- `nDCG@10`: ranking quality of the first ten hits (graded).
- `R@10`, `R@50`: share of the relevant judged spans among the first 10 / 50 hits.
- `unjudged@10`: share of the first ten hits without a judgment; high values make the
  other numbers unreliable.
- `mention_R@50`: share of all passages naming the term (found by regular expression
  over the whole snapshot) among the first 50 hits; measures completeness.
