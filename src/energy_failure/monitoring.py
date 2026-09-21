"""Local monitoring replay with explicit thresholds and mature-label evaluation.

This is a reproducible scheduled-job prototype, not a hosted monitoring service.
Changes in distributions are investigation signals, not evidence of model bias.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .batch_score import BatchScorer

THRESHOLDS = {"stale_days": 2, "imputed_row_rate": .10, "manual_review_rate": .20,
              "score_psi": .20, "alert_rate_absolute_change": .10, "mature_recall_floor": .50}


def evaluate(scored: pd.DataFrame, inputs: pd.DataFrame, labels: pd.DataFrame, as_of) -> dict:
    as_of = pd.Timestamp(as_of).normalize()
    for name, frame in (("scores", scored), ("inputs", inputs), ("labels", labels)):
        if not {"asset_id", "date"}.issubset(frame) or frame[["asset_id", "date"]].duplicated().any():
            raise ValueError(f"{name} must have unique asset/date keys")
    required = {"risk_score", "alert", "requires_manual_review"}
    if not required.issubset(scored) or not scored.risk_score.between(0, 1).all():
        raise ValueError("Scoring output schema or risk bounds invalid")
    if not scored.alert.isin([True, False]).all() or not scored.requires_manual_review.isin([True, False]).all():
        raise ValueError("Alert/review flags must be complete binary values")
    if set(map(tuple, scored[["asset_id", "date"]].to_numpy())) != set(map(tuple, inputs[["asset_id", "date"]].to_numpy())):
        raise ValueError("Scores and input records do not reconcile")
    joined = scored.merge(inputs, on=["asset_id", "date"], how="left", validate="one_to_one", suffixes=("", "_input"))
    if len(joined) != len(inputs):
        raise ValueError("Scores and input records do not reconcile")
    joined["date"] = pd.to_datetime(joined.date)
    if joined.date.isna().any() or joined.date.gt(as_of).any():
        raise ValueError("Monitoring dates must be valid and no later than as_of")
    current = joined[joined.date.between(as_of-pd.Timedelta(days=6), as_of)]
    reference = joined[joined.date.between(as_of-pd.Timedelta(days=34), as_of-pd.Timedelta(days=7))]
    findings = []
    def finding(code, owner, response, value):
        findings.append({"code": code, "owner": owner, "response": response, "value": value})
    latest = joined.groupby("asset_id").date.max()
    stale = int((as_of-latest).dt.days.gt(THRESHOLDS["stale_days"]).sum())
    if stale:
        finding("stale_assets", "SCADA/data engineer", "Check transport outages and restore telemetry before relying on scores.", stale)
    signals = {"current_rows": len(current), "reference_rows": len(reference), "tracked_assets": len(latest),
               "stale_assets": stale, "schema_contract": "passed", "mean_risk_score": None,
               "imputed_row_rate": None, "alert_rate": None, "manual_review_rate": None,
               "unknown_maintenance_rate": None, "flatline_review_rate": None,
               "score_psi": None, "alert_rate_absolute_change": None}
    if len(current):
        signals.update(mean_risk_score=float(current.risk_score.mean()), alert_rate=float(current.alert.mean()),
                       manual_review_rate=float(current.requires_manual_review.mean()))
        if "sensor_missing_count" in current:
            signals["imputed_row_rate"] = float(current.sensor_missing_count.gt(0).mean())
        for name, column, test in (("unknown_maintenance_rate", "maintenance_history_known", 0),
                                   ("flatline_review_rate", "sensor_flatline", 1)):
            if column in current:
                signals[name] = float(current[column].eq(test).mean())
        for metric, owner, response in (("imputed_row_rate", "SCADA/data engineer", "Inspect missing channel flags and sensor freshness."),
                                        ("manual_review_rate", "Reliability engineer", "Prioritize the advisory queue; investigate quality and commissioning reasons.")):
            if signals[metric] is not None and signals[metric] > THRESHOLDS[metric]:
                finding(metric, owner, response, signals[metric])
        if len(reference):
            bins = np.linspace(0, 1, 6)
            a = np.histogram(reference.risk_score, bins=bins)[0]+.5
            b = np.histogram(current.risk_score, bins=bins)[0]+.5
            a, b = a/a.sum(), b/b.sum()
            signals["score_psi"] = float(np.sum((b-a)*np.log(b/a)))
            signals["alert_rate_absolute_change"] = float(abs(current.alert.mean()-reference.alert.mean()))
            if signals["score_psi"] > THRESHOLDS["score_psi"]:
                finding("score_distribution_shift", "Data scientist", "Inspect input/asset mix and sensor changes; validate mature outcomes before any retraining.", signals["score_psi"])
            if signals["alert_rate_absolute_change"] > THRESHOLDS["alert_rate_absolute_change"]:
                finding("alert_rate_change", "Reliability engineer + data scientist", "Check workload, interventions and score changes; do not auto-adjust the threshold.", signals["alert_rate_absolute_change"])
    else:
        finding("no_recent_scores", "ML engineer", "Check the batch schedule and data delivery; surface unavailable status.", 0)
    truth = labels[["asset_id", "date", "target_failure_30d"]].copy()
    truth["date"] = pd.to_datetime(truth.date)
    mature = joined.merge(truth, on=["asset_id", "date"], how="left", validate="one_to_one")
    mature = mature[mature.date.le(as_of-pd.Timedelta(days=30)) & mature.target_failure_30d.isin([0, 1])]
    metrics = {"horizon_days": 30, "mature_rows": len(mature), "precision": None, "recall": None, "brier_score": None}
    if len(mature):
        truth_values = mature.target_failure_30d.eq(1)
        tp = int((truth_values & mature.alert).sum())
        positives, alerts = int(truth_values.sum()), int(mature.alert.sum())
        metrics.update(positive_rows=positives, precision=tp/alerts if alerts else None,
                       recall=tp/positives if positives else None,
                       brier_score=float(np.mean((mature.risk_score-mature.target_failure_30d)**2)))
        if metrics["recall"] is not None and metrics["recall"] < THRESHOLDS["mature_recall_floor"]:
            finding("mature_recall_below_floor", "Data scientist + reliability engineer", "Audit missed events and labeling; require reviewed validation before changing the model.", metrics["recall"])
    return {"as_of": as_of.date().isoformat(), "scope": "local replay; diagnostic thresholds, no automated dispatch/retraining",
            "current_window_days": 7, "reference_window_days": 28, "thresholds": THRESHOLDS,
            "signals": signals, "mature_label_metrics": metrics, "findings": findings}


def run(root: Path) -> dict:
    features = pd.read_csv(root/"data/processed/batch_features.csv")
    labels = pd.read_csv(root/"data/processed/dashboard/scored_readings.csv")
    scorer = BatchScorer(root/"artifacts/model.joblib")
    scored = scorer.score_frame(features)
    as_of = pd.to_datetime(features.date).max()
    baseline = evaluate(scored, features, labels, as_of)
    corrupted = features.copy()
    recent = pd.to_datetime(corrupted.date).ge(as_of-pd.Timedelta(days=6))
    corrupted.loc[recent, "sensor_missing_count"] = 7
    quality_spike = evaluate(scorer.score_frame(corrupted), corrupted, labels, as_of)
    delayed = evaluate(scored, features, labels, as_of+pd.Timedelta(days=7))
    report = {"cloud_deployed": False, "model_version": scorer.version, "artifact_sha256": scorer.artifact_sha256,
              "baseline": baseline, "controlled_quality_flag_spike": quality_spike, "controlled_delivery_delay": delayed,
              "scenario_note": "Quality flag spike exercises monitoring and review responses; it is not a physical sensor fault simulation."}
    out = root/"reports"
    out.mkdir(parents=True, exist_ok=True)
    (out/"monitoring_replay.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    rows = []
    for name in ("baseline", "controlled_quality_flag_spike", "controlled_delivery_delay"):
        rows.extend({"scenario": name, **finding} for finding in report[name]["findings"])
    pd.DataFrame(rows, columns=["scenario", "code", "owner", "response", "value"]).to_csv(out/"monitoring_findings.csv", index=False)
    print(json.dumps({"model_version": scorer.version, "baseline_findings": len(baseline["findings"]),
                      "quality_spike_findings": len(quality_spike["findings"]), "delay_findings": len(delayed["findings"])}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    run(parser.parse_args().root.resolve())
