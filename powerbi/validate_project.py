"""Validate official PBIP/PBIR schemas, native TMDL parsing and report contracts.

--download caches missing Microsoft schemas. --tom uses the included .NET TOM
validator after dotnet restore. Neither executes DAX/M or renders a report.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from urllib.request import urlopen
import jsonschema
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "schemas"
MODEL = ROOT / "EnergyPredictiveMaintenance.SemanticModel"
REPORT = ROOT / "EnergyPredictiveMaintenance.Report"


def cache_path(url):
    parts = urlparse(url)
    return CACHE / parts.netloc / parts.path.lstrip("/")


def source_hash():
    digest = hashlib.sha256()
    for path in sorted((MODEL / "definition").rglob("*.tmdl")):
        digest.update(path.relative_to(MODEL).as_posix().encode())
        # Git line-ending conversion must not invalidate unchanged definitions.
        digest.update(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").encode("utf-8"))
    return digest.hexdigest()


def normalized_expression(value):
    """Ignore TMDL serializer indentation without changing expression tokens."""
    text = "\n".join(value) if isinstance(value, list) else str(value)
    return "\n".join(line.strip() for line in text.strip().splitlines())


def folder_contract_errors(report=REPORT):
    """Desktop loads directories too, including empty folders left by a copy."""
    pages = report / "definition/pages"
    metadata = json.loads((pages / "pages.json").read_text(encoding="utf-8-sig"))
    ordered = metadata["pageOrder"]
    errors = []
    if len(ordered) != len(set(ordered)):
        errors.append("Duplicate page IDs in pageOrder")
    if metadata.get("activePageName") not in ordered:
        errors.append("activePageName is not in pageOrder")
    for name in ordered:
        if not (pages / name / "page.json").is_file():
            errors.append(f"Ordered page lacks page.json: {name}")
    for page in sorted(p for p in pages.iterdir() if p.is_dir()):
        if not (page / "page.json").is_file():
            errors.append(f"Page folder lacks page.json: {page.name}")
        if page.name not in ordered:
            errors.append(f"Page folder absent from pageOrder: {page.name}")
        if (page / "visuals").is_dir():
            for visual in sorted(p for p in (page / "visuals").iterdir() if p.is_dir()):
                if not (visual / "visual.json").is_file():
                    errors.append(f"Visual folder lacks visual.json: {page.name}/{visual.name}")
    return errors


def desktop_name_errors(table_names):
    return [f"Reserved Power BI Desktop table name: {name}" for name in table_names if name.strip().casefold() == "measures"]


def visual_format_errors(visual, theme):
    """PBIR's generic format objects do not validate native visual enum values.

    Read those enums from the cached official theme schema. Incorrect UI labels
    such as Continuous/forward can pass PBIR schema checks but be ignored by Desktop.
    """
    def choices(kind, group, prop):
        definition = theme["definitions"]["visual-" + kind]
        for block in definition.get("allOf", []):
            spec = block.get("properties", {}).get(group, {}).get("items", {}).get("properties", {}).get(prop, {})
            if "oneOf" in spec:
                return {item["const"] for item in spec["oneOf"] if "const" in item}
        raise ValueError(f"Official format enum missing: {kind}.{group}.{prop}")

    errors = []
    config = visual.get("visual", {})
    objects = config.get("objects", {})
    for item in objects.get("categoryAxis", []):
        props = item.get("properties", {})
        if "minimumCategoryWidth" in props:
            errors.append("Unsupported categoryAxis.minimumCategoryWidth; use preferredCategoryWidth")
        if "axisType" in props:
            value = props["axisType"].get("expr", {}).get("Literal", {}).get("Value", "").strip("'")
            if value not in choices("lineChart", "categoryAxis", "axisType"):
                errors.append(f"Unsupported categoryAxis.axisType: {value}")
            if config.get("visualType") == "lineChart" and value != "Scalar":
                errors.append("Date trend must use Scalar (continuous) to avoid a categorical scrollbar")
    if config.get("visualType") == "actionButton":
        for item in objects.get("icon", []):
            props = item.get("properties", {})
            value = props.get("shapeType", {}).get("expr", {}).get("Literal", {}).get("Value", "").strip("'")
            if value not in choices("actionButton", "icon", "shapeType"):
                errors.append(f"Unsupported actionButton.icon.shapeType: {value}")
            if props.get("show", {}).get("expr", {}).get("Literal", {}).get("Value") != "true":
                errors.append("Navigation button icon must be explicitly visible")
    return errors


def validate(download=False, tom=False):
    if tom:
        project = ROOT.parent / "tools/ModelValidator/ModelValidator.csproj"
        command = ["dotnet", "run", "--project", str(project), "--no-restore", "--verbosity", "quiet", "--", str(MODEL / "definition"), str(ROOT / "model_snapshot.json")]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        evidence = json.loads(completed.stdout[completed.stdout.index("{"):])
        evidence["tmdl_sha256"] = source_hash()
        (ROOT / "model_validation.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    resolved = {}

    def get_schema(url):
        url = url.split("#")[0]
        if url in resolved:
            return resolved[url]
        path = cache_path(url)
        if not path.exists():
            if not download:
                raise RuntimeError(f"Missing cached schema: {url}; run --download")
            if urlparse(url).netloc not in {"developer.microsoft.com", "raw.githubusercontent.com"}:
                raise ValueError(f"Unexpected schema host: {url}")
            with urlopen(url, timeout=30) as response:
                content = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        schema = json.loads(path.read_text(encoding="utf-8-sig"))
        resolved[url] = schema
        return schema

    registry = Registry(retrieve=lambda url: Resource.from_contents(get_schema(url)))
    paths = [ROOT / "EnergyPredictiveMaintenance.pbip", REPORT / "definition.pbir", MODEL / "definition.pbism"] + sorted(REPORT.rglob("*.json"))
    errors = folder_contract_errors()
    checked = 0
    for path in paths:
        instance = json.loads(path.read_text(encoding="utf-8-sig"))
        if "$schema" not in instance:
            continue
        schema = get_schema(instance["$schema"])
        validator = jsonschema.validators.validator_for(schema)(schema, registry=registry)
        errors.extend(f"{path.relative_to(ROOT)}: {e.json_path}: {e.message}" for e in validator.iter_errors(instance))
        checked += 1
    contract = json.loads((ROOT / "model_contract.json").read_text())
    tables = {name: {"columns": set(cfg["columns"]), "measures": set()} for name, cfg in contract["tables"].items()}
    tables[contract["measure_table"]]["measures"] = {m["name"] for m in contract["measures"]}
    errors.extend(desktop_name_errors(tables))

    def require(condition, message):
        if not condition:
            errors.append(message)

    def walk(obj, file):
        if isinstance(obj, dict):
            for kind, key in (("Column", "columns"), ("Measure", "measures")):
                if kind in obj and "Expression" in obj[kind]:
                    value = obj[kind]
                    entity = value["Expression"].get("SourceRef", {}).get("Entity")
                    if entity:
                        require(entity in tables and value["Property"] in tables[entity][key], f"{file}: Unknown {kind}: {entity}.{value['Property']}")
            for val in obj.values():
                walk(val, file)
        elif isinstance(obj, list):
            for val in obj:
                walk(val, file)

    visuals = list(REPORT.rglob("visual.json"))
    theme = get_schema("https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.157.json")
    for path in visuals:
        visual = json.loads(path.read_text())
        walk(visual, path.relative_to(ROOT))
        for error in visual_format_errors(visual, theme):
            require(False, f"{path.relative_to(ROOT)}: {error}")
    require(not (MODEL / "model.bim").exists(), "Legacy model.bim must be removed: definition/ is authoritative")
    native = json.loads((ROOT / "model_validation.json").read_text()) if (ROOT / "model_validation.json").exists() else {}
    require(native.get("tmdlParsed") is True and native.get("tmdl_sha256") == source_hash(), "TMDL parser evidence missing/stale; run --tom")
    if (ROOT / "model_snapshot.json").exists():
        model = json.loads((ROOT / "model_snapshot.json").read_text(encoding="utf-8-sig"))["model"]
        actual = {t["name"]: t for t in model["tables"]}
        require(set(actual) == set(tables), "Parsed TOM table set differs from contract")
        for name, fields in tables.items():
            if name in actual:
                require({c["name"] for c in actual[name].get("columns", [])} == fields["columns"], f"Parsed TOM columns differ: {name}")
                require({m["name"] for m in actual[name].get("measures", [])} == fields["measures"], f"Parsed TOM measures differ: {name}")
        measures = {m["name"]: m for m in actual[contract["measure_table"]].get("measures", [])}
        for expected_measure in contract["measures"]:
            found = measures.get(expected_measure["name"], {})
            require(normalized_expression(found.get("expression", "")) == normalized_expression(expected_measure["expression"]),
                    f"Parsed TOM measure expression differs from contract: {expected_measure['name']}")
        folder_expression = next((e for e in model.get("expressions", []) if e["name"] == "DataFolder"), {})
        mirror = (ROOT / "queries/DataFolder.pq").read_text(encoding="utf-8-sig").strip()
        require(normalized_expression(folder_expression.get("expression", "")) == normalized_expression(mirror), "DataFolder TMDL and PQ mirror differ")
        escaped_folder = contract["data_folder"].replace('"', '""')
        require(mirror.startswith('"' + escaped_folder + '" meta '), "DataFolder parameter and model contract differ; run configure_local.py")
        executive = normalized_expression(measures.get("Executive Insight", {}).get("expression", ""))
        require('"C$" & FORMAT(ABS(Savings), "#,##0", "en-CA")' in executive,
                "Executive Insight must keep literal CAD prefix outside FORMAT to avoid the currency-format range error")
        expected = {(f, d) for f in ["Fact_Readings", "Fact_Events", "Fact_ServiceVisits"] for d in ["Dim_Asset", "Dim_Site", "Dim_Date"]} | {("Fact_Events", "Dim_Policy"), ("Fact_ServiceVisits", "Dim_Policy")}
        relationships = model.get("relationships", [])
        require({(r["fromTable"], r["toTable"]) for r in relationships} == expected, "Star relationship set differs from expected 11 paths")
        for rel in relationships:
            require(rel.get("crossFilteringBehavior", "oneDirection") == "oneDirection", f"Bidirectional relationship: {rel['name']}")
            require(rel.get("fromCardinality", "many") == "many" and rel.get("toCardinality", "one") == "one", f"Invalid star cardinality: {rel['name']}")
            for side in ("from", "to"):
                require(rel[f"{side}Column"] in tables[rel[f"{side}Table"]]["columns"], f"Unknown relationship column: {rel['name']}")
        date = actual["Dim_Date"]
        require(date.get("dataCategory") == "Time" and next(c for c in date["columns"] if c["name"] == "Date").get("isKey"), "Dim_Date must be marked Time with a unique Date key")
        role = next((r for r in model.get("roles", []) if r["name"] == "Site Manager"), {})
        require({p["name"] for p in role.get("tablePermissions", [])} == {"Dim_Site", "Dim_Asset", "Dim_UserSite"}, "Site Manager must secure site, asset labels and mapping")
        for permission in role.get("tablePermissions", []):
            require("USERPRINCIPALNAME" in str(permission.get("filterExpression")), "Dynamic security predicate missing UPN")
        require(not any(s in json.dumps(model) for s in ["policy_summary.csv", "policy_asset_detail.csv", "asset_summary.csv"]), "Reporting model imports preaggregated validation tables")
    page_order = json.loads((REPORT / "definition/pages/pages.json").read_text())["pageOrder"]
    require(page_order[:6] == ["executive_roi", "policy_comparison", "fleet_risk", "model_performance", "service_audit", "methodology"], "Requested six-page order differs")
    types = {json.loads(p.read_text()).get("visual", {}).get("visualType") for p in visuals}
    require("keyDriversVisual" in types, "Native Key Influencers visual missing")
    require("qnaVisual" not in types, "Retiring Q&A visual must not be reintroduced")
    descriptor = json.loads((MODEL / "definition.pbism").read_text(encoding="utf-8-sig"))
    require(descriptor.get("settings", {}).get("qnaEnabled") is False, "Unused Q&A model feature must remain disabled")
    fleet_breakdowns = json.loads((REPORT / "definition/pages/fleet_risk/visuals/ask_fleet/visual.json").read_text())
    require(fleet_breakdowns["visual"]["visualType"] == "clusteredBarChart", "Fleet breakdown chart is missing")
    require('"Missed Events"' in json.dumps(fleet_breakdowns["visual"].get("query", {})), "Fleet chart must use the audited missed-event measure")
    require("'predictive'" in json.dumps(fleet_breakdowns.get("filterConfig", {})), "Fleet breakdown chart must scope outcomes to predictive policy")
    mobile = list((REPORT / "definition/pages/fleet_risk").rglob("mobile.json"))
    require(len(mobile) >= 5, "Fleet mobile layout missing")
    result = {"json_schema_files_validated": checked, "visual_bindings_checked": len(visuals), "tmdl_tables": len(tables), "relationship_count": len(contract["relationships"]), "visible_pages": 6, "hidden_pages": len(page_order)-6, "fleet_mobile_visuals": len(mobile), "errors": errors, "pbir_directory_contract_verified": not folder_contract_errors(), "reserved_table_names_checked": not desktop_name_errors(tables), "native_tmdl_parse_verified": native.get("tmdlParsed", False) and native.get("tmdl_sha256") == source_hash(), "desktop_refresh_verified": False, "dax_execution_verified": False, "service_rls_verified": False, "scope": "Official PBIP/PBIR JSON schemas, directory completeness, Desktop reserved-name guard, Microsoft TOM TMDL parse, bindings, star/role/date definitions; no engine execution or rendering"}
    result["retiring_qna_visual_absent"] = "qnaVisual" not in types
    result["native_format_objects_checked"] = len(visuals)
    (ROOT / "validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise SystemExit("\n".join(errors))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--tom", action="store_true")
    args = parser.parse_args()
    print(json.dumps(validate(args.download, args.tom), indent=2))
