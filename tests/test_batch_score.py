"""Contract and failure-mode tests for the deployable scoring path."""
import importlib.util
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from energy_failure.batch_score import BatchScorer


class ExampleModel:
    # Reversed classes deliberately exercises positive-class lookup.
    classes_ = np.array([1, 0])

    def predict_proba(self, frame):
        risk = frame["temperature"] / 100.0
        return np.column_stack([risk, 1 - risk])


class BrokenModel(ExampleModel):
    def predict_proba(self, frame):
        return np.full((len(frame), 2), np.nan)


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path / "model.joblib"
    joblib.dump({"model": ExampleModel(), "features": ["temperature", "vibration"],
                 "threshold": 0.6, "metadata": {"model_version": "test-v1"}}, path)
    return path


def test_feature_order_labels_and_identity(artifact):
    frame = pd.DataFrame({"equipment_id": ["A", "B"], "vibration": [1.0, 2.0],
                          "temperature": [20.0, 70.0], "future_failure_label": [0, 1]})
    result = BatchScorer(artifact).score_frame(frame)
    assert result["failure_probability_30d"].tolist() == [0.2, 0.7]
    assert result["alert"].tolist() == [False, True]
    assert result["equipment_id"].tolist() == ["A", "B"]
    assert "future_failure_label" not in result
    assert result["model_version"].unique().tolist() == ["test-v1"]


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, "invalid", True])
def test_reject_bad_feature_values(artifact, bad):
    with pytest.raises(ValueError, match="Feature values"):
        BatchScorer(artifact).score_frame(pd.DataFrame({"temperature": [bad], "vibration": [1.0]}))


def test_reject_missing_feature(artifact):
    with pytest.raises(ValueError, match="Missing feature"):
        BatchScorer(artifact).score_frame(pd.DataFrame({"temperature": [20.0]}))


def test_reject_duplicate_csv_columns(artifact, tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("temperature,vibration,vibration\n20,1,2\n")
    with pytest.raises(ValueError, match="unique"):
        BatchScorer(artifact).score_csv(csv_path)


def test_reject_invalid_model_probabilities(artifact):
    bundle = joblib.load(artifact)
    bundle["model"] = BrokenModel()
    joblib.dump(bundle, artifact)
    with pytest.raises(ValueError, match="invalid probabilities"):
        BatchScorer(artifact).score_frame(pd.DataFrame({"temperature": [20.0], "vibration": [1.0]}))


def test_azure_adapter_matches_local(artifact, tmp_path, monkeypatch):
    csv_path = tmp_path / "features.csv"
    pd.DataFrame({"equipment_id": ["A", "B"], "temperature": [20.0, 70.0],
                  "vibration": [1.0, 2.0]}).to_csv(csv_path, index=False)
    expected = BatchScorer(artifact).score_csv(csv_path, chunk_size=1)
    assert expected["source_row"].tolist() == [0, 1]
    module_path = Path(__file__).resolve().parents[1] / "deployment" / "score.py"
    spec = importlib.util.spec_from_file_location("azure_score", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("AZUREML_MODEL_DIR", str(tmp_path))
    module.init()
    pd.testing.assert_frame_equal(module.run([str(csv_path)]), expected)


def test_commissioning_review_boundary_preserves_scores_and_alerts(artifact):
    frame = pd.DataFrame({"temperature": [20.0, 70.0, 20.0], "vibration": [1.0, 1.0, 1.0],
                          "age_days": [0, 29, 30]})
    result = BatchScorer(artifact).score_frame(frame)
    assert result["requires_manual_review"].tolist() == [True, True, False]
    assert result["review_reason"].tolist() == ["cold_start_under_30_days", "cold_start_under_30_days", ""]
    assert result["risk_score"].tolist() == result["failure_probability_30d"].tolist() == [0.2, 0.7, 0.2]
    # A low score remains a low score even when review is required; no forced alert.
    assert result["alert"].tolist() == [False, True, False]


def test_missing_age_on_generic_artifact_requires_advisory_review(artifact):
    result = BatchScorer(artifact).score_frame(pd.DataFrame({"temperature": [20.0], "vibration": [1.0]}))
    assert result["requires_manual_review"].tolist() == [True]
    assert result["review_reason"].tolist() == ["age_unavailable"]
    assert result["alert"].tolist() == [False]


@pytest.mark.parametrize("bad_age", [-1, np.nan, np.inf, "29", True, None, 2+3j])
def test_rejects_invalid_commissioning_age_even_if_not_a_model_feature(artifact, bad_age):
    with pytest.raises(ValueError, match="age_days"):
        BatchScorer(artifact).score_frame(pd.DataFrame({"temperature": [20.0], "vibration": [1.0], "age_days": [bad_age]}))
