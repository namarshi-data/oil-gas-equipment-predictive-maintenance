# Start here

This portfolio connects failure prediction to a maintenance decision: whether early intervention improves on reactive repairs and fixed 90-day servicing. All equipment history and business results are synthetic.

## Review the work in two minutes

1. Read the [business case and results](README.md).
2. Open the [Power BI screenshots](screenshots/powerbi-native/README.md) or [complete 49-image gallery](screenshots/README.md). These render on GitHub without installation.
3. Follow the evidence relevant to your role: [model evaluation](docs/model-card.md), [ML engineering](docs/mlops.md) or [evidence assistant](docs/ai-assistant.md).

After downloading or cloning, open [reports/portfolio.html](reports/portfolio.html) for the role-based tour and [reports/dashboard.html](reports/dashboard.html) for the interactive browser companion. GitHub displays HTML source; run these files locally. The companion does not execute Power BI DAX or RLS.

## Run the demonstrations

The repository retains the trained reference model and curated synthetic dashboard facts. Raw telemetry and training intermediates are excluded from Git; the demos do not require them. See the [data publication policy](data/README.md).

Follow [LOCAL_SETUP.md](LOCAL_SETUP.md) to install Python dependencies and use the Windows launch menu, assistant or notebook. To relocate Power BI data paths, run this from the project root:

```powershell
python powerbi/configure_local.py
```

Open [EnergyPredictiveMaintenance.pbip](powerbi/EnergyPredictiveMaintenance.pbip) in Power BI Desktop, select **Refresh**, then **Fit to page**. Save as PBIP to retain the text-based model and report. Native acceptance steps, including role testing, are in the [Power BI guide](docs/powerbi.md).

## Reproduce the analysis

Install the environment first using [LOCAL_SETUP.md](LOCAL_SETUP.md), then run the following from the project root. On macOS/Linux, replace `.venv/Scripts/python` with `.venv/bin/python`.

```powershell
.venv/Scripts/python -m energy_failure.pipeline --output-root .
.venv/Scripts/python -m energy_failure.robustness --root .
.venv/Scripts/python -m energy_failure.sensor_faults --root .
.venv/Scripts/python -m energy_failure.generalization --root .
.venv/Scripts/python -m energy_failure.operations --root .
.venv/Scripts/python -m energy_failure.uncertainty --root .
.venv/Scripts/python -m energy_failure.monitoring --root .
.venv/Scripts/python -m energy_failure.assistant_eval --root .
.venv/Scripts/python deployment/local_smoke.py
.venv/Scripts/python scripts/build_portfolio.py
.venv/Scripts/python scripts/build_readme.py
.venv/Scripts/python -m pytest -q
.venv/Scripts/python powerbi/validate_data.py
.venv/Scripts/python powerbi/validate_project.py
```

The pipeline generates all omitted telemetry, feature tables and SQLite data, then retrains, scores and replays the maintenance policies. Regeneration replaces generated model/data/report outputs with the seeded scenario; run in a separate clone if you want to preserve an existing experiment. The existing user/site mapping is preserved. Refresh the README after the evidence reports so its headline figures and model comparisons reflect that run. The README script updates only its three marked evidence regions and chart, preserving the full authored walkthrough. Use `python scripts/build_readme.py --check` for a read-only check; review narrative experiment results when assumptions change.

The notebook, monitoring replay and full robustness/generalization studies use regenerated training inputs. Run the pipeline before those workflows. See [methodology](docs/methodology.md) for time splits, label maturity, policy assumptions and cost definitions. Reference results record their original runtime; new runs record their own provenance.

Optional checks: install Node.js and run `python scripts/validate_dashboard.py` to reconcile browser calculations; on Windows run `python powerbi/check_layout.py` for the source geometry check. The [Power BI guide](docs/powerbi.md) covers .NET parser validation. These checks do not replace Desktop rendering and Service security acceptance.

## Interpret the evidence

- Savings are annualized scenario estimates, not realized operator ROI. Gross avoided repair costs are part of operating savings and must not be added to them.
- Held-out results and independent synthetic-fleet stress results are separate. Cold-start limitations and lower external recall are retained.
- Azure deployment templates and the local batch adapter are included; a live Azure deployment is not claimed.
- The assistant defaults to a local rules-based planner with cited, site-filtered records. Its CLI identity is a demonstration fixture, not production authentication. Optional live LLM evaluation is not claimed.
- Eight native Power BI screenshots cover six main pages and two supporting pages. Sensor Associations has no supplied screenshot. Images do not prove every filter, drillthrough, mobile or RLS interaction.

[Validation record](reports/validation.md)
