import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from nacl.signing import SigningKey

from packages.protocol.python.lifeline_protocol import (
    HybridLogicalClock,
    merge_event_sets,
    sign_event,
    verify_event,
)


def make_event(seed: int):
    key = SigningKey(bytes([seed % 256]) * 32)
    return sign_event({"event_id": f"{seed:026d}",
                       "hlc": f"2026-01-01T00:00:00.000Z-0000-{seed}", "type": "sos.created",
                       "request_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV", "payload": {"n": seed}}, key)


def test_signing_verifies_and_tampering_fails():
    event = make_event(1)
    verify_event(event)
    with pytest.raises(ValueError, match="signature"):
        verify_event(event.model_copy(update={"payload": {"n": 9}}))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.sets(st.integers(min_value=0, max_value=255), max_size=12))
def test_merge_is_idempotent_commutative_and_order_independent(values):
    events = [make_event(n) for n in sorted(values)]
    assert merge_event_sets(events, events) == merge_event_sets(events)
    assert merge_event_sets(events, []) == merge_event_sets([], events)
    assert merge_event_sets(events) == merge_event_sets(list(reversed(events)))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.integers(min_value=0, max_value=255), max_size=12))
def test_merge_is_associative_and_converges(values):
    events = [make_event(n) for n in dict.fromkeys(values)]
    left, right = events[::2], events[1::2]
    assert merge_event_sets(merge_event_sets(left, right), events) == merge_event_sets(left, merge_event_sets(right, events))


def test_hlc_is_monotonic_and_merges_remote_clock():
    clock = HybridLogicalClock("node", wall_ms=1000)
    assert clock.tick(1000) < clock.tick(1000)
    assert "node" in clock.receive("1970-01-01T00:00:02.000Z-0004-other", now_ms=1000)
