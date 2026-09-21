"""The local smoke proof must detect duplicate or misassociated output records."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest


spec = importlib.util.spec_from_file_location(
    "azure_local_smoke", Path(__file__).resolve().parents[1] / "deployment/local_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@pytest.fixture
def records():
    source = pd.DataFrame({"asset_id": ["A1", "A2"], "date": ["2025-01-01", "2025-01-02"]})
    predictions = source.assign(source_file="features.csv", source_row=[0, 1])
    return source, predictions


def test_reconciliation_accepts_reordered_results(records):
    source, predictions = records
    smoke.validate_predictions(source, predictions.iloc[::-1], "features.csv")


def test_equal_counts_do_not_hide_duplicate_or_missing_records(records):
    source, predictions = records
    predictions.loc[1, "source_row"] = 0
    with pytest.raises(AssertionError, match="exactly once"):
        smoke.validate_predictions(source, predictions, "features.csv")


def test_reconciliation_catches_swapped_asset_identity(records):
    source, predictions = records
    predictions["asset_id"] = ["A2", "A1"]
    with pytest.raises(AssertionError, match="identity"):
        smoke.validate_predictions(source, predictions, "features.csv")


def test_reconciliation_rejects_wrong_source_file(records):
    source, predictions = records
    predictions.loc[0, "source_file"] = "different.csv"
    with pytest.raises(AssertionError, match="unexpected source file"):
        smoke.validate_predictions(source, predictions, "features.csv")


def test_reconciliation_requires_input_identity(records):
    source, predictions = records
    with pytest.raises(AssertionError, match="missing input identity"):
        smoke.validate_predictions(source, predictions.drop(columns="date"), "features.csv")
