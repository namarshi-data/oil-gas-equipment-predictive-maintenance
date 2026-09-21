"""Verify published reference bytes without requiring ignored training data.

The unit tests exercise provenance generation on small fixtures. These checks
instead protect the delivered model from stale source or environment files,
including byte-level changes such as removal of a final newline.
"""
import hashlib
import json
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[1]


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def test_published_code_and_environment_match_reference_provenance():
    provenance = read_json("artifacts/provenance.json")
    for group in ("code_files", "environment_files"):
        recorded = provenance[group]
        assert recorded, f"Reference provenance has no {group}"
        for relative, expected_hash in recorded.items():
            path = ROOT / relative
            assert path.is_file(), f"Required reference file is missing: {relative}"
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual_hash == expected_hash, (
                f"Reference provenance mismatch: {relative}. Restore the recorded "
                "file bytes or intentionally regenerate the model and its evidence."
            )


def test_published_model_and_metadata_mirrors_share_reference_identity():
    provenance = read_json("artifacts/provenance.json")
    model_path = ROOT / "artifacts/model.joblib"
    assert model_path.is_file(), "Required reference model is missing"
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() == provenance["model_artifact_sha256"]
    # Load only after the supplied artifact has matched its recorded hash.
    bundle = joblib.load(model_path)
    metadata = bundle["metadata"]
    recorded_training = {key: value for key, value in provenance.items() if key != "model_artifact_sha256"}
    assert metadata["provenance"] == recorded_training
    assert metadata["model_version"] == metadata["version"] == provenance["model_version"]
    metrics = read_json("artifacts/metrics.json")
    assert metrics["runtime"] == metadata
    assert bundle["features"] == read_json("artifacts/features.json") == provenance["features"]
    assert bundle["threshold"] == metrics["threshold"] == provenance["threshold"]
    assert metrics["selected_model"] == provenance["algorithm"]
