# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medical_surge | 5,000 | Baseline A: group chat | 3.6% | 15.5% | 36.5% | 95.0% | 68.3 | 0.00/0.00 | 0.0% | 0.43 | n/a | 94.6% | 0.00 |
| medical_surge | 5,000 | Baseline B: server triage | 4.8% | 16.9% | 38.8% | 98.1% | 55.7 | 1.00/0.97 | 25.5% | 1.00 | 50.4 | 97.9% | 0.00 |
| medical_surge | 5,000 | Lifeline: mesh + triage | 5.5% | 18.3% | 40.9% | 99.5% | 45.1 | 1.00/0.99 | 25.8% | 1.00 | 40.5 | 99.6% | 7.41 |
