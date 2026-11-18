# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medical_surge | 20,000 | Baseline A: group chat | 3.0% | 14.7% | 36.5% | 95.1% | 69.2 | 0.00/0.00 | 0.0% | 0.42 | n/a | 94.9% | 0.00 |
| medical_surge | 20,000 | Baseline B: server triage | 4.3% | 16.4% | 38.7% | 98.1% | 55.6 | 1.00/0.97 | 25.8% | 1.00 | 50.0 | 97.9% | 0.00 |
| medical_surge | 20,000 | Lifeline: mesh + triage | 4.9% | 17.9% | 40.8% | 99.5% | 45.5 | 1.00/0.99 | 26.1% | 1.00 | 41.0 | 99.4% | 7.28 |
