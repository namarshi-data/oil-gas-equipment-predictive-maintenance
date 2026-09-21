"""Build a self-contained companion from atomic facts and dimensions only."""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMERIC = {"default_downtime_cost_per_hour", "latitude", "longitude", "alert_threshold", "vibration_mm_s", "bearing_temperature_c", "pressure_bar", "power_kw", "load_pct", "rpm", "runtime_hours", "age_days", "sensor_missing_count", "risk_score", "alert", "target_failure_30d", "caught", "warning_days", "service_lead_days", "repair_cost_cad", "downtime_hours", "in_evaluation_window", "planned_cost_cad", "planned_downtime_hours"}

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in NUMERIC.intersection(row):
            row[key] = None if row[key] == "" else float(row[key])
            if row[key] is not None and not math.isfinite(row[key]):
                raise ValueError(f"Nonfinite {key} in {path}")
    return rows

def build(data_dir=None, output=None, root=None):
    project_root = Path(root).resolve() if root else ROOT
    data_dir = Path(data_dir) if data_dir else project_root / "data/processed/dashboard"
    output = Path(output) if output else project_root / "reports/dashboard.html"
    sources = {"events": "event_outcomes.csv", "readings": "scored_readings.csv", "visits": "service_visits.csv", "assets": "dim_asset.csv", "sites": "dim_site.csv", "settings": "model_settings.csv"}
    data = {key: read_csv(data_dir / filename) for key, filename in sources.items()}
    if len(data["settings"]) != 1 or not data["readings"]:
        raise ValueError("Expected one settings row and nonempty readings")
    data["settings"] = data["settings"][0]
    ids = {row["asset_id"] for row in data["assets"]}
    if len(ids) != len(data["assets"]):
        raise ValueError("Duplicate dimension asset keys")
    for table in ("readings", "events", "visits"):
        if any(row["asset_id"] not in ids for row in data[table]):
            raise ValueError(f"Unknown asset key in {table}")
    for table, keys in (("readings", ("asset_id", "date")), ("events", ("event_id", "policy"))):
        if len({tuple(row[k] for k in keys) for row in data[table]}) != len(data[table]):
            raise ValueError(f"Duplicate grain in {table}")
    columns = list(data["readings"][0])
    data["readingColumns"] = columns
    data["readings"] = [[row[key] for key in columns] for row in data["readings"]]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    template = (ROOT / "powerbi/dashboard_template.html").read_text(encoding="utf-8")
    if template.count("__DASHBOARD_DATA__") != 1:
        raise ValueError("Expected one data placeholder")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__DASHBOARD_DATA__", payload), encoding="utf-8")
    return {"output": str(output), "sources": sources, "assets": len(ids), "readings": len(data["readings"]), "events": len(data["events"]), "visits": len(data["visits"]), "preaggregated_reporting_inputs": []}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.data_dir, args.output, args.root), indent=2))
