"""Preregistered local synthetic generalization and independent calibration study.

Read docs/generalization-protocol.json before execution. Outputs are separate
from the published seed42 benchmark; no study result changes the headline model.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from .cleaning import clean_data
from .config import Config
from .modeling import prepare_features
from .policies import replay
from .robustness import _new_selected_model, classification_counts
from .synthetic import generate
from .uncertainty import bootstrap_classification, run as run_uncertainty


def split_assets(asset_ids, holdout_count=20, salt="energy-study-v1"):
    unique = sorted(set(asset_ids))
    if not 0 < holdout_count < len(unique):
        raise ValueError("Holdout count must leave at least one asset in each partition")
    ranked = sorted(unique, key=lambda aid: hashlib.sha256(f"{salt}|{aid}".encode()).hexdigest())
    holdout = set(ranked[:holdout_count])
    return sorted(set(unique) - holdout), sorted(holdout)


def calendar_masks(frame: pd.DataFrame, config: Config):
    if pd.Timestamp(config.train_end) + pd.Timedelta(days=config.horizon_days) >= pd.Timestamp(config.validation_start):
        raise ValueError("Training label horizon overlaps validation period")
    if pd.Timestamp(config.validation_end) + pd.Timedelta(days=config.horizon_days) >= pd.Timestamp(config.test_start):
        raise ValueError("Validation label horizon overlaps test period")
    return dict(train=frame.date.between(config.train_start, config.train_end),
        validation=frame.date.between(config.validation_start, config.validation_end),
        test=frame.date.between(config.test_start, config.test_end) & frame.target_failure_30d.notna())


def clipped_logit(scores):
    p = np.clip(np.asarray(scores, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def fit_calibrator(scores, labels):
    if len(np.unique(labels)) != 2:
        raise ValueError("Calibration needs both outcome classes")
    return LogisticRegression(C=1000000, solver="lbfgs", max_iter=1000, random_state=42).fit(clipped_logit(scores), labels)


def probability_metrics(labels, scores):
    y = np.asarray(labels, dtype=int)
    return dict(brier_score=float(brier_score_loss(y, scores)), log_loss=float(log_loss(y, scores, labels=[0, 1])),
        average_precision=float(average_precision_score(y, scores)) if y.sum() else None,
        roc_auc=float(roc_auc_score(y, scores)) if len(np.unique(y)) == 2 else None)


def future_modes(frame, events):
    modes = pd.Series("no_failure_next_30d", index=frame.index, dtype=object)
    for aid, rows in frame[frame.target_failure_30d.eq(1)].groupby("asset_id"):
        ordered = events[events.asset_id.eq(aid)].sort_values("event_date").reset_index(drop=True)
        dates = pd.to_datetime(ordered.event_date).to_numpy(dtype="datetime64[D]")
        indexes = np.searchsorted(dates, rows.date.to_numpy(dtype="datetime64[D]"), side="right")
        modes.loc[rows.index] = ordered.iloc[indexes].failure_mode.to_numpy()
    return modes


def _generated_fleet(directory, seed, config):
    raw, processed = directory / "raw", directory / "processed"
    manifest = generate(raw, replace(config, seed=seed))
    clean_data(raw, processed)
    events = pd.read_csv(processed / "events.csv")
    frame, features = prepare_features(pd.read_csv(processed / "daily_features.csv"), events, config)
    return frame, features, events, dict(seed=seed, manifest=manifest,
        raw_readings_sha256=hashlib.sha256((raw / "readings.csv").read_bytes()).hexdigest(),
        raw_events_sha256=hashlib.sha256((raw / "events.csv").read_bytes()).hexdigest())


def run(root: Path):
    root = root.resolve()
    protocol_path = root / "docs/generalization-protocol.json"
    protocol_bytes = protocol_path.read_bytes()
    protocol = json.loads(protocol_bytes)
    stored = json.loads((root / "artifacts/metrics.json").read_text(encoding="utf-8"))
    config = Config(**stored["config"])
    assert config.seed == protocol["reference_seed"] and config.n_assets == protocol["assets_per_fleet"]
    assert stored["selected_model"] == protocol["algorithm"] and stored["threshold"] == protocol["published_reference_threshold"]
    assert [config.train_start, config.train_end] == protocol["training_period"]
    assert [config.validation_start, config.validation_end] == protocol["validation_period"]
    assert [config.test_start, config.test_end] == protocol["test_period"]
    assets, events = (pd.read_csv(root / "data/processed" / f"{name}.csv") for name in ("assets", "events"))
    oracle_events = events.merge(pd.read_csv(root / "data/raw/simulation_truth.csv"), on="event_id", validate="one_to_one")
    frame, features = prepare_features(pd.read_csv(root / "data/processed/daily_features.csv"), events, config)
    masks = calendar_masks(frame, config)
    train_ids, holdout_ids = split_assets(assets.asset_id, protocol["heldout_asset_count"], protocol["asset_split_salt"])
    training_assets = frame.asset_id.isin(train_ids)
    models, train_rows = {}, {}
    for name, mask in (("published_reference_80_assets", masks["train"]),
                       ("asset_holdout_study_60_assets", masks["train"] & training_assets)):
        train = frame[mask]
        model = _new_selected_model(stored["selected_model"], config.seed)
        assert all(model[-1].get_params()[key] == value for key, value in protocol["hyperparameters"].items())
        models[name] = model.fit(train[features], train.target_failure_30d.astype(int))
        train_rows[name] = len(train)
    baseline_test = frame[masks["test"]]
    reference_scores = models["published_reference_80_assets"].predict_proba(baseline_test[features])[:, 1]
    exported = pd.read_csv(root / "data/processed/dashboard/scored_readings.csv", parse_dates=["date"])
    reconciliation = baseline_test[["asset_id", "date"]].merge(exported[["asset_id", "date", "risk_score"]],
        on=["asset_id", "date"], validate="one_to_one")
    np.testing.assert_allclose(reference_scores, reconciliation.risk_score, rtol=1e-9, atol=1e-12)
    # Only the 60 training assets enter model fitting and threshold selection.
    validation = frame[masks["validation"] & training_assets]
    study_model = models["asset_holdout_study_60_assets"]
    val_scores = validation[["asset_id", "date"]].assign(risk_score=study_model.predict_proba(validation[features])[:, 1])
    val_assets = assets[assets.asset_id.isin(train_ids)]
    val_events = oracle_events[oracle_events.asset_id.isin(train_ids)]
    assert set(validation.asset_id).isdisjoint(holdout_ids) and set(val_events.asset_id).isdisjoint(holdout_ids)
    tradeoffs = []
    for threshold in protocol["study_threshold_grid"]:
        summary, _, _, _ = replay(val_assets, val_events, val_scores,
            config.validation_start, config.validation_end, config, threshold)
        cost = float(summary.set_index("policy").loc["predictive", "total_cost_cad"])
        tradeoffs.append(dict(threshold=threshold, validation_predictive_cost_cad=cost))
    selected = min(tradeoffs, key=lambda row: (row["validation_predictive_cost_cad"], -row["threshold"]))
    thresholds = {"published_reference_80_assets": stored["threshold"], "asset_holdout_study_60_assets": selected["threshold"]}
    records, mode_records, curves, score_tables, evidence, intervals = [], [], [], [], [], []
    result = dict(study_id=protocol["study_id"], protocol_sha256=hashlib.sha256(protocol_bytes).hexdigest(),
        baseline_score_reproduction=True, training_assets=train_ids, heldout_assets=holdout_ids,
        heldout_site_counts=assets[assets.asset_id.isin(holdout_ids)].site.value_counts().to_dict(),
        training_rows=train_rows, thresholds=thresholds, validation_selection=selected,
        training_label_available_by=str((pd.Timestamp(config.train_end) + pd.Timedelta(days=30)).date()),
        validation_and_calibration_labels_available_by=str((pd.Timestamp(config.validation_end) + pd.Timedelta(days=30)).date()),
        calibration_dispatch_threshold=None, limitations=protocol["limitations"])
    with tempfile.TemporaryDirectory(prefix="energy-generalization-") as temporary:
        directory = Path(temporary)
        print("Fitting calibration on independent development fleet before external evaluation", flush=True)
        calibration_frame, calibration_features, _, calibration_manifest = _generated_fleet(directory / "calibration", protocol["calibration_development_seed"], config)
        assert calibration_features == features
        calibration_data = calibration_frame[calendar_masks(calibration_frame, config)["validation"]]
        calibrators, calibration_fits = {}, []
        for name, model in models.items():
            raw = model.predict_proba(calibration_data[features])[:, 1]
            calibrators[name] = fit_calibrator(raw, calibration_data.target_failure_30d.astype(int))
            calibration_fits.append(dict(model=name, rows=len(calibration_data), assets=calibration_data.asset_id.nunique(),
                seed=protocol["calibration_development_seed"], period=protocol["validation_period"],
                logit_coefficient=float(calibrators[name].coef_[0, 0]), intercept=float(calibrators[name].intercept_[0])))
        result["calibration_fits"] = calibration_fits
        evidence.append(calibration_manifest)

        def evaluate(cohort, seed, sample, cohort_events, relationship):
            modes = future_modes(sample, cohort_events)
            for name, model in models.items():
                raw = model.predict_proba(sample[features])[:, 1]
                calibrated = calibrators[name].predict_proba(clipped_logit(raw))[:, 1]
                record = dict(cohort=cohort, seed=seed, model=name, asset_relationship=relationship[name],
                    assets=sample.asset_id.nunique(), threshold=thresholds[name],
                    **classification_counts(sample.target_failure_30d, raw, thresholds[name]),
                    **{f"raw_{key}": value for key, value in probability_metrics(sample.target_failure_30d, raw).items()},
                    **{f"calibrated_{key}": value for key, value in probability_metrics(sample.target_failure_30d, calibrated).items()})
                records.append(record)
                table = sample[["asset_id", "date", "target_failure_30d"]].copy()
                table.insert(0, "model", name)
                table.insert(0, "cohort", cohort)
                table["failure_mode_if_positive"] = modes
                table["raw_risk_score"], table["calibrated_risk_score"] = raw, calibrated
                score_tables.append(table)
                scored_for_bootstrap = table.rename(columns={"raw_risk_score": "risk_score"})
                intervals.append(dict(cohort=cohort, model=name, **bootstrap_classification(scored_for_bootstrap,
                    thresholds[name], protocol["bootstrap"]["replicates"], protocol["bootstrap"]["rng_seed"])))
                for mode in ("bearing_wear", "overheating", "seal_leak", "electrical_trip"):
                    mask = modes.eq(mode).to_numpy()
                    count = int(mask.sum())
                    hits = int((raw[mask] >= thresholds[name]).sum())
                    mode_records.append(dict(cohort=cohort, model=name, failure_mode=mode,
                        positive_asset_days=count, alerted_positive_asset_days=hits, recall=hits / count if count else None))
                y = sample.target_failure_30d.to_numpy()
                for scale, values in (("raw", raw), ("calibrated", calibrated)):
                    bins = np.minimum((values * 10).astype(int), 9)
                    for bin_index in range(10):
                        mask = bins == bin_index
                        curves.append(dict(cohort=cohort, model=name, score_scale=scale, bin_lower=bin_index / 10,
                            bin_upper=(bin_index + 1) / 10, rows=int(mask.sum()),
                            mean_score=float(values[mask].mean()) if mask.any() else None,
                            observed_positive_rate=float(y[mask].mean()) if mask.any() else None))

        evaluate("seed42_retrospective_asset_holdout", 42, baseline_test[baseline_test.asset_id.isin(holdout_ids)], events,
            {"published_reference_80_assets": "seen_asset_history_reference_only", "asset_holdout_study_60_assets": "unseen_assets_and_future_calendar"})
        for seed in protocol["external_fleet_seeds"]:
            print(f"Evaluating declared external synthetic fleet seed {seed}", flush=True)
            external, external_features, external_events, manifest = _generated_fleet(directory / f"seed{seed}", seed, config)
            assert external_features == features
            evidence.append(manifest)
            evaluate(f"external_seed{seed}", seed, external[calendar_masks(external, config)["test"]], external_events,
                {name: "independent_fleet_same_generator_future_calendar" for name in models})
    result["metrics"], result["data_evidence"], result["cluster_intervals"] = records, evidence, intervals
    report = root / "reports"
    (report / "generalization.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame(records).to_csv(report / "generalization_metrics.csv", index=False)
    pd.DataFrame(tradeoffs).to_csv(report / "generalization_thresholds.csv", index=False)
    pd.DataFrame(mode_records).to_csv(report / "generalization_failure_modes.csv", index=False)
    pd.DataFrame(curves).to_csv(report / "generalization_calibration_bins.csv", index=False)
    pd.concat(score_tables, ignore_index=True).to_csv(report / "generalization_scores.csv", index=False)
    run_uncertainty(root)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = run(args.root)
    print(json.dumps({"thresholds": result["thresholds"], "metrics": result["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
