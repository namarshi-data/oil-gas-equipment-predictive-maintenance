"""Sensor corruption must remain causal and must never rewrite equipment truth."""
import numpy as np
import pandas as pd
import pytest

from energy_failure.cleaning import clean_data
from energy_failure.modeling import prepare_features
from energy_failure.robustness import cold_start_fixture
from energy_failure.sensor_faults import SCENARIOS, perturb_readings


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_one_channel_fault_preserves_truth_and_exposes_cleaning_limits(tmp_path, scenario):
    config = cold_start_fixture(tmp_path / "raw")
    original = pd.read_csv(tmp_path / "raw/readings.csv")
    first_asset = original.asset_id.iloc[0]
    events_before = (tmp_path / "raw/events.csv").read_bytes()
    history_before = (tmp_path / "raw/maintenance.csv").read_bytes()
    clean_data(tmp_path / "raw", tmp_path / "baseline")
    baseline, features = prepare_features(pd.read_csv(tmp_path / "baseline/daily_features.csv"),
        pd.read_csv(tmp_path / "raw/events.csv"), config)
    altered, targeted = perturb_readings(original, {first_asset}, scenario)
    pd.testing.assert_frame_equal(original.drop(columns="vibration_mm_s"), altered.drop(columns="vibration_mm_s"))
    if scenario != "abrupt_vibration_dropout":
        assert altered.loc[original.vibration_mm_s.isna(), "vibration_mm_s"].isna().all()
    altered.to_csv(tmp_path / "raw/readings.csv", index=False)
    clean_data(tmp_path / "raw", tmp_path / "changed")
    changed, _ = prepare_features(pd.read_csv(tmp_path / "changed/daily_features.csv"),
        pd.read_csv(tmp_path / "raw/events.csv"), config)
    before = baseline.date < pd.Timestamp("2025-04-15")
    np.testing.assert_allclose(changed.loc[before, features], baseline.loc[before, features])
    np.testing.assert_array_equal(changed.target_failure_30d, baseline.target_failure_30d)
    assert (tmp_path / "raw/events.csv").read_bytes() == events_before
    assert (tmp_path / "raw/maintenance.csv").read_bytes() == history_before
    last = changed[(changed.asset_id == first_asset) & (changed.date == pd.Timestamp("2025-05-15"))].iloc[0]
    prior = baseline[(baseline.asset_id == first_asset) & (baseline.date == pd.Timestamp("2025-05-15"))].iloc[0]
    if scenario == "abrupt_vibration_dropout":
        assert last.vibration_mm_s_missing == 1
        assert np.isfinite(last.vibration_mm_s)
    elif scenario == "abrupt_vibration_stuck_zero":
        assert last.vibration_mm_s == 0
        assert last.vibration_mm_s_missing == 0  # Zero is valid; no fault-diagnostic rule exists.
    else:
        assert last.vibration_mm_s == prior.vibration_mm_s + 5
        assert last.vibration_mm_s_missing == 0  # In-range bias passes simple physical bounds.


def test_unknown_fault_and_reversed_window_are_rejected():
    frame = pd.DataFrame(dict(asset_id=["A1"], date=["2025-04-15"], vibration_mm_s=[3.0]))
    with pytest.raises(ValueError, match="Unknown"):
        perturb_readings(frame, {"A1"}, "invented")
    with pytest.raises(ValueError, match="at least two"):
        perturb_readings(frame, {"A1"}, SCENARIOS[0], "2025-04-15", "2025-04-14")
