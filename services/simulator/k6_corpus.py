from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

from nacl.signing import SigningKey

from packages.protocol.python.lifeline_protocol import HybridLogicalClock, new_ulid, sign_event


def write_corpus(events: int, output: Path, seed: int = 1) -> int:
    if events < 1:
        raise ValueError("events must be positive")
    key = SigningKey(bytes.fromhex(f"{seed:064x}"))
    device_id = base64.urlsafe_b64encode(bytes(key.verify_key)).decode().rstrip("=")
    start_ms = int(time.time() * 1000)
    clock = HybridLogicalClock(device_id[:8], start_ms)
    highest_hlc = HybridLogicalClock(device_id[:8], start_ms + events)._format()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for _ in range(events):
            event = sign_event({
                "event_id": new_ulid(),
                "hlc": clock.tick(start_ms + _),
                "type": "sos.created",
                "request_id": new_ulid(),
                "payload": {
                    "people_count": 1,
                    "categories": ["medical"],
                    "special_needs": [],
                    "text_original": "Synthetic load-test request",
                    "language": "en",
                    "location": {"latitude": 10.0, "longitude": 76.0, "accuracy_m": 25, "source": "manual"},
                },
                "hops": 0,
            }, key)
            bundle = {"protocol_version": 1, "events": [event.model_dump()],
                      "known_event_ids": [], "highest_hlc_by_device": {device_id: highest_hlc}}
            handle.write(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False) + "\n")
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic signed sync workload corpus")
    parser.add_argument("--events", type=int, default=60000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("reports/k6-sync/events.jsonl"))
    args = parser.parse_args()
    count = write_corpus(args.events, args.output, args.seed)
    print(json.dumps({"events": count, "output": str(args.output), "data_classification": "synthetic"}))


if __name__ == "__main__":
    main()
