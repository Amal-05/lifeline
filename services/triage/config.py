from dataclasses import dataclass


@dataclass(frozen=True)
class TriageConfig:
    h3_resolution: int = 10
    candidate_window_hours: int = 72
    merge_distance_m: float = 100.0
    hard_merge_hours: int = 2
    maximum_auto_merge_distance_m: float = 300.0
    distance_sigma_base_m: float = 30.0
    auto_merge_threshold: float = 0.80
    review_threshold: float = 0.55
    distance_weight: float = 0.35
    text_weight: float = 0.25
    people_weight: float = 0.10
    contact_weight: float = 0.20
    media_weight: float = 0.10
    road_half_life_hours: float = 6.0
    road_expiry_confidence: float = 0.20


DEFAULT_CONFIG = TriageConfig()
