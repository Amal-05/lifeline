from services.simulator.m4 import run_suite


def test_m4_runs_all_scenarios_for_each_seed():
    result = run_suite(seeds=2)
    assert result["runs_total"] == 6
    assert {row["scenario"] for row in result["scenarios"]} == {
        "urban_flood", "rural_isolation", "medical_surge"
    }
    assert all(row["seed_count"] == 2 for row in result["scenarios"])
