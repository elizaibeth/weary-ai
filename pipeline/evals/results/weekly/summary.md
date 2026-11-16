# Ranking eval: 31 days x 3 samples

Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.

| variant | P(rel=3)@1 | P(rel=2)@1 | RR(rel=2) | nDCG@5 | model calls/day |
|---|---|---|---|---|---|
| legacy | 0.452 ± 0.056 | 0.796 ± 0.067 | 0.873 ± 0.039 | 0.804 ± 0.011 | 1.0 |
| +cluster | 0.430 ± 0.019 | 0.806 ± 0.085 | 0.878 ± 0.048 | 0.801 ± 0.015 | 1.0 |
| +permutations | 0.441 ± 0.019 | 0.785 ± 0.019 | 0.866 ± 0.012 | 0.799 ± 0.006 | 2.0 |
| +expected-value | 0.473 ± 0.067 | 0.860 ± 0.037 | 0.914 ± 0.016 | 0.816 ± 0.010 | 1.0 |
| +novelty | 0.419 ± 0.056 | 0.774 ± 0.056 | 0.863 ± 0.035 | 0.796 ± 0.009 | 1.0 |
| all | 0.409 ± 0.019 | 0.796 ± 0.037 | 0.881 ± 0.021 | 0.786 ± 0.013 | 2.0 |
