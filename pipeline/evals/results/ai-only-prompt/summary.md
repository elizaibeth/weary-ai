# Ranking prompt comparison: 20 days x 3 samples

Production ranking settings. Mean ± spread across samples. Off-topic first: the first candidate is graded 0.

| prompt | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | off-topic first |
|---|---|---|---|---|---|
| previous | 0.217 ± 0.062 | 0.417 ± 0.024 | 0.595 ± 0.013 | 0.502 ± 0.025 | 0.583 ± 0.024 |
| ai-only rule | 0.533 ± 0.062 | 0.850 ± 0.041 | 0.902 ± 0.023 | 0.816 ± 0.020 | 0.033 ± 0.024 |
| current | 0.500 ± 0.041 | 0.833 ± 0.047 | 0.901 ± 0.026 | 0.850 ± 0.012 | 0.000 ± 0.000 |

Grade of the first pick, current vs previous: better on 15 days (2026-10-06, 2026-10-08, 2026-10-14, 2026-10-15, 2026-10-19, 2026-10-20, 2026-10-21, 2026-10-23, 2026-10-26, 2026-10-28, 2026-10-29, 2026-11-02, 2026-11-03, 2026-11-04, 2026-11-06), worse on 2 (2026-10-22, 2026-10-27), the same on 3.
