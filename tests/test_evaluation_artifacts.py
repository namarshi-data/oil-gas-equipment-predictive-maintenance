"""Reconcile delivered evidence; skipped until the reproducible pipeline is run."""
import json
from pathlib import Path
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT/"artifacts/metrics.json").exists(), reason="Run the pipeline to build integration evidence")

def test_headlines_reconcile_to_independent_policy_ledgers():
    metrics = json.loads((ROOT/"artifacts/metrics.json").read_text())
    folder = ROOT/"data/processed/dashboard"
    summary = pd.read_csv(folder/"policy_summary.csv").set_index("policy")
    events = pd.read_csv(folder/"event_outcomes.csv")
    visits = pd.read_csv(folder/"service_visits.csv")
    for policy,row in summary.iterrows():
        subset = events[events.policy==policy]
        charged = visits[(visits.policy==policy)&(visits.in_evaluation_window==1)]
        assert row.event_count == len(subset)
        assert row.caught_failures == subset.caught.sum()
        assert row.missed_failures+row.caught_failures == row.event_count
        assert row.unplanned_downtime_hours == pytest.approx(subset.downtime_hours.sum())
        assert row.emergency_repair_cost_cad == pytest.approx(subset.repair_cost_cad.sum())
        assert row.planned_service_cost_cad == pytest.approx(charged.planned_cost_cad.sum())
        assert row.planned_downtime_hours == pytest.approx(charged.planned_downtime_hours.sum())
        assert row.service_visits == len(charged)
        assert row.total_cost_cad == pytest.approx(row.emergency_repair_cost_cad+row.planned_service_cost_cad+row.downtime_cost_cad)
    pred,fixed,reactive = [summary.loc[x] for x in ["predictive","fixed_90_day","reactive"]]
    assert metrics["headline"]["unplanned_downtime_reduction_pct"] == pytest.approx(100*(fixed.unplanned_downtime_hours-pred.unplanned_downtime_hours)/fixed.unplanned_downtime_hours)
    assert metrics["headline"]["annualized_net_savings_cad"] == pytest.approx((fixed.total_cost_cad-pred.total_cost_cad)/pred.evaluation_years)
    assert metrics["headline"]["annualized_emergency_repair_savings_cad"] == pytest.approx((reactive.emergency_repair_cost_cad-pred.emergency_repair_cost_cad)/pred.evaluation_years)

def test_dashboard_labels_are_censored_and_sql_preserves_asset_days():
    metrics = json.loads((ROOT/"artifacts/metrics.json").read_text())
    scores = pd.read_csv(ROOT/"data/processed/dashboard/scored_readings.csv",parse_dates=["date"])
    assert scores[["asset_id","date"]].duplicated().sum()==0
    assert scores.risk_score.between(0,1).all()
    assert scores.alert.eq(scores.risk_score>=metrics["threshold"]).all()
    censor = scores.date+pd.Timedelta(days=30)>pd.Timestamp(metrics["config"]["end"])
    assert scores.loc[censor,"target_failure_30d"].isna().all()
    assert scores.loc[~censor,"target_failure_30d"].isin([0,1]).all()
    assert metrics["quality"]["clean_readings"] == metrics["data"]["expected_asset_days"]
