# Ranking eval: 24 days x 3 samples

Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.

| variant | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | model calls/day |
|---|---|---|---|---|---|
| legacy | 0.444 ± 0.064 | 0.764 ± 0.064 | 0.859 ± 0.032 | 0.842 ± 0.004 | 1.0 |
| +cluster | 0.417 ± 0.042 | 0.778 ± 0.087 | 0.866 ± 0.043 | 0.836 ± 0.010 | 1.0 |
| +permutations | 0.458 ± 0.042 | 0.764 ± 0.024 | 0.863 ± 0.016 | 0.847 ± 0.007 | 2.0 |
| +expected-value | 0.472 ± 0.087 | 0.847 ± 0.024 | 0.907 ± 0.005 | 0.853 ± 0.012 | 1.0 |
| +novelty | 0.444 ± 0.064 | 0.736 ± 0.048 | 0.846 ± 0.025 | 0.838 ± 0.002 | 1.0 |
| all | 0.458 ± 0.042 | 0.819 ± 0.048 | 0.897 ± 0.026 | 0.844 ± 0.016 | 2.0 |
