from services.simulator.m2 import run


def test_m2_simulator_is_reproducible_and_reports_baseline_comparison():
    result = run(seed=7, requests=40)
    assert result == run(seed=7, requests=40)
    assert result["baseline_incidents"] == 40
    assert result["triaged_incidents"] <= result["baseline_incidents"]
    assert 0 <= result["precision"] <= 1
    assert 0 <= result["recall"] <= 1
