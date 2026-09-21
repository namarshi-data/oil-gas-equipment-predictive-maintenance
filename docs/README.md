# Technical documentation

Start with the [project overview](../README.md) for the business case and results, or follow the [full technical walkthrough](technical-walkthrough.md) for the seven-stage implementation. All equipment records and modeled savings are synthetic. The model uses daily sensor snapshots to estimate next-30-day failure risk.

| Area | Read first | Supporting evidence |
|---|---|---|
| Data and SQL | [Data dictionary](data_dictionary.md) | [Source mapping](sources.md), [publication policy](../data/README.md) |
| Data science | [Model card](model-card.md) | [Generalization](generalization.md), [declared experiment protocol](generalization-protocol.json), [robustness](robustness.md), [sensor-fault tests](sensor-fault-tests.md) |
| Maintenance economics | [Methodology](methodology.md) | [Capacity and cost scenarios](operations.md) |
| ML engineering | [MLOps design](mlops.md) | [Azure deployment](azure.md), [validation record](../reports/validation.md) |
| AI engineering | [Evidence assistant](ai-assistant.md) | [Local evaluation results](../reports/assistant-evaluation.json) |
| Power BI | [Dashboard and acceptance guide](powerbi.md) | [Formatting corrections and screenshot limits](powerbi-report-refinement.md), [security and AI features](powerbi-ai-and-security.md) |

## Setup and reproduction

[Screenshot gallery](../screenshots/README.md) · [Local setup](../LOCAL_SETUP.md) · [Full reproduction](../START_HERE.md)

Use the [validation record](../reports/validation.md) for current test and evidence counts, and the linked experiment reports above for measured results.

Azure templates, source checks and supplied Power BI images are documented separately from live deployment or native runtime acceptance.
