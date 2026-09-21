"""Check PBIR geometry and conservative text capacity; this is not a Desktop render.

Run from any working directory. Only reports/powerbi-layout-check.json and an
explicitly labelled geometry proof HTML are written; the PBIR is never modified.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "EnergyPredictiveMaintenance.Report/definition/pages"
OUT = ROOT.parent / "reports"
ERRORS: list[str] = []
WARNINGS: list[str] = []
FONT_MODE = "deterministic conservative fallback"
try:
    from PIL import ImageFont
    FONT_PATH = Path("C:/Windows/Fonts/segoeui.ttf")
    if not FONT_PATH.is_file():
        raise ImportError("Segoe UI unavailable")
    FONT_MODE = "Windows Segoe UI via Pillow; points converted at 96/72"
except ImportError:
    ImageFont = None
    FONT_PATH = None


def literal(value, default=None):
    if not isinstance(value, dict):
        return default
    raw = value.get("expr", {}).get("Literal", {}).get("Value")
    if raw is None:
        return default
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    try:
        return float(raw.rstrip("DdLlMm"))
    except ValueError:
        return raw


def props(collection, name):
    values = collection.get(name, [])
    return values[0].get("properties", {}) if values else {}


def font(size_pt, bold=False):
    px = max(1, math.ceil(float(str(size_pt).removesuffix("pt")) * 96 / 72))
    if ImageFont is not None:
        path = FONT_PATH.with_name("segoeuib.ttf") if bold else FONT_PATH
        result = ImageFont.truetype(str(path), px)
        ascent, descent = result.getmetrics()
        return result, ascent + descent
    return None, math.ceil(px * 1.3)


def measure_width(text, face, line_height):
    return face.getlength(text) if face is not None else sum(0.68 if c.isupper() else 0.53 for c in text) * line_height


def wrapped_lines(text, width, size_pt, bold=False, wrap=True):
    face, line_height = font(size_pt, bold)
    widest = 0.0
    count = 0
    for paragraph in str(text).split("\n"):
        if not wrap:
            count += 1
            widest = max(widest, measure_width(paragraph, face, line_height))
            continue
        line = ""
        for word in paragraph.split():
            word_width = measure_width(word, face, line_height)
            widest = max(widest, word_width)
            candidate = (line + " " + word).strip()
            if line and measure_width(candidate, face, line_height) > width:
                count += 1
                line = word
            else:
                line = candidate
        count += 1
    return count, line_height, widest


def rect(value):
    pos = value.get("position", {})
    return tuple(float(pos.get(key, 0)) for key in ("x", "y", "width", "height"))


def check_rects(items, width, height, context):
    for name, item in items:
        x, y, w, h = rect(item)
        if min(w, h) <= 0 or min(x, y) < 0 or x+w > width + .01 or y+h > height + .01:
            ERRORS.append(f"{context}/{name}: rectangle {(x,y,w,h)} outside {width}x{height}")
    for index, (name, item) in enumerate(items):
        x, y, w, h = rect(item)
        for other_name, other in items[index+1:]:
            ox, oy, ow, oh = rect(other)
            intersection_w = min(x+w, ox+ow)-max(x, ox)
            intersection_h = min(y+h, oy+oh)-max(y, oy)
            if intersection_w > .01 and intersection_h > .01:
                ERRORS.append(f"{context}: {name} overlaps {other_name} by {intersection_w:g}x{intersection_h:g}px")


def text_capacity(visual, name, mobile=None):
    v = visual.get("visual", {})
    containers = dict(v.get("visualContainerObjects", {}))
    if mobile:
        containers.update(mobile.get("visualContainerObjects", {}))
    _, _, w, h = rect(mobile or visual)
    padding = props(containers, "padding")
    # The generator sets explicit padding, so no unverified Desktop default is assumed.
    left, right, top, bottom = [literal(padding.get(key), 0) for key in ("left", "right", "top", "bottom")]
    width, height = w-left-right, h-top-bottom
    used = 0
    records = []
    for property_name in ("title", "subTitle"):
        properties = props(containers, property_name)
        if literal(properties.get("show"), property_name == "subTitle") is False:
            continue
        text = literal(properties.get("text"), "")
        if not text:
            continue
        size = literal(properties.get("fontSize"), 12)
        count, line_height, widest = wrapped_lines(text, width, size, bool(literal(properties.get("bold"), False)), literal(properties.get("titleWrap"), True))
        used += count*line_height + 4
        records.append({"kind": property_name, "lines": count, "line_height_px": line_height, "text": text})
        if widest > width+.5:
            ERRORS.append(f"{name}: {property_name} contains unbreakable text wider than {width:g}px")
    if v.get("visualType") == "textbox":
        paragraphs = props(v.get("objects", {}), "general").get("paragraphs", [])
        for paragraph in paragraphs:
            runs = paragraph.get("textRuns", [])
            text = "".join(run.get("value", "") for run in runs)
            size = max((float(str(run.get("textStyle", {}).get("fontSize", "11pt")).removesuffix("pt")) for run in runs), default=11)
            count, line_height, widest = wrapped_lines(text, width, size)
            used += count*line_height
            records.append({"kind": "paragraph", "lines": count, "line_height_px": line_height, "text": text})
            if widest > width+.5:
                ERRORS.append(f"{name}: textbox contains unbreakable text wider than {width:g}px")
        if used > height+.5:
            ERRORS.append(f"{name}: estimated text height {used:g}px exceeds available {height:g}px")
    elif used > height+.5:
        ERRORS.append(f"{name}: title/subtitle height {used:g}px exceeds available {height:g}px")
    return {"usable_width_px": width, "usable_height_px": height, "estimated_text_height_px": used, "blocks": records}


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def table_capacity(visual, page_name, name):
    key = f"{page_name}/{name}"
    v = visual["visual"]
    role_fields = {role: [p["field"] for p in definition.get("projections", [])] for role, definition in v.get("query", {}).get("queryState", {}).items()}
    columns = [node["Column"] for node in nodes(role_fields) if "Column" in node]
    column_names = {(column.get("Expression", {}).get("SourceRef", {}).get("Entity"), column.get("Property")) for column in columns}
    row_cap = None
    if key == "fleet_risk/asset_matrix":
        has_positive_rank = False
        for node in nodes(visual.get("filterConfig", {})):
            comparison = node.get("Comparison", {})
            left = comparison.get("Left", {}).get("Measure", {})
            right = literal({"expr": comparison.get("Right", {})})
            if left.get("Property") == "Fleet Queue Rank" and comparison.get("ComparisonKind") == 4 and isinstance(right, (int, float)) and 0 < right <= 6:
                row_cap = int(right)
            if left.get("Property") == "Fleet Queue Rank" and comparison.get("ComparisonKind") == 1 and right == 0:
                has_positive_rank = True
        if not has_positive_rank:
            ERRORS.append(f"{key}: missing positive rank filter; blank ranks must not enter the queue")
        if column_names != {("Dim_Asset", "asset_id")}:
            ERRORS.append(f"{key}: expected only asset_id as the row dimension")
    elif key == "asset_detail/asset_event_ledger":
        if column_names == {("Dim_Policy", "policy_label")}:
            row_cap = 3
    elif key == "model_performance/confusion_matrix":
        if column_names == {("Dim_ConfusionActual", "Actual"), ("Dim_ConfusionPredicted", "Predicted")}:
            row_cap = 2
    elif column_names == {("Dim_Policy", "policy_label")}:
        row_cap = 3
    if row_cap is None:
        ERRORS.append(f"{key}: unbounded table or missing supported rank cap")
        return {"row_cap": None}
    obj = v.get("objects", {})
    grid = props(obj, "grid")
    size = literal(props(obj, "values").get("fontSize"), literal(grid.get("textSize"), 11))
    _, line_height = font(size)
    row_padding = literal(grid.get("rowPadding"), 2)
    header_size = literal(props(obj, "columnHeaders").get("fontSize"), size)
    _, header_line = font(header_size)
    # Includes a header and a second hierarchy header for the 2x2 matrix.
    header_rows = 2 if "Columns" in role_fields else 1
    estimated_rows_height = row_cap*(line_height+2*row_padding)+header_rows*(header_line+2*row_padding)
    capacities = text_capacity(visual, key)
    available = capacities["usable_height_px"]-capacities["estimated_text_height_px"]
    if estimated_rows_height > available+.5:
        ERRORS.append(f"{key}: {row_cap} rows and headers need about {estimated_rows_height:g}px; only {available:g}px remain")
    return {"row_cap": row_cap, "estimated_rows_and_header_height_px": estimated_rows_height, "available_px": available}


def proof_html(pages):
    sections = []
    for page in pages:
        width, height = page["size"]
        rectangles = []
        for item in page["visuals"]:
            x, y, w, h = item["rect"]
            label = item["name"]+" / "+item["type"]
            rectangles.append(f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff" stroke="#64748b"/><text x="{x+6}" y="{y+15}" font-size="10" fill="#17324d">{html.escape(label)}</text></g>')
        sections.append(f'<section><h2>{html.escape(page["name"])}</h2><svg viewBox="0 0 {width} {height}" role="img" aria-label="Geometry only: {html.escape(page["name"])}"><rect width="{width}" height="{height}" fill="#f4f6f8"/>{"".join(rectangles)}</svg></section>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>PBIR geometry proof - not native rendering</title><style>body{font:16px Segoe UI,sans-serif;margin:24px;color:#17324d;background:#e2e8f0}section{max-width:1280px;margin:24px auto}svg{width:100%;height:auto}aside{padding:16px;background:white}</style><h1>PBIR geometry proof</h1><aside>Static rectangle and typography inspection only. These diagrams are not screenshots of Power BI and do not validate native visual rendering, DAX execution, AI visuals, or interaction.</aside>'+"".join(sections)+"</html>"


def main():
    ERRORS.clear()
    WARNINGS.clear()
    results = []
    visible_pages = []
    metadata = json.loads((PAGES/"pages.json").read_text(encoding="utf-8"))
    for page_name in metadata["pageOrder"]:
        folder = PAGES/page_name
        page = json.loads((folder/"page.json").read_text(encoding="utf-8"))
        if page.get("visibility") != "HiddenInViewMode":
            visible_pages.append(page_name)
        width, height = page["width"], page["height"]
        if page.get("type") != "Tooltip" and ((width,height) != (1280,720) or page.get("displayOption") != "FitToPage"):
            ERRORS.append(f"{page_name}: expected 1280x720 FitToPage")
        files = sorted((folder/"visuals").glob("*/visual.json"))
        items = [(path.parent.name, json.loads(path.read_text(encoding="utf-8"))) for path in files]
        check_rects(items, width, height, page_name)
        result = {"name": page_name, "size": [width,height], "visuals": [], "mobile": []}
        mobile_items = []
        for (name, visual), path in zip(items, files):
            kind = visual.get("visual", {}).get("visualType")
            item = {"name": name, "type": kind, "rect": rect(visual), "text": text_capacity(visual, page_name+"/"+name)}
            if kind in {"tableEx", "pivotTable"}:
                item["table_capacity"] = table_capacity(visual,page_name,name)
            result["visuals"].append(item)
            mobile_path = path.parent/"mobile.json"
            if mobile_path.exists():
                mobile = json.loads(mobile_path.read_text(encoding="utf-8"))
                mobile_items.append((name,mobile))
                result["mobile"].append({"name":name,"rect":rect(mobile),"text":text_capacity(visual,page_name+"/mobile/"+name,mobile)})
        if mobile_items:
            check_rects(mobile_items,324,600,page_name+"/mobile")
        elif page_name == "fleet_risk":
            ERRORS.append("fleet_risk: mobile overview is missing")
        results.append(result)
    expected_visible = ["executive_roi", "policy_comparison", "fleet_risk", "model_performance", "service_audit", "methodology"]
    if visible_pages != expected_visible:
        ERRORS.append(f"Visible pages or their order changed: {visible_pages}")
    OUT.mkdir(parents=True,exist_ok=True)
    report = {"validation_scope":"Static PBIR geometry, bounded rows and conservative font capacity; NOT Power BI Desktop rendering", "font_metrics":FONT_MODE,"desktop_runtime_verified":False,"visible_pages":visible_pages,"pages":results,"errors":ERRORS,"warnings":WARNINGS,"passed":not ERRORS}
    (OUT/"powerbi-layout-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"powerbi-layout-proof.html").write_text(proof_html(results),encoding="utf-8")
    print(json.dumps({"passed":not ERRORS,"pages":len(results),"visuals":sum(len(p["visuals"]) for p in results),"mobile_visuals":sum(len(p["mobile"]) for p in results),"font_metrics":FONT_MODE,"errors":ERRORS},indent=2))
    return int(bool(ERRORS))


if __name__ == "__main__":
    raise SystemExit(main())
