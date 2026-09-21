"""Export descriptive dimensions and model settings; never reuse policy aggregates."""
from pathlib import Path
import argparse
import csv
import json
import sys
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from energy_failure.config import EQUIPMENT

RATES = {name: values["downtime_cost"] for name, values in EQUIPMENT.items()}

def read(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))

def write(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def export(root):
    root=Path(root).resolve()
    folder=root/"data/processed/dashboard"
    folder.mkdir(parents=True,exist_ok=True)
    assets=read(root/"data/processed/assets.csv")
    metrics=json.loads((root/"artifacts/metrics.json").read_text(encoding="utf-8"))
    dims=[dict(asset_id=a["asset_id"],asset_type=a["asset_type"],site=a["site"],
               install_date=a["commissioned_date"],default_downtime_cost_per_hour=RATES[a["asset_type"]]) for a in assets]
    write(folder/"dim_asset.csv",dims,list(dims[0]))
    positions=defaultdict(list)
    for asset in assets:
        positions[asset["site"]].append((float(asset["latitude"]),float(asset["longitude"])))
    sites=[dict(site=site,latitude=round(sum(p[0] for p in coords)/len(coords),5),
                longitude=round(sum(p[1] for p in coords)/len(coords),5)) for site,coords in sorted(positions.items())]
    write(folder/"dim_site.csv",sites,["site","latitude","longitude"])
    # Example identities deliberately cannot grant a real tenant user access.
    # Preserve an existing reviewed mapping when generating new model inputs.
    mapping=folder/"dim_user_site.csv"
    if not mapping.exists():
        users=[dict(user_principal_name="peace.manager@portfolio.example",site="Peace River"),
               dict(user_principal_name="multi.manager@portfolio.example",site="Peace River"),
               dict(user_principal_name="multi.manager@portfolio.example",site="Grande Prairie")]
        users += [dict(user_principal_name="fleet.reviewer@portfolio.example",site=s["site"]) for s in sites]
        write(mapping,users,["user_principal_name","site"])
    settings=[dict(evaluation_start=metrics["config"]["test_start"],evaluation_end=metrics["config"]["test_end"],alert_threshold=metrics["threshold"])]
    write(folder/"model_settings.csv",settings,list(settings[0]))
    return dict(assets=len(dims),sites=len(sites),user_site_mappings=len(read(mapping)),security="Fictional .example UPNs; unmapped viewers have no access")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    print(json.dumps(export(parser.parse_args().root),indent=2))
