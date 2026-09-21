# Data and publication policy

All records are synthetic. The scenario represents 80 Alberta-inspired assets over 18 months, with degradation, communication gaps and simulated failure events. It is not AER incident data, operator history or a field failure-rate estimate.

Raw telemetry and training intermediates are not published in the current GitHub tree. The deterministic generator, SQL transformations and configuration are included so the experiment can be reproduced locally.

| Published | Purpose |
|---|---|
| `processed/dashboard/*.csv` | Curated synthetic scored readings, event-policy outcomes, service visits, dimensions and settings for the assistant and Power BI |
| `processed/cleaning_quality.json` | Aggregate cleaning audit |
| [Data dictionary](../docs/data_dictionary.md) | Field definitions and grains, including locally generated raw tables |
| [Generator](../src/energy_failure/synthetic.py), [configuration](../src/energy_failure/config.py) and [SQL](../sql) | Reproduction source |
| [Metrics](../artifacts/metrics.json) and [provenance](../artifacts/provenance.json) | Recorded results, configuration and source/input hashes |

The dashboard extracts contain 7,280 held-out asset-day readings, with 4,880 mature 30-day labels. They are derived demonstration facts, not raw ingestion or full training data. The browser dashboard embeds these derived facts so it can run without a server. Policy summaries are retained for reconciliation; Power BI measures use atomic fact tables.

## Generated locally and ignored by Git

- `data/raw/`: synthetic source readings, metadata, events, maintenance, manifest and simulation-only truth.
- Immediate CSV and SQLite files under `data/processed/`: cleaned history, training features, batch inputs and modeling frame.
- Detailed generalization scores, operations-visit traces and batch prediction exports. Their summary evidence remains public.

From an installed project, regenerate the excluded files with:

```powershell
python -m energy_failure.pipeline --output-root .
python scripts/build_readme.py
```

Use the project environment's Python. See [local installation](../LOCAL_SETUP.md) and the [full reproduction sequence](../START_HERE.md). The pipeline replaces generated outputs with its seeded scenario; the notebook and deeper evaluation workflows require these regenerated training inputs.

The trained reference artifact remains included for a runnable demonstration. Its provenance describes the recorded experiment; regenerating on another supported runtime records a new run rather than silently relabelling the old artifact.

Raw telemetry and training intermediates are excluded from this tree by `.gitignore` and are never committed going forward.