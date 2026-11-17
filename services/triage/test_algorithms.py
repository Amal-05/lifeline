from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from services.triage.algorithms import (
    MergeDecision,
    RequestSignal,
    ResourceCluster,
    ResourceTeam,
    candidate_pairs,
    cluster_by_h3,
    match_resources,
    multilingual_text_similarity,
    replay_request_events,
    road_confidence,
    score_pair,
    score_urgency,
)

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


def request(request_id="a", **overrides):
    data = {
        "request_id": request_id,
        "device_id": "device-a",
        "created_at": NOW,
        "latitude": 10.0,
        "longitude": 76.0,
        "accuracy_m": 5,
        "people_count": 2,
        "text_en": "people trapped near school",
        "categories": ("trapped",),
    }
    data.update(overrides)
    return RequestSignal(**data)


def test_same_device_repeat_hard_rule_and_far_never_auto_merges():
    repeated = request("b")
    result = score_pair(request(), repeated)
    assert result.decision == MergeDecision.AUTO_MERGED
    assert result.reason == "same_device_repeat"
    far = request("far", latitude=10.01, longitude=76.0, device_id="device-b")
    result = score_pair(request(), far)
    assert result.decision != MergeDecision.AUTO_MERGED


def test_candidate_pairs_use_h3_neighbours_and_72_hour_window():
    near = request("near", device_id="device-b", latitude=10.0001)
    old = request("old", device_id="device-c", created_at=NOW - timedelta(hours=73))
    assert [(a.request_id, b.request_id) for a, b in candidate_pairs([request(), near, old])] == [("a", "near")]


def test_multilingual_text_similarity_is_unicode_safe_and_bounded():
    assert multilingual_text_similarity("மருத்துவ உதவி", "மருத்துவ உதவி") == 1.0
    assert 0 <= multilingual_text_similarity("അടിയന്തരസഹായം", "पानी चाहिए") <= 1


def test_urgency_explanation_matches_spec_and_safe_is_zero():
    signal = request(
        categories=("medical", "trapped"), special_needs=("infant", "elderly", "pregnant"),
        water_level="roof", pre_registered=True, battery_pct=9,
        last_contact_at=NOW - timedelta(hours=7), people_count=20,
        created_at=NOW - timedelta(hours=7),
    )
    result = score_urgency(signal, NOW, independent_devices=6)
    assert result.score == 100
    assert {item["signal"] for item in result.explanation} >= {
        "trapped", "medical_emergency", "infant_present", "water_roof", "independent_reports", "score_cap"
    }
    safe = score_urgency(request(status="rescued"), NOW)
    assert safe.score == 0


def test_h3_clusters_join_neighbours_but_not_distant_incidents():
    groups = cluster_by_h3([("a", 10.0, 76.0), ("b", 10.00001, 76.0), ("c", 12.0, 76.0)])
    assert len(groups) == 2
    assert ["a", "b"] in groups


def test_resource_matching_respects_skills_capacity_and_availability():
    clusters = [ResourceCluster("flood", 10.0, 76.0, 90, 3, water_level="chest")]
    teams = [
        ResourceTeam("truck", 10.0, 76.0, 8, frozenset({"medic"})),
        ResourceTeam("boat", 10.01, 76.0, 4, frozenset({"boat", "medic"})),
        ResourceTeam("offline", 10.0, 76.0, 10, frozenset({"boat"}), available=False),
    ]
    assert match_resources(clusters, teams)[0][:2] == ("flood", "boat")


def test_road_confidence_half_life_is_six_hours():
    assert road_confidence(0.8, NOW - timedelta(hours=6), NOW) == 0.4


def test_projection_replay_is_hlc_ordered_and_keeps_original_text():
    events = [
        {"hlc": "2026-01-01T00:00:02Z-0000-b", "device_id": "b", "type": "status.changed", "request_id": "r", "payload": {"status": "assigned"}},
        {"hlc": "2026-01-01T00:00:01Z-0000-a", "device_id": "a", "type": "sos.created", "request_id": "r", "payload": {"text_original": "അപകടം", "text_en": "danger", "language": "ml", "location": {}}},
    ]
    projection = replay_request_events(events)
    assert projection["status"] == "assigned"
    assert projection["text_original"] == "അപകടം"
    assert projection["text_en"] == "danger"


@given(st.floats(min_value=0, max_value=1), st.integers(min_value=0, max_value=48))
def test_road_confidence_is_bounded_and_never_increases(confidence, age_hours):
    reported = NOW - timedelta(hours=age_hours)
    result = road_confidence(confidence, reported, NOW)
    assert 0 <= result <= confidence
