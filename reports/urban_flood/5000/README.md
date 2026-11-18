# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| urban_flood | 5,000 | Baseline A: group chat | 1.9% | 8.4% | 25.1% | 94.0% | 127.7 | 0.00/0.00 | 0.0% | 0.42 | n/a | 93.3% | 0.00 |
| urban_flood | 5,000 | Baseline B: server triage | 2.8% | 9.1% | 27.4% | 97.4% | 115.7 | 1.00/0.95 | 22.6% | 1.00 | 103.0 | 98.2% | 0.00 |
| urban_flood | 5,000 | Lifeline: mesh + triage | 3.1% | 10.6% | 30.8% | 99.7% | 100.0 | 1.00/0.99 | 23.0% | 1.00 | 89.4 | 99.6% | 3.57 |
