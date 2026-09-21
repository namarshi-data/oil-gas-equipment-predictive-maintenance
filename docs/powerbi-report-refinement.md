# Power BI formatting corrections and screenshot scope

The supplied native screenshots show the report before three source formatting corrections. They are retained as captured output; they do not verify how the corrected definitions render. The report remains PBIP + TMDL + PBIR, with the same data model, measures and policy results.

| Symptom | Source correction |
|---|---|
| Date trends used crowded categorical axes with internal scrollbars | The five date-trend visuals now use the serialized `axisType: Scalar` value instead of the unsupported `Continuous` label. |
| The forward icon on Explore sensor drivers was missing | Navigation uses `shapeType: rightArrow`, and forward/back icons are explicitly enabled. The target page remains `ai_analysis`. |
| Compact charts did not honor category sizing | Category axes use `preferredCategoryWidth` instead of `minimumCategoryWidth`. The four-site Fleet chart requests a width of 16, zero outer padding and no redundant legend. |

[build_report.py](../powerbi/build_report.py) and the 17 affected visual definitions contain these changes. [validate_project.py](../powerbi/validate_project.py) checks the axis and icon values against the cached Microsoft report-theme schema and rejects the three earlier mistakes. These checks supplement the general PBIR schemas, whose generic formatting objects did not reject those values.

The [recorded format validation](../reports/powerbi-format-validation.json), dated 18 September 2026, reports:

- 123 schema-bearing files and 101 visual bindings/format objects checked.
- Nine page layouts and six mobile elements checked statically.
- A separate builder run matching 120 report JSON files and 75 measure expressions.
- Rejection of all three deliberately reintroduced invalid format values.
- Unchanged atomic-ledger accounting, with Desktop refresh, DAX execution and Service RLS explicitly unverified.

The [TMDL parser result](../powerbi/model_validation.json) and [project validation](../powerbi/validation.json) record the semantic/source checks. Refer to the [current validation record](../reports/validation.md) for later executed checks; the formatting receipt is evidence of its dated run.

## Open and check the corrected report

The published `DataFolder` is the portable placeholder `C:/Energy-Predictive-Equipment-Failure/data/processed/dashboard`. From the installed project root, run:

```powershell
python powerbi/configure_local.py
```

This sets the source path to the extracted copy's included dashboard CSVs without rebuilding page definitions. Close a stale Power BI session before reopening [EnergyPredictiveMaintenance.pbip](../powerbi/EnergyPredictiveMaintenance.pbip); save any personal unsaved changes separately first.

In Desktop, refresh and inspect the date trends and all four Fleet sites. In editing mode, Ctrl+click **Explore sensor drivers** to verify page navigation. Repeat asset drillthrough, tooltip, mobile and **View as** checks using the [dashboard acceptance guide](powerbi.md). Record the Desktop version and resulting captures. Static source checks cannot establish native rendering, and actual Service Viewer accounts are still needed to validate published RLS.

[Native screenshot evidence](../screenshots/powerbi-native/README.md) · [Complete gallery](../screenshots/README.md)
