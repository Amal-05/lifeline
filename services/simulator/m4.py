from __future__ import annotations

import argparse
import json
from statistics import mean

from services.simulator.m2 import run

SCENARIOS = {"urban_flood": 500, "rural_isolation": 200, "medical_surge": 350}


def run_suite(seeds: int = 10) -> dict:
    runs = []
    for scenario, requests in SCENARIOS.items():
        results = [run(seed=seed, requests=requests) for seed in range(1, seeds + 1)]
        runs.append({"scenario": scenario, "requests_per_seed": requests, "seed_count": seeds,
                     "runs": results, "mean_precision": mean(row["precision"] for row in results),
                     "mean_recall": mean(row["recall"] for row in results),
                     "mean_duplicate_reduction": mean(row["duplicates_reduced"] for row in results)})
    return {"data_classification": "synthetic", "runs_total": seeds * len(SCENARIOS), "scenarios": runs}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic M4 scenarios")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--output", default="docs/results/m4-simulation.json")
    args = parser.parse_args()
    result = run_suite(args.seeds)
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({"runs_total": result["runs_total"], "output": args.output}))


if __name__ == "__main__":
    main()
