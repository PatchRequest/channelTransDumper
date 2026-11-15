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
