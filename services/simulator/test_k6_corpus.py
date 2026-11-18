import json

from packages.protocol.python.lifeline_protocol import EventEnvelope, verify_event
from services.simulator.k6_corpus import write_corpus


def test_k6_corpus_contains_unique_valid_synthetic_events(tmp_path):
    output = tmp_path / "events.jsonl"
    assert write_corpus(5, output, seed=7) == 5
    bundles = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    events = [EventEnvelope.model_validate(bundle["events"][0]) for bundle in bundles]
    assert len({event.event_id for event in events}) == 5
    for event in events:
        verify_event(event)
        assert event.payload["text_original"] == "Synthetic load-test request"
