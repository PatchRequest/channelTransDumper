# Benchmark results

One entry per run, appended by `channeltrans-bench evaluate --record`. Compare runs only
within the same snapshot.

## 2026-11-15 – Phase 0 gate: partial corpus, one judged span per fact case

- code: `a97dd81` (uncommitted changes in src/)
- snapshot: `2026-11-15-phase0.db` (8409 passages, created 2026-11-15T22:04:50+00:00)
- split: dev

| variant | group | cases | nDCG@10 | R@10 | R@50 | unjudged@10 | mention_R@50 |
|---|---|---|---|---|---|---|---|
| hybrid | fact | 16 | 0.762 | 0.844 | 0.938 | 0.894 |  |
| hybrid | fact/de | 6 | 0.558 | 0.667 | 0.833 | 0.917 |  |
| hybrid | fact/en | 10 | 0.884 | 0.950 | 1.000 | 0.880 |  |
| hybrid | mention | 4 |  |  |  |  | 0.489 |
| hybrid | mention/en | 4 |  |  |  |  | 0.489 |
| semantic | fact | 16 | 0.762 | 0.844 | 0.938 | 0.894 |  |
| semantic | fact/de | 6 | 0.558 | 0.667 | 0.833 | 0.917 |  |
| semantic | fact/en | 10 | 0.884 | 0.950 | 1.000 | 0.880 |  |
| semantic | mention | 4 |  |  |  |  | 0.338 |
| semantic | mention/en | 4 |  |  |  |  | 0.338 |
| hybrid_any | fact | 16 | 0.573 | 0.750 | 0.875 | 0.906 |  |
| hybrid_any | fact/de | 6 | 0.359 | 0.667 | 0.667 | 0.917 |  |
| hybrid_any | fact/en | 10 | 0.702 | 0.800 | 1.000 | 0.900 |  |
| hybrid_any | mention | 4 |  |  |  |  | 0.482 |
| hybrid_any | mention/en | 4 |  |  |  |  | 0.482 |
| fts_any | fact | 16 | 0.231 | 0.375 | 0.531 | 0.950 |  |
| fts_any | fact/de | 6 | 0.000 | 0.000 | 0.000 | 1.000 |  |
| fts_any | fact/en | 10 | 0.370 | 0.600 | 0.850 | 0.920 |  |
| fts_any | mention | 4 |  |  |  |  | 0.564 |
| fts_any | mention/en | 4 |  |  |  |  | 0.564 |

## 2026-11-15 – Paging (offset, fused depth 1000) and find_mentions; before: mention_R@200 = R@50 (0.451 dev / 0.302 test), nDCG@10 unchanged

- code: `b158718` (uncommitted changes in src/)
- snapshot: `2026-11-15-phase0.db` (8409 passages, created 2026-11-15T22:04:50+00:00)
- split: dev
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `daa26e9f2f99`)
- Skipped 14 cases without relevant judgments: fact-en-34, fact-de-35, fact-en-36, fact-de-37, fact-en-40, fact-en-41, sweep-en-05, sweep-en-08, sweep-en-09, sweep-en-10, sweep-en-11, sweep-en-13, sweep-en-14, sweep-en-15

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 |
|---|---|---|---|---|---|---|---|---|---|
| hybrid | fact | 15 | 0.809 | 0.900 | 0.967 | 1.000 | 0.873 |  |  |
| hybrid | fact/de | 5 | 0.582 | 0.700 | 0.900 | 1.000 | 0.860 |  |  |
| hybrid | fact/en | 10 | 0.922 | 1.000 | 1.000 | 1.000 | 0.880 |  |  |
| hybrid | mention | 4 |  |  |  |  |  | 0.497 | 0.719 |
| hybrid | mention/en | 4 |  |  |  |  |  | 0.497 | 0.719 |
| mentions | mention | 4 |  |  |  |  |  | 0.487 | 0.655 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.487 | 0.655 |

## 2026-11-15 – Paging (offset, fused depth 1000) and find_mentions; before: mention_R@200 = R@50 (0.451 dev / 0.302 test), nDCG@10 unchanged

- code: `b158718` (uncommitted changes in src/)
- snapshot: `2026-11-15-phase0.db` (8409 passages, created 2026-11-15T22:04:50+00:00)
- split: test
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `daa26e9f2f99`)
- Skipped 12 cases without relevant judgments: fact-en-32, fact-en-33, fact-en-38, fact-de-39, sweep-en-01, sweep-en-02, sweep-de-03, sweep-en-04, sweep-en-06, sweep-de-07, sweep-de-12, sweep-de-16

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 |
|---|---|---|---|---|---|---|---|---|---|
| hybrid | fact | 16 | 0.641 | 0.844 | 0.938 | 1.000 | 0.912 |  |  |
| hybrid | fact/de | 7 | 0.480 | 0.714 | 0.857 | 1.000 | 0.929 |  |  |
| hybrid | fact/en | 9 | 0.766 | 0.944 | 1.000 | 1.000 | 0.900 |  |  |
| hybrid | mention | 4 |  |  |  |  |  | 0.316 | 0.674 |
| hybrid | mention/en | 4 |  |  |  |  |  | 0.316 | 0.674 |
| mentions | mention | 4 |  |  |  |  |  | 0.288 | 0.457 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.288 | 0.457 |
