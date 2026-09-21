"""Same-history policy replay. Oracle information adjudicates visits, never triggers them."""
from dataclasses import replace
import numpy as np
import pandas as pd
from .config import Config, EQUIPMENT

POLICIES = ("reactive", "fixed_90_day", "predictive")

def replay(assets, events, scores, start, end, config: Config, threshold: float, planned_actions=None):
    """Adjudicate policies, optionally using explicit externally planned visits.

    planned_actions is {policy: {asset_id: [(alert_date, service_date), ...]}}.
    The operational planner never receives the event oracle. None preserves the
    original benchmark exactly; an empty policy mapping means no visits.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if planned_actions is not None:
        if set(planned_actions) - {"fixed_90_day", "predictive"}:
            raise ValueError("Only fixed and predictive actions may be overridden")
        for mapping in planned_actions.values():
            if set(mapping) - set(assets.asset_id):
                raise ValueError("Action plan contains unknown assets")
            for actions in mapping.values():
                for alert, service in actions:
                    if pd.Timestamp(alert) > pd.Timestamp(service) or pd.Timestamp(service) > end:
                        raise ValueError("Action dates must be ordered and service cannot exceed evaluation end")
    evaluation_years = ((end-start).days+1)/365.25
    events = events.copy()
    events["event_date"] = pd.to_datetime(events.event_date)
    events = events[events.event_date.between(start,end)]
    scores = scores.copy()
    scores["date"] = pd.to_datetime(scores.date)
    outcomes, visits, asset_rows = [], [], []
    for policy in POLICIES:
        for asset in assets.to_dict("records"):
            aid, kind = asset["asset_id"], asset["asset_type"]
            spec = EQUIPMENT[kind]
            ae = events[events.asset_id.eq(aid)].sort_values("event_date").to_dict("records")
            actions = []
            if planned_actions is not None and policy in planned_actions:
                actions = sorted((pd.Timestamp(a), pd.Timestamp(s))
                                 for a, s in planned_actions[policy].get(aid, []))
            elif policy == "fixed_90_day":
                origin = pd.Timestamp(asset["commissioned_date"])
                # The status quo is already running. Credit pre-window scheduled
                # visits that can still prevent a failure inside the test window.
                lookback = start-pd.Timedelta(days=config.actionable_days)
                first_k = max(1, int(np.ceil((lookback-origin).days/config.fixed_interval_days)))
                service = origin+pd.Timedelta(days=first_k*config.fixed_interval_days)
                while service <= end:
                    actions.append((service, service))
                    service += pd.Timedelta(days=config.fixed_interval_days)
            elif policy == "predictive":
                eligible_after = start
                asc = scores[(scores.asset_id.eq(aid)) & scores.date.between(start,end)].sort_values("date")
                for row in asc.itertuples():
                    if row.date >= eligible_after and row.risk_score >= threshold:
                        service = row.date+pd.Timedelta(days=config.dispatch_delay_days)
                        if service <= end:
                            actions.append((row.date,service))
                            eligible_after = service+pd.Timedelta(days=config.service_cooldown_days)
            caught = {}
            local_visits = []
            for alert, service in actions:
                # Truth used ONLY after a policy has chosen the visit date.
                candidates = [e for e in ae if e["event_id"] not in caught and e["preventable"]
                              and 1 <= (e["event_date"]-service).days <= config.actionable_days]
                candidate = min(candidates,key=lambda e:e["event_date"]) if candidates else None
                success = candidate is not None and candidate["repair_success_draw"] < config.intervention_success
                if success:
                    caught[candidate["event_id"]] = (alert, service)
                row = dict(policy=policy, asset_id=aid, asset_type=kind, site=asset["site"],
                           alert_date=alert.date(),service_date=service.date(),
                           event_id=candidate["event_id"] if candidate else "",
                           outcome="prevented_failure" if success else "intervention_unsuccessful" if candidate else "no_actionable_failure",
                           in_evaluation_window=int(service>=start),
                           planned_cost_cad=spec["planned_cost"], planned_downtime_hours=spec["planned_hours"])
                visits.append(row)
                local_visits.append(row)
            local_outcomes = []
            for event in ae:
                match = caught.get(event["event_id"])
                alert, service = match if match else (None,None)
                row = dict(event_id=event["event_id"], asset_id=aid, asset_type=kind, site=asset["site"],
                           event_date=event["event_date"].date(), policy=policy, caught=int(bool(match)),
                           alert_date=alert.date() if alert else "", service_date=service.date() if service else "",
                           warning_days=(event["event_date"]-alert).days if alert else 0,
                           service_lead_days=(event["event_date"]-service).days if service else 0,
                           repair_cost_cad=0 if match else event["emergency_cost_cad"],
                           downtime_hours=0 if match else event["emergency_downtime_hours"])
                outcomes.append(row)
                local_outcomes.append(row)
            unplanned = sum(x["downtime_hours"] for x in local_outcomes)
            emergency_cost = sum(x["repair_cost_cad"] for x in local_outcomes)
            charged_visits = [v for v in local_visits if v["in_evaluation_window"]]
            planned_hours = len(charged_visits)*spec["planned_hours"]
            planned_cost = len(charged_visits)*spec["planned_cost"]
            asset_rows.append(dict(policy=policy,asset_id=aid,asset_type=kind,site=asset["site"],
                                   event_count=len(ae),caught_failures=len(caught),missed_failures=len(ae)-len(caught),
                                   service_visits=len(charged_visits),carry_in_visits=len(local_visits)-len(charged_visits),
                                   unnecessary_services=sum(x["outcome"]=="no_actionable_failure" for x in charged_visits),
                                   unsuccessful_services=sum(x["outcome"]=="intervention_unsuccessful" for x in charged_visits),
                                   planned_downtime_hours=planned_hours,unplanned_downtime_hours=unplanned,
                                   total_downtime_hours=planned_hours+unplanned,
                                   emergency_repair_cost_cad=emergency_cost,planned_service_cost_cad=planned_cost,
                                   downtime_cost_cad=(planned_hours+unplanned)*spec["downtime_cost"],
                                   total_cost_cad=emergency_cost+planned_cost+(planned_hours+unplanned)*spec["downtime_cost"]))
    detail = pd.DataFrame(asset_rows)
    outcomes = pd.DataFrame(outcomes,columns=["event_id","asset_id","asset_type","site","event_date","policy","caught","alert_date","service_date","warning_days","service_lead_days","repair_cost_cad","downtime_hours"])
    visits = pd.DataFrame(visits,columns=["policy","asset_id","asset_type","site","alert_date","service_date","event_id","outcome","in_evaluation_window","planned_cost_cad","planned_downtime_hours"])
    numeric = [c for c in detail.columns if c not in ["policy","asset_id","asset_type","site"]]
    summary = detail.groupby("policy",sort=False)[numeric].sum().reset_index()
    for i, row in summary.iterrows():
        warnings = outcomes[(outcomes.policy==row.policy)&(outcomes.caught==1)].warning_days
        summary.loc[i,"mean_warning_days"] = float(warnings.mean()) if len(warnings) else 0
        summary.loc[i,"median_warning_days"] = float(warnings.median()) if len(warnings) else 0
    summary["evaluation_years"] = evaluation_years
    summary["asset_years"] = evaluation_years*len(assets)
    summary["annualized_cost_cad"] = summary.total_cost_cad/evaluation_years
    return summary, outcomes, visits, detail

def sensitivity(assets, events, scores, start, end, config, threshold):
    rows = []
    for days in (14,21,30,45):
        for success in (.70,.90,1.):
            scenario = replace(config,actionable_days=days,intervention_success=success)
            summary,_,_,_ = replay(assets,events,scores,start,end,scenario,threshold)
            table = summary.set_index("policy")
            fixed,pred = table.loc["fixed_90_day"],table.loc["predictive"]
            rows.append(dict(actionable_days=days,intervention_success=success,
                             annualized_savings_cad=fixed.annualized_cost_cad-pred.annualized_cost_cad,
                             unplanned_downtime_reduction_pct=100*(1-pred.unplanned_downtime_hours/fixed.unplanned_downtime_hours)
                             if fixed.unplanned_downtime_hours else None,
                             predictive_caught=int(pred.caught_failures),fixed_caught=int(fixed.caught_failures)))
    return pd.DataFrame(rows)
