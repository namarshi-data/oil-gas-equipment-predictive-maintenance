"""Build the HTML screenshot gallery while preserving authored Markdown.

Run from any directory: python scripts/build_screenshot_gallery.py
Validates screenshot files, supplied hashes and complete image links in both
screenshots/README.md and screenshots/powerbi-native/README.md before writing
screenshots/index.html. Both READMEs, all images and capture-manifest.json are
preserved byte for byte. Capture provenance remains in the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

GROUPS = {
    "powerbi-native": ("Power BI operations dashboard", "Maintenance cost, policy tradeoffs, fleet risk and service outcomes in the native report."),
    "reviewer-tour": ("Explore by role", "Decision, Data Scientist, ML Engineer and AI Engineer views of the project."),
    "assistant": ("Evidence assistant", "Supported questions, cited answers and access-boundary examples from the local rules-based demonstration."),
    "dashboard-companion": ("Browser dashboard companion", "A separate HTML application for exploring the same maintenance analysis locally."),
}

NATIVE_PAGES = [
    ("Executive ROI Summary", "executive_roi"),
    ("Policy Comparison", "policy_comparison"),
    ("Fleet Risk Explorer", "fleet_risk"),
    ("Model Performance", "model_performance"),
    ("Service Visit Audit", "service_audit"),
    ("Methodology / About", "methodology"),
]
NATIVE_SUPPORT = [
    ("Asset Detail", "asset_detail"),
    ("Asset Context (tooltip)", "context_tooltip"),
    ("Sensor Associations", "ai_analysis"),
]
CAPTIONS = {
    "executive_roi": "Compare annualized policy costs and trace the cost bridge from reactive repairs to predictive maintenance.",
    "policy_comparison": "Compare caught and missed failures, warning time and visits that did not prevent a failure.",
    "fleet_risk": "Review the highest-risk assets, risk trends and missed failures by site.",
    "model_performance": "Inspect precision, recall, the confusion matrix and score distribution for mature labels.",
    "service_audit": "Trace intervention outcomes and monthly service activity by maintenance policy.",
    "methodology": "Review data lineage, policy assumptions, cost definitions and model limitations.",
    "asset_detail": "Inspect sensor trends alongside risk and failure outcomes.",
    "context_tooltip": "Check the risk summary, review status and latest observed reading.",
}
ROLE_CAPTIONS = {
    "01-decision.jpg": "Connect model output to maintenance costs and operational tradeoffs.",
    "02-data-scientist.jpg": "Inspect leakage prevention, generalization, calibration and uncertainty.",
    "03-ml-engineer.jpg": "Follow reproducibility, scoring contracts, deployment gates and monitoring.",
    "04-ai-engineer.jpg": "Inspect grounded calculations, site access controls and refusal handling.",
}


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def viewport_text(value: object) -> str:
    if value is None:
        return "Not recorded"
    if isinstance(value, dict):
        return f"{value.get('width', '?')} x {value.get('height', '?')}"
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{value[0]} x {value[1]}"
    return str(value)


def read_entries(folder: Path) -> list[dict]:
    manifest = folder / "capture-manifest.json"
    if not manifest.is_file():
        raise ValueError(f"Capture manifest is missing: {manifest}. Capture the browser views first.")
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or not entries:
        raise ValueError("Capture manifest must contain a non-empty entries list.")
    result = []
    seen = set()
    for position, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {position} must be an object.")
        required = {"file", "title", "surface", "phase", "url", "viewport", "captured_at"}
        missing = required - entry.keys()
        if missing:
            raise ValueError(f"Entry {position} is missing {sorted(missing)}.")
        relative = str(entry["file"]).replace("\\", "/")
        if relative.startswith("screenshots/"):
            relative = relative[len("screenshots/"):]
        target = (folder / relative).resolve()
        try:
            normalized = target.relative_to(folder.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f"Entry {position} points outside screenshots/: {relative}") from exc
        if not target.is_file() or target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError(f"Entry {position} must point to an existing screenshot image: {relative}")
        group = normalized.split("/", 1)[0]
        if group not in GROUPS:
            raise ValueError(f"Entry {position} has unsupported screenshot folder: {group}")
        if normalized in seen:
            raise ValueError(f"Duplicate screenshot entry: {normalized}")
        seen.add(normalized)
        if entry.get("sha256") and hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Screenshot hash does not match the manifest: {normalized}")
        result.append({**entry, "file": normalized, "group": group, "viewport_label": viewport_text(entry["viewport"]), "image_label": viewport_text(entry.get("image_dimensions", "Not recorded"))})
    return result


def coverage(entries: list[dict]) -> dict:
    group_counts = Counter(entry["group"] for entry in entries)
    before = sum(entry["group"] == "assistant" and str(entry["phase"]).lower().startswith("before") for entry in entries)
    after = sum(entry["group"] == "assistant" and str(entry["phase"]).lower().startswith("after") for entry in entries)
    reviewer_titles = " ".join(str(entry["title"]).lower() for entry in entries if entry["group"] == "reviewer-tour")
    dashboard_titles = " ".join(str(entry["title"]).lower() for entry in entries if entry["group"] == "dashboard-companion")
    reviewer = {label: token in reviewer_titles for label, token in [
        ("Decision", "decision"), ("Data Scientist", "data scientist"),
        ("ML Engineer", "ml engineer"), ("AI Engineer", "ai engineer"),
    ]}
    dashboard = {label: token in dashboard_titles for label, token in [
        ("Executive ROI Summary", "executive"), ("Policy Comparison", "policy"),
        ("Fleet Risk Explorer", "fleet"), ("Model Performance", "model"),
        ("Service Visit Audit", "service"), ("Methodology / About", "methodology"),
    ]}
    native_ids = {entry.get("page_id") for entry in entries if entry["group"] == "powerbi-native"}
    return {
        "total": len(entries), "groups": group_counts, "before": before, "after": after,
        "reviewer": reviewer, "dashboard": dashboard,
        "browser": sum(count for group, count in group_counts.items() if group != "powerbi-native"),
        "native_main": {label: key in native_ids for label, key in NATIVE_PAGES},
        "native_support": {label: key in native_ids for label, key in NATIVE_SUPPORT},
    }


CSS = '\n:root{--navy:#17324d;--teal:#087f8c;--ink:#23384a;--muted:#627387;--line:#dce5eb;--paper:#f3f7fa;--amber:#815f1b}\n*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Segoe UI",Arial,sans-serif}a{color:var(--teal)}a:focus-visible{outline:3px solid #bd721b;outline-offset:5px}header{background:var(--navy);color:white;padding:22px 5vw}.brand{font-size:13px;letter-spacing:.13em;font-weight:700}main{max-width:1440px;margin:auto;padding:40px 5vw 64px}.eyebrow{color:var(--teal);font-size:12px;letter-spacing:.12em;font-weight:700;text-transform:uppercase}h1{font-size:clamp(28px,4vw,43px);line-height:1.18;margin:10px 0 15px}.intro{max-width:900px;color:var(--muted);margin-bottom:24px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.stat{background:white;border:1px solid var(--line);border-radius:10px;padding:16px 20px}.stat strong{display:block;color:var(--teal);font-size:27px}.stat span{font-size:13px;color:var(--muted)}.note{border-left:4px solid var(--line);background:white;color:var(--muted);padding:15px 20px;border-radius:4px}nav{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0 40px}nav a{background:white;border:1px solid var(--line);border-radius:6px;padding:8px 14px;text-decoration:none;font-size:14px;font-weight:600}section{margin-bottom:48px;scroll-margin-top:20px}.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:18px}h2{font-size:25px;margin:0 0 4px}.section-head p{margin:0;color:var(--muted);max-width:850px;font-size:14px}.count{white-space:nowrap;color:var(--muted);font-size:13px;padding-top:7px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.card{background:white;border:1px solid var(--line);border-radius:12px;overflow:hidden}.image-link{display:block;background:#e8eef3;border-bottom:1px solid var(--line)}.image-link img{width:100%;aspect-ratio:16/9;object-fit:contain;display:block}.card-body{padding:20px 23px}.phase{display:inline-block;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--teal);background:#e9f5f5;border-radius:4px;padding:3px 7px;font-weight:700}h3{font-size:20px;line-height:1.3;margin:10px 0 12px}.question{background:var(--paper);padding:10px 12px;font-size:14px;border-left:3px solid var(--teal)}.question strong{display:block;color:var(--muted);font-size:11px;letter-spacing:.06em;text-transform:uppercase}dl{display:grid;grid-template-columns:75px minmax(0,1fr);gap:5px 12px;font-size:12px;margin:15px 0}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}.source{font-family:Consolas,monospace;font-size:11px}.full-size{font-weight:600;font-size:13px;text-decoration:none}footer{border-top:1px solid var(--line);padding-top:20px;font-size:13px;color:var(--muted)}footer p{max-width:960px}@media(max-width:760px){main{padding:26px 20px}.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.section-head{display:block}header{padding:18px 20px}.count{display:block;margin-top:5px}}@media print{body{background:white}nav{display:none}.card{break-inside:avoid}.grid{grid-template-columns:1fr}}\n.capture-context{font-size:13px;color:var(--muted);margin:16px 0;max-width:1100px}.card.standalone{grid-column:1/-1;display:grid;grid-template-columns:1.35fr 1fr}.card.standalone .image-link{border-bottom:0;border-right:1px solid var(--line);align-self:center}@media(max-width:760px){.card.standalone{display:block}.card.standalone .image-link{border-bottom:1px solid var(--line);border-right:0}}\n'


def validate_markdown(folder: Path, entries: list[dict]) -> dict[str, int]:
    """Require complete, valid curated indexes; never rewrite authored text."""
    root = folder.parent.resolve()
    expected_all = {(folder / entry["file"]).resolve() for entry in entries}
    expected_native = {(folder / entry["file"]).resolve() for entry in entries if entry["group"] == "powerbi-native"}
    counts = {}
    for relative, expected in [("README.md", expected_all), ("powerbi-native/README.md", expected_native)]:
        path = folder / relative
        if not path.is_file():
            raise ValueError(f"Authored screenshot index is missing: {relative}. Restore it before generating HTML.")
        text = path.read_text(encoding="utf-8-sig")
        images = set()
        for target in re.findall(r"\]\(([^)\r\n]+)\)", text):
            target = target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (path.parent / unquote(parsed.path)).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"{relative} has a link outside the project: {target}") from exc
            if not resolved.exists():
                raise ValueError(f"{relative} has a missing link target: {target}")
            if resolved.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                images.add(resolved)
        missing = expected - images
        unexpected = images - expected
        if missing or unexpected:
            missing_names = sorted(item.relative_to(root).as_posix() for item in missing)
            extra_names = sorted(item.relative_to(root).as_posix() for item in unexpected)
            raise ValueError(f"{relative} screenshot coverage differs from the manifest: missing={missing_names}; unexpected={extra_names}")
        counts[relative] = len(images)
    return counts


def caption(entry: dict) -> str:
    group = entry["group"]
    if group == "powerbi-native":
        return CAPTIONS.get(entry.get("page_id"), "Inspect the report's maintenance decision context.")
    if group == "reviewer-tour":
        return ROLE_CAPTIONS.get(Path(entry["file"]).name, "Explore the implementation and evidence relevant to this role.")
    if group == "assistant":
        return {
            "welcome": "Start with supported questions about maintenance policies, equipment risk and methodology.",
            "before": "Inspect the question before submission.",
            "after": "Inspect the answer or refusal, its site context and supporting evidence.",
            "trace": "Follow the authorized query and records behind an answer.",
        }.get(entry["phase"], "Inspect the question and its evidence-based response.")
    stem = Path(entry["file"]).stem
    page_key = {"01": "executive_roi", "02": "policy_comparison", "03": "fleet_risk", "04": "model_performance", "05": "service_audit", "06": "methodology"}.get(stem[:2])
    return CAPTIONS.get(page_key, "Explore the maintenance analysis in the browser companion.")


def build_html(entries: list[dict], stats: dict) -> str:
    sections = []
    for group, (title, description) in GROUPS.items():
        cards = []
        for entry in (item for item in entries if item["group"] == group):
            path = quote(entry["file"], safe="/")
            question = f'<p class="question"><strong>Question</strong> {escape(entry["question"])}</p>' if entry.get("question") else ""
            phase = {"user-supplied-native": "Power BI", "before": "Question", "after": "Response", "welcome": "Welcome", "trace": "Evidence trace", "page": "Role view"}.get(entry["phase"], "Browser view")
            cards.append(f'''<article class="card">
<a class="image-link" href="{escape(path)}" target="_blank" rel="noopener" aria-label="Open full-size screenshot: {escape(entry['title'])}"><img src="{escape(path)}" alt="{escape(entry['title'])}" loading="lazy"></a>
<div class="card-body"><span class="phase">{escape(phase)}</span><h3>{escape(entry['title'])}</h3><p>{escape(caption(entry))}</p>{question}
<a class="full-size" href="{escape(path)}" target="_blank" rel="noopener">Open full-size image <span aria-hidden="true">&#8599;</span></a></div></article>''')
        section_body = "\n".join(cards) or '<p class="empty">No captures are included for this surface yet.</p>'
        sections.append(f'<section id="{group}"><div class="section-head"><div><h2>{title}</h2><p>{description}</p></div><span class="count">{len(cards)} images</span></div><div class="grid">{section_body}</div></section>')
    nav = "".join(f'<a href="#{group}">{title}</a>' for group, (title, _) in GROUPS.items())
    missing_native = [title for title, included in {**stats["native_main"], **stats["native_support"]}.items() if not included]
    missing_note = f' Native pages not pictured: {escape(", ".join(missing_native))}.' if missing_native else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Energy reliability | Screenshot gallery</title><style>{CSS}</style></head>
<body><header><div class="brand">ENERGY / RELIABILITY INTELLIGENCE</div></header><main>
<div class="eyebrow">Portfolio walkthrough</div><h1>From equipment telemetry to maintenance decisions.</h1>
<p class="intro">Explore policy costs, failure prediction and the evidence assistant. All results use synthetic data. Select any image to inspect the original capture at full size.</p>
<details class="note"><summary><strong>Capture notes and validation scope</strong></summary><p>Native images predate a later report-formatting pass; some charts retain scrollbars, and Asset Detail and Asset Context show fleet aggregates. Screenshots do not establish refresh, interactive, mobile or Service RLS acceptance.{missing_note} Browser views are separate applications; the assistant uses rules-based queries.</p></details>
<nav aria-label="Gallery sections">{nav}<a href="README.md">GitHub image index</a></nav>
{''.join(sections)}<footer><p><a href="../README.md">Project overview</a> | <a href="../START_HERE.md">Run locally</a> | <a href="../reports/validation.md">Validation evidence</a></p><p>Original images and authored Markdown indexes are preserved by the gallery builder.</p></footer></main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="Project root. Generates index.html only; preserves both authored screenshot READMEs, images and manifest.")
    args = parser.parse_args()
    folder = args.root.resolve() / "screenshots"
    try:
        entries = read_entries(folder)
        indexes = validate_markdown(folder, entries)
        stats = coverage(entries)
        rendered = build_html(entries, stats)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Gallery not generated: {exc}\n")
    (folder / "index.html").write_text(rendered, encoding="utf-8", newline="\n")
    print(json.dumps({"screenshots": stats["total"], "groups": dict(stats["groups"]), "authored_markdown_preserved": True, "markdown_image_coverage": indexes, "generated": "screenshots/index.html", "native_missing_pages": [title for title, included in {**stats['native_main'], **stats['native_support']}.items() if not included]}, indent=2))


if __name__ == "__main__":
    main()
