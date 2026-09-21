"""Check the companion's JavaScript and compare it with independent CSV arithmetic.

Requires Python and Node.js, no third-party packages. This validates calculations,
not browser layout, Power BI DAX execution, native RLS or cloud services.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def reference(root, scope):
    folder = root / "data/processed/dashboard"
    assets = read_csv(folder / "dim_asset.csv")
    settings = read_csv(folder / "model_settings.csv")[0]
    selected = [a for a in assets if (not scope.get("site") or a["site"] == scope["site"]) and (not scope.get("assetType") or a["asset_type"] == scope["assetType"])]
    ids = {a["asset_id"] for a in selected}
    rates = {a["asset_id"]: float(a["default_downtime_cost_per_hour"]) for a in assets}
    start, end = scope.get("from", settings["evaluation_start"]), scope.get("to", settings["evaluation_end"])
    within = lambda d: start <= d <= end
    evaluation = lambda d: settings["evaluation_start"] <= d <= settings["evaluation_end"]
    all_readings = read_csv(folder / "scored_readings.csv")
    readings = [r for r in all_readings if r["asset_id"] in ids and within(r["date"])]
    events = [r for r in read_csv(folder / "event_outcomes.csv") if r["asset_id"] in ids and within(r["event_date"]) and evaluation(r["event_date"])]
    all_visits = read_csv(folder / "service_visits.csv")
    visits = [r for r in all_visits if r["asset_id"] in ids and within(r["service_date"]) and evaluation(r["service_date"]) and int(r["in_evaluation_window"]) == 1]
    carry = [r for r in all_visits if r["asset_id"] in ids and int(r["in_evaluation_window"]) == 0]
    days = len({r["date"] for r in readings if evaluation(r["date"])})
    ratio = lambda a, b: a / b if b else None
    rate = lambda aid: scope.get("hourlyRate", 1000) if scope.get("costMode") == "uniform" else rates[aid]
    policies = {}
    for policy in ("reactive", "fixed_90_day", "predictive"):
        erows = [r for r in events if r["policy"] == policy]
        vrows = [r for r in visits if r["policy"] == policy]
        caught = [r for r in erows if int(r["caught"]) == 1]
        warning = [float(r["warning_days"]) for r in caught]
        repair = sum(float(r["repair_cost_cad"]) for r in erows)
        service = sum(float(r["planned_cost_cad"]) for r in vrows)
        unplanned = sum(float(r["downtime_hours"]) for r in erows)
        planned = sum(float(r["planned_downtime_hours"]) for r in vrows)
        downtime = sum(float(r["downtime_hours"]) * rate(r["asset_id"]) for r in erows) + sum(float(r["planned_downtime_hours"]) * rate(r["asset_id"]) for r in vrows)
        unnecessary = sum(r["outcome"] == "no_actionable_failure" for r in vrows)
        unsuccessful = sum(r["outcome"] == "intervention_unsuccessful" for r in vrows)
        total = repair + service + downtime
        policies[policy] = dict(policy=policy, events=len(erows), caught=len(caught), missed=len(erows)-len(caught), catchRate=ratio(len(caught), len(erows)), meanWarning=statistics.mean(warning) if warning else None, medianWarning=statistics.median(warning) if warning else None, visits=len(vrows), unnecessary=unnecessary, unsuccessful=unsuccessful, successful=sum(r["outcome"] == "prevented_failure" for r in vrows), falseAlarmRate=ratio(unnecessary, len(vrows)), unsuccessfulRate=ratio(unsuccessful, len(vrows)), repair=repair, service=service, unplannedHours=unplanned, plannedHours=planned, downtimeCost=downtime, total=total if days else None, annualized=total*365.25/days if days else None)
    labeled = [r for r in readings if r["target_failure_30d"] != "" and r["alert"] != ""]
    counts = {key: 0 for key in ("tp", "fp", "fn", "tn")}
    for r in labeled:
        actual, predicted = float(r["target_failure_30d"]) == 1, float(r["alert"]) == 1
        counts["tp" if actual and predicted else "fp" if predicted else "fn" if actual else "tn"] += 1
    classification = {**counts, "precision": ratio(counts["tp"], counts["tp"]+counts["fp"]), "recall": ratio(counts["tp"], counts["tp"]+counts["fn"]), "fpr": ratio(counts["fp"], counts["fp"]+counts["tn"])}
    fleet = []
    for asset in selected:
        rows = [r for r in readings if r["asset_id"] == asset["asset_id"]]
        latest = max(rows, key=lambda r: r["date"]) if rows else None
        window_start = (date.fromisoformat(latest["date"])-timedelta(days=6)).isoformat() if latest else None
        window = [float(r["risk_score"]) for r in all_readings if latest and r["asset_id"] == asset["asset_id"] and window_start <= r["date"] <= latest["date"] and r["risk_score"] != ""]
        fleet.append(dict(asset_id=asset["asset_id"], date=latest["date"] if latest else None, risk=float(latest["risk_score"]) if latest else None, rolling=statistics.mean(window) if window else None))
    fleet.sort(key=lambda a: (-(a["risk"] if a["risk"] is not None else -1), a["asset_id"]))
    return dict(days=days, assets=len(selected), readings=len(readings), events=len(events), visits=len(visits), carryIn=len(carry), labeled=len(labeled), unlabeled=len(readings)-len(labeled), classification=classification, policies=policies, fleet=fleet)


def validate(root):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to execute the companion's JavaScript")
    html = (root / "reports/dashboard.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'<script type="application/json" id="dashboard-data">(.*?)</script>', html, re.S).group(1))
    code = re.search(r'<script id="dashboard-code">(.*?)</script>', html, re.S).group(1)
    assert set(payload) == {"events", "readings", "visits", "assets", "sites", "settings", "readingColumns"}, "Unexpected embedded reporting input"
    cases = [{}, {"site": "Peace River"}, {"site": "Grande Prairie"}, {"assetType": "compressor"}, {"site": "Peace River", "assetType": "pumpjack", "from": "2025-05-01", "to": "2025-05-31"}, {"from": "2025-06-01", "to": "2025-06-30"}, {"from": "2025-04-01", "to": "2025-04-01"}, {"site": "Unknown site"}, {"from": "2025-06-01", "to": "2025-04-01"}, {"costMode": "uniform", "hourlyRate": 0}, {"costMode": "uniform", "hourlyRate": 1000}, {"site": "Grande Prairie", "assetType": "compressor", "costMode": "uniform", "hourlyRate": 2500}]
    worker = code + '''
const fs=require('fs');
const request=JSON.parse(fs.readFileSync(0,'utf8'));
const model=createEnergyModel(request.payload);
const results=request.cases.map(c=>{const s=model.calculate(c);return {days:s.days,assets:s.assets.length,readings:s.readings.length,events:s.events.length,visits:s.visits.length,carryIn:s.carryIn.length,labeled:s.labeled.length,unlabeled:s.unlabeled,classification:s.classification,policies:s.policies,fleet:s.fleet.map(a=>({asset_id:a.asset_id,date:a.latest?.date||null,risk:a.risk,rolling:a.rolling}))}});
process.stdout.write(JSON.stringify(results));
'''
    with tempfile.TemporaryDirectory(prefix="energy-dashboard-") as tmp:
        path = Path(tmp) / "validate.cjs"
        path.write_text(worker, encoding="utf-8")
        subprocess.run([node, "--check", str(path)], check=True, capture_output=True, text=True)
        run = subprocess.run([node, str(path)], input=json.dumps({"payload": payload, "cases": cases}), check=True, capture_output=True, text=True, encoding="utf-8")
    actual = json.loads(run.stdout)
    comparisons = 0

    def compare(expected, observed, path):
        nonlocal comparisons
        if isinstance(expected, dict):
            assert expected.keys() == observed.keys(), path
            for key in expected:
                compare(expected[key], observed[key], f"{path}.{key}")
        elif isinstance(expected, list):
            assert len(expected) == len(observed), path
            for index, (e, o) in enumerate(zip(expected, observed)):
                compare(e, o, f"{path}[{index}]")
        elif isinstance(expected, (int, float)):
            comparisons += 1
            assert isinstance(observed, (int, float)) and math.isclose(expected, observed, rel_tol=1e-10, abs_tol=1e-7), f"{path}: expected {expected}, got {observed}"
        else:
            comparisons += 1
            assert expected == observed, f"{path}: expected {expected}, got {observed}"

    for index, (case, result) in enumerate(zip(cases, actual)):
        compare(reference(root, case), result, f"case[{index}]")
    report = {"status": "pass", "javascript_syntax": "pass", "independent_csv_reference": "pass", "cases": cases, "case_count": len(cases), "scalar_assertions": comparisons, "preaggregated_reporting_inputs": [], "runtime_scope": "Actual HTML JavaScript calculations executed in Node and compared to Python CSV arithmetic; no browser or Power BI engine claim."}
    output = root / "reports/dashboard_validation.json"
    output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), indent=2))
