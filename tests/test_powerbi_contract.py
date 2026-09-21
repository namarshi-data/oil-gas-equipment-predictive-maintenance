"""Business and security reference cases for the authored Power BI model."""
import importlib.util
from pathlib import Path
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("powerbi_validation",ROOT/"powerbi/validate_data.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.fixture(scope="module")
def data(): return module.load(ROOT)

def test_detail_facts_reconcile_to_legacy_validation_references():
    result=module.validate(ROOT)
    assert result["labeled_rows"]==4880 and result["censored_rows"]==2400

def test_unmapped_manager_has_no_fact_rows(data):
    sites=module.authorized_sites(data,"unknown@portfolio.example")
    assert not sites
    for key in ["readings","events","visits"]:
        assert data[key][data[key].site.isin(sites)].empty
    assert module.reference_metrics(data,"predictive",sites=sites)["annualized_cost"] is None

def test_upn_normalization_and_multi_site_access(data):
    assert module.authorized_sites(data," PEACE.Manager@portfolio.example ")=={"Peace River"}
    assert module.authorized_sites(data,"multi.manager@portfolio.example")=={"Peace River","Grande Prairie"}

def test_site_filter_is_preserved_in_policy_comparison(data):
    for site in data["sites"].site:
        selected={site}
        pred=module.reference_metrics(data,"predictive",sites=selected)
        reactive=module.reference_metrics(data,"reactive",sites=selected)
        assert pred["evaluation_days"]==91
        assert reactive["annualized_cost"]-pred["annualized_cost"]>0
        assert reactive["annualized_cost"]!=module.reference_metrics(data,"reactive")["annualized_cost"]

def test_parameter_changes_only_downtime_cost(data):
    a=module.reference_metrics(data,"predictive",override_rate=0)
    b=module.reference_metrics(data,"predictive",override_rate=1000)
    assert b["cost"]-a["cost"]==pytest.approx(1000*(b["unplanned_hours"]+b["planned_hours"]))
    assert a["caught"]==b["caught"] and a["service_visits"]==b["service_visits"]

def test_annualization_uses_selected_observed_calendar_days(data):
    selected=module.reference_metrics(data,"predictive",start="2025-05-01",end="2025-05-31")
    assert selected["evaluation_days"]==31
    assert selected["annualized_cost"]==pytest.approx(selected["cost"]*365.25/31)
    # A future period with no telemetry must not invent exposure.
    empty=module.reference_metrics(data,"predictive",start="2026-01-01",end="2026-01-31")
    assert empty["annualized_cost"] is None

def test_false_service_rate_keeps_unsuccessful_interventions_separate(data):
    result=module.reference_metrics(data,"predictive")
    assert result["false_alarm_rate"]==pytest.approx(10/51)
    assert result["unsuccessful"]==4
    assert result["catch_rate"]==pytest.approx(37/44)

def test_existing_schedule_carry_in_is_auditable_but_not_billed(data):
    visits=data["visits"]
    prior=visits[(visits.policy=="fixed_90_day")&(visits.in_evaluation_window==0)]
    assert len(prior)==25
    assert prior.planned_cost_cad.sum()>0
    assert module.reference_metrics(data,"fixed_90_day")["service_visits"]==81
