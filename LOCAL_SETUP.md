# Run the portfolio locally

Clone or extract the project into a normal folder. Open a terminal at that folder's root. Python 3.11 or later is required for the Python workflows; Power BI Desktop is required only for the PBIP report.

The [screenshot gallery](screenshots/README.md), [local HTML gallery](screenshots/index.html), [role tour](reports/portfolio.html) and [dashboard companion](reports/dashboard.html) can be reviewed without installing Python.

## Install once

On Windows:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pip install -e ".[dev,notebook]"
.venv/Scripts/python powerbi/configure_local.py
.venv/Scripts/python scripts/launch_local.py check
```

On macOS/Linux use `.venv/bin/python` in place of `.venv/Scripts/python`. Power BI Desktop and the Windows command launcher require Windows. A virtual environment is not shipped in Git or the ZIP; the check reports which local Python and project copy are being used.

If this folder already has a working `.venv`, run the check first instead of recreating it. After installation, double-click [START_LOCAL.cmd](START_LOCAL.cmd) for the tour, dashboard, assistant, screenshots, notebook, Power BI or tests.

## Open an application

| Application | Command from the project root |
|---|---|
| Role tour | `.venv/Scripts/python scripts/launch_local.py tour` |
| Dashboard companion | `.venv/Scripts/python scripts/launch_local.py dashboard` |
| Evidence assistant | `.venv/Scripts/python scripts/launch_local.py assistant` |
| Screenshot gallery | `.venv/Scripts/python scripts/launch_local.py screenshots` |
| Power BI | `.venv/Scripts/python scripts/launch_local.py powerbi` |
| Notebook | Run the pipeline below, then `.venv/Scripts/python scripts/launch_local.py notebook` |
| Tests | `.venv/Scripts/python scripts/launch_local.py tests` |

The assistant runs on loopback with a fictional Peace River manager identity in rules-based mode. It needs no paid API. It prints its local URL, using port 8790 when available; stop it with Ctrl+C. This identity is a trusted demonstration fixture, not a login system.

For Power BI, run `powerbi/configure_local.py` after moving the folder. Then open the PBIP, choose **Refresh** and **Fit to page**, and keep saving as PBIP. Fictional user/site mappings illustrate dynamic RLS; use the [acceptance guide](docs/powerbi.md) before claiming actual-user security.

## Regenerate training inputs

The GitHub edition includes curated dashboard facts and a trained reference model. Raw telemetry, SQLite data and training feature tables are generated locally:

```powershell
.venv/Scripts/python -m energy_failure.pipeline --output-root .
.venv/Scripts/python scripts/build_readme.py
```

Run this before opening the EDA notebook or executing workflows that consume training inputs. It replaces generated model/data/report outputs. For the full sequence, including independent-fleet studies, monitoring and batch validation, follow [START_HERE.md](START_HERE.md). Files excluded by the [publication policy](data/README.md) remain local when generated.
