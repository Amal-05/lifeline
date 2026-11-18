# Synthetic Lifeline simulation

Runs: 30 · seeds per case: 10

Generated model estimates only; not a field measurement.

| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medical_surge | 500 | Baseline A: group chat | 4.4% | 18.5% | 40.6% | 96.3% | 61.1 | 0.00/0.00 | 0.0% | 0.35 | n/a | 95.0% | 0.00 |
| medical_surge | 500 | Baseline B: server triage | 5.6% | 19.4% | 42.7% | 97.9% | 46.3 | 1.00/0.98 | 27.0% | 1.00 | 37.1 | 96.6% | 0.00 |
| medical_surge | 500 | Lifeline: mesh + triage | 6.2% | 20.0% | 44.2% | 99.4% | 38.8 | 1.00/0.98 | 26.6% | 1.00 | 33.7 | 100.0% | 6.67 |
