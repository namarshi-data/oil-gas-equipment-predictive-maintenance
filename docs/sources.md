# Sources and schema mapping

No real operator or AER records were downloaded into the training data. The following primary sources informed naming and structure; all numerical degradation, cost and failure-frequency assumptions are authored for this project. Sources checked 17 September 2026.

| Project choice | Primary source and scope |
|---|---|
| Separate equipment, event, location, licence and cause fields | [AER Field Surveillance Incident Inspection List](https://www1.aer.ca/ProductCatalogue/215.html) lists incident identifiers, dates, location, licence information and cause/failure fields. Our fictional `event_id`, `event_date`, `site`, `synthetic_licence_id`, `cause_category` and `failure_mode` are a simplified conceptual mapping. |
| Separate equipment outages from reportable pipeline incidents | [AER incident classification](https://www.aer.ca/data-and-performance-reports/industry-performance/pipeline-performance/classifying-incidents) distinguishes incident types and pipeline loss of containment. A bearing failure or electrical trip in this project is an equipment outage, not automatically an AER-reportable spill or pipeline failure. |
| Timestamped sensors with quality flags | [AVEVA Historian documentation](https://docs-be.aveva.com/bundle/sp-historian-2023-r2/raw/resource/enus/sp-historian-2023-r2.pdf) describes recording value, timestamp and quality. We use daily wide snapshots and explicit missing/invalid flags rather than reproducing a vendor tag database or OPC quality codes. |

The generator's mechanical examples (bearing wear, seal leakage, overheating) are engineering teaching scenarios. This project does not claim that their distribution comes from AER incident statistics, or that AER publishes pump-bearing telemetry. Fictional equipment IDs and locations must not be joined to real AER licence records.

Azure and Power BI format/deployment references are linked in [Azure integration](azure.md) and [Power BI guide](powerbi.md).
