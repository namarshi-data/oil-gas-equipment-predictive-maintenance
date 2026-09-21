"""Run the Azure batch adapter locally without Azure credentials or resources."""
from pathlib import Path
import argparse
import importlib.util
import importlib.metadata
import hashlib
import json
import os
import platform

import pandas as pd


def validate_predictions(source: pd.DataFrame, predictions: pd.DataFrame, source_file: str) -> None:
    """Reconcile every input record; matching counts alone can hide duplicates."""
    if source.empty or len(source) != len(predictions):
        raise AssertionError("Batch adapter did not return every input record")
    required = {"source_file", "source_row"}
    if not required.issubset(predictions.columns):
        raise AssertionError("Batch output is missing source reconciliation keys")
    if not predictions["source_file"].eq(source_file).all():
        raise AssertionError("Batch output contains an unexpected source file")
    row_numbers = predictions["source_row"]
    if (not pd.api.types.is_integer_dtype(row_numbers)
            or row_numbers.duplicated().any()
            or set(row_numbers) != set(range(len(source)))):
        raise AssertionError("Batch output source rows must cover each input exactly once")
    ordered = predictions.sort_values("source_row").reset_index(drop=True)
    keys = [name for name in ("asset_id", "equipment_id", "date", "timestamp") if name in source]
    if not set(keys).issubset(ordered.columns):
        raise AssertionError("Batch output is missing input identity columns")
    pd.testing.assert_frame_equal(source[keys].reset_index(drop=True), ordered[keys], check_dtype=False,
                                  obj="Input identity at each source row")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    features_path = root / "data" / "processed" / "batch_features.csv"
    source = pd.read_csv(features_path)
    spec = importlib.util.spec_from_file_location("azure_score", Path(__file__).with_name("score.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous_model_dir = os.environ.get("AZUREML_MODEL_DIR")
    try:
        os.environ["AZUREML_MODEL_DIR"] = str(root / "artifacts")
        module.init()
        predictions = module.run([str(features_path)])
    finally:
        if previous_model_dir is None:
            os.environ.pop("AZUREML_MODEL_DIR", None)
        else:
            os.environ["AZUREML_MODEL_DIR"] = previous_model_dir
    validate_predictions(source, predictions, features_path.name)
    output = root / "artifacts" / "azure-local-smoke"
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output / "predictions.csv", index=False)
    report = {"execution": "local simulation of Azure ML batch adapter", "cloud_deployed": False,
              "input_rows": len(source), "output_rows": len(predictions),
              "model_versions": sorted(predictions["model_version"].unique().tolist()),
              "all_rows_scored": True, "source_rows_unique_and_complete": True,
              "asset_date_identity_preserved": True,
              "risk_score_matches_legacy_output": bool(predictions["risk_score"].equals(predictions["failure_probability_30d"])),
              "requires_manual_review_rows": int(predictions["requires_manual_review"].sum()),
              "review_reason_counts": predictions.loc[predictions["requires_manual_review"], "review_reason"].value_counts().to_dict(),
              "model_sha256": hashlib.sha256((root / "artifacts/model.joblib").read_bytes()).hexdigest(),
              "features_sha256": hashlib.sha256(features_path.read_bytes()).hexdigest(),
              "runtime": {"python": platform.python_version(),
                          **{name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scikit-learn")}}}
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()