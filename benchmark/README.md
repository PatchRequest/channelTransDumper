# Retrieval benchmark

Measures how well search serves research agents: not only whether the best passage
ranks first, but how much of everything relevant an agent gets to see.

## Files

- `cases.json`: test cases. `kind` is `fact` (one specific answer), `sweep` (everything
  said on a topic) or `mention` (all passages naming a term, incl. transcription errors
  listed in `terms`). `split` separates `dev` cases, used for tuning, from `test` cases,
  used for reporting.
  `same_as` links a case to one asking the same question in another language (judged
  together); `keywords` is the keyword query an agent would add, written from the
  question's words only.
- `judgments.json`: graded time spans per case (0 = not relevant, 1 = touches the topic,
  2 = answers it). Spans instead of passage IDs keep judgments valid across rebuilds.
- `RESULTS.md`: one entry per recorded run.
- `judge-prompt.md`: the instructions every judge gets (see the rubric below).

## Workflow

Always measure on a frozen snapshot, never on the live database: a growing corpus
changes rankings without any code change.

```bash
uv run channeltrans-bench snapshot ~/.channeltrans/transcripts.db ~/.channeltrans/snapshots/NAME.db
uv run channeltrans-bench pool --db ~/.channeltrans/snapshots/NAME.db --out pool.json
uv run channeltrans-bench judge-pack --db ~/.channeltrans/snapshots/NAME.db --pool pool.json --out round/
# one judge per round/prompt-NN.md; each writes round/grades-NN.json
uv run channeltrans-bench judge-collect round/
uv run channeltrans-bench import-judgments round/import.json
uv run channeltrans-bench evaluate --db ~/.channeltrans/snapshots/NAME.db --split dev --record "note"
```

## Judging rubric

Grades are given by LLM judges (one model for all rounds, so rounds stay comparable)
reading the passage text only; the video title is context, not evidence. Transcripts
are automatic captions, so misspellings ("Harris hog", "gosh hawk") count as the word.

- **2** – fact: a reader could answer the question from this passage alone, i.e. it
  states the answer or the core reason asked for. Sweep: it makes a substantive,
  specific statement about the topic (advice, explanation, experience) worth citing.
- **1** – on the topic but not enough for 2: the subject is mentioned or discussed
  without the asked-for answer, only part of it, or a passing remark.
- **0** – not relevant; shared keywords alone are not relevance.

When unsure between two grades, the lower one is given. Judging rounds mix in known
positive and known negative control passages and give about 5 % of the candidates to
two judges, so leniency and disagreement are measured rather than assumed.

`pool` collects the unjudged passages that any variant returns, so a new variant is
not penalised for finding passages nobody judged; `unjudged@10` shows how much of a
ranking is still unjudged.

## Metrics

Judged spans of different videos that repeat the same speech (compilations, clips:
at least half of the word 5-grams shared) form one information unit, which counts once
in all fact and sweep metrics: seeing the same statement twice teaches an agent nothing
new.

- `nDCG@10`: ranking quality of the first ten hits (graded).
- `R@10`, `R@50`: share of the relevant judged spans among the first 10 / 50 hits.
- `unjudged@10`: share of the first ten hits without a judgment; high values make the
  other numbers unreliable.
- `R@200`: the same within 200 hits (four pages); measures how much a thorough agent
  can reach by paging.
- `mention_R@50`, `mention_R@200`: share of all passages naming the term (found by
  regular expression over the whole snapshot) among the first 50 / 200 hits; measures
  completeness. `mention_R@all` counts everything the variant returns when asked for
  all mentions (paged rankings stop at 1000 hits); it is the measure for exhaustive
  tools such as `find_mentions`.
