# Ranking eval: 20 days x 3 samples

Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.

| variant | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | model calls/day |
|---|---|---|---|---|---|
| legacy | 0.450 ± 0.087 | 0.767 ± 0.058 | 0.861 ± 0.028 | 0.846 ± 0.010 | 1.0 |
| +cluster | 0.433 ± 0.076 | 0.783 ± 0.076 | 0.869 ± 0.035 | 0.840 ± 0.010 | 1.0 |
| +permutations | 0.483 ± 0.076 | 0.767 ± 0.029 | 0.869 ± 0.026 | 0.855 ± 0.021 | 2.0 |
| +expected-value | 0.467 ± 0.104 | 0.850 ± 0.000 | 0.906 ± 0.009 | 0.853 ± 0.013 | 1.0 |
| +novelty | 0.450 ± 0.087 | 0.750 ± 0.050 | 0.854 ± 0.023 | 0.843 ± 0.012 | 1.0 |
| all | 0.500 ± 0.050 | 0.833 ± 0.058 | 0.901 ± 0.032 | 0.850 ± 0.014 | 2.0 |
