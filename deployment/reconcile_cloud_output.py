"""Fail-closed gate for Azure headerless append-row output versus component output."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd


def reconcile(expected_path: Path, actual_path: Path) -> dict:
    expected = pd.read_csv(expected_path, keep_default_na=False)
    actual = pd.read_csv(actual_path, header=None, keep_default_na=False)
    if actual.shape[1] != len(expected.columns):
        raise ValueError("Cloud CSV column count differs from the reference scoring schema")
    actual.columns = expected.columns
    keys = ["source_file", "source_row"]
    if not set(keys).issubset(expected) or expected.empty:
        raise ValueError("Expected scoring output has no source record contract")
    for frame in (expected, actual):
        frame["source_row"] = pd.to_numeric(frame.source_row, errors="raise")
        if frame[keys].duplicated().any() or not frame.source_row.mod(1).eq(0).all():
            raise ValueError("Source record keys must be unique and integral")
    if set(map(tuple, expected[keys].to_numpy())) != set(map(tuple, actual[keys].to_numpy())):
        raise ValueError("Cloud output omitted or introduced source records")
    expected, actual = [frame.sort_values(keys).reset_index(drop=True) for frame in (expected, actual)]
    for column in expected:
        if pd.api.types.is_numeric_dtype(expected[column]) and not pd.api.types.is_bool_dtype(expected[column]):
            observed = pd.to_numeric(actual[column], errors="raise")
            if not np.allclose(expected[column], observed, rtol=1e-9, atol=1e-12):
                raise ValueError(f"Cloud values differ for {column}")
        elif pd.api.types.is_bool_dtype(expected[column]):
            if not expected[column].astype(str).str.lower().equals(actual[column].astype(str).str.lower()):
                raise ValueError(f"Cloud values differ for {column}")
        elif not expected[column].astype(str).equals(actual[column].astype(str)):
            raise ValueError(f"Cloud values differ for {column}")
    return {"passed": True, "rows": len(expected), "columns": list(expected),
            "source_keys_complete_unique": True, "identity_scores_and_advisories_match": True,
            "model_versions": sorted(expected.model_version.astype(str).unique().tolist())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = reconcile(args.expected, args.actual)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report))