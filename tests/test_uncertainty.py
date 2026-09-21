"""Resample whole equipment histories and paired costs, not independent daily rows."""
import numpy as np
import pandas as pd
import pytest

from energy_failure.uncertainty import bootstrap_classification, bootstrap_paired_policy_cost, cluster_totals


def test_single_asset_keeps_entire_correlated_history_in_every_replicate():
    scores = pd.DataFrame(dict(asset_id=["A"] * 4, target_failure_30d=[1, 1, 0, 0], risk_score=[.99, .1, .99, .1]))
    result = bootstrap_classification(scores, .9, 100, 7)
    assert result["assets"] == 1 and result["rows"] == 4
    for name in ("precision", "recall", "false_positive_rate"):
        interval = result["metrics"][name]
        assert interval["point"] == interval["lower_95"] == interval["upper_95"] == .5


def test_cluster_bootstrap_allows_undefined_denominators_without_false_perfection():
    scores = pd.DataFrame(dict(asset_id=["A", "B"], target_failure_30d=[0, 0], risk_score=[.1, .1]))
    result = bootstrap_classification(scores, .9, 20, 7)
    assert result["metrics"]["precision"]["point"] is None
    assert result["metrics"]["recall"]["valid_replicates"] == 0
    assert result["metrics"]["false_positive_rate"]["point"] == 0
    with pytest.raises(ValueError):
        cluster_totals(scores.assign(target_failure_30d=[0, np.nan]), .9)


def test_cost_bootstrap_pairs_policies_by_asset_and_annualizes_after_sum():
    detail = pd.DataFrame(dict(asset_id=["A", "B", "A", "B"],
        policy=["fixed_90_day", "fixed_90_day", "predictive", "predictive"], total_cost_cad=[20, 10, 10, 20]))
    result = bootstrap_paired_policy_cost(detail, 2, 2000, 7)
    assert result["window_cost_difference_cad"]["point"] == 0
    assert result["window_cost_difference_cad"]["lower_95"] == -20
    assert result["window_cost_difference_cad"]["upper_95"] == 20
    assert result["annualized_cost_difference_cad"]["lower_95"] == -40
    assert result == bootstrap_paired_policy_cost(detail.sample(frac=1, random_state=9), 2, 2000, 7)
    with pytest.raises(ValueError, match="Both"):
        bootstrap_paired_policy_cost(detail.iloc[:3], 2)
    with pytest.raises(ValueError, match="exactly one"):
        bootstrap_paired_policy_cost(pd.concat([detail, detail.iloc[:1]]), 2)
