"""Partitions and probability evaluation must preserve their scientific meaning."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from energy_failure.config import Config
from energy_failure.generalization import calendar_masks, clipped_logit, fit_calibrator, probability_metrics, split_assets


def test_asset_holdout_is_disjoint_complete_and_order_independent():
    ids = [f"AB-{i:03d}" for i in range(1, 81)]
    train, holdout = split_assets(ids)
    assert len(train) == 60 and len(holdout) == 20
    assert set(train).isdisjoint(holdout)
    assert set(train) | set(holdout) == set(ids)
    assert split_assets(reversed(ids)) == (train, holdout)
    with pytest.raises(ValueError):
        split_assets(ids, 80)


def test_calendar_masks_reject_horizon_overlap_and_exclude_censoring():
    frame = pd.DataFrame(dict(date=pd.to_datetime(["2024-10-31", "2024-12-01", "2025-04-01", "2025-06-01"]),
        target_failure_30d=[0, 1, 1, np.nan]))
    masks = calendar_masks(frame, Config())
    assert masks["train"].tolist() == [True, False, False, False]
    assert masks["test"].tolist() == [False, False, True, False]
    with pytest.raises(ValueError, match="Training"):
        calendar_masks(frame, replace(Config(), validation_start="2024-11-30"))
    with pytest.raises(ValueError, match="Validation"):
        calendar_masks(frame, replace(Config(), test_start="2025-03-30"))


def test_calibration_handles_extreme_scores_without_reusing_raw_threshold():
    assert np.isfinite(clipped_logit([0, 1])).all()
    calibrator = fit_calibrator([.05, .1, .2, .7, .8, .95], [0, 0, 1, 0, 1, 1])
    transformed = calibrator.predict_proba(clipped_logit([0, .5, 1]))[:, 1]
    assert np.isfinite(transformed).all() and ((transformed >= 0) & (transformed <= 1)).all()
    metrics = probability_metrics([0, 1, 1], transformed)
    assert "precision" not in metrics and "recall" not in metrics
    assert metrics["brier_score"] >= 0 and metrics["log_loss"] >= 0
    with pytest.raises(ValueError, match="both"):
        fit_calibrator([.1, .2], [0, 0])


def test_prospective_protocol_separates_calibration_and_every_external_seed():
    path = Path(__file__).resolve().parents[1] / "docs/generalization-protocol.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    seeds = protocol["external_fleet_seeds"]
    assert seeds == [101, 202, 303]
    assert len(set(seeds + [protocol["reference_seed"], protocol["calibration_development_seed"]])) == 5
    assert protocol["bootstrap"]["unit"] == "asset"
