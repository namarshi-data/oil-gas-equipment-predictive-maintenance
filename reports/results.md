# Reproduced results - synthetic scenario

Seed 42; 80 assets; 43,760 daily snapshots. All currency CAD. Policy evaluation: 2025-04-01 to 2025-06-30 inclusive.

| Policy | Failures prevented / total | Planned visits | Unplanned hours | Total hours | Test-period total cost |
|---|---:|---:|---:|---:|---:|
| Reactive | 0/44 | 0 | 3,877.0 | 3,877.0 | $5,505,868 |
| Fixed 90-day | 13/44 | 81 | 2,607.1 | 3,093.1 | $4,527,234 |
| Predictive | 37/44 | 51 | 469.0 | 771.0 | $1,183,653 |

Selected model: **hist_gradient_boosting**, threshold **0.90**. Selection minimizes validation policy cost; no test retuning or post-selection refit. The table below evaluates each algorithm at its own validation-selected threshold.

| Algorithm | Threshold | Average precision | Precision | Recall | Brier score |
|---|---:|---:|---:|---:|---:|
| logistic regression | 0.85 | 0.909 | 0.963 | 0.587 | 0.043 |
| hist gradient boosting | 0.90 | 0.931 | 0.991 | 0.662 | 0.036 |

Classification includes only test dates with complete 30-day follow-up, through 2025-05-31. These are asset-day metrics; repeated positive days before one failure are not independent events. Event prevention recall is reported separately above. Scores are not independently calibrated; see the reliability diagram before interpreting them as precise probabilities.

## Business case arithmetic

- Median warning among prevented predictive events: **19.0 days**; reactive maintenance: 0 days. Missed failures still receive zero useful warning.
- Unplanned-hours reduction vs fixed: **82.0%** = 100 × (fixed hours − predictive hours) / fixed hours.
- Net scenario savings vs fixed: **CAD $13,420,251/year** for the whole fleet; includes planned service and downtime costs.
- Avoided emergency repair costs vs reactive: **CAD $4,931,920/year** (gross repair-only savings; do not add to net savings).
- Annualization factor: **4.013736** = 365.25 / test days. This extrapolates a short synthetic period; it is not a one-year observation.

See [methodology](../docs/methodology.md) for boundary handling and causal limits, [sensitivity.csv](sensitivity.csv) for alternative actionability/success assumptions, and [policy service ledger](../data/processed/dashboard/service_visits.csv) for every charged visit. When a sensitivity scenario reverses the benefit, retain that result.
