"""Reproducible stress checks; never retune or replace the headline model.

Run after the main pipeline: ``python -m energy_failure.robustness --root .``.
Models are refitted from reviewed source and training rows, rather than loading a
pickled model from an archive. JSON/CSV outputs are written only to robustness files.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .cleaning import RAW_SCHEMAS, SENSORS, clean_data
from .config import Config, EQUIPMENT
from .modeling import prepare_features

GAP_FEATURES = {"sensor_missing_count", "sensor_missing_count_mean_7d", "missing_gap_days"}


def classification_counts(labels, scores, threshold: float) -> dict:
    """Keep undefined denominators null; distinguish FPR from false discovery."""
    y, prediction = np.asarray(labels, dtype=int), np.asarray(scores) >= threshold
    tp = int(np.sum((y == 1) & prediction))
    fp = int(np.sum((y == 0) & prediction))
    fn = int(np.sum((y == 1) & ~prediction))
    tn = int(np.sum((y == 0) & ~prediction))
    return dict(rows=len(y), positives=tp + fn, alerts=tp + fp,
                true_positive=tp, false_positive=fp, false_negative=fn, true_negative=tn,
                precision=tp / (tp + fp) if tp + fp else None,
                recall=tp / (tp + fn) if tp + fn else None,
                false_discovery_rate=fp / (tp + fp) if tp + fp else None,
                false_positive_rate=fp / (fp + tn) if fp + tn else None)


def _write_raw(raw: Path, tables: dict[str, list[dict]]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    for name, schema in RAW_SCHEMAS.items():
        with (raw / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(schema))
            writer.writeheader()
            writer.writerows(tables.get(name, []))


def cold_start_fixture(raw: Path) -> Config:
    """Six new units, 61 observed days, no inherited telemetry or maintenance.

    Three equipment types x gradual/abrupt signatures. One event occurs on day
    25; scoring is restricted to ages 0..29, with complete 30-day label follow-up.
    This deliberately enriched controlled challenge is NOT a fleet prevalence.
    """
    tables = {name: [] for name in RAW_SCHEMAS}
    start = pd.Timestamp("2025-04-01")
    dates = pd.date_range(start, periods=61)
    for kind, spec in EQUIPMENT.items():
        for signature in ("gradual", "abrupt"):
            aid = f"COLD-{kind}-{signature}"
            tables["assets"].append(dict(asset_id=aid, asset_type=kind, site="Cold-start test",
                commissioned_date=str(start.date()), rated_power_kw=spec["power"]))
            tables["events"].append(dict(event_id=f"E-{aid}", asset_id=aid,
                event_date=str(dates[25].date()), failure_mode="bearing_wear" if signature == "gradual" else "electrical_trip",
                emergency_cost_cad=spec["emergency_cost"], emergency_downtime_hours=spec["emergency_hours"]))
            runtime = 0.0
            for day, date in enumerate(dates):
                wear = max(0.0, (day - 5) / 20) ** 1.5 if signature == "gradual" and day < 25 else 0.0
                down = 25 <= day < 28
                load = 0 if down else 70.0
                values = [0.1 if down else spec["vibration"] + 4.7 * wear,
                          spec["temperature"] + 20 * wear,
                          spec["pressure"] * (0.3 if down else 1) - 1.6 * wear,
                          0 if down else spec["power"] * 0.7 * (1 + 0.18 * wear),
                          load, 0 if down else spec["rpm"] * (0.99 - 0.07 * wear), runtime]
                # Missing first reading exercises SQL fixed defaults, with no past to borrow.
                if day in (0, 10, 11, 12):
                    values = [None] * len(SENSORS)
                tables["readings"].append(dict(ingestion_id=len(tables["readings"]) + 1,
                    asset_id=aid, date=str(date.date()), **dict(zip(SENSORS, values))))
                runtime += 24 * load / 100
    _write_raw(raw, tables)
    return Config(start=str(start.date()), end=str(dates[-1].date()), n_assets=6)


def gap_regression_case(raw: Path, processed: Path) -> dict:
    """Recreate a zero-fill bug explicitly; do not claim a historical ML result."""
    tables = {name: [] for name in RAW_SCHEMAS}
    tables["assets"] = [dict(asset_id="GAP-1", asset_type="pumpjack", site="Gap test",
        commissioned_date="2024-01-01", rated_power_kw=45)]
    for day, date in enumerate(pd.date_range("2025-04-01", periods=7)):
        values = [3, 65, 7, 100, 70, 1800, 1000 + day * 17]
        if day in (2, 3, 4):
            values = [None] * len(SENSORS)
        tables["readings"].append(dict(ingestion_id=day + 1, asset_id="GAP-1",
            date=str(date.date()), **dict(zip(SENSORS, values))))
    _write_raw(raw, tables)
    clean_data(raw, processed)
    before = pd.read_csv(raw / "readings.csv").vibration_mm_s.fillna(0).diff().fillna(0)
    after = pd.read_csv(processed / "daily_features.csv")
    return dict(case="controlled_zero_fill_reproduction", observation_days=7, outage_days=3,
                zero_fill_min_vibration_change=float(before.min()),
                causal_fill_min_vibration_change=float(after.vibration_mm_s_change_per_day.min()),
                naive_drop_rule="vibration change per day < -2 mm/s/day (illustrative rule, not ML)",
                zero_fill_artificial_drop_flags=int((before < -2).sum()),
                causal_fill_artificial_drop_flags=int((after.vibration_mm_s_change_per_day < -2).sum()),
                outage_rows_explicitly_flagged=int((after.sensor_missing_count == 7).sum()))


def _new_selected_model(name: str, seed: int):
    # Exactly the baseline source hyperparameters. No test-driven selection.
    if name == "hist_gradient_boosting":
        return make_pipeline(HistGradientBoostingClassifier(max_iter=180, learning_rate=.055,
            max_leaf_nodes=15, min_samples_leaf=60, l2_regularization=5, random_state=seed))
    if name == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(C=.15, class_weight="balanced",
            max_iter=1500, random_state=seed))
    raise ValueError(f"Unsupported selected model: {name}")


def run(root: Path) -> dict:
    root = root.resolve()
    stored = json.loads((root / "artifacts/metrics.json").read_text(encoding="utf-8"))
    config, threshold = Config(**stored["config"]), float(stored["threshold"])
    frame, features = prepare_features(pd.read_csv(root / "data/processed/daily_features.csv"),
        pd.read_csv(root / "data/processed/events.csv"), config)
    train = frame[frame.date.between(config.train_start, config.train_end)]
    test = frame[frame.date.between(config.test_start, config.test_end) & frame.target_failure_30d.notna()].copy()
    model = _new_selected_model(stored["selected_model"], config.seed)
    model.fit(train[features], train.target_failure_30d.astype(int))
    baseline_scores = model.predict_proba(test[features])[:, 1]
    # Refit must reproduce the selected held-out scores before any stress result is accepted.
    exported = pd.read_csv(root / "data/processed/dashboard/scored_readings.csv", parse_dates=["date"])
    aligned = test[["asset_id", "date"]].merge(exported[["asset_id", "date", "risk_score"]],
        on=["asset_id", "date"], how="left", validate="one_to_one")
    np.testing.assert_allclose(baseline_scores, aligned.risk_score, rtol=1e-9, atol=1e-12)
    result = dict(scope="Synthetic controlled stress tests; no test-driven retuning or headline replacement",
        selected_model=stored["selected_model"], threshold=threshold,
        test_start=str(test.date.min().date()), test_end=str(test.date.max().date()),
        baseline_score_reproduction=True, classification=[])

    def record(name, data, scores, subset="all"):
        result["classification"].append(dict(scenario=name, subset=subset,
            **classification_counts(data.target_failure_30d, scores, threshold)))

    record("baseline", test, baseline_scores)
    gap_rows = (test.sensor_missing_count_mean_7d > 0) | (test.missing_gap_days > 0)
    record("baseline", test.loc[gap_rows], baseline_scores[gap_rows], "gap_or_imputation_in_last_7_days")
    no_gap_features = [feature for feature in features if feature not in GAP_FEATURES]
    ablation = clone(model).fit(train[no_gap_features], train.target_failure_30d.astype(int))
    ablated_scores = ablation.predict_proba(test[no_gap_features])[:, 1]
    record("without_explicit_gap_features", test, ablated_scores)
    record("without_explicit_gap_features", test.loc[gap_rows], ablated_scores[gap_rows], "gap_or_imputation_in_last_7_days")
    result["gap_ablation_design"] = "Same training rows, algorithm/hyperparameters and frozen baseline threshold; causal imputation unchanged; removes three gap predictors. Not separately policy-optimized."

    with tempfile.TemporaryDirectory(prefix="energy-robustness-") as directory:
        temporary = Path(directory)
        maintenance = pd.read_csv(root / "data/raw/maintenance.csv")
        sorted_maintenance = maintenance.sort_values(["asset_id", "service_date", "maintenance_id"])
        # Select by identity/order, never by label, risk or eventual outcome.
        partial = sorted_maintenance[~((sorted_maintenance.groupby("asset_id").cumcount() % 2 == 1)
                                      & sorted_maintenance.maintenance_type.ne("commissioning"))]
        missing_assets = set(sorted(frame.asset_id.unique())[::4])
        none_for_quarter = maintenance[~maintenance.asset_id.isin(missing_assets)]
        result["maintenance_scenarios"] = []
        for name, altered in (("alternating_recorded_repairs_removed", partial),
                              ("no_history_for_every_fourth_asset", none_for_quarter)):
            raw, processed = temporary / name / "raw", temporary / name / "processed"
            raw.mkdir(parents=True)
            for table in ("assets", "readings", "events"):
                shutil.copyfile(root / "data/raw" / f"{table}.csv", raw / f"{table}.csv")
            altered.to_csv(raw / "maintenance.csv", index=False)
            clean_data(raw, processed)
            changed, changed_features = prepare_features(pd.read_csv(processed / "daily_features.csv"),
                pd.read_csv(processed / "events.csv"), config)
            changed = test[["asset_id", "date"]].merge(changed, on=["asset_id", "date"], validate="one_to_one")
            assert changed_features == features
            # Missing history changes recency only, never labels or sensor measurements.
            other_features = [f for f in features if f != "days_since_last_recorded_maintenance"]
            np.testing.assert_allclose(changed[other_features], test[other_features])
            np.testing.assert_array_equal(changed.target_failure_30d, test.target_failure_30d)
            scores = model.predict_proba(changed[features])[:, 1]
            record(name, changed, scores)
            result["maintenance_scenarios"].append(dict(scenario=name,
                input_maintenance_rows=len(maintenance), retained_maintenance_rows=len(altered),
                removed_maintenance_rows=len(maintenance) - len(altered),
                changed_test_recency_rows=int((changed.days_since_last_recorded_maintenance.to_numpy()
                    != test.days_since_last_recorded_maintenance.to_numpy()).sum()),
                alert_decisions_changed=int(((scores >= threshold) != (baseline_scores >= threshold)).sum())))
        cold_raw, cold_processed = temporary / "cold/raw", temporary / "cold/processed"
        cold_config = cold_start_fixture(cold_raw)
        cold_quality = clean_data(cold_raw, cold_processed)
        cold, cold_features = prepare_features(pd.read_csv(cold_processed / "daily_features.csv"),
            pd.read_csv(cold_processed / "events.csv"), cold_config)
        cold = cold[cold.age_days < 30].copy()
        assert cold.target_failure_30d.notna().all() and cold_features == features
        cold_scores = model.predict_proba(cold[features])[:, 1]
        record("cold_start_controlled_fixture", cold, cold_scores)
        for signature in ("gradual", "abrupt"):
            mask = cold.asset_id.str.endswith(signature)
            record("cold_start_controlled_fixture", cold[mask], cold_scores[mask], signature)
        result["cold_start_design"] = dict(assets=6, scored_rows=len(cold), age_days=[0, 29],
            observed_days_per_asset=61, signature_types=["gradual", "abrupt"], equipment_types=list(EQUIPMENT),
            event_age_days=25, outage_ages=[0, 10, 11, 12], inherited_history_rows=0,
            missing_first_reading_default_cells=sum(cold_quality["cold_start_default_cells_by_sensor"].values()),
            training_age_min_days=int(train.age_days.min()),
            limitation="Controlled out-of-distribution challenge with 83.3% positives; not an estimate of new-unit production accuracy or cost.")
        result["gap_regression"] = gap_regression_case(temporary / "gap/raw", temporary / "gap/processed")

    events = pd.read_csv(root / "data/processed/events.csv")
    # Failure-mode recall is a separate classifier diagnostic. Policy catches also
    # depend on service timing and the simulated preventability/success oracle.
    positive_modes = []
    for aid, rows in test.assign(score=baseline_scores).groupby("asset_id"):
        future_events = events[events.asset_id.eq(aid)].sort_values("event_date").reset_index(drop=True)
        event_dates = pd.to_datetime(future_events.event_date).to_numpy(dtype="datetime64[D]")
        for row in rows[rows.target_failure_30d.eq(1)].itertuples():
            event_index = int(np.searchsorted(event_dates, np.datetime64(row.date.date()), side="right"))
            event = future_events.iloc[event_index]
            positive_modes.append(dict(failure_mode=event.failure_mode, event_id=event.event_id,
                alerted=int(row.score >= threshold)))
    result["positive_failure_modes"] = []
    for mode, rows in pd.DataFrame(positive_modes).groupby("failure_mode", sort=True):
        result["positive_failure_modes"].append(dict(failure_mode=mode,
            positive_asset_days=len(rows), distinct_future_events=int(rows.event_id.nunique()),
            alerted_positive_asset_days=int(rows.alerted.sum()),
            recall=float(rows.alerted.mean())))
    outcomes = pd.read_csv(root / "data/processed/dashboard/event_outcomes.csv")
    joined = outcomes.merge(events[["event_id", "failure_mode"]], on="event_id", validate="many_to_one")
    grouped = []
    for (policy, mode), rows in joined.groupby(["policy", "failure_mode"], sort=True):
        caught = rows.caught.eq(1)
        grouped.append(dict(policy=policy, failure_mode=mode,
            signature="abrupt" if mode == "electrical_trip" else "gradual",
            events=len(rows), caught=int(caught.sum()), missed=int((~caught).sum()),
            catch_rate=float(caught.mean()), median_warning_days=float(rows.loc[caught, "warning_days"].median()) if caught.any() else None,
            emergency_repair_cost_cad=float(rows.loc[~caught, "repair_cost_cad"].sum()),
            unplanned_downtime_hours=float(rows.loc[~caught, "downtime_hours"].sum())))
    result["event_subgroups"] = grouped
    result["cost_scope"] = "Subgroup costs use the existing 91-day event replay and are not annualized. Stress/ablation classifications have no cost-savings claim; they do not replay interventions."
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "robustness.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(result["classification"]).to_csv(reports / "robustness_classification.csv", index=False)
    pd.DataFrame(grouped).to_csv(reports / "robustness_failure_modes.csv", index=False)
    pd.DataFrame(result["positive_failure_modes"]).to_csv(reports / "robustness_mode_recall.csv", index=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = run(args.root)
    print(json.dumps({"baseline_score_reproduction": result["baseline_score_reproduction"],
                      "classification": result["classification"], "gap_regression": result["gap_regression"]}, indent=2))


if __name__ == "__main__":
    main()
