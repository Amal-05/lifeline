from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

SCENARIO_DIR = Path("scenarios")
PHONE_COUNTS = (500, 5000, 20000)
METHODS = ("Baseline A: group chat", "Baseline B: server triage", "Lifeline: mesh + triage")


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row[key] is not None]
    return mean(values) if values else None


def _load_scenarios(directory: Path = SCENARIO_DIR) -> dict[str, dict[str, Any]]:
    scenarios = {}
    for path in sorted(directory.glob("*.yaml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        scenarios[str(config["name"])] = config
    return scenarios


def simulate(config: dict[str, Any], phones: int, seed: int) -> list[dict[str, Any]]:
    """Run a seeded synthetic phone/SOS scenario. No real-world data is loaded."""
    rng = random.Random(seed)
    hours = float(config["duration_hours"])
    app_share = float(config["app_share"])
    density = float(config["population"]) / float(config["area_km2"])
    expected = max(1, round(phones * float(config["sos_per_1000_phones_hour"]) * hours / 1000))
    events = []
    for index in range(expected):
        created = rng.random() * hours
        duplicate_share = float(config["duplicate_report_share"])
        truth = index if rng.random() > duplicate_share else max(0, index - rng.randint(1, min(4, index + 1)))
        severity = rng.choices([1, 2, 3, 4, 5], weights=[10, 20, 25, 25, 20])[0]
        vulnerable = rng.random() < float(config["vulnerable_share"])
        isolated = rng.random() < float(config["outage_area_share"])
        recovery = rng.uniform(float(config["tower_recovery_min_hours"]), hours) if isolated else rng.uniform(0, .15)
        app_installed = rng.random() < app_share
        relay_chance = min(.98, app_share * min(1, density / 1000) * min(1, float(config["mesh_range_km"]) / .8) * 1.5)
        mesh = app_installed and rng.random() < relay_chance
        if isolated and mesh:
            lifeline_time = created + rng.uniform(.05, min(1.5, max(.1, hours-created)))
        elif isolated:
            lifeline_time = max(created, recovery)
        else:
            lifeline_time = created + rng.uniform(.01, .15)
        events.append({"truth": truth, "created": created, "severity": severity, "vulnerable": vulnerable,
                       "A": max(created, recovery) + rng.uniform(.05, .8),
                       "B": max(created, recovery) + rng.uniform(.02, .3), "Lifeline": lifeline_time,
                       "mesh_bytes": rng.randint(200, 900) if mesh else 0})

    truth_rows: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        truth_rows.setdefault(event["truth"], []).append(event)
    truth_ids = set(truth_rows)
    urgent = {truth for truth, rows in truth_rows.items() if max(row["severity"] for row in rows) >= 4}
    output = []
    for label, key, dedupe in ((METHODS[0], "A", False), (METHODS[1], "B", True), (METHODS[2], "Lifeline", True)):
        delivered = [event for event in events if event[key] <= hours]
        grouped: dict[int, list[dict[str, Any]]] = {}
        for event in delivered:
            grouped.setdefault(event["truth"], []).append(event)
        detected_count = len(grouped) if dedupe else len(delivered)
        reduced = len(delivered) - detected_count if dedupe else 0
        true_duplicates = sum(len(rows) - 1 for rows in truth_rows.values())
        delivery = {f"delivered_{cutoff}h_pct": round(100 * sum(event[key] <= cutoff for event in events) / len(events), 2)
                    for cutoff in (1, 3, 6, 12)}
        latencies = [(event[key] - event["created"]) * 60 for event in delivered]
        if dedupe:
            ranked_groups = sorted(grouped.values(), key=lambda rows: max(row["severity"] for row in rows), reverse=True)
        else:
            ranked_groups = [[event] for event in sorted(delivered, key=lambda row: row["created"])]
        ranked = ranked_groups
        dcg = sum(1 / (index + 1) for index, rows in enumerate(ranked[:20]) if max(row["severity"] for row in rows) >= 4)
        idcg = sum(1 / (index + 1) for index in range(min(20, len(urgent))))
        urgent_latency = sorted(min((event[key] - event["created"]) * 60 for event in rows if event[key] <= hours)
                                for truth, rows in truth_rows.items() if truth in urgent and any(event[key] <= hours for event in rows))
        top10_latency = urgent_latency[min(max(0, (len(urgent) + 9) // 10 - 1), len(urgent_latency) - 1)] if urgent_latency else None
        assignments = [min(event[key] - event["created"] for event in rows) * 60 + 8 for rows in grouped.values()] if dedupe else []
        vulnerable_count = sum(event["vulnerable"] for event in events)
        vulnerable_delivered = sum(event["vulnerable"] and event[key] <= hours for event in events)
        output.append({"method": label, "phones": phones, "sos_events": len(events),
                       "unique_ground_truth_incidents": len(truth_ids), "delivered_events": len(delivered), **delivery,
                       "mean_latency_minutes": round(mean(latencies), 2) if latencies else None,
                       "duplicate_precision": 1.0 if dedupe else 0.0,
                       "duplicate_recall": round(min(1, reduced / max(1, true_duplicates)), 4) if dedupe else 0.0,
                       "duplicates_reduced": reduced,
                       "manual_review_reduction_pct": round(100 * reduced / max(1, len(delivered)), 2),
                       "ndcg_at_20": round(dcg / idcg, 4) if idcg else 1.0,
                       "time_to_top_10pct_minutes": round(top10_latency, 2) if top10_latency is not None else None,
                       "mean_assignment_minutes": round(mean(assignments), 2) if assignments else None,
                       "vulnerable_coverage_pct": round(100 * vulnerable_delivered / max(1, vulnerable_count), 2),
                       "mesh_bytes_per_phone": round(sum(event["mesh_bytes"] for event in events) / phones, 2) if key == "Lifeline" else 0})
    return output


def run_suite(seeds: int = 10, phone_counts: tuple[int, ...] = PHONE_COUNTS,
              scenarios: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if seeds < 1:
        raise ValueError("seeds must be positive")
    configs = scenarios or _load_scenarios()
    cases = []
    for name, config in configs.items():
        for phones in phone_counts:
            runs = [row for seed in range(1, seeds + 1) for row in simulate(config, phones, seed)]
            cases.append({"scenario": name, "phones": phones, "seed_count": seeds, "runs": runs})
    return {"data_classification": "synthetic", "scenario_count": len(configs),
            "phone_counts": list(phone_counts), "seeds_per_case": seeds,
            "runs_total": len(cases) * seeds * len(METHODS), "cases": cases}


def write_reports(result: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    rows = [row for case in result["cases"] for row in case["runs"]]
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "simulation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = ["# Synthetic Lifeline simulation", "", f"Runs: {result['runs_total']} · seeds per case: {result['seeds_per_case']}",
             "", "Generated model estimates only; not a field measurement.", "",
             "| Scenario | Phones | Method | ≤1h | ≤3h | ≤6h | ≤12h | Latency min | Dedup P/R | Review reduction | NDCG@20 | Assignment min | Vulnerable coverage | Mesh bytes/phone |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for case in result["cases"]:
        for method in METHODS:
            selected = [row for row in case["runs"] if row["method"] == method]
            assignment = _mean(selected, "mean_assignment_minutes")
            assignment_text = f"{assignment:.1f}" if assignment is not None else "n/a"
            lines.append(f"| {case['scenario']} | {case['phones']:,} | {method} | {_mean(selected, 'delivered_1h_pct'):.1f}% | {_mean(selected, 'delivered_3h_pct'):.1f}% | {_mean(selected, 'delivered_6h_pct'):.1f}% | {_mean(selected, 'delivered_12h_pct'):.1f}% | {_mean(selected, 'mean_latency_minutes'):.1f} | {_mean(selected, 'duplicate_precision'):.2f}/{_mean(selected, 'duplicate_recall'):.2f} | {_mean(selected, 'manual_review_reduction_pct'):.1f}% | {_mean(selected, 'ndcg_at_20'):.2f} | {assignment_text} | {_mean(selected, 'vulnerable_coverage_pct'):.1f}% | {_mean(selected, 'mesh_bytes_per_phone'):.2f} |")
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    bars = []
    for index, row in enumerate(rows[:30]):
        x, h = 50 + index * 29, row["delivered_3h_pct"] * 3
        color = "#bd512e" if row["method"].startswith("Baseline A") else "#597c98" if row["method"].startswith("Baseline B") else "#287b65"
        bars.append(f'<rect x="{x}" y="{440-h:.1f}" width="18" height="{h:.1f}" fill="{color}"/>')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 480"><rect width="100%" height="100%" fill="white"/><text x="30" y="30" font-family="sans-serif" font-size="18">Delivery within 3 hours (%) · first 30 runs</text><line x1="30" y1="440" x2="930" y2="440" stroke="#333"/>' + "".join(bars) + "</svg>"
    (output / "delivery-3h.svg").write_text(svg, encoding="utf-8")
    dedup_bars = []
    for index, row in enumerate(rows[:30]):
        x, h = 50 + index * 29, row["manual_review_reduction_pct"] * 3
        color = "#bd512e" if row["method"].startswith("Baseline A") else "#597c98" if row["method"].startswith("Baseline B") else "#287b65"
        dedup_bars.append(f'<rect x="{x}" y="{440-h:.1f}" width="18" height="{h:.1f}" fill="{color}"/>')
    dedup_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 480"><rect width="100%" height="100%" fill="white"/><text x="30" y="30" font-family="sans-serif" font-size="18">Duplicate workload reduction (%) · first 30 runs</text><line x1="30" y1="440" x2="930" y2="440" stroke="#333"/>' + "".join(dedup_bars) + "</svg>"
    (output / "dedup-reduction.svg").write_text(dedup_svg, encoding="utf-8")


def main() -> None:
    scenarios = _load_scenarios()
    parser = argparse.ArgumentParser(description="Run synthetic offline-first Lifeline scenarios")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--scenario", choices=["all", *scenarios], default="all")
    parser.add_argument("--phones", type=int, choices=PHONE_COUNTS, action="append")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--output", default="docs/results/m4-simulation.json")
    args = parser.parse_args()
    selected = scenarios if args.scenario == "all" else {args.scenario: scenarios[args.scenario]}
    result = run_suite(args.seeds, tuple(args.phones or PHONE_COUNTS), selected)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for case in result["cases"]:
        write_reports({**result, "cases": [case], "runs_total": len(case["runs"])}, Path(args.output_dir) / case["scenario"] / str(case["phones"]))
    print(json.dumps({"runs_total": result["runs_total"], "cases": len(result["cases"]), "output_dir": args.output_dir}))


if __name__ == "__main__":
    main()
