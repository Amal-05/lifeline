"""Deterministic, testable triage rules; learned providers can implement the same interfaces."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

import h3
from scipy.optimize import linear_sum_assignment

from services.triage.config import DEFAULT_CONFIG, TriageConfig


@dataclass(frozen=True)
class RequestSignal:
    request_id: str
    device_id: str
    created_at: datetime
    latitude: float | None
    longitude: float | None
    accuracy_m: float = 0.0
    people_count: int = 1
    text_en: str = ""
    categories: tuple[str, ...] = ()
    special_needs: tuple[str, ...] = ()
    contact_hash: str | None = None
    perceptual_hash: str | None = None
    water_level: str | None = None
    last_contact_at: datetime | None = None
    pre_registered: bool = False
    battery_pct: int | None = None
    status: str = "received"


class MergeDecision(StrEnum):
    AUTO_MERGED = "auto_merged"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MergeScore:
    score: float
    decision: MergeDecision
    distance_m: float
    features: dict[str, float]
    reason: str = "weighted_similarity"


def _ngrams(text: str) -> Counter[str]:
    normalized = re.sub(r"\s+", " ", text.casefold().strip())
    padded = f"  {normalized}  "
    return Counter(padded[index : index + size] for size in (2, 3, 4) for index in range(max(0, len(padded) - size + 1)))


def multilingual_text_similarity(left: str, right: str) -> float:
    """Cosine similarity over Unicode character n-grams; works without a model download."""
    a, b = _ngrams(left), _ngrams(right)
    if not a or not b:
        return 0.0
    common = a.keys() & b.keys()
    dot = sum(a[token] * b[token] for token in common)
    magnitude_a = math.sqrt(sum(value * value for value in a.values()))
    magnitude_b = math.sqrt(sum(value * value for value in b.values()))
    return max(0.0, min(1.0, dot / (magnitude_a * magnitude_b)))


def haversine_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius = 6_371_000.0
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    delta_phi = math.radians(lat_b - lat_a)
    delta_lambda = math.radians(lon_b - lon_a)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


def _media_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    try:
        distance = (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 0.0
    return float(distance <= 8)


def score_pair(
    a: RequestSignal,
    b: RequestSignal,
    config: TriageConfig = DEFAULT_CONFIG,
) -> MergeScore:
    if a.latitude is None or a.longitude is None or b.latitude is None or b.longitude is None:
        distance = math.inf
    else:
        distance = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
    mean_accuracy = (max(0, a.accuracy_m) + max(0, b.accuracy_m)) / 2
    sigma = config.distance_sigma_base_m + mean_accuracy
    features = {
        "distance": 0.0 if math.isinf(distance) else math.exp(-distance / sigma),
        "text": multilingual_text_similarity(a.text_en, b.text_en),
        "people": 1 - abs(a.people_count - b.people_count) / max(a.people_count, b.people_count, 1),
        "contact": float(a.device_id == b.device_id or (a.contact_hash is not None and a.contact_hash == b.contact_hash)),
        "media": _media_similarity(a.perceptual_hash, b.perceptual_hash),
    }
    weighted = (
        config.distance_weight * features["distance"]
        + config.text_weight * features["text"]
        + config.people_weight * features["people"]
        + config.contact_weight * features["contact"]
        + config.media_weight * features["media"]
    )
    age = abs((a.created_at - b.created_at).total_seconds())
    if a.device_id == b.device_id and distance <= config.merge_distance_m and age <= config.hard_merge_hours * 3600:
        return MergeScore(1.0, MergeDecision.AUTO_MERGED, distance, features, "same_device_repeat")
    if distance > config.maximum_auto_merge_distance_m:
        decision = MergeDecision.NEEDS_REVIEW if weighted >= config.review_threshold else MergeDecision.REJECTED
        return MergeScore(weighted, decision, distance, features, "distance_over_auto_merge_limit")
    if weighted >= config.auto_merge_threshold:
        decision = MergeDecision.AUTO_MERGED
    elif weighted >= config.review_threshold:
        decision = MergeDecision.NEEDS_REVIEW
    else:
        decision = MergeDecision.REJECTED
    return MergeScore(weighted, decision, distance, features)


def candidate_pairs(
    requests: Sequence[RequestSignal], config: TriageConfig = DEFAULT_CONFIG
) -> list[tuple[RequestSignal, RequestSignal]]:
    buckets: dict[str, list[int]] = defaultdict(list)
    request_cells: list[str | None] = []
    for index, request in enumerate(requests):
        if request.latitude is None or request.longitude is None:
            request_cells.append(None)
            continue
        cell = h3.latlng_to_cell(request.latitude, request.longitude, config.h3_resolution)
        request_cells.append(cell)
        buckets[cell].append(index)
    pairs: set[tuple[int, int]] = set()
    window = timedelta(hours=config.candidate_window_hours)
    for index, request in enumerate(requests):
        cell = request_cells[index]
        if cell is None:
            continue
        for neighbour in h3.grid_disk(cell, 1):
            for other_index in buckets.get(neighbour, ()):
                if other_index <= index:
                    continue
                other = requests[other_index]
                if abs(request.created_at - other.created_at) <= window:
                    pairs.add((index, other_index))
    return [(requests[left], requests[right]) for left, right in sorted(pairs)]


WATER_POINTS = {"ankle": 0, "knee": 5, "waist": 10, "chest": 18, "roof": 25}


@dataclass(frozen=True)
class UrgencyResult:
    score: int
    explanation: tuple[dict[str, int | str], ...]


def score_urgency(
    request: RequestSignal,
    now: datetime,
    independent_devices: int = 1,
    config: TriageConfig = DEFAULT_CONFIG,
) -> UrgencyResult:
    if request.status in {"safe", "rescued", "closed"}:
        return UrgencyResult(0, ({"signal": request.status, "points": 0},))
    points: list[tuple[str, int]] = []
    categories, needs = set(request.categories), set(request.special_needs)
    if "trapped" in categories:
        points.append(("trapped", 20))
    if "medical" in categories:
        points.append(("medical_emergency", 20))
    for need, label, value in (
        ("infant", "infant_present", 15),
        ("bedridden", "bedridden", 15),
        ("disabled", "disabled", 15),
        ("elderly", "elderly", 12),
        ("pregnant", "pregnant", 12),
    ):
        if need in needs:
            points.append((label, value))
    water = WATER_POINTS.get((request.water_level or "").casefold(), 0)
    if water:
        points.append((f"water_{request.water_level}", water))
    people = min(10, max(0, request.people_count))
    if people:
        points.append(("people_count", people))
    extra_devices = min(5, max(0, independent_devices - 1))
    if extra_devices:
        points.append(("independent_reports", extra_devices * 2))
    last_contact = request.last_contact_at or request.created_at
    if now - last_contact >= timedelta(hours=6):
        points.append(("no_contact_over_6_hours", 10))
    waiting = min(10, max(0, int((now - request.created_at).total_seconds() // 1800)))
    if waiting:
        points.append(("waiting_time", waiting))
    if request.pre_registered:
        points.append(("pre_registered_household", 15))
    if request.battery_pct is not None and request.battery_pct < 15:
        points.append(("device_battery_below_15_percent", 5))
    total = sum(value for _, value in points)
    if total > 100:
        points.append(("score_cap", 100 - total))
    return UrgencyResult(min(100, total), tuple({"signal": name, "points": value} for name, value in points))


def cluster_by_h3(
    items: Sequence[tuple[str, float, float]], resolution: int = 9
) -> list[list[str]]:
    """Group neighbouring H3 cells into connected incident clusters."""
    cells = [h3.latlng_to_cell(lat, lon, resolution) for _, lat, lon in items]
    parent = list(range(len(items)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    indexes: dict[str, list[int]] = defaultdict(list)
    for index, cell in enumerate(cells):
        indexes[cell].append(index)
    for index, cell in enumerate(cells):
        for neighbour in h3.grid_disk(cell, 1):
            for other in indexes.get(neighbour, ()):
                if other > index:
                    union(index, other)
    groups: dict[int, list[str]] = defaultdict(list)
    for index, (incident_id, _, _) in enumerate(items):
        groups[find(index)].append(incident_id)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])


@dataclass(frozen=True)
class ResourceTeam:
    team_id: str
    latitude: float
    longitude: float
    capacity: int
    skills: frozenset[str] = field(default_factory=frozenset)
    available: bool = True


@dataclass(frozen=True)
class ResourceCluster:
    cluster_id: str
    latitude: float
    longitude: float
    urgency: int
    people_count: int
    water_level: str | None = None
    medical: bool = False


def match_resources(
    clusters: Sequence[ResourceCluster], teams: Sequence[ResourceTeam], speed_m_s: float = 8.0
) -> list[tuple[str, str, float]]:
    available = [team for team in teams if team.available]
    if not clusters or not available:
        return []
    costs: list[list[float]] = []
    for cluster in clusters:
        row = []
        for team in available:
            distance = haversine_m(cluster.latitude, cluster.longitude, team.latitude, team.longitude)
            cost = distance / max(speed_m_s, 0.1)
            capabilities = set(team.skills)
            if cluster.water_level in {"chest", "roof"} and "boat" not in capabilities:
                cost += 100_000
            if cluster.medical and "medic" not in capabilities:
                cost += 100_000
            if team.capacity < cluster.people_count:
                cost += 10_000 + (cluster.people_count - team.capacity) * 100
            row.append(cost - max(0, min(100, cluster.urgency)) * 100)
        costs.append(row)
    rows, columns = linear_sum_assignment(costs)
    return [
        (clusters[row].cluster_id, available[column].team_id, float(costs[row][column]))
        for row, column in zip(rows, columns, strict=True)
    ]


def road_confidence(
    confidence: float,
    reported_at: datetime,
    now: datetime,
    config: TriageConfig = DEFAULT_CONFIG,
) -> float:
    age_hours = max(0.0, (now - reported_at).total_seconds() / 3600)
    return max(0.0, min(1.0, confidence)) * 0.5 ** (age_hours / config.road_half_life_hours)


def replay_request_events(events: Iterable[dict]) -> dict[str, object]:
    """Rebuild one request projection by ordered events, preserving original language text."""
    projection: dict[str, object] = {}
    for event in sorted(events, key=lambda item: (item["hlc"], item["device_id"])):
        kind, payload = event["type"], event["payload"]
        if kind == "sos.created":
            location = payload.get("location", {})
            projection.update(
                request_id=event["request_id"], device_id=event["device_id"], created_hlc=event["hlc"],
                people_count=payload.get("people_count", 1), categories=payload.get("categories", []),
                special_needs=payload.get("special_needs", []), text_original=payload.get("text_original", ""),
                text_en=payload.get("text_en", payload.get("text_original", "")),
                language=payload.get("language", "und"), latitude=location.get("latitude"),
                longitude=location.get("longitude"), accuracy_m=location.get("accuracy_m"),
                location_source=location.get("source", "unavailable"), status="received",
            )
        elif kind == "sos.ping":
            projection["last_contact_hlc"] = event["hlc"]
            projection["sender_state"] = payload.get("state", "still_needs_help")
        elif kind == "status.changed":
            projection["status"] = payload.get("status", projection.get("status", "received"))
            if "urgency_override" in payload:
                projection["urgency_override"] = payload["urgency_override"]
                projection["urgency_override_reason"] = payload.get("reason")
        elif kind == "sos.updated":
            for key in ("people_count", "categories", "special_needs", "text_original", "text_en", "language", "incident_id"):
                if key in payload:
                    projection[key] = payload[key]
    return projection
