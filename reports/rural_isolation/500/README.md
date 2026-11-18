# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rural_isolation | 500 | Baseline A: group chat | 0.5% | 2.4% | 11.0% | 88.6% | 146.1 | 0.00/0.00 | 0.0% | 0.54 | n/a | 95.1% | 0.00 |
| rural_isolation | 500 | Baseline B: server triage | 1.9% | 2.4% | 11.4% | 96.7% | 137.8 | 1.00/0.93 | 16.6% | 0.99 | 131.9 | 98.0% | 0.00 |
| rural_isolation | 500 | Lifeline: mesh + triage | 2.4% | 2.4% | 13.3% | 100.0% | 135.8 | 1.00/1.00 | 17.1% | 1.00 | 129.5 | 100.0% | 0.12 |
