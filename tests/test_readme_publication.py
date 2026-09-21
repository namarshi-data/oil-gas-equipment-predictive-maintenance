"""A metrics refresh must never discard the hand-written portfolio."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("portfolio_readme", ROOT / "scripts/build_readme.py")
readme_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readme_builder)


def document(newline="\n"):
    pieces = ["Authored introduction: Alberta, café.  ", ""]
    for name in readme_builder.REGIONS:
        pieces.extend([f"<!-- {name}:START -->", "Old generated evidence.", f"<!-- {name}:END -->",
                       "", "<details><summary>Keep my technical narrative</summary>",
                       "", "![Original screenshot](screenshots/keep.png)",
                       "```python", "print('preserve this example')", "```", "</details>", ""])
    pieces.append("Authored final line, including its trailing spaces.  ")
    return newline.join(pieces)


def authored_only(text):
    spans = readme_builder.validate_regions(text)
    for _, (start, end) in sorted(spans.items(), key=lambda item: item[1][0], reverse=True):
        text = text[:start] + "[generated]" + text[end:]
    return text


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_generated_refresh_preserves_every_authored_byte(newline):
    before = document(newline)
    sections = {name: "Updated line one.\nUpdated line two." for name in readme_builder.REGIONS}
    after = readme_builder.update_regions(before, sections)
    assert authored_only(after).encode("utf-8") == authored_only(before).encode("utf-8")
    assert after.count("Updated line one.") == 3
    assert readme_builder.update_regions(after, sections) == after
    if newline == "\r\n":
        assert "\n" not in after.replace("\r\n", "")


@pytest.mark.parametrize("damage", ["missing", "duplicate", "reversed", "nested", "malformed"])
def test_bad_markers_refuse_before_any_outputs_are_written(tmp_path, damage):
    text = document()
    start = "<!-- PORTFOLIO_MODELS:START -->"
    end = "<!-- PORTFOLIO_MODELS:END -->"
    if damage == "missing":
        text = text.replace(start, "")
    elif damage == "duplicate":
        text += "\n" + start
    elif damage == "reversed":
        text = text.replace(start, "TEMP").replace(end, start).replace("TEMP", end)
    elif damage == "nested":
        text = text.replace("<!-- PORTFOLIO_HEADLINE:END -->", "TEMP")
        text = text.replace(end, "<!-- PORTFOLIO_HEADLINE:END -->").replace("TEMP", end)
    else:
        text = text.replace(start, "<!--PORTFOLIO_MODELS:START-->")
    target = tmp_path / "README.md"
    target.write_bytes(text.encode("utf-8"))
    image = tmp_path / readme_builder.CHART_PATH
    image.parent.mkdir(parents=True)
    image.write_bytes(b"existing figure must remain untouched")
    snapshot = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        readme_builder.build(tmp_path)
    assert snapshot == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_generated_metrics_reconcile_to_delivered_evidence():
    metrics, policies, models, events = readme_builder.load_evidence(ROOT)
    sections = readme_builder.render_sections(metrics, policies, models)
    headline = sections["PORTFOLIO_HEADLINE"]
    assert "19-day median warning" in headline
    assert "82.0% less unplanned downtime" in headline
    assert "C$13.42M/year" in headline and "C$4.93M/year" in headline
    assert headline.count("vs. current") == 4
    assert "| **Gradient boosting** | 0.90 | 0.931 | 99.1% | 66.2% | 0.036 |" in sections["PORTFOLIO_MODELS"]
    assert "| Fixed 90-day | 13 / 31 | 81 | 2,607.1 | 3,093.1 | C$4,527,234 |" in sections["PORTFOLIO_POLICIES"]
    records = readme_builder.chart_records(events)
    assert records.groupby("policy").events.sum().eq(44).all()
    assert records.loc[records.warning_band.eq("Missed / 0")].set_index("policy").events.to_dict() == {
        "reactive": 44, "fixed_90_day": 31, "predictive": 7}


def test_check_mode_is_read_only_even_when_evidence_blocks_are_stale(tmp_path):
    for relative in ("artifacts/metrics.json", "reports/test_models.csv", "data/processed/dashboard/event_outcomes.csv"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    (tmp_path / "README.md").write_bytes(document().encode("utf-8"))
    snapshot = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = readme_builder.build(tmp_path, check=True)
    assert not result["current"]
    assert "README.md generated regions" in result["stale"]
    assert snapshot == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_mismatched_headline_refuses_before_updating_readme_or_chart(tmp_path):
    for relative in ("artifacts/metrics.json", "reports/test_models.csv", "data/processed/dashboard/event_outcomes.csv"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    (tmp_path / "README.md").write_bytes(document().encode("utf-8"))
    metrics_path = tmp_path / "artifacts/metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["headline"]["annualized_net_savings_cad"] += 1_000_000
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    snapshot = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="Headline does not reconcile"):
        readme_builder.build(tmp_path)
    assert snapshot == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
