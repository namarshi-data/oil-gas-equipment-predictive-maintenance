"""Point this extracted PBIP at its CSVs without rebuilding the report.

Run before opening Power BI Desktop, or close the project before changing files.
Uses only the Python standard library. No refresh, cloud deployment or UI changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def configure(data_folder: Path | None = None, *, check: bool = False) -> dict:
    folder = (data_folder or ROOT.parent / "data/processed/dashboard").expanduser().resolve()
    contract_path = ROOT / "model_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    expected = sorted({item["filename"] for item in contract["tables"].values() if item.get("filename")})
    missing = [name for name in expected if not (folder / name).is_file()]
    if missing:
        raise ValueError("Dashboard data folder is incomplete: " + ", ".join(missing))
    if any(c in folder.as_posix() for c in "\r\n"):
        raise ValueError("The data directory must not contain a newline.")

    expression_path = ROOT / "EnergyPredictiveMaintenance.SemanticModel/definition/expressions.tmdl"
    original = expression_path.read_text(encoding="utf-8-sig")
    query = ('"' + folder.as_posix().replace('"', '""')
             + '" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]')
    changed, count = re.subn(r"(?m)^expression DataFolder = [^\r\n]*", lambda _: "expression DataFolder = " + query, original)
    if count != 1:
        raise ValueError("Expected exactly one single-line DataFolder expression; no files were changed.")
    contract["data_folder"] = folder.as_posix()
    replacements = {
        expression_path: changed,
        ROOT / "queries/DataFolder.pq": query + "\n",
        contract_path: json.dumps(contract, indent=2) + "\n",
    }
    updates = {path: text for path, text in replacements.items()
               if path.read_text(encoding="utf-8-sig") != text}
    if not check:
        for path, text in updates.items():
            path.write_text(text, encoding="utf-8")
    return {
        "data_folder": folder.as_posix(),
        "csv_files_found": len(expected),
        "check_only": check,
        "files_to_change" if check else "files_changed": [p.relative_to(ROOT).as_posix() for p in updates],
        "report_rebuilt": False,
        "next_step": ("Run without --check to apply; open the PBIP and Refresh."
                      if check else "Open EnergyPredictiveMaintenance.pbip and Refresh. If already open, reopen the project first."),
        "validation_note": "A changed TMDL path invalidates the saved parser hash; rerun validate_project.py --tom for fresh parser evidence.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-folder", type=Path, help="Defaults to data/processed/dashboard beside this project.")
    parser.add_argument("--check", action="store_true", help="Validate sources and show planned edits without writing files.")
    options = parser.parse_args()
    try:
        print(json.dumps(configure(options.data_folder, check=options.check), indent=2))
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
