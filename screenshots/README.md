# Project Screenshot Gallery

Explore how this project connects equipment telemetry to maintenance decisions, model evaluation and an evidence-based assistant. All results use synthetic data and represent modeled scenarios.

**Start here:** [Maintenance costs](powerbi-native/01-executive-roi.png) · [Policy tradeoffs](powerbi-native/02-policy-comparison.png) · [Assistant response](assistant/01-policy-comparison-after.jpg)

| Power BI: maintenance cost comparison | Assistant: policy comparison with evidence |
|---|---|
| [![Executive ROI Summary](powerbi-native/01-executive-roi.png)](powerbi-native/01-executive-roi.png) | [![Evidence assistant response](assistant/01-policy-comparison-after.jpg)](assistant/01-policy-comparison-after.jpg) |

## Power BI Operations Dashboard

| Page | Business question | Screenshot |
|---|---|---|
| Executive ROI Summary | How do annualized costs compare across maintenance policies? | [View](powerbi-native/01-executive-roi.png) |
| Policy Comparison | How much warning does each policy provide, and what service burden does it create? | [View](powerbi-native/02-policy-comparison.png) |
| Fleet Risk Explorer | Which assets should the reliability team review first? | [View](powerbi-native/03-fleet-risk.png) |
| Model Performance | What are the tradeoffs between missed failures and false alarms? | [View](powerbi-native/04-model-performance.png) |
| Service Visit Audit | Which interventions prevented failures or produced unnecessary visits? | [View](powerbi-native/05-service-audit.png) |
| Methodology / About | What data, assumptions and limitations support the results? | [View](powerbi-native/06-methodology.png) |

**Supporting views:** [Asset Detail](powerbi-native/07-asset-detail.png) · [Asset Context](powerbi-native/08-asset-context.png)

These native captures predate a later report-formatting pass. Asset Detail and Asset Context show fleet aggregates in the captured state. Refresh, Service RLS, mobile and interactive behavior require separate validation; screenshots do not establish those checks. Sensor Associations is not pictured.

## Explore by Role

| View | What to look for | Screenshot |
|---|---|---|
| Decision | Cost comparisons, maintenance tradeoffs and scenario assumptions | [View](reviewer-tour/01-decision.jpg) |
| Data Scientist | Leakage prevention, model generalization and uncertainty | [View](reviewer-tour/02-data-scientist.jpg) |
| ML Engineer | Reproducibility, scoring contracts, deployment gates and monitoring | [View](reviewer-tour/03-ml-engineer.jpg) |
| AI Engineer | Evidence retrieval, site access controls and refusal handling | [View](reviewer-tour/04-ai-engineer.jpg) |

## Evidence Assistant

The local demonstration answers supported questions from project evidence, applies site access rules and refuses unsupported requests. It uses a rules-based query planner; the optional LLM integration is documented separately in the [assistant guide](../docs/ai-assistant.md).

[Welcome screen](assistant/00-welcome.jpg) · [Example response](assistant/01-policy-comparison-after.jpg) · [Query and evidence trace](assistant/12-evidence-trace.jpg)

<details>
<summary><strong>Explore 11 question-and-response examples</strong></summary>

| Question | Question entered | Response shown |
|---|---|---|
| Compare policy costs and caught failures | [View](assistant/01-policy-comparison-before.jpg) | [View](assistant/01-policy-comparison-after.jpg) |
| Show the top 6 assets by latest risk | [View](assistant/02-highest-risk-assets-before.jpg) | [View](assistant/02-highest-risk-assets-after.jpg) |
| Explain the model and its validation | [View](assistant/03-model-explanation-before.jpg) | [View](assistant/03-model-explanation-after.jpg) |
| How does site security work? | [View](assistant/04-access-controls-before.jpg) | [View](assistant/04-access-controls-after.jpg) |
| Latest risk for AB-001 | [View](assistant/05-asset-detail-before.jpg) | [View](assistant/05-asset-detail-after.jpg) |
| How is annualized cost calculated? | [View](assistant/06-cost-methodology-before.jpg) | [View](assistant/06-cost-methodology-after.jpg) |
| Are risk scores calibrated? | [View](assistant/07-calibration-before.jpg) | [View](assistant/07-calibration-after.jpg) |
| Latest risk for AB-002 | [View](assistant/08-cross-site-refusal-before.jpg) | [View](assistant/08-cross-site-refusal-after.jpg) |
| What if downtime cost is $2000 per hour? | [View](assistant/09-cost-scenario-refusal-before.jpg) | [View](assistant/09-cost-scenario-refusal-after.jpg) |
| What were July costs? | [View](assistant/10-date-refusal-before.jpg) | [View](assistant/10-date-refusal-after.jpg) |
| Book maintenance for AB-001 tomorrow | [View](assistant/11-booking-refusal-before.jpg) | [View](assistant/11-booking-refusal-after.jpg) |

The last four examples show cross-site access refusal, an unsupported cost scenario, an unavailable reporting period and the maintenance-booking boundary.

</details>

## Browser Dashboard Companion

A separate HTML dashboard provides an account-free way to explore the maintenance analysis locally. The images below show the browser application.

<details>
<summary><strong>View all six companion pages</strong></summary>

| Page | Screenshots |
|---|---|
| Executive ROI Summary | [Upper page](dashboard-companion/01-executive-roi-top.jpg) · [Lower page](dashboard-companion/01-executive-roi-bottom.jpg) |
| Policy Comparison | [Upper page](dashboard-companion/02-policy-comparison-top.jpg) · [Lower page](dashboard-companion/02-policy-comparison-bottom.jpg) |
| Fleet Risk Explorer | [Overview](dashboard-companion/03-fleet-risk-top.jpg) · [Asset trends](dashboard-companion/03-fleet-risk-middle.jpg) · [Lower page](dashboard-companion/03-fleet-risk-bottom.jpg) |
| Model Performance | [Upper page](dashboard-companion/04-model-performance-top.jpg) · [Lower page](dashboard-companion/04-model-performance-bottom.jpg) |
| Service Visit Audit | [Upper page](dashboard-companion/05-service-audit-top.jpg) · [Lower page](dashboard-companion/05-service-audit-bottom.jpg) |
| Methodology / About | [Upper page](dashboard-companion/06-methodology-top.jpg) · [Lower page](dashboard-companion/06-methodology-bottom.jpg) |

</details>

[Project overview](../README.md) · [Run locally](../START_HERE.md) · [Validation evidence](../reports/validation.md)