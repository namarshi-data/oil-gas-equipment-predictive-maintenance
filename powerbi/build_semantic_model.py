"""Generate the reviewable TMDL star schema and its report binding contract.

Reporting reads atomic ledgers and asset metadata. Policy aggregates are validation
references only. This generator never writes model.bim or a PBIX binary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFINITION = ROOT / "EnergyPredictiveMaintenance.SemanticModel" / "definition"
M_TYPES = {"string": "type text", "int64": "Int64.Type", "double": "type number", "dateTime": "type date"}
TABLES: dict = {}
MEASURES: list[dict] = []


def quoted(name):
    return "'" + name.replace("'", "''") + "'"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def csv_query(filename, fields, additions=None):
    ordinary = [f'{{"{name}", {M_TYPES[kind]}}}' for name, kind in fields.items() if kind != "boolean"]
    booleans = [name for name, kind in fields.items() if kind == "boolean"]
    lines = ["let", f'    Source = Csv.Document(File.Contents(DataFolder & "/{filename}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
             '    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
             '    BlankToNull = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, Table.ColumnNames(Headers)),',
             '    Typed = Table.TransformColumnTypes(BlankToNull, {' + ", ".join(ordinary) + '}, "en-CA")']
    previous = "Typed"
    if booleans:
        pairs = [f'{{"{name}", each if _ = null then null else if List.Contains({{"1", "1.0", "true"}}, Text.Lower(Text.From(_))) then true else if List.Contains({{"0", "0.0", "false"}}, Text.Lower(Text.From(_))) then false else error "Invalid boolean", type nullable logical}}' for name in booleans]
        lines[-1] += ","
        lines.append('    Logical = Table.TransformColumns(Typed, {' + ", ".join(pairs) + '})')
        previous = "Logical"
    for step, expression in additions or []:
        lines[-1] += ","
        lines.append(f"    {step} = " + expression.replace("$PREVIOUS", previous))
        previous = step
    lines += ["in", "    " + previous]
    return "\n".join(lines)


def add_measure(name, expression, fmt="#,0", folder="Operations", description=""):
    MEASURES.append(dict(name=name, expression=expression, formatString=fmt, displayFolder=folder, description=description))


def table(name, fields, query, description, *, filename=None, hidden=False, calculated=False, metadata=None):
    TABLES[name] = dict(columns=dict(fields), query=query, description=description, filename=filename,
                        hidden=hidden, calculated=calculated, metadata=metadata or {})


def policy_expression(expression, filters=(), clip=True):
    if expression.startswith("COUNTROWS("):
        expression = f"COALESCE({expression}, 0)"
    arguments = [expression, "KEEPFILTERS(Dim_Policy[policy] = ChosenPolicy)", *filters]
    if clip:
        arguments += ["KEEPFILTERS(Dim_Date[Date] >= PeriodStart)", "KEEPFILTERS(Dim_Date[Date] <= PeriodEnd)"]
    return ("VAR ChosenPolicy = [Selected Policy]\n"
            + ("VAR PeriodStart = MIN(Config_Model[evaluation_start])\nVAR PeriodEnd = MAX(Config_Model[evaluation_end])\n" if clip else "")
            + "RETURN\n    IF(NOT ISBLANK(ChosenPolicy),\n        CALCULATE(\n            "
            + ",\n            ".join(arguments) + "\n        )\n    )")


def build_measures():
    MEASURES.clear()
    money = '"C$"#,0;("C$"#,0);"C$"0'
    add_measure("Selected Policy", 'IF(HASONEVALUE(Dim_Policy[policy]), SELECTEDVALUE(Dim_Policy[policy]), IF(NOT ISFILTERED(Dim_Policy), "predictive", BLANK()))', "@", "Context", "Policy in context; predictive when unfiltered. An explicit multiple-policy selection returns blank to prevent adding mutually exclusive scenarios.")
    add_measure("Policy Selection Note", 'VAR ChosenPolicy = [Selected Policy]\nRETURN IF(ISBLANK(ChosenPolicy), "Choose one policy for comparable totals", IF(NOT ISFILTERED(Dim_Policy), "Predictive policy (default)", SELECTEDVALUE(Dim_Policy[policy_label])))', "@", "Context", "Visible policy scope, including the default and ambiguous multiple selections.")
    add_measure("Observed Days", '''VAR PeriodStart = MIN(Config_Model[evaluation_start])
VAR PeriodEnd = MAX(Config_Model[evaluation_end])
RETURN
    CALCULATE(
        DISTINCTCOUNT(Fact_Readings[date]),
        KEEPFILTERS(Dim_Date[Date] >= PeriodStart),
        KEEPFILTERS(Dim_Date[Date] <= PeriodEnd),
        REMOVEFILTERS(Dim_Policy)
    )''', "#,0", "Exposure", "Distinct observed calendar days in the selected date/site/asset scope and evaluation window. Zero-event days count. RLS remains in force.")
    add_measure("Evaluation Years", "DIVIDE([Observed Days], 365.25)", "0.0000", "Exposure", "Selected observed days divided by 365.25; full evaluation is 91 days, not a full observed year.")
    add_measure("Asset Years", '''VAR PeriodStart = MIN(Config_Model[evaluation_start])
VAR PeriodEnd = MAX(Config_Model[evaluation_end])
VAR AssetDays = CALCULATE(COUNTROWS(Fact_Readings), KEEPFILTERS(Dim_Date[Date] >= PeriodStart), KEEPFILTERS(Dim_Date[Date] <= PeriodEnd), REMOVEFILTERS(Dim_Policy))
RETURN DIVIDE(AssetDays, 365.25)''', "0.00", "Exposure", "Observed asset-days divided by 365.25; exposure diagnostic, not the fleet annualization denominator.")
    add_measure("Downtime Cost Per Hour Value", 'SELECTEDVALUE(Param_DowntimeCost[Downtime Cost Per Hour], 1000)', money, "Scenario", "Uniform downtime-cost what-if value. Takes effect only in Uniform override mode.")
    add_measure("Cost Mode", 'SELECTEDVALUE(Param_CostMode[Cost Mode], "Equipment defaults")', "@", "Scenario", "Equipment defaults retain the original scenario assumptions; Uniform override applies the selected rate to every asset.")
    add_measure("Emergency Repair Cost", policy_expression("SUM(Fact_Events[repair_cost_cad])"), money, "Costs", "Repair costs recognized on failure date in the selected policy/date scope.")
    add_measure("Planned Service Cost", policy_expression("SUM(Fact_ServiceVisits[planned_cost_cad])", ["KEEPFILTERS(Fact_ServiceVisits[in_evaluation_window] = TRUE())"]), money, "Costs", "Planned service costs recognized on service date. Carry-in visits stay in the audit ledger but are not charged again.")
    for name, fact, hours, charged in [("Unplanned Downtime Cost", "Fact_Events", "downtime_hours", False), ("Planned Downtime Cost", "Fact_ServiceVisits", "planned_downtime_hours", True)]:
        expr = f'SUMX({fact}, {fact}[{hours}] * IF(UseUniformRate, UniformRate, RELATED(Dim_Asset[default_downtime_cost_per_hour])))'
        core = policy_expression(expr, ["KEEPFILTERS(Fact_ServiceVisits[in_evaluation_window] = TRUE())"] if charged else [])
        add_measure(name, 'VAR UseUniformRate = [Cost Mode] = "Uniform override"\nVAR UniformRate = [Downtime Cost Per Hour Value]\n' + core, money, "Costs", "Atomic downtime hours multiplied by the related equipment rate, or the live uniform-rate scenario. Date, site, asset and RLS filters are retained.")
    add_measure("Total Cost", 'VAR ChosenPolicy = [Selected Policy]\nVAR IncurredCost = COALESCE([Emergency Repair Cost], 0) + COALESCE([Planned Service Cost], 0) + COALESCE([Unplanned Downtime Cost], 0) + COALESCE([Planned Downtime Cost], 0)\nRETURN IF(NOT ISBLANK(ChosenPolicy) && [Observed Days] > 0, IncurredCost)', money, "Costs", "Emergency repair plus planned service plus all incurred downtime cost. A day with observations and no costs returns zero.")
    add_measure("Annualized Cost", 'VAR IncurredCost = [Total Cost]\nVAR ExposureYears = [Evaluation Years]\nRETURN DIVIDE(IncurredCost, ExposureYears)', money, "Costs", "Fleet cost annualized over selected observed days. This is a synthetic extrapolation, not realized savings or an observed full year.")
    add_measure("Cost Avoided vs Reactive", '''VAR SelectedCost = [Annualized Cost]
VAR ReactiveCost = CALCULATE([Annualized Cost], REMOVEFILTERS(Dim_Policy), Dim_Policy[policy] = "reactive")
RETURN IF(NOT ISBLANK(SelectedCost), ReactiveCost - SelectedCost)''', money, "Comparisons", "Annualized reactive cost minus the current policy cost. The baseline re-evaluates the measure inside CALCULATE and removes only policy filters; site/date/asset/RLS and cost parameters remain.")
    for label, policy in [("Reactive", "reactive"), ("Fixed", "fixed_90_day"), ("Predictive", "predictive")]:
        add_measure(f"{label} Annualized Cost", f'CALCULATE([Annualized Cost], REMOVEFILTERS(Dim_Policy), Dim_Policy[policy] = "{policy}")', money, "Comparisons", "Explicit policy comparison with the same date, site, asset, security and cost scenario scope.")
    add_measure("Cost Avoided vs Fixed", "[Fixed Annualized Cost] - [Predictive Annualized Cost]", money, "Comparisons", "Predictive annualized net cost advantage over the fixed 90-day maintenance scenario.")
    add_measure("Waterfall Cost", '''VAR Stage = SELECTEDVALUE(Dim_CostStep[Step])
RETURN SWITCH(Stage,
    "Reactive baseline", [Reactive Annualized Cost],
    "Fixed schedule change", [Fixed Annualized Cost] - [Reactive Annualized Cost],
    "Predictive change", [Predictive Annualized Cost] - [Fixed Annualized Cost],
    "Predictive total", [Predictive Annualized Cost],
    BLANK())''', money, "Comparisons", "Three additive waterfall bars reach predictive annual cost. Predictive total is reserved for a total marker, never added as another change.")
    add_measure("Event Count", policy_expression("COUNTROWS(Fact_Events)"), "#,0", "Events", "Events for one maintenance policy. Scenarios replay the same physical failures and must not be added across policies.")
    add_measure("Caught Events", policy_expression("COUNTROWS(Fact_Events)", ["KEEPFILTERS(Fact_Events[caught] = TRUE())"]), "#,0", "Events", "Failure events prevented by a successful intervention in the chosen policy.")
    add_measure("Missed Events", policy_expression("COUNTROWS(Fact_Events)", ["KEEPFILTERS(Fact_Events[caught] = FALSE())"]), "#,0", "Events", "Failures not prevented in the chosen maintenance policy, including unsuccessful interventions.")
    add_measure("Breakdowns", "[Missed Events]", "#,0", "Events", "Breakdown means caught=false events. Uses predictive policy when policy is unfiltered; select one other policy to compare. Never a synonym for the caught Boolean column.")
    add_measure("Catch Rate", "VAR Caught = [Caught Events]\nVAR EligibleEvents = [Event Count]\nRETURN DIVIDE(COALESCE(Caught, 0), EligibleEvents)", "0.0%", "Events", "Successfully prevented failure events divided by all events for the selected policy; event-level, not classifier recall.")
    add_measure("Mean Warning Days", policy_expression("AVERAGE(Fact_Events[warning_days])", ["KEEPFILTERS(Fact_Events[caught] = TRUE())"]), "0.0", "Events", "Mean alert-to-failure lead time among caught events only. Blank for reactive maintenance because no events were caught.")
    add_measure("Median Warning Days", policy_expression("MEDIAN(Fact_Events[warning_days])", ["KEEPFILTERS(Fact_Events[caught] = TRUE())"]), "0.0", "Events", "Median warning among successfully caught events; excludes missed-event zeroes.")
    add_measure("Service Visits", policy_expression("COUNTROWS(Fact_ServiceVisits)", ["KEEPFILTERS(Fact_ServiceVisits[in_evaluation_window] = TRUE())"]), "#,0", "Service", "Charged visits whose service date lies within the evaluation window and current date selection.")
    add_measure("Ledger Service Visits", policy_expression("COUNTROWS(Fact_ServiceVisits)", clip=False), "#,0", "Service", "All recorded visits, including carry-in visits when their service dates are selected. Does not expand the date selection automatically.")
    add_measure("Carry In Visits", policy_expression("COUNTROWS(Fact_ServiceVisits)", ["KEEPFILTERS(Fact_ServiceVisits[in_evaluation_window] = FALSE())"], clip=False), "#,0", "Service", "Audit-only visits preceding evaluation; excluded from incurred cost and operational false-alarm denominators.")
    for name, outcome in [("Unnecessary Services", "no_actionable_failure"), ("Unsuccessful Services", "intervention_unsuccessful"), ("Successful Services", "prevented_failure")]:
        add_measure(name, policy_expression("COUNTROWS(Fact_ServiceVisits)", ["KEEPFILTERS(Fact_ServiceVisits[in_evaluation_window] = TRUE())", f'KEEPFILTERS(Fact_ServiceVisits[outcome] = "{outcome}")']), "#,0", "Service", "Charged visits with this outcome; carry-in visits are excluded.")
    add_measure("False Alarm Rate", "VAR FalseAlarms = [Unnecessary Services]\nVAR ChargedVisits = [Service Visits]\nRETURN DIVIDE(COALESCE(FalseAlarms, 0), ChargedVisits)", "0.0%", "Service", "Operational false-alarm rate = no_actionable_failure visits / charged visits. This is not classifier FP/(FP+TN).")
    add_measure("Unnecessary Service Rate", "[False Alarm Rate]", "0.0%", "Service", "Share of charged service visits with no actionable failure.")
    add_measure("Unsuccessful Service Rate", "DIVIDE(COALESCE([Unsuccessful Services], 0), [Service Visits])", "0.0%", "Service", "Share of charged visits where intervention did not prevent the actionable failure.")
    add_measure("Unplanned Downtime Hours", policy_expression("SUM(Fact_Events[downtime_hours])"), "#,0.0", "Costs", "Unplanned downtime recognized on event date in the selected policy.")
    add_measure("Planned Downtime Hours", policy_expression("SUM(Fact_ServiceVisits[planned_downtime_hours])", ["KEEPFILTERS(Fact_ServiceVisits[in_evaluation_window] = TRUE())"]), "#,0.0", "Costs", "Planned downtime of charged service visits.")
    add_measure("Downtime Reduction vs Fixed", '''VAR FixedHours = CALCULATE([Unplanned Downtime Hours], REMOVEFILTERS(Dim_Policy), Dim_Policy[policy] = "fixed_90_day")
VAR PredictiveHours = CALCULATE([Unplanned Downtime Hours], REMOVEFILTERS(Dim_Policy), Dim_Policy[policy] = "predictive")
RETURN DIVIDE(FixedHours - PredictiveHours, FixedHours)''', "0.0%", "Comparisons", "Relative reduction in unplanned downtime for the predictive versus fixed-interval policy within identical filters.")
    add_measure("Asset Count", "COALESCE(DISTINCTCOUNT(Fact_Readings[asset_id]), 0)", "#,0", "Condition", "Assets with observations in the selected date/site/asset scope, respecting RLS. Zero when there are no visible observations.")
    add_measure("Reading Count", "COALESCE(COUNTROWS(Fact_Readings), 0)", "#,0", "Condition", "Daily asset observations; shared by all maintenance policies and never duplicated by policy. Zero for an empty visible set.")
    add_measure("Mean Risk Score", "AVERAGE(Fact_Readings[risk_score])", "0.0%", "Condition", "Mean model risk score across selected daily observations. Scores are not separately calibrated probabilities.")
    add_measure("Latest Risk Score", '''AVERAGEX(
    VALUES(Dim_Asset[asset_id]),
    VAR LatestObservedDate = CALCULATE(MAX(Fact_Readings[date]))
    RETURN IF(NOT ISBLANK(LatestObservedDate), CALCULATE(AVERAGE(Fact_Readings[risk_score]), KEEPFILTERS(Dim_Date[Date] = LatestObservedDate)))
)''', "0.0%", "Condition", "Each asset's latest observed risk within selected dates; aggregate cells average these latest asset risks. Never sums risk or reads a precomputed asset-summary score.")
    add_measure("Fleet Queue Rank", 'VAR CurrentAsset = SELECTEDVALUE(Dim_Asset[asset_id])\nVAR CurrentRisk = [Latest Risk Score]\nVAR Candidates =\n    FILTER(\n        ADDCOLUMNS(ALLSELECTED(Dim_Asset[asset_id]), "__QueueRisk", [Latest Risk Score]),\n        NOT ISBLANK([__QueueRisk])\n    )\nRETURN\n    IF(\n        NOT ISBLANK(CurrentAsset) && NOT ISBLANK(CurrentRisk),\n        1 + COUNTROWS(\n            FILTER(\n                Candidates,\n                [__QueueRisk] > CurrentRisk\n                    || ([__QueueRisk] = CurrentRisk && Dim_Asset[asset_id] < CurrentAsset)\n            )\n        )\n    )', "0", "Condition", 'Unique latest-risk rank within selected site, asset and date context; descending score with asset ID as deterministic tie-break. Blank risks are excluded and RLS remains in force. Used only to bound the six-row Fleet queue.')
    add_measure("latest_risk_score", "[Latest Risk Score]", "0.0%", "Condition", "Compatibility alias for Latest Risk Score.")
    add_measure("Latest Observation Date", "MAX(Fact_Readings[date])", "yyyy-mm-dd", "Condition", "Latest telemetry snapshot within the current asset/site/date/security scope.")
    add_measure("Alert Threshold", "MAX(Config_Model[alert_threshold])", "0.000", "Condition", "Decision threshold selected on validation data; fixed for the test period.")
    add_measure("Risk Score 7D Avg", '''VAR LastObservedDate = MAX(Fact_Readings[date])
VAR WindowStart = LastObservedDate - 6
RETURN IF(NOT ISBLANK(LastObservedDate),
    CALCULATE(
        [Mean Risk Score],
        REMOVEFILTERS(Dim_Date),
        DATESBETWEEN(Dim_Date[Date], WindowStart, LastObservedDate)
    )
)''', "0.0%", "Condition", "Trailing seven calendar days ending at the current visible latest observation. The date filter is replaced by that window; asset/site/RLS remain. Missing scores are excluded from the average.")
    for name, column, fmt in [("Mean Vibration", "vibration_mm_s", "0.00"), ("Mean Temperature", "bearing_temperature_c", "0.0"), ("Mean Pressure", "pressure_bar", "0.00"), ("Mean RPM", "rpm", "#,0.0"), ("Mean Runtime Hours", "runtime_hours", "#,0.0"), ("Mean Load", "load_pct", "0.0"), ("Mean Power", "power_kw", "0.0")]:
        add_measure(name, f"AVERAGE(Fact_Readings[{column}])", fmt, "Sensors", "Mean sensor reading in the selected daily observations; units follow the source column.")
    add_measure("Sensor Gap Rate", "DIVIDE(CALCULATE(COUNTROWS(Fact_Readings), KEEPFILTERS(Fact_Readings[sensor_missing_count] > 0)), [Reading Count])", "0.0%", "Condition", "Share of asset-days with at least one originally missing sensor; dashboard readings contain the pipeline's imputed values.")
    add_measure("Labeled Readings", "COALESCE(COUNTROWS(FILTER(Fact_Readings, NOT ISBLANK(Fact_Readings[target_failure_30d]) && NOT ISBLANK(Fact_Readings[alert]))), 0)", "#,0", "Classification", "Observations with a fully observed 30-day outcome and nonblank prediction; right-censored target rows are excluded. Empty sets count as zero.")
    add_measure("Unlabeled Readings", "[Reading Count] - [Labeled Readings]", "#,0", "Classification", "Right-censored or unlabeled observations excluded from classifier performance, retained for risk operations.")
    for suffix, actual, predicted in [("TP", True, True), ("FP", False, True), ("FN", True, False), ("TN", False, False)]:
        expr = f"COUNTROWS(FILTER(Fact_Readings, NOT ISBLANK(Fact_Readings[target_failure_30d]) && NOT ISBLANK(Fact_Readings[alert]) && Fact_Readings[target_failure_30d] == {str(actual).upper()}() && Fact_Readings[alert] == {str(predicted).upper()}()))"
        add_measure("Prediction " + suffix, f"COALESCE({expr}, 0)", "#,0", "Classification", "Asset-day classification count after excluding blank targets/predictions. Empty cells count as zero. Distinct from event-level catch rate.")
    add_measure("Confusion Count", '''VAR Actual = SELECTEDVALUE(Dim_ConfusionActual[Actual])
VAR Predicted = SELECTEDVALUE(Dim_ConfusionPredicted[Predicted])
RETURN SWITCH(TRUE(),
    Actual = "Failure" && Predicted = "Failure", [Prediction TP],
    Actual = "No failure" && Predicted = "Failure", [Prediction FP],
    Actual = "Failure" && Predicted = "No failure", [Prediction FN],
    Actual = "No failure" && Predicted = "No failure", [Prediction TN],
    BLANK())''', "#,0", "Classification", "One confusion-matrix cell from disconnected actual/predicted label axes. Totals intentionally blank.")
    add_measure("Precision", "DIVIDE([Prediction TP], [Prediction TP] + [Prediction FP])", "0.0%", "Classification", "Asset-day positive predictive value among labeled rows.")
    add_measure("Recall", "DIVIDE([Prediction TP], [Prediction TP] + [Prediction FN])", "0.0%", "Classification", "Asset-day sensitivity among labeled rows; not the policy event catch rate.")
    add_measure("Classifier False Positive Rate", "DIVIDE([Prediction FP], [Prediction FP] + [Prediction TN])", "0.0%", "Classification", "FP/(FP+TN) on labeled asset-days, distinct from unnecessary service/charged visits.")
    add_measure("Current User", "USERPRINCIPALNAME()", "@", "Security", "Diagnostic UPN for security testing. Use the actual sign-in UPN, not an assumed email alias.")
    add_measure("Risk Status", 'VAR Risk = [Latest Risk Score]\nRETURN IF(ISBLANK(Risk), "No observation", IF(Risk >= [Alert Threshold], "Inspect / dispatch", IF(Risk >= [Alert Threshold] / 2, "Watch trend", "Routine monitoring")))', "@", "Condition", "Latest model score versus the validation-selected threshold; a decision aid for the reliability engineer.")
    add_measure("Risk Color", 'VAR Risk = [Latest Risk Score]\nRETURN SWITCH(TRUE(), ISBLANK(Risk), "#64748B", Risk >= [Alert Threshold], "#B54747", Risk >= [Alert Threshold] / 2, "#B7791F", "#087F8C")', "@", "Condition", "Accessible severity palette for current asset risk. Always pair colour with Risk Status text.")
    for name, target, fmt in [("Mean Risk", "Mean Risk Score", "0.0%"), ("Labeled Reading Count", "Labeled Readings", "#,0"), ("Latest Reading Date", "Latest Observation Date", "yyyy-mm-dd"), ("Latest Risk Status", "Risk Status", "@"), ("Latest Risk Color", "Risk Color", "@"), ("Breakdown Events", "Breakdowns", "#,0")]:
        add_measure(name, f"[{target}]", fmt, "Report aliases", "Report binding alias for " + target + "; same filter and denominator semantics.")
    add_measure("Executive Insight", '''VAR Savings = [Cost Avoided vs Fixed]
VAR Days = [Observed Days]
VAR Assets = [Asset Count]
RETURN IF(Days > 0,
    "Predictive maintenance " & IF(Savings >= 0, "avoids ", "adds ") & "C$" & FORMAT(ABS(Savings), "#,##0", "en-CA") & "/year versus fixed service | " & FORMAT(Assets, "0") & " assets, " & FORMAT(Days, "0") & " observed days | Synthetic scenario",
    "No observed exposure in the selected site, asset and date scope")''', "@", "Context", "Dynamic comparison statement that displays selected observed exposure and labels the scenario as synthetic.")


def build_tables():
    TABLES.clear()
    assets = {"asset_id": "string", "asset_type": "string", "site": "string", "install_date": "dateTime", "default_downtime_cost_per_hour": "double"}
    sites = {"site": "string", "latitude": "double", "longitude": "double"}
    users = {"user_principal_name": "string", "site": "string"}
    config = {"evaluation_start": "dateTime", "evaluation_end": "dateTime", "alert_threshold": "double"}
    readings = {"date": "dateTime", "asset_id": "string", "asset_type": "string", "site": "string", **{x:"double" for x in ["vibration_mm_s", "bearing_temperature_c", "pressure_bar", "power_kw", "load_pct", "rpm", "runtime_hours"]}, "age_days":"int64", "sensor_missing_count":"int64", "risk_score":"double", "alert":"boolean", "target_failure_30d":"boolean"}
    events = {"event_id":"string", "asset_id":"string", "asset_type":"string", "site":"string", "event_date":"dateTime", "policy":"string", "caught":"boolean", "alert_date":"dateTime", "service_date":"dateTime", "warning_days":"double", "service_lead_days":"double", "repair_cost_cad":"double", "downtime_hours":"double"}
    visits = {"policy":"string", "asset_id":"string", "asset_type":"string", "site":"string", "alert_date":"dateTime", "service_date":"dateTime", "event_id":"string", "outcome":"string", "in_evaluation_window":"boolean", "planned_cost_cad":"double", "planned_downtime_hours":"double"}
    for name, filename, fields, description, hidden in [
        ("Dim_Asset", "dim_asset.csv", assets, "One row per asset, derived from raw equipment metadata; no preaggregated risk or outcome columns.", False),
        ("Dim_Site", "dim_site.csv", sites, "One row per synthetic Alberta site. Direct filters to each fact; no Site-to-Asset relationship diamond.", False),
        ("Dim_UserSite", "dim_user_site.csv", users, "Disconnected access mapping, one row per allowed UPN/site pair. Demonstration identities require deployment-specific replacement.", True),
        ("Config_Model", "model_settings.csv", config, "Disconnected evaluation bounds and validation-selected alert threshold. Not an outcome summary.", True),
        ("Fact_ServiceVisits", "service_visits.csv", visits, "One visit per policy/asset/service date. Includes carry-in ledger rows, excluded from incurred cost measures.", False),
    ]:
        extra = [("NormalizedUsers", 'Table.TransformColumns($PREVIOUS, {{"user_principal_name", each Text.Lower(Text.Trim(_)), type text}})')] if name == "Dim_UserSite" else None
        table(name, fields, csv_query(filename, fields, extra), description, filename=filename, hidden=hidden)
    reading_add = [("RiskBand", 'Table.AddColumn($PREVIOUS, "risk_band", each if [risk_score] = null then "No score" else if [risk_score] < 0.1 then "00-10%" else if [risk_score] < 0.2 then "10-20%" else if [risk_score] < 0.3 then "20-30%" else if [risk_score] < 0.4 then "30-40%" else if [risk_score] < 0.5 then "40-50%" else if [risk_score] < 0.6 then "50-60%" else if [risk_score] < 0.7 then "60-70%" else if [risk_score] < 0.8 then "70-80%" else if [risk_score] < 0.9 then "80-90%" else "90-100%", type text)'),
                   ("LabelStatus", 'Table.AddColumn($PREVIOUS, "label_status", each if [target_failure_30d] = null then "Unlabeled / censored" else if [target_failure_30d] then "Failure within 30 days" else "No failure within 30 days", type text)')]
    table("Fact_Readings", {**readings, "risk_band":"string", "label_status":"string"}, csv_query("scored_readings.csv", readings, reading_add), "One observation per asset/day; policy-agnostic sensor history shared by every replayed policy. Blank targets remain blank.", filename="scored_readings.csv")
    event_add = [("OutcomeLabel", 'Table.AddColumn($PREVIOUS, "outcome_label", each if [caught] then "Caught" else "Missed / breakdown", type text)'),
                 ("WarningBand", 'Table.AddColumn($PREVIOUS, "warning_band", each if not [caught] then "Missed / 0 days" else if [warning_days] < 8 then "01-07 days" else if [warning_days] < 15 then "08-14 days" else if [warning_days] < 22 then "15-21 days" else if [warning_days] <= 30 then "22-30 days" else "31+ days", type text)'),
                 ("WarningBandOrder", 'Table.AddColumn($PREVIOUS, "warning_band_order", each if not [caught] then 0 else if [warning_days] < 8 then 1 else if [warning_days] < 15 then 2 else if [warning_days] < 22 then 3 else if [warning_days] <= 30 then 4 else 5, Int64.Type)')]
    table("Fact_Events", {**events, "outcome_label":"string", "warning_band":"string", "warning_band_order":"int64"}, csv_query("event_outcomes.csv", events, event_add), "One physical failure event per maintenance-policy replay. Event date is the accounting date for repair/unplanned downtime.", filename="event_outcomes.csv", metadata={"warning_band":{"sortByColumn":"warning_band_order"}, "warning_band_order":{"hidden":True}})
    table("Dim_Policy", {"policy":"string", "policy_label":"string", "policy_order":"int64"}, 'let\n    Source = #table(type table [policy=text, policy_label=text, policy_order=Int64.Type], {{"reactive", "Reactive", 1}, {"fixed_90_day", "Fixed interval (90 days)", 2}, {"predictive", "Predictive", 3}})\nin\n    Source', "Three mutually exclusive maintenance scenarios replayed on the same history; filters events and visits, not policy-agnostic readings.", metadata={"policy_label":{"sortByColumn":"policy_order"}, "policy_order":{"hidden":True}})
    date_query = '''let
    Start = #date(Date.Year(List.Min(Config_Model[evaluation_start])), 1, 1),
    End = #date(Date.Year(List.Max(Config_Model[evaluation_end])), 12, 31),
    Dates = Table.FromList(List.Dates(Start, Duration.Days(End - Start) + 1, #duration(1, 0, 0, 0)), Splitter.SplitByNothing(), {"Date"}),
    Typed = Table.TransformColumnTypes(Dates, {{"Date", type date}}),
    Year = Table.AddColumn(Typed, "Year", each Date.Year([Date]), Int64.Type),
    MonthNumber = Table.AddColumn(Year, "MonthNumber", each Date.Month([Date]), Int64.Type),
    Month = Table.AddColumn(MonthNumber, "Month", each Date.ToText([Date], "MMM", "en-CA"), type text),
    YearMonth = Table.AddColumn(Month, "YearMonth", each Date.ToText([Date], "yyyy-MM"), type text)
in
    YearMonth'''
    table("Dim_Date", {"Date":"dateTime", "Year":"int64", "MonthNumber":"int64", "Month":"string", "YearMonth":"string"}, date_query, "Complete gapless calendar year(s) around evaluation, marked Time with a unique Date key. The current evaluation calendar contains 365 dates.", metadata={"Date":{"isKey":True}, "Month":{"sortByColumn":"MonthNumber"}})
    table("KPI_Measures", {"_anchor":"int64"}, 'let Source = #table(type table [_anchor=Int64.Type], {{0}}) in Source', "Explicit measures with documented grains, denominators and filter behavior.", metadata={"_anchor":{"hidden":True}})
    table("Param_DowntimeCost", {"Downtime Cost Per Hour":"int64"}, "GENERATESERIES(0, 2500, 50)", "What-if downtime cost in CAD/hour, 0 to 2500 by 50. Default selected value 1000; effective only in uniform override mode.", calculated=True, metadata={"Downtime Cost Per Hour":{"source":"[Value]", "format":"\"C$\"#,0", "parameter":True}})
    table("Param_CostMode", {"Cost Mode":"string"}, 'let Source = #table(type table [#"Cost Mode"=text], {{"Equipment defaults"}, {"Uniform override"}}) in Source', "Select equipment-specific rates or the uniform what-if rate. Equipment defaults preserves the baseline published scenario.")
    table("Param_Breakdown", {"Breakdown":"string", "Breakdown Fields":"string", "Breakdown Order":"int64"}, '{ ("Site", NAMEOF(Dim_Site[site]), 0), ("Asset type", NAMEOF(Dim_Asset[asset_type]), 1) }', "Native field parameter for chart axes. Uses NAMEOF plus groupByColumns and ParameterMetadata; not used in Q&A or Key Influencers.", calculated=True, metadata={"Breakdown":{"source":"[Value1]", "sortByColumn":"Breakdown Order", "groupBy":"Breakdown Fields"}, "Breakdown Fields":{"source":"[Value2]", "hidden":True, "sortByColumn":"Breakdown Order", "fieldParameter":True}, "Breakdown Order":{"source":"[Value3]", "hidden":True}})
    for name, label in [("Dim_ConfusionActual", "Actual"), ("Dim_ConfusionPredicted", "Predicted")]:
        table(name, {label:"string", "Sort":"int64"}, f'let Source = #table(type table [{label}=text, Sort=Int64.Type], {{{{"Failure", 1}}, {{"No failure", 2}}}}) in Source', "Disconnected confusion-matrix axis; explicit measures exclude censored observations.", metadata={label:{"sortByColumn":"Sort"}, "Sort":{"hidden":True}})
    table("Dim_CostStep", {"Step":"string", "Sort":"int64"}, 'let Source = #table(type table [Step=text, Sort=Int64.Type], {{"Reactive baseline", 1}, {"Fixed schedule change", 2}, {"Predictive change", 3}}) in Source', "Disconnected additive waterfall steps; three bars accumulate from reactive cost to predictive cost without double-counting a final total.", metadata={"Step":{"sortByColumn":"Sort"}, "Sort":{"hidden":True}})


def emit_table(name, config):
    lines = ["/// " + config["description"], "table " + quoted(name)]
    if config["hidden"]:
        lines += ["\tisHidden"]
    if name == "Dim_Date":
        lines += ["\tdataCategory: Time"]
    if name == "KPI_Measures":
        for measure in MEASURES:
            lines += ["", "\t/// " + measure["description"], "\tmeasure " + quoted(measure["name"]) + " = ```"]
            lines += ["\t\t\t" + line for line in measure["expression"].splitlines()]
            lines += ["\t\t\t```", "\t\tformatString: " + measure["formatString"], "\t\tdisplayFolder: " + measure["displayFolder"]]
    for column, dtype in config["columns"].items():
        meta = config["metadata"].get(column, {})
        lines += ["", "\t/// " + column.replace("_", " ") + ("; null means outcome is not fully observed." if column == "target_failure_30d" else "."), "\tcolumn " + quoted(column), "\t\tdataType: " + dtype]
        if config["calculated"]:
            lines += ["\t\tisNameInferred: false"]
        if meta.get("hidden") or (name.startswith("Fact_") and column in {"asset_id", "site", "asset_type", "policy"}):
            lines += ["\t\tisHidden"]
        if meta.get("isKey") or (name == "Dim_Asset" and column == "asset_id") or (name == "Dim_Site" and column == "site") or (name == "Dim_Policy" and column == "policy"):
            lines += ["\t\tisKey"]
        if dtype == "dateTime":
            lines += ["\t\tformatString: yyyy-mm-dd"]
        if column in {"latitude", "longitude"}:
            lines += ["\t\tdataCategory: " + column.title()]
        if name == "Dim_Site" and column == "site":
            lines += ["\t\tdataCategory: City"]
        if "format" in meta:
            lines += ["\t\tformatString: " + meta["format"]]
        lines += ["\t\tsummarizeBy: none", "\t\tsourceColumn: " + meta.get("source", column)]
        if "sortByColumn" in meta:
            lines += ["\t\tsortByColumn: " + quoted(meta["sortByColumn"])]
        if "groupBy" in meta:
            lines += ["", "\t\trelatedColumnDetails", "\t\t\tgroupByColumn: " + quoted(meta["groupBy"])]
        if meta.get("fieldParameter"):
            lines += ["", '\t\textendedProperty ParameterMetadata = {"version":3,"kind":2}']
        if meta.get("parameter"):
            lines += ["", "\t\tannotation PBI_ParameterMetadata = {\"version\":0}"]
        if dtype == "dateTime":
            lines += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    lines += ["", "\tpartition " + quoted(name) + " = " + ("calculated" if config["calculated"] else "m"), "\t\tmode: import", "\t\tsource ="]
    lines += ["\t\t\t" + line for line in config["query"].splitlines()]
    write(DEFINITION / "tables" / (name + ".tmdl"), "\n".join(lines))
    if not config["calculated"]:
        write(ROOT / "queries" / (name + ".pq"), config["query"])


def build(data_folder):
    build_tables()
    build_measures()
    for name, config in TABLES.items():
        emit_table(name, config)
    write(DEFINITION / "database.tmdl", "database EnergyPredictiveMaintenance\n\tcompatibilityLevel: 1604")
    lines = ["model Model", "\tculture: en-CA", "\tdefaultPowerBIDataSourceVersion: powerBI_V3", "\tsourceQueryCulture: en-CA", "", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "", "\tannotation __PBI_TimeIntelligenceEnabled = 0", ""]
    lines += ["ref table " + quoted(name) for name in TABLES]
    lines += ["", "ref role 'Site Manager'", "ref cultureInfo en-US"]
    write(DEFINITION / "model.tmdl", "\n".join(lines))
    folder_query = '"' + str(data_folder).replace('"', '""').replace("\\", "/") + '" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    write(DEFINITION / "expressions.tmdl", '/// Dashboard CSV directory; set this Power Query parameter before refresh.\nexpression DataFolder = ' + folder_query)
    write(ROOT / "queries" / "DataFolder.pq", folder_query)
    relationships = []
    for fact, datecol in [("Fact_Readings", "date"), ("Fact_Events", "event_date"), ("Fact_ServiceVisits", "service_date")]:
        for column, dim, key in [("asset_id", "Dim_Asset", "asset_id"), ("site", "Dim_Site", "site"), (datecol, "Dim_Date", "Date")]:
            relationships.append(dict(name=f"{fact}_{dim}", fromTable=fact, fromColumn=column, toTable=dim, toColumn=key, fromCardinality="many", toCardinality="one", crossFilteringBehavior="oneDirection", securityFilteringBehavior="oneDirection", isActive=True))
        if fact != "Fact_Readings":
            relationships.append(dict(name=f"{fact}_Dim_Policy", fromTable=fact, fromColumn="policy", toTable="Dim_Policy", toColumn="policy", fromCardinality="many", toCardinality="one", crossFilteringBehavior="oneDirection", securityFilteringBehavior="oneDirection", isActive=True))
    relation_lines = []
    for r in relationships:
        relation_lines += ["relationship " + quoted(r["name"]), "\tfromCardinality: many", "\ttoCardinality: one", "\tcrossFilteringBehavior: oneDirection", "\tsecurityFilteringBehavior: oneDirection", f"\tfromColumn: {r['fromTable']}.{quoted(r['fromColumn'])}", f"\ttoColumn: {r['toTable']}.{quoted(r['toColumn'])}", ""]
    write(DEFINITION / "relationships.tmdl", "\n".join(relation_lines))
    predicates = {"Dim_UserSite": "LOWER(TRIM(Dim_UserSite[user_principal_name])) = LOWER(TRIM(USERPRINCIPALNAME()))"}
    for dimension in ["Dim_Site", "Dim_Asset"]:
        predicates[dimension] = f'''VAR CurrentUPN = LOWER(TRIM(USERPRINCIPALNAME()))
VAR CurrentSite = {dimension}[site]
RETURN COUNTROWS(FILTER(Dim_UserSite, LOWER(TRIM(Dim_UserSite[user_principal_name])) = CurrentUPN && Dim_UserSite[site] = CurrentSite)) > 0'''
    role = ["/// Dynamic allow-list security. Unknown UPNs receive zero sites/assets/facts; dimension labels and the mapping are secured too.", "role 'Site Manager'", "\tmodelPermission: read"]
    for name, expr in predicates.items():
        role += ["", "\ttablePermission " + name + " = ```", *["\t\t\t" + line for line in expr.splitlines()], "\t\t\t```"]
    write(DEFINITION / "roles" / "Site Manager.tmdl", "\n".join(role))
    synonyms = {
        "breakdowns": ("KPI_Measures", "Breakdowns", ["breakdown", "breakdowns", "breakdown events", "missed failures", "unprevented failures"]),
        "risk": ("KPI_Measures", "Latest Risk Score", ["latest risk", "current risk", "latest risk score"]),
        "asset": ("Dim_Asset", "asset_id", ["asset", "equipment", "equipment identifier"]),
        "site": ("Dim_Site", "site", ["site", "location", "field"]),
        "annualized_cost": ("KPI_Measures", "Annualized Cost", ["annualized cost", "annual cost"]),
        "caught": ("KPI_Measures", "Caught Events", ["caught failures", "prevented failures"]),
    }
    entities = {key:{"Definition":{"Binding":{"ConceptualEntity":entity,"ConceptualProperty":prop}}, "Terms":[{term:{}} for term in terms]} for key,(entity,prop,terms) in synonyms.items()}
    linguistic = {"Version":"2.0.0", "Language":"en-US", "Entities":entities}
    write(DEFINITION / "cultures" / "en-US.tmdl", "cultureInfo en-US\n\tlinguisticMetadata = " + json.dumps(linguistic, ensure_ascii=False) + "\n\t\tcontentType: json")
    write(ROOT / "queries" / "qa_synonyms.json", json.dumps(linguistic, indent=2))
    dax = ["// Generated by build_semantic_model.py. The authoritative executable definitions are in tables/KPI_Measures.tmdl.", "// Every cost/policy comparison preserves site, asset, date, RLS and scenario context.", ""]
    for m in MEASURES:
        dax += ["// " + m["description"], "'KPI_Measures'[" + m["name"] + "] =", m["expression"], ""]
    write(ROOT / "measures.dax", "\n".join(dax))
    contract = {"format":"TMDL", "compatibilityLevel":1604, "measure_table":"KPI_Measures", "data_folder":str(data_folder).replace("\\", "/"), "tables":{name:{k:v for k,v in cfg.items() if k not in {"query"}} for name,cfg in TABLES.items()}, "measures":MEASURES, "relationships":relationships, "roles":{"Site Manager":predicates}, "reporting_excludes":["policy_summary.csv", "policy_asset_detail.csv", "asset_summary.csv"], "defaults":{"policy":"predictive", "cost_mode":"Equipment defaults", "uniform_cost_per_hour":1000}, "notes":["Policy relates to events and visits only; sensor observations are shared history and remain policy-agnostic.", "Multiple explicitly selected policies return blank on scenario totals; unfiltered policy defaults to predictive.", "365-day marked calendar; current evaluation exposure clips to Apr 1-Jun 30 2025 (91 days).", "Annualization uses selected observed calendar days/365.25, not selected event days or visible min/max span.", "Full default scenario must reconcile to the original aggregates, which are used only by validation.", "Culture linguistic metadata binds breakdown to a caught=false measure. Natural-language answers require Desktop/service acceptance testing."]}
    write(ROOT / "model_contract.json", json.dumps(contract, indent=2))
    return contract


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-folder", default=str(ROOT.parent / "data" / "processed" / "dashboard"))
    args = parser.parse_args()
    result = build(args.data_folder)
    print(f"Generated {len(result['tables'])} TMDL tables, {len(result['measures'])} measures and {len(result['relationships'])} single-direction relationships.")
