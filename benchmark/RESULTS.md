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

## 2026-11-16 – Official baseline: full corpus, 4122 new judgments (strict rubric, 27/28 controls, 175/200 judge agreement)

- code: `c3efb13`
- snapshot: `2026-11-16-full.db` (10882 passages, created 2026-11-16T00:11:35+00:00)
- split: dev
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `1537d6354413`)
- All cases judged.

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 |
|---|---|---|---|---|---|---|---|---|---|
| hybrid | fact | 21 | 0.675 | 0.316 | 0.730 | 0.909 | 0.000 |  |  |
| hybrid | fact/de | 7 | 0.579 | 0.274 | 0.615 | 0.901 | 0.000 |  |  |
| hybrid | fact/en | 14 | 0.724 | 0.337 | 0.788 | 0.913 | 0.000 |  |  |
| hybrid | mention | 4 |  |  |  |  |  | 0.447 | 0.657 |
| hybrid | mention/en | 4 |  |  |  |  |  | 0.447 | 0.657 |
| hybrid | sweep | 8 | 0.829 | 0.155 | 0.652 | 0.881 | 0.000 |  |  |
| hybrid | sweep/en | 8 | 0.829 | 0.155 | 0.652 | 0.881 | 0.000 |  |  |
| hybrid_any | fact | 21 | 0.533 | 0.285 | 0.757 | 0.967 | 0.000 |  |  |
| hybrid_any | fact/de | 7 | 0.346 | 0.188 | 0.547 | 0.902 | 0.000 |  |  |
| hybrid_any | fact/en | 14 | 0.626 | 0.333 | 0.862 | 1.000 | 0.000 |  |  |
| hybrid_any | mention | 4 |  |  |  |  |  | 0.402 | 0.657 |
| hybrid_any | mention/en | 4 |  |  |  |  |  | 0.402 | 0.657 |
| hybrid_any | sweep | 8 | 0.705 | 0.142 | 0.582 | 0.964 | 0.000 |  |  |
| hybrid_any | sweep/en | 8 | 0.705 | 0.142 | 0.582 | 0.964 | 0.000 |  |  |
| hybrid_kw | fact | 21 | 0.629 | 0.331 | 0.794 | 0.937 | 0.000 |  |  |
| hybrid_kw | fact/de | 7 | 0.651 | 0.353 | 0.816 | 0.992 | 0.000 |  |  |
| hybrid_kw | fact/en | 14 | 0.617 | 0.320 | 0.783 | 0.909 | 0.000 |  |  |
| hybrid_kw | sweep | 8 | 0.759 | 0.147 | 0.619 | 0.962 | 0.000 |  |  |
| hybrid_kw | sweep/en | 8 | 0.759 | 0.147 | 0.619 | 0.962 | 0.000 |  |  |
| semantic | fact | 21 | 0.675 | 0.316 | 0.730 | 0.909 | 0.000 |  |  |
| semantic | fact/de | 7 | 0.579 | 0.274 | 0.615 | 0.901 | 0.000 |  |  |
| semantic | fact/en | 14 | 0.724 | 0.337 | 0.788 | 0.913 | 0.000 |  |  |
| semantic | mention | 4 |  |  |  |  |  | 0.266 | 0.553 |
| semantic | mention/en | 4 |  |  |  |  |  | 0.266 | 0.553 |
| semantic | sweep | 8 | 0.840 | 0.155 | 0.652 | 0.880 | 0.000 |  |  |
| semantic | sweep/en | 8 | 0.840 | 0.155 | 0.652 | 0.880 | 0.000 |  |  |
| fts_any | fact | 21 | 0.319 | 0.198 | 0.423 | 0.586 | 0.000 |  |  |
| fts_any | fact/de | 7 | 0.014 | 0.018 | 0.087 | 0.173 | 0.000 |  |  |
| fts_any | fact/en | 14 | 0.472 | 0.288 | 0.592 | 0.793 | 0.000 |  |  |
| fts_any | mention | 4 |  |  |  |  |  | 0.466 | 0.585 |
| fts_any | mention/en | 4 |  |  |  |  |  | 0.466 | 0.585 |
| fts_any | sweep | 8 | 0.569 | 0.126 | 0.435 | 0.630 | 0.000 |  |  |
| fts_any | sweep/en | 8 | 0.569 | 0.126 | 0.435 | 0.630 | 0.000 |  |  |
| mentions | mention | 4 |  |  |  |  |  | 0.466 | 0.585 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.466 | 0.585 |
| reranked | fact | 21 | 0.657 | 0.309 | 0.730 | 0.730 | 0.000 |  |  |
| reranked | fact/de | 7 | 0.489 | 0.246 | 0.615 | 0.615 | 0.000 |  |  |
| reranked | fact/en | 14 | 0.740 | 0.340 | 0.788 | 0.788 | 0.000 |  |  |
| reranked | mention | 4 |  |  |  |  |  | 0.447 | 0.447 |
| reranked | mention/en | 4 |  |  |  |  |  | 0.447 | 0.447 |
| reranked | sweep | 8 | 0.844 | 0.152 | 0.652 | 0.652 | 0.000 |  |  |
| reranked | sweep/en | 8 | 0.844 | 0.152 | 0.652 | 0.652 | 0.000 |  |  |

## 2026-11-16 – Official baseline: full corpus, 4122 new judgments (strict rubric, 27/28 controls, 175/200 judge agreement)

- code: `c3efb13`
- snapshot: `2026-11-16-full.db` (10882 passages, created 2026-11-16T00:11:35+00:00)
- split: test
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `1537d6354413`)
- All cases judged.

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 |
|---|---|---|---|---|---|---|---|---|---|
| hybrid | fact | 20 | 0.690 | 0.383 | 0.797 | 0.919 | 0.000 |  |  |
| hybrid | fact/de | 8 | 0.571 | 0.401 | 0.756 | 0.875 | 0.000 |  |  |
| hybrid | fact/en | 12 | 0.769 | 0.371 | 0.823 | 0.948 | 0.000 |  |  |
| hybrid | mention | 4 |  |  |  |  |  | 0.215 | 0.525 |
| hybrid | mention/en | 4 |  |  |  |  |  | 0.215 | 0.525 |
| hybrid | sweep | 8 | 0.877 | 0.170 | 0.640 | 0.874 | 0.000 |  |  |
| hybrid | sweep/de | 4 | 0.823 | 0.171 | 0.606 | 0.836 | 0.000 |  |  |
| hybrid | sweep/en | 4 | 0.931 | 0.170 | 0.674 | 0.912 | 0.000 |  |  |
| hybrid_any | fact | 20 | 0.514 | 0.268 | 0.771 | 0.949 | 0.000 |  |  |
| hybrid_any | fact/de | 8 | 0.263 | 0.177 | 0.634 | 0.874 | 0.000 |  |  |
| hybrid_any | fact/en | 12 | 0.681 | 0.329 | 0.862 | 1.000 | 0.000 |  |  |
| hybrid_any | mention | 4 |  |  |  |  |  | 0.215 | 0.525 |
| hybrid_any | mention/en | 4 |  |  |  |  |  | 0.215 | 0.525 |
| hybrid_any | sweep | 8 | 0.703 | 0.147 | 0.575 | 0.893 | 0.000 |  |  |
| hybrid_any | sweep/de | 4 | 0.603 | 0.123 | 0.442 | 0.785 | 0.000 |  |  |
| hybrid_any | sweep/en | 4 | 0.803 | 0.170 | 0.708 | 1.000 | 0.000 |  |  |
| hybrid_kw | fact | 20 | 0.738 | 0.425 | 0.883 | 0.965 | 0.000 |  |  |
| hybrid_kw | fact/de | 8 | 0.768 | 0.510 | 0.927 | 0.969 | 0.000 |  |  |
| hybrid_kw | fact/en | 12 | 0.718 | 0.369 | 0.853 | 0.962 | 0.000 |  |  |
| hybrid_kw | sweep | 8 | 0.900 | 0.185 | 0.728 | 0.988 | 0.000 |  |  |
| hybrid_kw | sweep/de | 4 | 0.920 | 0.196 | 0.779 | 0.996 | 0.000 |  |  |
| hybrid_kw | sweep/en | 4 | 0.880 | 0.174 | 0.677 | 0.979 | 0.000 |  |  |
| semantic | fact | 20 | 0.690 | 0.383 | 0.797 | 0.919 | 0.000 |  |  |
| semantic | fact/de | 8 | 0.571 | 0.401 | 0.756 | 0.875 | 0.000 |  |  |
| semantic | fact/en | 12 | 0.769 | 0.371 | 0.823 | 0.948 | 0.000 |  |  |
| semantic | mention | 4 |  |  |  |  |  | 0.190 | 0.412 |
| semantic | mention/en | 4 |  |  |  |  |  | 0.190 | 0.412 |
| semantic | sweep | 8 | 0.877 | 0.170 | 0.640 | 0.874 | 0.000 |  |  |
| semantic | sweep/de | 4 | 0.823 | 0.171 | 0.606 | 0.836 | 0.000 |  |  |
| semantic | sweep/en | 4 | 0.931 | 0.170 | 0.674 | 0.912 | 0.000 |  |  |
| fts_any | fact | 20 | 0.308 | 0.152 | 0.418 | 0.523 | 0.000 |  |  |
| fts_any | fact/de | 8 | 0.007 | 0.031 | 0.031 | 0.049 | 0.000 |  |  |
| fts_any | fact/en | 12 | 0.509 | 0.233 | 0.675 | 0.839 | 0.000 |  |  |
| fts_any | mention | 4 |  |  |  |  |  | 0.215 | 0.527 |
| fts_any | mention/en | 4 |  |  |  |  |  | 0.215 | 0.527 |
| fts_any | sweep | 8 | 0.413 | 0.094 | 0.393 | 0.550 | 0.000 |  |  |
| fts_any | sweep/de | 4 | 0.195 | 0.033 | 0.173 | 0.232 | 0.000 |  |  |
| fts_any | sweep/en | 4 | 0.631 | 0.155 | 0.613 | 0.868 | 0.000 |  |  |
| mentions | mention | 4 |  |  |  |  |  | 0.197 | 0.384 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.197 | 0.384 |
| reranked | fact | 20 | 0.668 | 0.379 | 0.797 | 0.797 | 0.000 |  |  |
| reranked | fact/de | 8 | 0.548 | 0.409 | 0.756 | 0.756 | 0.000 |  |  |
| reranked | fact/en | 12 | 0.748 | 0.359 | 0.823 | 0.823 | 0.000 |  |  |
| reranked | mention | 4 |  |  |  |  |  | 0.215 | 0.215 |
| reranked | mention/en | 4 |  |  |  |  |  | 0.215 | 0.215 |
| reranked | sweep | 8 | 0.893 | 0.174 | 0.640 | 0.640 | 0.000 |  |  |
| reranked | sweep/de | 4 | 0.823 | 0.171 | 0.606 | 0.606 | 0.000 |  |  |
| reranked | sweep/en | 4 | 0.963 | 0.177 | 0.674 | 0.674 | 0.000 |  |  |

## 2026-11-16 – suggest_spellings. mentions_spelled accepts the suggestions listed in the case's terms (perfect judge). Separately, a real LLM agent choosing from the suggestions of the distinctive word reached mention recall 0.99-1.00 in all 8 cases (goshawk 0.48->1.00, harris 0.79->0.99, caracara 0.71->1.00, peregrine 0.39->0.99, ferruginous 0.82->1.00, imprint 0.07->1.00), adding 238 passages outside the case term lists, mostly real variants missing from those lists

- code: `310dcb0`
- snapshot: `2026-11-16-full-v3.db` (10882 passages, created 2026-11-16T10:44:48+00:00)
- split: dev
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `1537d6354413`)
- All cases judged.

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 |
|---|---|---|---|---|---|---|---|---|---|
| mentions | mention | 4 |  |  |  |  |  | 0.466 | 0.585 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.466 | 0.585 |
| mentions_spelled | mention | 4 |  |  |  |  |  | 0.474 | 0.659 |
| mentions_spelled | mention/en | 4 |  |  |  |  |  | 0.474 | 0.659 |

## 2026-11-16 – suggest_spellings. mentions_spelled accepts the suggestions listed in the case's terms (perfect judge). Separately, a real LLM agent choosing from the suggestions of the distinctive word reached mention recall 0.99-1.00 in all 8 cases (goshawk 0.48->1.00, harris 0.79->0.99, caracara 0.71->1.00, peregrine 0.39->0.99, ferruginous 0.82->1.00, imprint 0.07->1.00), adding 238 passages outside the case term lists, mostly real variants missing from those lists

- code: `310dcb0`
- snapshot: `2026-11-16-full-v3.db` (10882 passages, created 2026-11-16T10:44:48+00:00)
- split: test
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `1537d6354413`)
- All cases judged.

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 |
|---|---|---|---|---|---|---|---|---|---|
| mentions | mention | 4 |  |  |  |  |  | 0.197 | 0.384 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.197 | 0.384 |
| mentions_spelled | mention | 4 |  |  |  |  |  | 0.197 | 0.384 |
| mentions_spelled | mention/en | 4 |  |  |  |  |  | 0.197 | 0.384 |

## 2026-11-16 – mention_R@all: completeness without the 200-hit cap. Test mention cases query a qualified name ('peregrine falcon', 'imprinted birds') that find_mentions takes literally; with the distinctive word, as the MCP instructions now advise, a real agent reached 0.99-1.00 (see previous entry)

- code: `d6dc80e` (uncommitted changes in src/)
- snapshot: `2026-11-16-full-v3.db` (10882 passages, created 2026-11-16T10:44:48+00:00)
- split: dev
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `1537d6354413`)
- All cases judged.

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 | mention_R@all |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid | fact | 21 | 0.675 | 0.316 | 0.730 | 0.909 | 0.000 |  |  |  |
| hybrid | fact/de | 7 | 0.579 | 0.274 | 0.615 | 0.901 | 0.000 |  |  |  |
| hybrid | fact/en | 14 | 0.724 | 0.337 | 0.788 | 0.913 | 0.000 |  |  |  |
| hybrid | mention | 4 |  |  |  |  |  | 0.447 | 0.657 | 0.891 |
| hybrid | mention/en | 4 |  |  |  |  |  | 0.447 | 0.657 | 0.891 |
| hybrid | sweep | 8 | 0.829 | 0.155 | 0.652 | 0.881 | 0.000 |  |  |  |
| hybrid | sweep/en | 8 | 0.829 | 0.155 | 0.652 | 0.881 | 0.000 |  |  |  |
| mentions | mention | 4 |  |  |  |  |  | 0.466 | 0.585 | 0.745 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.466 | 0.585 | 0.745 |
| mentions_spelled | mention | 4 |  |  |  |  |  | 0.474 | 0.659 | 0.952 |
| mentions_spelled | mention/en | 4 |  |  |  |  |  | 0.474 | 0.659 | 0.952 |

## 2026-11-16 – mention_R@all: completeness without the 200-hit cap. Test mention cases query a qualified name ('peregrine falcon', 'imprinted birds') that find_mentions takes literally; with the distinctive word, as the MCP instructions now advise, a real agent reached 0.99-1.00 (see previous entry)

- code: `d6dc80e` (uncommitted changes in src/)
- snapshot: `2026-11-16-full-v3.db` (10882 passages, created 2026-11-16T10:44:48+00:00)
- split: test
- cases: `benchmark/cases.json`, judgments: `benchmark/judgments.json` (fingerprint `1537d6354413`)
- All cases judged.

| variant | group | cases | nDCG@10 | R@10 | R@50 | R@200 | unjudged@10 | mention_R@50 | mention_R@200 | mention_R@all |
|---|---|---|---|---|---|---|---|---|---|---|
| hybrid | fact | 20 | 0.690 | 0.383 | 0.797 | 0.919 | 0.000 |  |  |  |
| hybrid | fact/de | 8 | 0.571 | 0.401 | 0.756 | 0.875 | 0.000 |  |  |  |
| hybrid | fact/en | 12 | 0.769 | 0.371 | 0.823 | 0.948 | 0.000 |  |  |  |
| hybrid | mention | 4 |  |  |  |  |  | 0.215 | 0.525 | 0.842 |
| hybrid | mention/en | 4 |  |  |  |  |  | 0.215 | 0.525 | 0.842 |
| hybrid | sweep | 8 | 0.877 | 0.170 | 0.640 | 0.874 | 0.000 |  |  |  |
| hybrid | sweep/de | 4 | 0.823 | 0.171 | 0.606 | 0.836 | 0.000 |  |  |  |
| hybrid | sweep/en | 4 | 0.931 | 0.170 | 0.674 | 0.912 | 0.000 |  |  |  |
| mentions | mention | 4 |  |  |  |  |  | 0.197 | 0.384 | 0.569 |
| mentions | mention/en | 4 |  |  |  |  |  | 0.197 | 0.384 | 0.569 |
| mentions_spelled | mention | 4 |  |  |  |  |  | 0.197 | 0.384 | 0.572 |
| mentions_spelled | mention/en | 4 |  |  |  |  |  | 0.197 | 0.384 | 0.572 |
