"""Boundary contracts for controlled robustness experiments, not score targets."""
from pathlib import Path

import numpy as np
import pandas as pd

from energy_failure.cleaning import clean_data
from energy_failure.modeling import prepare_features
from energy_failure.robustness import classification_counts, cold_start_fixture, gap_regression_case


def test_metric_denominators_distinguish_false_alarm_definitions():
    row = classification_counts([1, 1, 0, 0, 0], [.99, .1, .99, .1, .1], .9)
    assert row["precision"] == .5
    assert row["recall"] == .5
    assert row["false_discovery_rate"] == .5
    assert row["false_positive_rate"] == 1 / 3
    empty = classification_counts([], [], .9)
    assert empty["rows"] == 0
    assert empty["precision"] is None and empty["recall"] is None


def test_cold_start_has_real_truncated_history_and_complete_labels(tmp_path: Path):
    config = cold_start_fixture(tmp_path / "raw")
    quality = clean_data(tmp_path / "raw", tmp_path / "processed")
    frame, features = prepare_features(pd.read_csv(tmp_path / "processed/daily_features.csv"),
        pd.read_csv(tmp_path / "processed/events.csv"), config)
    cold = frame[frame.age_days < 30]
    assert len(cold) == 180 and cold.asset_id.nunique() == 6
    assert cold.age_days.min() == 0 and cold.age_days.max() == 29
    assert cold.target_failure_30d.notna().all()
    assert cold.target_failure_30d.sum() == 150
    assert np.isfinite(cold[features].to_numpy()).all()
    assert quality["raw_maintenance"] == 0
    assert sum(quality["cold_start_default_cells_by_sensor"].values()) == 42
    first = cold[cold.age_days.eq(0)]
    assert first.runtime_hours.eq(0).all()
    assert first.days_since_last_recorded_maintenance.eq(0).all()
    # One available day means rolling values must not borrow another asset's past.
    assert first.vibration_mm_s.eq(first.vibration_mm_s_mean_30d).all()


def test_gradual_and_abrupt_challenges_are_distinct_before_failure(tmp_path: Path):
    cold_start_fixture(tmp_path / "raw")
    raw = pd.read_csv(tmp_path / "raw/readings.csv", parse_dates=["date"])
    for _, rows in raw.groupby("asset_id"):
        rows = rows.sort_values("date").reset_index(drop=True)
        if rows.asset_id.iloc[0].endswith("gradual"):
            assert rows.vibration_mm_s.iloc[24] > rows.vibration_mm_s.iloc[1] + 4
        else:
            assert rows.vibration_mm_s.iloc[24] == rows.vibration_mm_s.iloc[1]
        # Event and physical shutdown are tied to day 25 for both modes.
        assert rows.rpm.iloc[25] == 0


def test_gap_fix_removes_artificial_drop_without_hiding_outage(tmp_path: Path):
    result = gap_regression_case(tmp_path / "raw", tmp_path / "processed")
    assert result["zero_fill_min_vibration_change"] == -3
    assert result["causal_fill_min_vibration_change"] == 0
    assert result["zero_fill_artificial_drop_flags"] == 1
    assert result["causal_fill_artificial_drop_flags"] == 0
    assert result["outage_rows_explicitly_flagged"] == 3


def test_incomplete_maintenance_cannot_borrow_future_or_other_asset_history(tmp_path: Path):
    cold_start_fixture(tmp_path / "raw")
    assets = pd.read_csv(tmp_path / "raw/assets.csv")
    assets["commissioned_date"] = "2024-01-01"
    assets.to_csv(tmp_path / "raw/assets.csv", index=False)
    first, second = assets.asset_id.iloc[:2]
    pd.DataFrame([
        dict(maintenance_id="M1", asset_id=first, service_date="2025-04-07", maintenance_type="inspection"),
        dict(maintenance_id="M2", asset_id=first, service_date="2025-04-25", maintenance_type="inspection"),
    ]).to_csv(tmp_path / "raw/maintenance.csv", index=False)
    clean_data(tmp_path / "raw", tmp_path / "processed")
    features = pd.read_csv(tmp_path / "processed/daily_features.csv")
    selected = features[features.date.eq("2025-04-10")].set_index("asset_id")
    assert selected.loc[first, "days_since_last_recorded_maintenance"] == 3
    expected_unknown = (pd.Timestamp("2025-04-10") - pd.Timestamp("2024-01-01")).days
    assert selected.loc[second, "days_since_last_recorded_maintenance"] == expected_unknown
