"""Build the Git-diffable PBIR report without changing its TMDL semantic model.

Native AI visual types and roles are verified against Microsoft's Artificial
Intelligence Sample (powerbi-desktop-samples, Sample Reports). Mobile layouts use
the public visualContainerMobileState schema, not the opaque mobileState.json.
JSON/schema validation cannot replace Power BI Desktop rendering and refresh.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "EnergyPredictiveMaintenance.Report"
BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
NAVY = "#17324D"
TEAL = "#087F8C"
AMBER = "#B7791F"
GRAY = "#64748B"
RED = "#B54747"
BG = "#F4F6F8"
INK = "#233B51"
WHITE = "#FFFFFF"
PAGES = [
    ("executive_roi", "01 | Executive ROI Summary"),
    ("policy_comparison", "02 | Policy Comparison"),
    ("fleet_risk", "03 | Fleet Risk Explorer"),
    ("model_performance", "04 | Model Performance"),
    ("service_audit", "05 | Service Visit Audit"),
    ("methodology", "06 | Methodology / About"),
    ("asset_detail", "Asset Detail"),
    ("context_tooltip", "Asset Context"),
    ("ai_analysis", "Sensor Associations"),
]


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def schema(kind, version):
    return BASE + kind + "/" + version + "/schema.json"


def lit(value):
    if isinstance(value, bool):
        value = "true" if value else "false"
    elif value is None:
        value = "null"
    elif isinstance(value, (int, float)):
        value = str(value) + "D"
    else:
        value = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": value}}}


def color(value):
    return {"solid": {"color": lit(value)}}


def field(entity, prop, measure=False):
    return {"Measure" if measure else "Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def measure(name):
    return ("KPI_Measures", name, True)


def projection(spec):
    entity, prop, *rest = spec
    is_measure = rest[0] if rest else False
    return {"field": field(entity, prop, is_measure), "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def objects(**kwargs):
    return [{"properties": kwargs}]


def categorical(name, entity, prop, values=None, **extra):
    result = {"name": name, "field": field(entity, prop), "type": "Categorical", "howCreated": "User", **extra}
    if values is not None:
        expression = {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}
        result["filter"] = {"Version": 2, "From": [{"Name": "f", "Entity": entity, "Type": 0}],
                            "Where": [{"Condition": {"In": {"Expressions": [expression], "Values": [[lit(v)["expr"]] for v in values]}}}]}
    return result


def positive_measure_filter(name, measure_name):
    """Keep rows with observations in the selected site/date/asset scope."""
    expression = {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": measure_name}}
    return {"name": name, "field": field("KPI_Measures", measure_name, True), "type": "Advanced", "howCreated": "User",
            "isLockedInViewMode": True,
            "filter": {"Version": 2, "From": [{"Name": "m", "Entity": "KPI_Measures", "Type": 0}],
                       "Where": [{"Condition": {"Comparison": {"ComparisonKind": 1, "Left": expression, "Right": lit(0)["expr"]}}}]}}


def bounded_queue_filter():
    expression = {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": "Fleet Queue Rank"}}
    return {"name": "six_asset_queue", "field": field("KPI_Measures", "Fleet Queue Rank", True),
            "type": "Advanced", "howCreated": "User", "isLockedInViewMode": True,
            "filter": {"Version": 2, "From": [{"Name": "m", "Entity": "KPI_Measures", "Type": 0}],
                       "Where": [{"Condition": {"Comparison": {"ComparisonKind": 4, "Left": expression, "Right": lit(6)["expr"]}}}]}}


def visual(page, name, kind, box, roles=None, title=None, subtitle=None, text=None,
           size=14, text_color=INK, bg=WHITE, filters=None, tooltip=False, order=1, extra_objects=None):
    x, y, w, h = box
    v = {"visualType": kind, "drillFilterOtherVisuals": True}
    result = {"$schema": schema("visualContainer", "2.9.0"), "name": name,
              "position": {"x": x, "y": y, "width": w, "height": h, "z": order * 1000, "tabOrder": order * 1000}, "visual": v}
    if roles:
        v["query"] = {"queryState": {role: {"projections": [projection(p) for p in props]} for role, props in roles.items()}}
    vc = {
        "background": objects(show=lit(True), color=color(bg), transparency=lit(0)),
        "border": objects(show=lit(False)),
        "padding": objects(top=lit(0 if kind == "textbox" else 8), bottom=lit(0 if kind == "textbox" else 8),
                           left=lit(0 if kind == "textbox" else 12), right=lit(0 if kind == "textbox" else 12)),
        "general": objects(altText=lit(title or text or name)),
    }
    if title:
        vc["title"] = objects(show=lit(True), text=lit(title), fontColor=color(NAVY), fontSize=lit(13), bold=lit(True), titleWrap=lit(False))
    else:
        vc["title"] = objects(show=lit(False))
    if subtitle:
        vc["subTitle"] = objects(show=lit(True), text=lit(subtitle), fontColor=color(GRAY), fontSize=lit(10))
    if tooltip:
        vc["visualTooltip"] = objects(show=lit(True), type=lit("ReportPage"), section=lit("context_tooltip"))
    v["visualContainerObjects"] = vc
    v["objects"] = {}
    if text is not None:
        v["objects"]["general"] = objects(paragraphs=[{"textRuns": [{"value": line, "textStyle": {
            "fontFamily": "Segoe UI", "fontSize": str(size) + "pt", "color": text_color}}]} for line in text.split("\n")])
    if kind in {"card", "cardVisual"}:
        if kind == "card":
            v["objects"].update({"labels": objects(fontSize=lit(size if size != 14 else 30), color=color(text_color)),
                                 "categoryLabels": objects(show=lit(False))})
        else:
            v["objects"].update({"value": [{"properties": {"fontSize": lit(28), "fontColor": color(text_color)}, "selector": {"id": "default"}}],
                                 "label": [{"properties": {"fontSize": lit(13)}, "selector": {"id": "default"}}]})
    if kind in {"tableEx", "pivotTable"}:
        v["objects"].update({"grid": objects(gridVertical=lit(False), gridHorizontal=lit(True), rowPadding=lit(6), textSize=lit(11)),
                             "columnHeaders": objects(fontColor=color(NAVY), backColor=color("#E9EFF4"), fontSize=lit(11), autoSizeColumnWidth=lit(False), wordWrap=lit(False)),
                             "values": objects(fontSize=lit(11), wordWrap=lit(False)),
                             "rowHeaders": objects(fontSize=lit(11), wordWrap=lit(False))})
        # Policy alternatives, raw audit rows and latest-risk statuses have no
        # meaningful additive total. Explicit measures/cards provide context.
        if kind == "tableEx":
            v["objects"]["total"] = objects(totals=lit(False))
        else:
            v["objects"]["subTotals"] = objects(rowSubtotals=lit(False), columnSubtotals=lit(False))
    if kind in {"columnChart", "clusteredColumnChart", "clusteredBarChart", "lineChart", "waterfallChart"}:
        v["objects"].update({"categoryAxis": objects(fontSize=lit(10), showAxisTitle=lit(False),
                                                      axisType=lit("Scalar" if kind == "lineChart" else "Categorical"),
                                                      preferredCategoryWidth=lit(20)),
                             "valueAxis": objects(fontSize=lit(10), showAxisTitle=lit(False)),
                             "legend": objects(fontSize=lit(10), showTitle=lit(False), position=lit("Top")),
                             "zoomSliders": objects(show=lit(False))})
    if filters:
        result["filterConfig"] = {"filters": filters}
    if extra_objects:
        v["objects"].update(extra_objects)
    path = REPORT / "definition/pages" / page / "visuals" / name / "visual.json"
    write(path, result)
    return result


def revise(page, name, value):
    write(REPORT / "definition/pages" / page / "visuals" / name / "visual.json", value)


def sort_by(value, spec, direction="Ascending"):
    value["visual"]["query"]["sortDefinition"] = {"sort": [{"field": field(*spec), "direction": direction}], "isDefaultSort": False}


def series_colors(value, mapping):
    value["visual"]["objects"]["dataPoint"] = [
        {"properties": {"fill": color(c)}, "selector": {"metadata": "KPI_Measures." + name}} for name, c in mapping.items()]


def policy_colors(value):
    points = []
    for label, c in [("Reactive", GRAY), ("Fixed interval (90 days)", AMBER), ("Predictive", TEAL)]:
        scope = {"Comparison": {"ComparisonKind": 0, "Left": field("Dim_Policy", "policy_label"), "Right": lit(label)["expr"]}}
        points.append({"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": scope}]}})
    value["visual"]["objects"]["dataPoint"] = points


def field_parameter_axis(value, role="Category"):
    # ParameterExpr must reference the hidden NAMEOF field, not its display label.
    value["visual"]["query"]["queryState"][role]["fieldParameters"] = [{
        "parameterExpr": field("Param_Breakdown", "Breakdown Fields"), "index": 0, "length": 1}]


def page(name, display, hidden=False, kind=None, width=1280, height=720):
    result = {"$schema": schema("page", "2.1.0"), "name": name, "displayName": display,
              "displayOption": "FitToPage", "width": width, "height": height,
              "objects": {"background": objects(color=color(BG), transparency=lit(0))}}
    if hidden:
        result["visibility"] = "HiddenInViewMode"
    if kind:
        result["type"] = kind
        result["pageBinding"] = {"name": "binding_" + name, "type": kind, "acceptsFilterContext": "Default"}
    if kind == "Drillthrough":
        result["filterConfig"] = {"filters": [categorical("asset_drillthrough", "Dim_Asset", "asset_id", howCreated="Drillthrough")]}
        result["pageBinding"]["parameters"] = [{"name": "asset_detail_asset", "boundFilter": "asset_drillthrough", "fieldExpr": field("Dim_Asset", "asset_id")}]
    write(REPORT / "definition/pages" / name / "page.json", result)
    return result


def header(p, title, subtitle):
    # 18pt text = 24px before line spacing. A 44px box with zero padding has headroom.
    v = visual(p, "page_title", "textbox", (24, 16, 1232, 44), text=title, size=18, text_color=WHITE, bg=NAVY)
    v["visual"]["visualContainerObjects"]["padding"] = objects(top=lit(4), bottom=lit(4), left=lit(12), right=lit(12))
    revise(p, "page_title", v)
    visual(p, "page_subtitle", "textbox", (24, 70, 1232, 28), text=subtitle, size=11, bg=BG, order=2)


def footer(p, text):
    visual(p, "footer", "textbox", (24, 680, 1232, 28), text=text, size=10, text_color=GRAY, bg=BG, order=90)


def slicer(p, name, entity, prop, label, x, y=110, width=296, selected=None, single=False, sync=True):
    v = visual(p, name, "slicer", (x, y, width, 72), {"Values": [(entity, prop)]}, label, order=10 + int(x/300),
               extra_objects={"data": objects(mode=lit("Between" if prop == "Date" else "Dropdown")), "selection": objects(singleSelect=lit(single), selectAllCheckboxEnabled=lit(not single)),
                              "header": objects(show=lit(False)), "items": objects(fontSize=lit(11))})
    if selected is not None:
        # Persist the slicer selection, not a visual filter that removes all other
        # choices from the dropdown. This is the native general.filter contract.
        selected_filter = categorical(p + "_" + name, entity, prop, [selected])["filter"]
        v["visual"]["objects"]["general"] = objects(filter={"filter": selected_filter})
    if prop == "asset_id":
        v["visual"]["objects"].setdefault("general", objects())[0]["properties"]["selfFilterEnabled"] = lit(True)
    if sync:
        v["visual"]["syncGroup"] = {"groupName": entity + "_" + prop, "fieldChanges": True, "filterChanges": True}
    revise(p, name, v)


def navigation(p, name, title, box, target=None):
    button = visual(p, name, "actionButton", box, title=title, order=15,
                    extra_objects={"icon": [{"properties": {"show": lit(True), "shapeType": lit("back" if target is None else "rightArrow")}, "selector": {"id": "default"}}]})
    props = {"show": lit(True), "type": lit("Back" if target is None else "PageNavigation")}
    if target:
        props["navigationSection"] = lit(target)
    button["visual"]["visualContainerObjects"]["visualLink"] = objects(**props)
    revise(p, name, button)


def common_filters(p, policy=False, asset=False, breakdown=False, ai=False):
    slicer(p, "site_filter", "Dim_Site", "site", "Site", 24)
    slicer(p, "type_filter", "Dim_Asset", "asset_type", "Equipment type", 336)
    slicer(p, "date_filter", "Dim_Date", "Date", "History date", 648, width=328)
    if policy:
        slicer(p, "policy_filter", "Dim_Policy", "policy_label", "Policy", 992, width=264, selected="Predictive", single=True, sync=False)
    elif asset:
        slicer(p, "asset_filter", "Dim_Asset", "asset_id", "Find an asset", 992, width=264, single=True, sync=False)
    elif breakdown:
        slicer(p, "breakdown_selector", "Param_Breakdown", "Breakdown", "Group by", 992, width=264, selected="Site", single=True, sync=False)
    elif ai:
        navigation(p, "open_sensor_analysis", "Explore sensor drivers", (992, 110, 264, 72), "ai_analysis")
    else:
        visual(p, "scope_note", "textbox", (992, 124, 264, 52), text="SYNTHETIC SCENARIO\nCAD · held-out history", size=10, text_color=GRAY, bg=BG, order=13)


def card(p, name, m, title, box, c=INK, size=26):
    return visual(p, name, "card", box, {"Values": [measure(m)]}, title, size=size, text_color=c, order=20)


def build_theme():
    theme = {"$schema": "https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.157.json",
             "name": "Energy Operations", "dataColors": [TEAL, NAVY, GRAY, "#6FA3B4", AMBER, RED],
             "background": WHITE, "foreground": INK, "tableAccent": TEAL,
             "good": TEAL, "neutral": AMBER, "bad": RED,
             "textClasses": {"callout": {"fontFace": "Segoe UI Semibold", "fontSize": 26, "color": NAVY},
                             "title": {"fontFace": "Segoe UI Semibold", "fontSize": 13, "color": NAVY},
                             "header": {"fontFace": "Segoe UI", "fontSize": 11, "color": INK},
                             "label": {"fontFace": "Segoe UI", "fontSize": 11, "color": INK}},
             "visualStyles": {"*": {"*": {"title": [{"fontFamily": "Segoe UI", "fontSize": 13}],
                                             "legend": [{"fontSize": 10}], "categoryAxis": [{"fontSize": 10}],
                                             "valueAxis": [{"fontSize": 10}], "labels": [{"fontSize": 11}],
                                             "visualHeader": [{"show": True}]}},
                              "page": {"*": {"background": [{"color": {"solid": {"color": BG}}, "transparency": 0}]}},
                              "waterfallChart": {"*": {"sentimentColors": [{"increaseFill": {"solid": {"color": RED}},
                                                                                           "decreaseFill": {"solid": {"color": TEAL}},
                                                                                           "totalFill": {"solid": {"color": GRAY}}}]}}}}
    write(ROOT / "energy_theme.json", theme)
    write(REPORT / "StaticResources/RegisteredResources/EnergyOperations.json", theme)


def build():
    # Delete only generated definition files within this report's resolved folder.
    # This avoids leaving obsolete pages or visuals after a layout change.
    pages_root = (REPORT / "definition/pages").resolve()
    assert pages_root.is_relative_to(REPORT.resolve())
    if pages_root.exists():
        for file in pages_root.rglob("*.json"):
            file.unlink()
        for directory in sorted(pages_root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    build_theme()
    write(REPORT / "definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                      "version": "4.0", "datasetReference": {"byPath": {"path": "../EnergyPredictiveMaintenance.SemanticModel"}}})
    write(REPORT / "definition/version.json", {"$schema": schema("versionMetadata", "1.0.0"), "version": "2.0.0"})
    versions = {"visual": "2.9.0", "report": "3.3.0", "page": "2.1.0"}
    write(REPORT / "definition/report.json", {"$schema": schema("report", "3.3.0"),
        "themeCollection": {"baseTheme": {"name": "CY24SU06", "reportVersionAtImport": versions, "type": "SharedResources"},
                            "customTheme": {"name": "EnergyOperations.json", "reportVersionAtImport": versions, "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": [{
            "name": "EnergyOperations.json", "path": "EnergyOperations.json", "type": "CustomTheme"}]}],
        "settings": {"useEnhancedTooltips": True, "defaultFilterActionIsDataFilter": True, "exportDataMode": "AllowSummarized",
                     "useDefaultAggregateDisplayName": True, "locale": "en-CA"},
        "annotations": [{"name": "DataDisclaimer", "value": "Synthetic scenario; held-out replay; costs are CAD assumptions, not observed savings."},
                        {"name": "NativeAIRolesSource", "value": "https://github.com/microsoft/powerbi-desktop-samples/blob/main/Sample%20Reports/Artificial%20Intelligence%20Sample.pbix"},
                        {"name": "RuntimeValidation", "value": "Desktop refresh, View as RLS, AI rendering and mobile device acceptance are separate required runtime checks."}]})
    write(REPORT / "definition/pages/pages.json", {"$schema": schema("pagesMetadata", "1.0.0"), "pageOrder": [n for n, _ in PAGES], "activePageName": "executive_roi"})
    for n, d in PAGES:
        page(n, d, hidden=n in {"asset_detail", "context_tooltip", "ai_analysis"}, kind="Drillthrough" if n == "asset_detail" else "Tooltip" if n == "context_tooltip" else None,
             width=480 if n == "context_tooltip" else 1280, height=360 if n == "context_tooltip" else 720)

    p = "executive_roi"
    header(p, "01 / Executive ROI Summary", "Earlier intervention reduces modeled emergency and downtime exposure.")
    common_filters(p)
    for i, (m, label, c) in enumerate([
        ("Reactive Annualized Cost", "Reactive · CAD / year", GRAY),
        ("Fixed Annualized Cost", "Fixed 90-day · CAD / year", AMBER),
        ("Predictive Annualized Cost", "Predictive · CAD / year", TEAL),
        ("Cost Avoided vs Fixed", "Savings vs fixed · CAD / year", TEAL),
    ]):
        card(p, "cost_" + str(i) if i < 3 else "executive_insight", m, label, (24 + i*312, 198, 296, 100), c)
    v = visual(p, "cost_bridge", "waterfallChart", (24, 314, 816, 348),
               {"Category": [("Dim_CostStep", "Step")], "Y": [measure("Waterfall Cost")]},
               "Annual cost bridge", "Downward steps = avoided cost; total = predictive policy.", order=30,
               filters=[categorical("bridge_steps", "Dim_CostStep", "Step", ["Reactive baseline", "Fixed schedule change", "Predictive change"])],
               extra_objects={"sentimentColors": objects(increaseFill=color(GRAY), decreaseFill=color(TEAL), totalFill=color(NAVY))})
    sort_by(v, ("Dim_CostStep", "Step")); revise(p, "cost_bridge", v)
    slicer(p, "cost_mode", "Param_CostMode", "Cost Mode", "Downtime costing basis", 856, 314, 400, "Equipment defaults", True, False)
    slicer(p, "downtime_cost", "Param_DowntimeCost", "Downtime Cost Per Hour", "Uniform override · CAD / hour", 856, 402, 400, 1000, True, False)
    visual(p, "cost_guidance", "textbox", (856, 496, 400, 166), text="SCENARIO, NOT REALIZED ROI\n\nUniform override applies the hourly rate above.\nEquipment defaults use asset-specific rates.\n\nImplementation cost is not included.", size=11, text_color=GRAY, bg=BG, order=33)
    footer(p, "Synthetic held-out replay · policies share the same failure history · costs are annualized over selected observed days.")

    p = "policy_comparison"
    header(p, "02 / Compare prevention with service burden", "A useful policy catches more failures without sending crews to unnecessary work.")
    common_filters(p, breakdown=True)
    v = visual(p, "caught_missed", "columnChart", (24, 198, 608, 224),
               {"Category": [("Dim_Policy", "policy_label")], "Y": [measure("Caught Events"), measure("Missed Events")]},
               "Caught and missed failures", "Identical failure opportunities under each policy.", order=21)
    series_colors(v, {"Caught Events": TEAL, "Missed Events": RED}); revise(p, "caught_missed", v)
    v = visual(p, "warning_distribution", "clusteredColumnChart", (648, 198, 608, 224),
               {"Category": [("Fact_Events", "warning_band")], "Series": [("Dim_Policy", "policy_label")], "Y": [measure("Event Count")]},
               "Time available to act", "Missed events remain a separate warning band.", order=22)
    policy_colors(v); revise(p, "warning_distribution", v)
    v = visual(p, "service_rates", "clusteredBarChart", (24, 438, 608, 224),
               {"Category": [("Dim_Policy", "policy_label")], "Y": [measure("Unnecessary Service Rate"), measure("Unsuccessful Service Rate")]},
               "Visits without prevention", "Unnecessary: no event. Unsuccessful: event not caught.", order=23)
    series_colors(v, {"Unnecessary Service Rate": AMBER, "Unsuccessful Service Rate": RED}); revise(p, "service_rates", v)
    v = visual(p, "catch_by_breakdown", "clusteredColumnChart", (648, 438, 608, 224),
               {"Category": [("Dim_Site", "site")], "Series": [("Dim_Policy", "policy_label")], "Y": [measure("Catch Rate")]},
               "Catch rate by operating group", "Use Group by to compare sites or equipment types.", order=24)
    field_parameter_axis(v); policy_colors(v); revise(p, "catch_by_breakdown", v)
    footer(p, "Catch rate uses event-policy opportunities. Service rates use visits. Reactive has no planned-service denominator.")

    p = "fleet_risk"
    header(p, "03 / Fleet Risk Explorer", "Start with the six highest-risk assets, then select an asset to investigate its history.")
    common_filters(p, asset=True)
    for i, (m, t, c, fs) in enumerate([
        ("Asset Count", "Assets with observations", NAVY, 26),
        ("Latest Risk Score", "Latest observed risk", TEAL, 26),
        ("Risk Score 7D Avg", "Trailing 7-day mean risk", TEAL, 26),
        ("Latest Reading Date", "Latest scored reading", NAVY, 20),
    ]):
        card(p, ["asset_count", "latest_risk", "rolling_risk", "latest_date"][i], m, t, (24+i*312, 198, 296, 96), c, fs)
    v = visual(p, "asset_matrix", "pivotTable", (24, 310, 592, 352),
               {"Rows": [("Dim_Asset", "asset_id")], "Values": [measure("Latest Risk Score"), measure("Latest Risk Status")]},
               "Highest-risk assets · top 6", "Right-click an asset → Drill through → Asset Detail.", tooltip=True, order=25,
               filters=[positive_measure_filter("fleet_assets_with_observations", "Reading Count"),
                        positive_measure_filter("fleet_rank_positive", "Fleet Queue Rank"), bounded_queue_filter()])
    sort_by(v, ("KPI_Measures", "Latest Risk Score", True), "Descending")
    v["visual"]["query"]["queryState"]["Values"]["projections"][0]["displayName"] = "Risk score"
    v["visual"]["query"]["queryState"]["Values"]["projections"][1]["displayName"] = "Review status"
    v["visual"]["objects"]["columnWidth"] = [
        {"properties": {"value": lit(width)}, "selector": {"metadata": name}}
        for name, width in [("Dim_Asset.asset_id", 132), ("KPI_Measures.Latest Risk Score", 112), ("KPI_Measures.Latest Risk Status", 270)]]
    v["visual"]["objects"]["values"].append({"properties": {"fontColor": {"solid": {"color": {"expr": field("KPI_Measures", "Latest Risk Color", True)}}}},
                                              "selector": {"metadata": "KPI_Measures.Latest Risk Score", "data": [{"dataViewWildcard": {"matchingOption": 1}}]}})
    revise(p, "asset_matrix", v)
    v = visual(p, "fleet_risk_trend", "lineChart", (632, 310, 624, 168),
               {"Category": [("Dim_Date", "Date")], "Y": [measure("Mean Risk"), measure("Risk Score 7D Avg")]},
               "Condition trend", order=26)
    for item, label in zip(v["visual"]["query"]["queryState"]["Y"]["projections"], ["Daily mean", "7-day mean"]):
        item["displayName"] = label
    series_colors(v, {"Mean Risk": GRAY, "Risk Score 7D Avg": TEAL}); revise(p, "fleet_risk_trend", v)
    v = visual(p, "ask_fleet", "clusteredBarChart", (632, 494, 624, 168),
               {"Category": [("Dim_Site", "site")], "Y": [measure("Missed Events")]},
               "Missed failures by site · predictive policy", order=27,
               filters=[categorical("predictive_breakdowns_only", "Dim_Policy", "policy", ["predictive"], isLockedInViewMode=True)])
    sort_by(v, ("KPI_Measures", "Missed Events", True), "Descending")
    # Four sites must fit the compact panel. Use Microsoft's serialized property
    # names; minimumCategoryWidth is a UI label, not a supported format property.
    v["visual"]["objects"]["categoryAxis"][0]["properties"].update(
        preferredCategoryWidth=lit(16), outerPadding=lit(0))
    v["visual"]["objects"]["legend"][0]["properties"]["show"] = lit(False)
    series_colors(v, {"Missed Events": RED}); revise(p, "ask_fleet", v)
    footer(p, "Risk colour is paired with review status. Scores are uncalibrated. Find an asset searches the full fleet; the queue shows up to six.")
    # A bounded 324 x 588 mobile composition. Detail remains on the desktop page.
    mobile_items = [("page_title", 0, 44), ("site_filter", 52, 72), ("asset_filter", 132, 72),
                    ("latest_risk", 212, 88), ("latest_date", 308, 88), ("fleet_risk_trend", 404, 184)]
    for order, (name, y, h) in enumerate(mobile_items):
        state = {"$schema": schema("visualContainerMobileState", "2.3.0"),
                 "position": {"x": 0, "y": y, "width": 324, "height": h, "z": order*1000, "tabOrder": order*1000},
                 "visualContainerObjects": {"padding": objects(top=lit(0 if name == "page_title" else 6), bottom=lit(0 if name == "page_title" else 6), left=lit(0 if name == "page_title" else 8), right=lit(0 if name == "page_title" else 8))}}
        write(REPORT / "definition/pages" / p / "visuals" / name / "mobile.json", state)

    p = "model_performance"
    header(p, "04 / Evaluate the cost of missed failures", "Classification uses mature asset-day labels; physical event outcomes are reported separately.")
    common_filters(p, ai=True)
    pg = json.loads((REPORT / "definition/pages" / p / "page.json").read_text(encoding="utf-8"))
    pg["filterConfig"] = {"filters": [categorical("mature_labels_only", "Fact_Readings", "target_failure_30d", [True, False], isLockedInViewMode=True)]}
    write(REPORT / "definition/pages" / p / "page.json", pg)
    for i, (m, t) in enumerate([("Precision", "Precision · alerted days"), ("Recall", "Recall · positive days"),
                                 ("Classifier False Positive Rate", "False positive rate"), ("Labeled Reading Count", "Mature labeled asset-days")]):
        card(p, "metric_" + str(i), m, t, (24+i*312, 198, 296, 96), TEAL if i < 2 else INK)
    visual(p, "confusion_matrix", "pivotTable", (24, 310, 432, 352),
           {"Rows": [("Dim_ConfusionActual", "Actual")], "Columns": [("Dim_ConfusionPredicted", "Predicted")], "Values": [measure("Confusion Count")]},
           "Actual × predicted", "Rows = actual label; columns = model alert.", order=25)
    visual(p, "risk_distribution", "clusteredColumnChart", (472, 310, 784, 352),
           {"Category": [("Fact_Readings", "risk_band")], "Series": [("Fact_Readings", "target_failure_30d")], "Y": [measure("Labeled Reading Count")]},
           "Risk-score distribution by actual label", "True = failure within 30 days. Scores are not calibrated probabilities.", order=26)
    footer(p, "Unknown labels are excluded. Missed positive days differ from missed failures. Open sensor associations for exploratory AI analysis.")

    p = "service_audit"
    header(p, "05 / Audit the outcome of every intervention", "Review visit outcomes and timing for one maintenance policy at a time.")
    common_filters(p, policy=True)
    for i, (m, t) in enumerate([("Service Visits", "Service visits"), ("Unnecessary Service Rate", "Unnecessary visits"),
                                 ("Unsuccessful Service Rate", "Unsuccessful visits"), ("False Alarm Rate", "Operational false alarms")]):
        card(p, "service_kpi_"+str(i), m, t, (24+i*312, 198, 296, 96), TEAL if i == 0 else INK)
    outcomes = {"prevented_failure": TEAL, "no_actionable_failure": AMBER, "intervention_unsuccessful": RED}
    for name, kind, box, roles, title, subtitle in [
        ("outcome_breakdown", "clusteredBarChart", (24, 310, 464, 352),
         {"Category": [("Fact_ServiceVisits", "outcome")], "Y": [measure("Service Visits")]}, "Visit outcomes", "Aggregated from the source intervention ledger."),
        ("visit_by_policy", "columnChart", (504, 310, 752, 352),
         {"Category": [("Dim_Date", "YearMonth")], "Series": [("Fact_ServiceVisits", "outcome")], "Y": [measure("Service Visits")]}, "Service activity by month", "Service date drives the date context on this page."),
    ]:
        v = visual(p, name, kind, box, roles, title, subtitle, order=25,
                   filters=[categorical("visits_in_scope", "Fact_ServiceVisits", "in_evaluation_window", [True], isLockedInViewMode=True)])
        v["visual"]["objects"]["dataPoint"] = [{"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {
            "Comparison": {"ComparisonKind": 0, "Left": field("Fact_ServiceVisits", "outcome"), "Right": lit(label)["expr"]}}}]}} for label, c in outcomes.items()]
        revise(p, name, v)
    footer(p, "Operational false alarms = unnecessary visits / visits. Classifier FPR = FP / (FP + TN). Visit-level records remain in the source CSV.")

    p = "methodology"
    header(p, "06 / Make the assumptions visible", "Synthetic Alberta-inspired equipment history · reproducible analysis · scenario estimates in CAD")
    blocks = [
        ("lineage", 24, 126, "DATA LINEAGE", "Sensors → SQL → Python scoring\nThree atomic facts → star schema → DAX\nAll source files remain in the repository."),
        ("grain", 648, 126, "GRAIN & SECURITY", "Readings: asset-day. Events: event-policy.\nVisits: one intervention per row.\nSite Manager RLS filters all three facts."),
        ("counterfactual", 24, 306, "POLICY COMPARISON", "Reactive, fixed 90-day and predictive.\nSame failure opportunities for every policy.\nPrevention is simulated, not proven savings."),
        ("cost", 648, 306, "COST ASSUMPTIONS", "Annualized over selected observed days.\nRepairs + service + downtime exposure.\nAvoided cost excludes implementation cost."),
        ("ai", 24, 486, "MODEL & AI LIMITS", "Labels mature after the future 30-day window.\nRaw scores are not calibrated probabilities.\nKey Influencers describes associations."),
        ("acceptance", 648, 486, "REPRODUCIBILITY", "PBIP + TMDL + PBIR stay Git-diffable.\nValidate refresh, filters and RLS in Desktop.\nDefinitions and audit records: repository docs."),
    ]
    for n, x, y, heading, text in blocks:
        visual(p, n, "textbox", (x, y, 608, 164), title=heading, text=text, size=12, bg=WHITE, order=20)
    footer(p, "No real operator incidents or customer records are represented. See repository documentation for formulas, interviews and lineage.")

    p = "asset_detail"
    header(p, "Asset Detail / Verify the signal", "Use sensor freshness and operating context together before authorizing maintenance.")
    navigation(p, "back_button", "Back to fleet", (24, 110, 208, 72))
    slicer(p, "asset_identifier", "Dim_Asset", "asset_id", "Asset in drillthrough context", 248, 110, 368, single=True, sync=False)
    visual(p, "asset_context_note", "textbox", (632, 122, 624, 52), text="Drillthrough keeps asset, site and history date context.\nReadings are daily imputed values; missing-sensor flags are retained.", size=10, text_color=GRAY, bg=BG)
    for i, (name, m, title, fs) in enumerate([
        ("asset_latest_risk", "Latest Risk Score", "Latest risk", 26),
        ("asset_risk_status", "Latest Risk Status", "Review status", 17),
        ("asset_rolling_risk", "Risk Score 7D Avg", "7-day risk mean", 26),
        ("asset_last_reading", "Latest Reading Date", "Latest reading", 20),
    ]):
        card(p, name, m, title, (24+i*312, 198, 296, 96), TEAL if i in (0, 2) else NAVY, fs)
    for i, (m, title) in enumerate([("Mean Vibration", "Vibration · mm/s"), ("Mean Temperature", "Bearing temperature · °C"), ("Mean Pressure", "Pressure · bar")]):
        visual(p, "sensor_"+str(i), "lineChart", (24+i*416, 310, 400, 168),
               {"Category": [("Dim_Date", "Date")], "Y": [measure(m)]}, title, order=25+i)
    v = visual(p, "asset_score_trend", "lineChart", (24, 494, 592, 168),
               {"Category": [("Dim_Date", "Date")], "Y": [measure("Mean Risk"), measure("Risk Score 7D Avg")]}, "Risk and trailing mean", order=28)
    series_colors(v, {"Mean Risk": GRAY, "Risk Score 7D Avg": TEAL}); revise(p, "asset_score_trend", v)
    v = visual(p, "asset_event_ledger", "tableEx", (632, 494, 624, 168),
               {"Values": [("Dim_Policy", "policy_label"), measure("Caught Events"), measure("Missed Events"), measure("Mean Warning Days")]},
               "Failure outcomes by policy", order=29)
    for item, label in zip(v["visual"]["query"]["queryState"]["Values"]["projections"], ["Policy", "Caught", "Missed", "Warning days"]):
        item["displayName"] = label
    v["visual"]["objects"]["grid"][0]["properties"]["rowPadding"] = lit(4)
    v["visual"]["objects"]["columnWidth"] = [{"properties": {"value": lit(width)}, "selector": {"metadata": name}} for name, width in [
        ("Dim_Policy.policy_label", 204), ("KPI_Measures.Caught Events", 88), ("KPI_Measures.Missed Events", 88), ("KPI_Measures.Mean Warning Days", 148)]]
    revise(p, "asset_event_ledger", v)
    footer(p, "Policy summary has at most three rows. Warning days average caught events only. A high score is a review signal, not a work order.")

    p = "context_tooltip"
    visual(p, "tooltip_title", "textbox", (16, 16, 448, 36), text="ASSET CONDITION", size=16, text_color=WHITE, bg=NAVY)
    card(p, "tooltip_risk", "Latest Risk Score", "Latest risk", (16, 68, 208, 96), TEAL, 24)
    card(p, "tooltip_status", "Latest Risk Status", "Review status", (240, 68, 224, 96), NAVY, 15)
    card(p, "tooltip_date", "Latest Reading Date", "Last observed reading", (16, 180, 448, 80), NAVY, 20)
    visual(p, "tooltip_context", "textbox", (16, 276, 448, 68), text="Latest reading within the selected history.\nScore is not a calibrated failure probability.\nRight-click the asset to inspect sensor trends.", size=11, bg=BG)

    p = "ai_analysis"
    header(p, "Sensor Associations / Explore the evidence", "Key Influencers describes patterns in synthetic data; it does not prove causality or explain model internals.")
    navigation(p, "back_button", "Back to model performance", (24, 110, 296, 64))
    visual(p, "analysis_note", "textbox", (336, 118, 920, 48), text="Analyze: failure in the next 30 days · mature labels only.\nUse the native AI controls to inspect sensor associations and segments.", size=11, text_color=GRAY, bg=BG)
    pg = json.loads((REPORT / "definition/pages" / p / "page.json").read_text(encoding="utf-8"))
    pg["filterConfig"] = {"filters": [categorical("mature_labels_only", "Fact_Readings", "target_failure_30d", [True, False], isLockedInViewMode=True)]}
    write(REPORT / "definition/pages" / p / "page.json", pg)
    visual(p, "key_influencers", "keyDriversVisual", (24, 190, 1232, 472), {
        "Target": [("Fact_Readings", "target_failure_30d")],
        "ExplainBy": [("Fact_Readings", s) for s in ["vibration_mm_s", "bearing_temperature_c", "pressure_bar", "rpm", "runtime_hours", "power_kw", "load_pct"]]},
        order=27,
        extra_objects={"keyDrivers": objects(targetValue=lit("true"), selectedAnalysis=lit("keyInfluencers"), selectedSort=lit("impact"), allowKeyDriversCounting=lit(True), countType=lit("relative")),
                       "keyInfluencersVisual": objects(primaryColor=color(TEAL), primaryFontColor=color(WHITE), secondaryColor=color("#E1EFF1"), secondaryFontColor=color(INK), canvasColor=color(WHITE))})
    footer(p, "Exploratory associations only. Synthetic degradation and repeated asset-days limit causal interpretation. Native AI controls may paginate results.")

    # Keyboard focus follows reading order, independent of build order.
    for page_name, _ in PAGES:
        paths = list((REPORT / "definition/pages" / page_name / "visuals").glob("*/visual.json"))
        values = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]
        for index, (path, value) in enumerate(sorted(values, key=lambda item: (item[1]["position"]["y"], item[1]["position"]["x"], item[0].as_posix()))):
            value["position"]["tabOrder"] = index * 1000
            write(path, value)
    return {"pages": len(PAGES), "visible_pages": 6, "visuals": len(list((REPORT / "definition/pages").rglob("visual.json"))), "mobile_visuals": len(list((REPORT / "definition/pages").rglob("mobile.json")))}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
