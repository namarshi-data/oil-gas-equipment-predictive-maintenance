"""Regenerate the Git-diffable PBIP, TMDL semantic model and PBIR report."""
import argparse
import json
from pathlib import Path
from build_semantic_model import build as build_model
from build_report import build as build_report

ROOT = Path(__file__).resolve().parent


def build(data_folder=None):
    model = build_model(data_folder or ROOT.parent / "data/processed/dashboard")
    descriptor = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json", "version": "4.2", "settings": {"qnaEnabled": False}}
    (ROOT / "EnergyPredictiveMaintenance.SemanticModel/definition.pbism").write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
    legacy = ROOT / "EnergyPredictiveMaintenance.SemanticModel/model.bim"
    if legacy.exists():
        legacy.unlink()
    return {"format": "PBIP / TMDL / PBIR", "tables": len(model["tables"]), "measures": len(model["measures"]), **build_report()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-folder", type=Path)
    print(json.dumps(build(parser.parse_args().data_folder), indent=2))
