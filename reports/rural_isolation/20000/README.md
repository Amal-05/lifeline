# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rural_isolation | 20,000 | Baseline A: group chat | 0.8% | 4.4% | 13.5% | 92.1% | 168.5 | 0.00/0.00 | 0.0% | 0.39 | n/a | 92.0% | 0.00 |
| rural_isolation | 20,000 | Baseline B: server triage | 1.3% | 4.8% | 15.7% | 96.9% | 156.6 | 1.00/0.94 | 17.0% | 1.00 | 146.1 | 96.7% | 0.00 |
| rural_isolation | 20,000 | Lifeline: mesh + triage | 1.5% | 5.1% | 17.1% | 99.9% | 149.7 | 1.00/1.00 | 17.6% | 1.00 | 137.7 | 100.0% | 0.24 |
