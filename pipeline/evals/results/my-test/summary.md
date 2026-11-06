# Ranking eval: 19 days x 3 samples

Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.

| variant | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | model calls/day |
|---|---|---|---|---|---|
| legacy | 0.491 ± 0.030 | 0.825 ± 0.030 | 0.898 ± 0.018 | 0.758 ± 0.029 | 1.0 |
| +cluster | 0.491 ± 0.030 | 0.825 ± 0.030 | 0.898 ± 0.018 | 0.747 ± 0.018 | 1.0 |
| +permutations | 0.561 ± 0.061 | 0.842 ± 0.053 | 0.912 ± 0.026 | 0.784 ± 0.017 | 2.0 |
| +expected-value | 0.579 ± 0.053 | 0.842 ± 0.053 | 0.906 ± 0.031 | 0.767 ± 0.037 | 1.0 |
| +novelty | 0.491 ± 0.030 | 0.825 ± 0.030 | 0.901 ± 0.020 | 0.757 ± 0.028 | 1.0 |
| all | 0.614 ± 0.061 | 0.877 ± 0.030 | 0.930 ± 0.015 | 0.788 ± 0.026 | 2.0 |
