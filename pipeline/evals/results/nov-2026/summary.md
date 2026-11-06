# Ranking eval: 19 days x 3 samples

Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.

| variant | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | model calls/day |
|---|---|---|---|---|---|
| legacy | 0.544 ± 0.061 | 0.842 ± 0.053 | 0.907 ± 0.028 | 0.775 ± 0.039 | 1.0 |
| +cluster | 0.526 ± 0.053 | 0.842 ± 0.053 | 0.907 ± 0.028 | 0.781 ± 0.022 | 1.0 |
| +permutations | 0.544 ± 0.030 | 0.842 ± 0.053 | 0.911 ± 0.029 | 0.787 ± 0.023 | 2.0 |
| +expected-value | 0.579 ± 0.000 | 0.860 ± 0.030 | 0.919 ± 0.018 | 0.779 ± 0.037 | 1.0 |
| +novelty | 0.544 ± 0.061 | 0.842 ± 0.053 | 0.907 ± 0.028 | 0.776 ± 0.039 | 1.0 |
| all | 0.632 ± 0.000 | 0.877 ± 0.030 | 0.930 ± 0.015 | 0.796 ± 0.026 | 2.0 |
