"""Decision-changing MLOps contracts without a full benchmark or Azure account."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from energy_failure.input_quality import history_quality, review_flags
from energy_failure.monitoring import evaluate
from energy_failure.provenance import build_provenance

ROOT = Path(__file__).resolve().parents[1]


def test_provenance_changes_with_inputs_but_not_local_folder(tmp_path):
    repo, raw = tmp_path/"repo", tmp_path/"raw"
    (repo/"src").mkdir(parents=True); raw.mkdir()
    (repo/"src/model.py").write_text("model = 1\n")
    data = raw/"readings.csv"; data.write_text("x\n1\n")
    args = (repo, raw, {"seed": 42}, ["x"], "test", .5)
    a = build_provenance(*args)
    assert a["model_version"] == build_provenance(*args)["model_version"]
    data.write_text("x\n2\n")
    b = build_provenance(*args)
    assert a["model_version"] != b["model_version"]
    assert a["data_sha256"] != b["data_sha256"]
    assert a["code_sha256"] == b["code_sha256"]


def test_flatline_requires_seven_valid_consecutive_observations_and_no_future():
    frame = pd.DataFrame({"asset_id": ["A"]*8, "date": pd.date_range("2025-01-01", periods=8),
                          "vibration_mm_s": [3.]*7+[4.], "vibration_mm_s_missing": [0]*8})
    maintenance = pd.DataFrame({"asset_id": ["A"], "service_date": ["2025-01-08"]})
    full = history_quality(frame, maintenance)
    prefix = history_quality(frame.iloc[:7], maintenance)
    assert full.sensor_flatline.tolist() == [False]*6+[True, False]
    assert full.maintenance_history_known.tolist() == [False]*7+[True]
    pd.testing.assert_frame_equal(full.iloc[:7], prefix)
    frame.loc[4, "vibration_mm_s_missing"] = 1
    assert not history_quality(frame, maintenance).sensor_flatline.any()


def test_quality_guards_are_independent_and_do_not_claim_unknown_is_known():
    result = review_flags(pd.DataFrame({"age_days": [50, 50], "sensor_missing_count": [1, 0],
        "telemetry_staleness_days": [3, 0], "maintenance_history_known": [False, True], "sensor_flatline": [True, False]}))
    assert result.requires_manual_review.tolist() == [True, False]
    assert result.review_reason.iloc[0] == "imputed_inputs;stale_inputs;maintenance_history_unknown;sensor_flatline_review"
    assert review_flags(pd.DataFrame({"age_days": [50]})).review_reason.iloc[0] == ""
    with pytest.raises(ValueError):
        review_flags(pd.DataFrame({"age_days": [50], "sensor_missing_count": [8]}))


def monitor_fixture():
    dates = ["2025-01-01", "2025-01-02", "2025-01-31"]
    scores = pd.DataFrame({"asset_id": ["A"]*3, "date": dates, "risk_score": [.9, .1, .8],
                           "alert": [True, False, True], "requires_manual_review": [False]*3})
    inputs = scores[["asset_id", "date"]].assign(sensor_missing_count=0)
    labels = inputs[["asset_id", "date"]].assign(target_failure_30d=[1, 1, 1])
    return scores, inputs, labels


def test_monitor_never_scores_immature_labels_even_if_supplied():
    report = evaluate(*monitor_fixture(), "2025-01-31")
    assert report["mature_label_metrics"]["mature_rows"] == 1  # Jan 1 is exactly 30 days old.
    assert report["mature_label_metrics"]["recall"] == 1
    delayed = evaluate(*monitor_fixture(), "2025-02-08")
    assert delayed["signals"]["stale_assets"] == 1
    assert {f["code"] for f in delayed["findings"]} >= {"stale_assets", "no_recent_scores"}


def test_monitor_rejects_same_count_different_keys():
    scores, inputs, labels = monitor_fixture()
    inputs.loc[0, "asset_id"] = "B"
    with pytest.raises(ValueError, match="reconcile"):
        evaluate(scores, inputs, labels, "2025-01-31")


def test_clean_checkout_real_model_adapter_integration(tmp_path):
    """Fit a tiny real estimator; no ignored/published project artifact required."""
    x = pd.DataFrame({"temperature": [10., 20., 80., 90.]})
    model = LogisticRegression().fit(x, [0, 0, 1, 1])
    (tmp_path/"artifacts").mkdir()
    (tmp_path/"data/processed").mkdir(parents=True)
    joblib.dump({"model": model, "features": ["temperature"], "threshold": .5,
                 "metadata": {"model_version": "ci-fit-model"}}, tmp_path/"artifacts/model.joblib")
    x.assign(asset_id=["A", "B", "C", "D"], date="2025-01-01", age_days=40).to_csv(tmp_path/"data/processed/batch_features.csv", index=False)
    subprocess.run([sys.executable, str(ROOT/"deployment/local_smoke.py"), "--root", str(tmp_path)], check=True, capture_output=True)
    report = json.loads((tmp_path/"artifacts/azure-local-smoke/validation.json").read_text())
    assert report["source_rows_unique_and_complete"] and report["output_rows"] == 4
    assert report["cloud_deployed"] is False


def test_cloud_reconciliation_is_order_independent_and_rejects_wrong_identity(tmp_path):
    spec = importlib.util.spec_from_file_location("reconcile", ROOT/"deployment/reconcile_cloud_output.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    expected = pd.DataFrame({"source_file": ["input.csv"]*2, "source_row": [0, 1], "asset_id": ["A", "B"],
                             "risk_score": [.2, .9], "alert": [False, True], "model_version": ["v3"]*2})
    a, b = tmp_path/"expected.csv", tmp_path/"actual.csv"
    expected.to_csv(a, index=False); expected.iloc[::-1].to_csv(b, index=False, header=False)
    assert module.reconcile(a, b)["passed"]
    wrong_identity = expected.copy(); wrong_identity.loc[0, "asset_id"] = "a"
    wrong_identity.to_csv(b, index=False, header=False)
    with pytest.raises(ValueError, match="asset_id"):
        module.reconcile(a, b)
    expected.loc[1, "source_row"] = 0
    expected.to_csv(b, index=False, header=False)
    with pytest.raises(ValueError, match="unique"):
        module.reconcile(a, b)


def test_deployment_promotion_occurs_only_after_reconciliation():
    script = (ROOT/"deployment/deploy.ps1").read_text()
    assert "--set-default" not in script
    assert "'--deployment-name', $candidate" in script
    assert script.index("deployment/reconcile_cloud_output.py") < script.index('"defaults.deployment_name=$candidate"')
    assert "rollback_arguments" in script
