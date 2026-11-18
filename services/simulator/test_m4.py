from services.simulator.m4 import METHODS, run_suite, write_reports


def test_m4_runs_scenarios_phone_scales_and_all_baselines():
    result = run_suite(seeds=2)
    assert result["runs_total"] == 54
    assert len(result["cases"]) == 9
    assert {row["scenario"] for row in result["cases"]} == {"urban_flood", "rural_isolation", "medical_surge"}
    assert {row["phones"] for row in result["cases"]} == {500, 5000, 20000}
    assert all(row["seed_count"] == 2 and {run["method"] for run in row["runs"]} == set(METHODS)
               for row in result["cases"])


def test_m4_writes_csv_chart_and_markdown_report(tmp_path):
    result = run_suite(seeds=1, phone_counts=(500,), scenarios={"urban_flood": {
        "name": "urban_flood", "duration_hours": 12, "app_share": .4, "population": 10000,
        "area_km2": 50, "sos_per_1000_phones_hour": 3, "duplicate_report_share": .3,
        "vulnerable_share": .2, "outage_area_share": .5, "tower_recovery_min_hours": 2,
        "mesh_range_km": .4,
    }})
    case = result["cases"][0]
    write_reports({**result, "cases": [case]}, tmp_path)
    assert {"comparison.csv", "simulation.json", "README.md", "delivery-3h.svg", "dedup-reduction.svg"} <= {path.name for path in tmp_path.iterdir()}
    assert "Baseline A" in (tmp_path / "README.md").read_text()
