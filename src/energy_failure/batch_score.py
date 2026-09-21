"""Use the same validated scorer locally and in an Azure ML batch deployment.

Only load trusted joblib artifacts: joblib deserialization executes Python code.
Input CSVs contain already engineered, causal features in the training contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from .input_quality import review_flags


class BatchScorer:
    """Validate a versioned artifact and score bounded CSV chunks."""

    def __init__(self, artifact_path: str | Path):
        artifact_path = Path(artifact_path)
        bundle = joblib.load(artifact_path)
        if not isinstance(bundle, dict):
            raise ValueError("Model artifact must be a dictionary")
        features = bundle.get("features")
        if (not isinstance(features, list) or not features
                or any(not isinstance(name, str) or not name for name in features)
                or len(set(features)) != len(features)):
            raise ValueError("Model features must be unique nonempty strings")
        threshold = bundle.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("Model threshold must be numeric")
        if not np.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("Model threshold must be finite and within [0, 1]")
        self.model = bundle.get("model")
        if not callable(getattr(self.model, "predict_proba", None)):
            raise ValueError("Model must implement predict_proba")
        classes = list(getattr(self.model, "classes_", []))
        if len(classes) != 2 or set(classes) != {0, 1}:
            raise ValueError("Model classes must be binary labels 0 and 1")
        self.positive_column = classes.index(1)
        self.features = features
        self.threshold = float(threshold)
        metadata = bundle.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Model metadata must be a dictionary")
        if metadata.get("target_horizon_days", 30) != 30:
            raise ValueError("This scoring contract requires a 30-day model")
        self.version = str(metadata.get("model_version") or metadata.get("version")
                           or hashlib.sha256(artifact_path.read_bytes()).hexdigest()[:12])
        self.artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    def score_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Score required features and add an independent commissioning review flag.

        The review flag does not change the classifier score or threshold alert.
        A model that requires age_days still rejects that missing feature; generic
        artifacts without age as a feature can score with age_unavailable review.
        """
        if not frame.columns.is_unique:
            raise ValueError("Duplicate input columns are not allowed")
        missing = sorted(set(self.features) - set(frame.columns))
        if missing:
            raise ValueError(f"Missing feature columns: {missing}")
        values = frame.loc[:, self.features]
        if any(not pd.api.types.is_numeric_dtype(values[name])
               or pd.api.types.is_bool_dtype(values[name]) for name in self.features):
            raise ValueError("Feature values must be numeric, not booleans or strings")
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError("Feature values must be finite and non-null")
        if frame.empty:
            raise ValueError("Input contains no rows")
        quality = review_flags(frame)
        probabilities = np.asarray(self.model.predict_proba(values), dtype=float)
        if probabilities.shape != (len(frame), 2):
            raise ValueError("Model returned an unexpected probability shape")
        if (not np.isfinite(probabilities).all()
                or ((probabilities < 0) | (probabilities > 1)).any()
                or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6)):
            raise ValueError("Model returned invalid probabilities")
        risk = probabilities[:, self.positive_column]
        # Preserve record keys for reconciliation; never copy labels into outputs.
        keys = [name for name in ("asset_id", "equipment_id", "timestamp", "date", "cycle_id", "asset_type", "site")
                if name in frame.columns]
        result = frame.loc[:, keys].copy().reset_index(drop=True)
        result["failure_probability_30d"] = risk
        result["alert"] = risk >= self.threshold
        result["threshold"] = self.threshold
        result["model_version"] = self.version
        # Retain the legacy output column/order; both score names are uncalibrated.
        # Commissioning review is advisory and never dispatches maintenance.
        result["risk_score"] = risk
        result["requires_manual_review"] = quality.requires_manual_review.to_numpy()
        result["review_reason"] = quality.review_reason.to_numpy()
        result["model_artifact_sha256"] = self.artifact_sha256
        return result

    def score_csv(self, path: str | Path, chunk_size: int = 10000) -> pd.DataFrame:
        path = Path(path)
        # pandas otherwise silently renames duplicate CSV headers (x -> x.1).
        with path.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        if not header or len(set(header)) != len(header):
            raise ValueError("CSV must contain unique, nonempty column headers")
        results: list[pd.DataFrame] = []
        offset = 0
        for chunk in pd.read_csv(path, chunksize=chunk_size):
            if chunk.empty:
                continue
            result = self.score_frame(chunk)
            result.insert(0, "source_row", np.arange(offset, offset + len(chunk)))
            result.insert(0, "source_file", path.name)
            results.append(result)
            offset += len(chunk)
        if not results:
            raise ValueError(f"CSV contains no data rows: {path.name}")
        return pd.concat(results, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True,
                        help="One feature CSV or a directory containing feature CSVs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scorer = BatchScorer(args.model)
    files = sorted(args.input.glob("*.csv")) if args.input.is_dir() else [args.input]
    if not files:
        parser.error("Input directory contains no CSV files")
    predictions = pd.concat([scorer.score_csv(path) for path in files], ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(args.output, index=False)
    print(f"Scored {len(predictions):,} rows with model {scorer.version}: {args.output}")


if __name__ == "__main__":
    main()
