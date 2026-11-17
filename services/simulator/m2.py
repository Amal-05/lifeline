from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta

from services.triage.algorithms import MergeDecision, RequestSignal, score_pair


def run(seed: int = 1, requests: int = 500) -> dict[str, float | int]:
    """Generate deterministic synthetic SOS clusters and compare triage with no dedup."""
    rng = random.Random(seed)
    now = datetime.now(UTC)
    signals: list[RequestSignal] = []
    truth: dict[str, str] = {}
    for index in range(requests):
        incident = f"incident-{index // 5}"
        lat_base = 10.0 + (index // 5) * 0.01
        lon_base = 76.0 + (index // 5) * 0.01
        people_count = (index // 5) % 4 + 1
        signal = RequestSignal(
            request_id=f"request-{index:06d}", device_id=f"device-{index:06d}",
            created_at=now - timedelta(minutes=rng.randrange(0, 120)),
            latitude=lat_base + rng.uniform(-0.00008, 0.00008),
            longitude=lon_base + rng.uniform(-0.00008, 0.00008), accuracy_m=10,
            people_count=people_count, text_en="trapped need water medical help",
            categories=("medical",), special_needs=(), contact_hash=incident,
            perceptual_hash=None, water_level=None, last_contact_at=now,
        )
        signals.append(signal)
        truth[signal.request_id] = incident
    predicted: set[tuple[str, str]] = set()
    expected: set[tuple[str, str]] = set()
    # Compare a bounded set of temporally adjacent reports (matches the production spatial window).
    for index, left in enumerate(signals):
        for right in signals[index + 1:index + 25]:
            same = truth[left.request_id] == truth[right.request_id]
            if same:
                expected.add((left.request_id, right.request_id))
            if score_pair(left, right).decision == MergeDecision.AUTO_MERGED:
                predicted.add((left.request_id, right.request_id))
    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else 1.0
    recall = true_positive / len(expected) if expected else 1.0
    parent = list(range(requests))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    indexes = {signal.request_id: index for index, signal in enumerate(signals)}
    for left_id, right_id in predicted:
        left, right = find(indexes[left_id]), find(indexes[right_id])
        parent[right] = left
    merged_count = requests - len({find(index) for index in range(requests)})
    return {
        "seed": seed, "requests": requests, "baseline_incidents": requests,
        "triaged_incidents": requests - merged_count, "duplicates_reduced": merged_count,
        "precision": precision, "recall": recall,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic M2 triage metrics")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--requests", type=int, default=500)
    args = parser.parse_args()
    print(json.dumps(run(args.seed, args.requests), indent=2))


if __name__ == "__main__":
    main()
