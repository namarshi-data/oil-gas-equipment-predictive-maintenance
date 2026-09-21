"""Independent row-ledger checks for the Power BI contract; does not execute DAX."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]

def load(root=ROOT):
    folder=Path(root)/"data/processed/dashboard"
    return {key:pd.read_csv(folder/name) for key,name in {
        "assets":"dim_asset.csv","sites":"dim_site.csv","users":"dim_user_site.csv",
        "settings":"model_settings.csv","readings":"scored_readings.csv",
        "events":"event_outcomes.csv","visits":"service_visits.csv"}.items()}

def authorized_sites(data,upn):
    users=data["users"]
    return set(users.loc[users.user_principal_name.str.strip().str.lower().eq(upn.strip().lower()),"site"])

def reference_metrics(data,policy,sites=None,assets=None,start=None,end=None,override_rate=None):
    setting=data["settings"].iloc[0]
    start=max(start or setting.evaluation_start,setting.evaluation_start)
    end=min(end or setting.evaluation_end,setting.evaluation_end)
    rates=data["assets"].set_index("asset_id").default_downtime_cost_per_hour
    subsets={}
    for kind,datecol in [("readings","date"),("events","event_date"),("visits","service_date")]:
        frame=data[kind]
        keep=frame[datecol].between(start,end)
        if sites is not None: keep &= frame.site.isin(sites)
        if assets is not None: keep &= frame.asset_id.isin(assets)
        if kind!="readings": keep &= frame.policy.eq(policy)
        if kind=="visits": keep &= frame.in_evaluation_window.eq(1)
        subsets[kind]=frame.loc[keep]
    r,e,v=[subsets[k] for k in ["readings","events","visits"]]
    days=int(r.date.nunique())
    erate=e.asset_id.map(rates) if override_rate is None else override_rate
    vrate=v.asset_id.map(rates) if override_rate is None else override_rate
    cost=float(e.repair_cost_cad.sum()+v.planned_cost_cad.sum()+(e.downtime_hours*erate).sum()+(v.planned_downtime_hours*vrate).sum())
    caught=e[e.caught.eq(1)]
    return dict(cost=cost,annualized_cost=cost*365.25/days if days else None,
                evaluation_days=days,event_count=len(e),caught=len(caught),missed=len(e)-len(caught),
                catch_rate=len(caught)/len(e) if len(e) else None,
                warning_days=float(caught.warning_days.mean()) if len(caught) else None,
                service_visits=len(v),unnecessary=int(v.outcome.eq("no_actionable_failure").sum()),
                unsuccessful=int(v.outcome.eq("intervention_unsuccessful").sum()),
                false_alarm_rate=float(v.outcome.eq("no_actionable_failure").mean()) if len(v) else None,
                unplanned_hours=float(e.downtime_hours.sum()),planned_hours=float(v.planned_downtime_hours.sum()))

def validate(root=ROOT):
    root=Path(root)
    data=load(root)
    assert data["assets"].asset_id.is_unique
    assert data["sites"].site.is_unique
    assert not data["users"].duplicated().any()
    assert set(data["users"].site)<=set(data["sites"].site)
    assert not data["readings"].duplicated(["asset_id","date"]).any()
    assert not data["events"].duplicated(["event_id","policy"]).any()
    assert not data["visits"].duplicated(["asset_id","policy","service_date"]).any()
    asset_sites=data["assets"].set_index("asset_id").site
    for key in ["readings","events","visits"]:
        f=data[key]
        assert set(f.asset_id)<=set(data["assets"].asset_id)
        assert f.site.eq(f.asset_id.map(asset_sites)).all(),f"Site/asset mismatch in {key}"
    summary=pd.read_csv(root/"data/processed/dashboard/policy_summary.csv").set_index("policy")
    detail=pd.read_csv(root/"data/processed/dashboard/policy_asset_detail.csv")
    results={}
    for policy,row in summary.iterrows():
        m=reference_metrics(data,policy)
        for got,expected in [(m["cost"],row.total_cost_cad),(m["annualized_cost"],row.annualized_cost_cad),
                             (m["caught"],row.caught_failures),(m["missed"],row.missed_failures),
                             (m["service_visits"],row.service_visits),(m["unnecessary"],row.unnecessary_services),
                             (m["unsuccessful"],row.unsuccessful_services)]:
            assert np.isclose(got,expected), (policy,got,expected)
        results[policy]=m
        for site in data["sites"].site:
            actual=reference_metrics(data,policy,sites={site})["cost"]
            expected=detail.loc[detail.policy.eq(policy)&detail.site.eq(site),"total_cost_cad"].sum()
            assert np.isclose(actual,expected),(policy,site,actual,expected)
    r=data["readings"]
    labeled=r[r.target_failure_30d.notna()]
    confusion={name:int(((labeled.target_failure_30d==truth)&(labeled.alert==prediction)).sum())
               for name,truth,prediction in [("TP",1,1),("FP",0,1),("FN",1,0),("TN",0,0)]}
    assert sum(confusion.values())==len(labeled)
    unknown=authorized_sites(data,"unknown@portfolio.example")
    assert not unknown
    security={}
    for upn in ["peace.manager@portfolio.example","multi.manager@portfolio.example","fleet.reviewer@portfolio.example","unknown@portfolio.example"]:
        allowed=authorized_sites(data,upn)
        security[upn]={"sites":sorted(allowed),**{k:int(data[k].site.isin(allowed).sum()) for k in ["readings","events","visits"]}}
    return {"fact_grains_valid":True,"dimension_keys_and_site_consistency_valid":True,
            "aggregate_references_used_only_for_validation":True,"baseline_policy_metrics":results,
            "site_policy_metrics":{site:{policy:reference_metrics(data,policy,sites={site}) for policy in results} for site in data["sites"].site},
            "uniform_1000_policy_metrics":{policy:reference_metrics(data,policy,override_rate=1000) for policy in results},
            "confusion_matrix":confusion,"labeled_rows":len(labeled),"censored_rows":len(r)-len(labeled),
            "rls_reference_cases":security,"dax_executed":False,"service_role_tested":False}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,default=ROOT)
    args=p.parse_args();result=validate(args.root)
    out=args.root/"powerbi/data_validation.json";out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
