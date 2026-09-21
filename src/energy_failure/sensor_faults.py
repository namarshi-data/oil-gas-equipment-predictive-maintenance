"""Frozen equipment-model sensitivity to sensor hardware faults, not fault diagnosis.

Run after the main pipeline: python -m energy_failure.sensor_faults --root .
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .cleaning import clean_data
from .config import Config
from .modeling import prepare_features
from .robustness import _new_selected_model, classification_counts

SCENARIOS = ("gradual_vibration_bias", "abrupt_vibration_stuck_zero", "abrupt_vibration_dropout")
ONSET, END = "2025-04-15", "2025-05-15"
CHANGING_FEATURES = {"vibration_mm_s", "vibration_mm_s_mean_7d", "vibration_mm_s_mean_30d",
                     "vibration_mm_s_change_per_day", "sensor_missing_count", "sensor_missing_count_mean_7d"}


def perturb_readings(readings: pd.DataFrame, assets: set[str], scenario: str,
                     onset: str = ONSET, end: str = END) -> tuple[pd.DataFrame, pd.Series]:
    """Alter one channel only; preserve existing invalid/gap values for bias/stuck tests."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown sensor fault: {scenario}")
    start_date, end_date = pd.Timestamp(onset), pd.Timestamp(end)
    if end_date <= start_date:
        raise ValueError("Fault window must contain at least two dates")
    changed = readings.copy(deep=True)
    dates = pd.to_datetime(changed.date)
    window = changed.asset_id.str.strip().isin(assets) & dates.between(start_date, end_date)
    valid = pd.to_numeric(changed.vibration_mm_s, errors="coerce").between(0, 60)
    targeted = window if scenario == "abrupt_vibration_dropout" else window & valid
    if scenario == "gradual_vibration_bias":
        bias = (dates - start_date).dt.days / (end_date - start_date).days * 5.0
        changed.loc[targeted, "vibration_mm_s"] += bias[targeted]
    elif scenario == "abrupt_vibration_stuck_zero":
        changed.loc[targeted, "vibration_mm_s"] = 0.0
    else:
        changed.loc[targeted, "vibration_mm_s"] = np.nan
    pd.testing.assert_frame_equal(changed.drop(columns="vibration_mm_s"), readings.drop(columns="vibration_mm_s"))
    pd.testing.assert_series_equal(changed.loc[~targeted, "vibration_mm_s"], readings.loc[~targeted, "vibration_mm_s"])
    return changed, targeted


def run(root: Path) -> dict:
    root = root.resolve()
    stored = json.loads((root / "artifacts/metrics.json").read_text(encoding="utf-8"))
    config, threshold = Config(**stored["config"]), float(stored["threshold"])
    events = pd.read_csv(root / "data/processed/events.csv")
    frame, features = prepare_features(pd.read_csv(root / "data/processed/daily_features.csv"), events, config)
    train = frame[frame.date.between(config.train_start, config.train_end)]
    test = frame[frame.date.between(config.test_start, config.test_end) & frame.target_failure_30d.notna()].copy()
    model = _new_selected_model(stored["selected_model"], config.seed)
    model.fit(train[features], train.target_failure_30d.astype(int))
    baseline_scores = model.predict_proba(test[features])[:, 1]
    exported = pd.read_csv(root / "data/processed/dashboard/scored_readings.csv", parse_dates=["date"])
    aligned = test[["asset_id", "date"]].merge(exported[["asset_id", "date", "risk_score"]],
        on=["asset_id", "date"], validate="one_to_one")
    np.testing.assert_allclose(baseline_scores, aligned.risk_score, rtol=1e-9, atol=1e-12)
    selected_assets = set(sorted(frame.asset_id.unique())[::4])
    window = test.asset_id.isin(selected_assets) & test.date.between(ONSET, END)
    raw_readings = pd.read_csv(root / "data/raw/readings.csv")
    result = dict(scope="Equipment-failure prediction under sensor-only corruption; not a sensor-fault diagnostic model",
        selected_model=stored["selected_model"], frozen_threshold=threshold, baseline_scores_reproduced=True,
        fault_window=[ONSET, END], affected_assets=sorted(selected_assets), asset_selection="Every fourth sorted asset ID; independent of scores and labels",
        affected_asset_sites={str(site): int(count) for site, count in frame[frame.asset_id.isin(selected_assets)]
            .drop_duplicates("asset_id").site.value_counts().items()},
        labeled_test_rows=len(test), affected_window_rows=int(window.sum()),
        training_changed=False, ground_truth_changed=False, metrics=[], scenarios=[])

    def record(scenario, changed, scores):
        for subset, mask in (("all_labeled_test", np.ones(len(test), dtype=bool)),
                             ("affected_assets_during_fault", window.to_numpy())):
            result["metrics"].append(dict(scenario=scenario, subset=subset,
                **classification_counts(changed.target_failure_30d.to_numpy()[mask], scores[mask], threshold),
                alert_decisions_changed=int(((scores[mask] >= threshold) != (baseline_scores[mask] >= threshold)).sum())))

    record("baseline", test, baseline_scores)
    with tempfile.TemporaryDirectory(prefix="energy-sensor-fault-") as directory:
        temporary = Path(directory)
        for scenario in SCENARIOS:
            raw, processed = temporary / scenario / "raw", temporary / scenario / "processed"
            raw.mkdir(parents=True)
            for name in ("assets", "events", "maintenance"):
                shutil.copyfile(root / "data/raw" / f"{name}.csv", raw / f"{name}.csv")
            perturbed, targeted = perturb_readings(raw_readings, selected_assets, scenario)
            perturbed.to_csv(raw / "readings.csv", index=False)
            quality = clean_data(raw, processed)
            changed_full, changed_features = prepare_features(pd.read_csv(processed / "daily_features.csv"), events, config)
            changed_full = frame[["asset_id", "date"]].merge(changed_full, on=["asset_id", "date"], validate="one_to_one")
            assert changed_features == features
            before = frame.date < pd.Timestamp(ONSET)
            np.testing.assert_allclose(changed_full.loc[before, features], frame.loc[before, features], rtol=1e-10, atol=1e-10)
            unaffected = ~frame.asset_id.isin(selected_assets)
            np.testing.assert_allclose(changed_full.loc[unaffected, features], frame.loc[unaffected, features], rtol=1e-10, atol=1e-10)
            unchanged_features = [name for name in features if name not in CHANGING_FEATURES]
            np.testing.assert_allclose(changed_full[unchanged_features], frame[unchanged_features], rtol=1e-10, atol=1e-10)
            np.testing.assert_array_equal(changed_full.target_failure_30d, frame.target_failure_30d)
            changed = test[["asset_id", "date"]].merge(changed_full, on=["asset_id", "date"], validate="one_to_one")
            scores = model.predict_proba(changed[features])[:, 1]
            record(scenario, changed, scores)
            valid_raw_changed = targeted & raw_readings.vibration_mm_s.notna() & perturbed.vibration_mm_s.notna()
            raw_delta = (perturbed.vibration_mm_s - raw_readings.vibration_mm_s).abs()
            result["scenarios"].append(dict(scenario=scenario,
                targeted_raw_rows=int(targeted.sum()), numeric_raw_rows_changed=int((valid_raw_changed & (raw_delta > 0)).sum()),
                before_onset_features_unchanged=True, other_assets_features_unchanged=True,
                other_sensor_features_unchanged=True, labels_unchanged=True,
                vibration_imputed_cells=int(quality["imputed_cells_by_sensor"]["vibration_mm_s"]),
                affected_window_vibration_missing_flags=int(changed.loc[window.to_numpy(), "vibration_mm_s_missing"].sum()),
                baseline_affected_window_vibration_missing_flags=int(test.loc[window, "vibration_mm_s_missing"].sum()),
                max_abs_7d_mean_change=float(np.abs(changed.vibration_mm_s_mean_7d.to_numpy() - test.vibration_mm_s_mean_7d.to_numpy()).max()),
                max_abs_30d_mean_change=float(np.abs(changed.vibration_mm_s_mean_30d.to_numpy() - test.vibration_mm_s_mean_30d.to_numpy()).max()),
                max_abs_daily_rate_change=float(np.abs(changed.vibration_mm_s_change_per_day.to_numpy() - test.vibration_mm_s_change_per_day.to_numpy()).max())))
    result["limitations"] = [
        "Sensor biases and stuck-zero values can remain inside physical bounds; current cleaning does not diagnose hardware faults.",
        "A null dropout is recognized as missing and causally imputed, but long carry-forward can conceal changing equipment condition.",
        "All-test results include carryover through trailing windows after the May 15 fault ends; the affected subset contains only the 620 fault-window rows.",
        "Ground truth and intervention assumptions are unchanged. No policy replay, avoided-cost claim, sensor diagnosis accuracy or threshold optimization is performed.",
        "One deterministic synthetic corruption window and 20 assets do not establish field robustness or independent-event confidence intervals."]
    (root / "reports/sensor_faults.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(result["metrics"]).to_csv(root / "reports/sensor_faults_metrics.csv", index=False)
    pd.DataFrame(result["scenarios"]).to_csv(root / "reports/sensor_faults_quality.csv", index=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = run(args.root)
    print(json.dumps({"baseline_scores_reproduced": result["baseline_scores_reproduced"], "metrics": result["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
