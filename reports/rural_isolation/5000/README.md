# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rural_isolation | 5,000 | Baseline A: group chat | 0.7% | 3.6% | 12.5% | 91.4% | 170.9 | 0.00/0.00 | 0.0% | 0.45 | n/a | 90.6% | 0.00 |
| rural_isolation | 5,000 | Baseline B: server triage | 1.1% | 4.2% | 14.9% | 97.1% | 160.0 | 1.00/0.94 | 17.6% | 1.00 | 150.7 | 96.3% | 0.00 |
| rural_isolation | 5,000 | Lifeline: mesh + triage | 1.3% | 4.5% | 16.5% | 100.0% | 152.1 | 1.00/1.00 | 18.1% | 1.00 | 141.3 | 100.0% | 0.33 |
