# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| urban_flood | 20,000 | Baseline A: group chat | 1.8% | 8.3% | 25.0% | 93.6% | 123.4 | 0.00/0.00 | 0.0% | 0.34 | n/a | 94.2% | 0.00 |
| urban_flood | 20,000 | Baseline B: server triage | 2.7% | 9.0% | 27.0% | 97.5% | 110.8 | 1.00/0.95 | 22.8% | 1.00 | 98.7 | 97.7% | 0.00 |
| urban_flood | 20,000 | Lifeline: mesh + triage | 3.2% | 10.6% | 30.2% | 99.7% | 95.7 | 1.00/0.99 | 23.2% | 1.00 | 84.8 | 99.8% | 3.86 |
