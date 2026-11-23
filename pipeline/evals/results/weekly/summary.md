# Ranking eval: 38 days x 3 samples

Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.

| variant | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | model calls/day |
|---|---|---|---|---|---|
| legacy | 0.404 ± 0.061 | 0.781 ± 0.076 | 0.860 ± 0.045 | 0.785 ± 0.010 | 1.0 |
| +cluster | 0.377 ± 0.015 | 0.789 ± 0.091 | 0.867 ± 0.052 | 0.785 ± 0.020 | 1.0 |
| +permutations | 0.412 ± 0.015 | 0.763 ± 0.026 | 0.853 ± 0.014 | 0.779 ± 0.008 | 2.0 |
| +expected-value | 0.456 ± 0.066 | 0.860 ± 0.030 | 0.914 ± 0.012 | 0.811 ± 0.010 | 1.0 |
| +novelty | 0.377 ± 0.061 | 0.763 ± 0.070 | 0.852 ± 0.043 | 0.778 ± 0.008 | 1.0 |
| all | 0.412 ± 0.015 | 0.807 ± 0.015 | 0.889 ± 0.001 | 0.778 ± 0.002 | 2.0 |
