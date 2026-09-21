"""Causal capacity-constrained maintenance plans and full-program cost scenarios."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, EQUIPMENT
from .policies import replay

PLAN_COLUMNS = ["policy", "asset_id", "site", "alert_date", "service_date", "due_date", "delay_days", "risk_score", "priority_index"]


def consequence(kind):
    spec = EQUIPMENT[kind]
    return spec["emergency_cost"] + spec["emergency_hours"] * spec["downtime_cost"]


def plan_visits(assets, scores, start, end, config, threshold, weekly_capacity):
    """Book visits using only known calendars or scores available on that day.

    Each policy gets the SAME weekly visit capacity in its separate scenario.
    Fixed appointments defer FIFO when capacity is full. Predictive visits book
    dispatch dates greedily in descending current risk-weighted consequence.
    Scores are uncalibrated, so this ranking is NOT expected monetary benefit.
    No failures, labels, event costs or oracle information enter the planner.
    """
    if isinstance(weekly_capacity, bool) or not isinstance(weekly_capacity, int) or weekly_capacity < 0:
        raise ValueError("weekly_capacity must be a nonnegative integer")
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if end < start or config.dispatch_delay_days < 0 or not 0 < threshold <= 1:
        raise ValueError("Invalid planning interval, delay or threshold")
    metadata = assets.set_index("asset_id").to_dict("index")
    if not assets.asset_id.is_unique:
        raise ValueError("Asset keys must be unique")
    available = scores[["asset_id", "date", "risk_score"]].copy()
    available["date"] = pd.to_datetime(available.date)
    if available[["asset_id", "date"]].duplicated().any() or not available.risk_score.between(0, 1).all():
        raise ValueError("Scores must be unique asset-days within [0,1]")
    if set(available.asset_id) - set(metadata):
        raise ValueError("Unknown scoring asset")
    rows, overrides = [], {"fixed_90_day": {}, "predictive": {}}
    book = lambda date: tuple(date.isocalendar()[:2])
    first = start - pd.Timedelta(days=config.actionable_days)
    due = []
    for aid, asset in metadata.items():
        origin = pd.Timestamp(asset["commissioned_date"])
        k = max(1, int(np.ceil((first-origin).days / config.fixed_interval_days)))
        date = origin + pd.Timedelta(days=k*config.fixed_interval_days)
        while date <= end:
            due.append((date, aid))
            date += pd.Timedelta(days=config.fixed_interval_days)
    due.sort()
    queue, used, cursor = [], defaultdict(int), 0
    for day in pd.date_range(first, end):
        while cursor < len(due) and due[cursor][0] <= day:
            queue.append(due[cursor]); cursor += 1
        while queue and used[book(day)] < weekly_capacity:
            original_due, aid = queue.pop(0)
            used[book(day)] += 1
            overrides["fixed_90_day"].setdefault(aid, []).append((day, day))
            rows.append(dict(policy="fixed_90_day", asset_id=aid, site=metadata[aid]["site"],
                alert_date=day.date(), service_date=day.date(), due_date=original_due.date(),
                delay_days=(day-original_due).days, risk_score=None, priority_index=None))
    unserved_fixed = len(queue)
    used, eligible = defaultdict(int), defaultdict(lambda: start)
    capacity_deferrals = 0
    for day, daily in available[available.date.between(start, end)].groupby("date", sort=True):
        candidates = []
        service = day + pd.Timedelta(days=config.dispatch_delay_days)
        if service > end:
            continue
        for row in daily.itertuples():
            if row.risk_score >= threshold and day >= eligible[row.asset_id]:
                candidates.append((row.risk_score * consequence(metadata[row.asset_id]["asset_type"]), row.asset_id, row.risk_score))
        for priority, aid, risk in sorted(candidates, key=lambda r: (-r[0], r[1])):
            if used[book(service)] >= weekly_capacity:
                capacity_deferrals += 1
                continue
            used[book(service)] += 1
            eligible[aid] = service + pd.Timedelta(days=config.service_cooldown_days)
            overrides["predictive"].setdefault(aid, []).append((day, service))
            rows.append(dict(policy="predictive", asset_id=aid, site=metadata[aid]["site"],
                alert_date=day.date(), service_date=service.date(), due_date=service.date(),
                delay_days=config.dispatch_delay_days, risk_score=float(risk), priority_index=float(priority)))
    plan = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    audit = dict(weekly_capacity=weekly_capacity, fixed_due_visits=len(due),
                 fixed_unserved_at_end=unserved_fixed, predictive_capacity_deferred_asset_days=capacity_deferrals,
                 priority="Current raw risk score × type-level emergency repair plus downtime consequence; not calibrated expected value",
                 resource_scope="Equal visits per ISO service week for each alternative policy, including fixed carry-in period")
    return overrides, plan, audit


def program_economics(fixed, predictive, hourly_multiplier, annual_staffing, annual_cloud, annual_support, implementation):
    """Comparable scenario costs; recurring program costs and one-time setup separate."""
    try:
        years = np.asarray([fixed.evaluation_years, predictive.evaluation_years], dtype=float)
        costs = np.asarray([hourly_multiplier, annual_staffing, annual_cloud, annual_support, implementation,
                            fixed.total_cost_cad, fixed.downtime_cost_cad,
                            predictive.total_cost_cad, predictive.downtime_cost_cad], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Evaluation years and costs must be numeric") from exc
    if not np.isfinite(years).all() or (years <= 0).any() or not np.isclose(years[0], years[1], rtol=1e-10, atol=0):
        raise ValueError("Policies must have matched, positive, finite evaluation years")
    if not np.isfinite(costs).all() or (costs < 0).any():
        raise ValueError("Scenario and policy costs must be finite and nonnegative")
    (hourly_multiplier, annual_staffing, annual_cloud, annual_support, implementation,
     fixed_total, fixed_downtime, predictive_total, predictive_downtime) = costs.tolist()
    years = float(years[0])
    fixed_annual = (fixed_total + (hourly_multiplier-1)*fixed_downtime)/years
    predictive_annual = (predictive_total + (hourly_multiplier-1)*predictive_downtime)/years
    operating_savings = fixed_annual - predictive_annual
    recurring = annual_staffing + annual_cloud + annual_support
    net = operating_savings - recurring
    return dict(hourly_cost_multiplier=hourly_multiplier, annual_staffing_cad=annual_staffing,
                annual_cloud_cad=annual_cloud, annual_support_cad=annual_support,
                one_time_implementation_cad=implementation, annual_operating_savings_cad=operating_savings,
                annual_net_program_savings_cad=net, first_year_net_savings_cad=net-implementation,
                break_even_annual_program_budget_cad=operating_savings,
                payback_months=12*implementation/net if net > 0 else None)


def run(root: Path):
    root = root.resolve()
    metrics = json.loads((root/'artifacts/metrics.json').read_text(encoding='utf-8'))
    config = Config(**metrics['config'])
    assets = pd.read_csv(root/'data/processed/assets.csv')
    events = pd.read_csv(root/'data/processed/events.csv').merge(pd.read_csv(root/'data/raw/simulation_truth.csv'), on='event_id', validate='one_to_one')
    scores = pd.read_csv(root/'data/processed/dashboard/scored_readings.csv')
    rows, audits, economics, plans = [], [], [], []
    for capacity in (3, 5, 10, 1000):
        for delay in (2, 7):
            cfg = replace(config, dispatch_delay_days=delay)
            actions, plan, audit = plan_visits(assets, scores, config.test_start, config.test_end, cfg, metrics['threshold'], capacity)
            summary, _, _, _ = replay(assets, events, scores, config.test_start, config.test_end, cfg, metrics['threshold'], planned_actions=actions)
            plan['weekly_capacity'], plan['dispatch_delay_days'] = capacity, delay
            plans.append(plan)
            audits.append(dict(dispatch_delay_days=delay, **audit))
            for record in summary.to_dict('records'):
                rows.append(dict(weekly_capacity=capacity, dispatch_delay_days=delay, **record))
            fixed, predictive = [summary.set_index('policy').loc[name] for name in ('fixed_90_day', 'predictive')]
            for multiplier in (.5, 1., 1.5):
                # Explicit scenario assumptions, not researched salaries/cloud quotes.
                economics.append(dict(weekly_capacity=capacity, dispatch_delay_days=delay,
                    **program_economics(fixed, predictive, multiplier, 150000, 12000, 30000, 75000)))
    summary = pd.DataFrame(rows)
    original = pd.DataFrame(metrics['policies']).set_index('policy')
    unconstrained = summary[(summary.weekly_capacity==1000)&(summary.dispatch_delay_days==2)].set_index('policy')
    for column in ('caught_failures','service_visits','total_cost_cad','unplanned_downtime_hours'):
        np.testing.assert_allclose(unconstrained.loc[original.index,column], original[column], rtol=1e-10)
    complete_plans = pd.concat(plans, ignore_index=True)
    week = pd.to_datetime(complete_plans.service_date).dt.isocalendar()
    check = complete_plans.assign(iso_year=week.year,iso_week=week.week).groupby(['weekly_capacity','dispatch_delay_days','policy','iso_year','iso_week']).size()
    assert all(count <= key[0] for key,count in check.items())
    summary.to_csv(root/'reports/operations_policies.csv',index=False)
    pd.DataFrame(economics).to_csv(root/'reports/operations_economics.csv',index=False)
    complete_plans.to_csv(root/'reports/operations_visits.csv',index=False)
    result = dict(scope='Synthetic constrained scenario; original headline benchmark unchanged',
        scenarios=audits, unlimited_capacity_reconciles_to_original=True, all_weekly_limits_verified=True,
        staffing_cloud_support_assumptions='CAD150000 +12000 +30000 annually; CAD75000 one-time implementation. Authored illustrative inputs, not market quotes.',
        limitations=['Visit count is a coarse capacity proxy; no route optimization, work-hour/skill/parts constraints.',
                     'Raw risk is uncalibrated. Ranking by weighted consequence is a heuristic, not expected-dollar optimization.',
                     'Shared-history causal limits and synthetic annualization still apply. No field ROI is established.'])
    (root/'reports/operations.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    result=run(parser.parse_args().root)
    print(json.dumps({'scenarios':len(result['scenarios']),'unlimited_reconciliation':True,'weekly_limits':True},indent=2))
