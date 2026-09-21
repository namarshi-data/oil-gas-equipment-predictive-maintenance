from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from energy_failure.config import Config
from energy_failure.operations import plan_visits, program_economics
from energy_failure.policies import replay


def inputs():
    assets = pd.DataFrame([dict(asset_id=aid,asset_type=kind,site='Test',commissioned_date='2025-01-01')
        for aid,kind in [('A','pumpjack'),('B','compressor'),('C','pipeline_pump')]])
    scores=pd.DataFrame([dict(asset_id=aid,date=date,risk_score=.95) for date in pd.date_range('2025-04-01','2025-04-21') for aid in assets.asset_id])
    return assets,scores


def test_same_weekly_capacity_applies_to_both_policies_and_priority_is_causal():
    assets,scores=inputs()
    _,plan,audit=plan_visits(assets,scores,'2025-04-01','2025-04-21',Config(),.9,1)
    week=pd.to_datetime(plan.service_date).dt.isocalendar()
    assert plan.assign(year=week.year,week=week.week).groupby(['policy','year','week']).size().max()==1
    assert plan[plan.policy.eq('predictive')].iloc[0].asset_id=='B'
    assert plan[plan.policy.eq('fixed_90_day')].iloc[0].asset_id=='A'
    assert plan[plan.policy.eq('fixed_90_day')].delay_days.max()>0
    assert audit['predictive_capacity_deferred_asset_days']>0


def test_future_scores_cannot_change_prior_actions():
    assets,scores=inputs()
    _,first,_=plan_visits(assets,scores,'2025-04-01','2025-04-21',Config(),.9,2)
    altered=scores.copy()
    altered.loc[altered.date>pd.Timestamp('2025-04-10'),'risk_score']=0
    _,second,_=plan_visits(assets,altered,'2025-04-01','2025-04-21',Config(),.9,2)
    columns=['policy','asset_id','alert_date','service_date']
    a=first[pd.to_datetime(first.alert_date)<=pd.Timestamp('2025-04-10')][columns].reset_index(drop=True)
    b=second[pd.to_datetime(second.alert_date)<=pd.Timestamp('2025-04-10')][columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b)


def test_zero_capacity_means_no_visits_not_an_unbounded_fallback():
    assets,scores=inputs()
    actions,plan,audit=plan_visits(assets,scores,'2025-04-01','2025-04-21',Config(),.9,0)
    assert plan.empty and actions=={'fixed_90_day':{},'predictive':{}}
    assert audit['fixed_unserved_at_end']==3
    events=pd.DataFrame([dict(event_id='E',asset_id='A',event_date='2025-04-15',preventable=1,repair_success_draw=0,emergency_cost_cad=100,emergency_downtime_hours=10)])
    summary,_,visits,_=replay(assets,events,scores,'2025-04-01','2025-04-21',Config(),.9,planned_actions=actions)
    assert summary.caught_failures.sum()==0 and visits.empty


def test_program_costs_are_not_double_counted_or_annualized_twice():
    fixed=pd.Series(dict(total_cost_cad=500,downtime_cost_cad=100,evaluation_years=.25))
    predictive=pd.Series(dict(total_cost_cad=300,downtime_cost_cad=50,evaluation_years=.25))
    costs=program_economics(fixed,predictive,1,60,20,20,200)
    assert costs['annual_operating_savings_cad']==800
    assert costs['annual_net_program_savings_cad']==700
    assert costs['first_year_net_savings_cad']==500
    assert costs['payback_months']==pytest.approx(200/700*12)
    loss=program_economics(fixed,predictive,1,1000,0,0,200)
    assert loss['payback_months'] is None


def test_invalid_capacity_and_duplicate_scores_reject():
    assets,scores=inputs()
    for capacity in (-1,True,1.5):
        with pytest.raises(ValueError,match='capacity'):
            plan_visits(assets,scores,'2025-04-01','2025-04-21',Config(),.9,capacity)
    with pytest.raises(ValueError,match='unique'):
        plan_visits(assets,pd.concat([scores,scores.iloc[:1]]),'2025-04-01','2025-04-21',Config(),.9,1)


@pytest.mark.parametrize('fixed_years,predictive_years', [
    (.25,.5), (0,.25), (.25,0), (-.25,.25), (np.nan,.25), (.25,np.inf),
])
def test_program_economics_rejects_unmatched_or_invalid_exposure(fixed_years,predictive_years):
    fixed=pd.Series(dict(total_cost_cad=500,downtime_cost_cad=100,evaluation_years=fixed_years))
    predictive=pd.Series(dict(total_cost_cad=300,downtime_cost_cad=50,evaluation_years=predictive_years))
    with pytest.raises(ValueError,match='matched, positive, finite'):
        program_economics(fixed,predictive,1,60,20,20,200)


@pytest.mark.parametrize('bad_value', [-1,np.nan,np.inf])
def test_program_economics_rejects_invalid_program_and_policy_costs(bad_value):
    fixed=pd.Series(dict(total_cost_cad=500,downtime_cost_cad=100,evaluation_years=.25))
    predictive=pd.Series(dict(total_cost_cad=300,downtime_cost_cad=50,evaluation_years=.25))
    for position in range(5):
        arguments=[1,60,20,20,200]
        arguments[position]=bad_value
        with pytest.raises(ValueError,match='finite and nonnegative'):
            program_economics(fixed,predictive,*arguments)
    for policy in ('fixed','predictive'):
        for field in ('total_cost_cad','downtime_cost_cad'):
            altered_fixed,altered_predictive=fixed.copy(),predictive.copy()
            (altered_fixed if policy=='fixed' else altered_predictive)[field]=bad_value
            with pytest.raises(ValueError,match='finite and nonnegative'):
                program_economics(altered_fixed,altered_predictive,1,60,20,20,200)
