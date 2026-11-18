# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| urban_flood | 500 | Baseline A: group chat | 1.7% | 8.7% | 26.7% | 94.3% | 114.8 | 0.00/0.00 | 0.0% | 0.49 | n/a | 96.9% | 0.00 |
| urban_flood | 500 | Baseline B: server triage | 3.0% | 9.0% | 27.7% | 97.3% | 104.3 | 1.00/0.96 | 23.6% | 1.00 | 93.8 | 98.6% | 0.00 |
| urban_flood | 500 | Lifeline: mesh + triage | 3.3% | 10.3% | 32.0% | 99.3% | 85.4 | 1.00/0.98 | 23.8% | 1.00 | 74.8 | 100.0% | 4.17 |
