"""Regressions for Desktop loader hazards that JSON/TOM parsing did not catch."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("project_validation", ROOT / "powerbi/validate_project.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def minimal_report(tmp_path):
    pages = tmp_path / "definition/pages"
    (pages / "current/visuals/chart").mkdir(parents=True)
    (pages / "pages.json").write_text(json.dumps({"pageOrder": ["current"], "activePageName": "current"}))
    (pages / "current/page.json").write_text("{}")
    (pages / "current/visuals/chart/visual.json").write_text("{}")
    return pages


def test_rejects_retired_empty_page_directory(tmp_path):
    pages = minimal_report(tmp_path)
    assert module.folder_contract_errors(tmp_path) == []
    (pages / "retired").mkdir()
    assert "Page folder lacks page.json: retired" in module.folder_contract_errors(tmp_path)


def test_rejects_empty_visual_directory_inside_live_page(tmp_path):
    pages = minimal_report(tmp_path)
    (pages / "current/visuals/retired_chart").mkdir()
    assert "Visual folder lacks visual.json: current/retired_chart" in module.folder_contract_errors(tmp_path)


def test_rejects_reserved_measure_table_name():
    assert module.desktop_name_errors(["Measures"])
    assert module.desktop_name_errors(["measures"])
    assert module.desktop_name_errors(["KPI_Measures", "Fact_Readings"]) == []
