# Tested against failure signatures, missing history and new equipment

The core benchmark remains unchanged. These checks deliberately search for weak
spots in the selected model and preserve failures as findings. A project that
reports its operating limits is more defensible than one that promises every
equipment failure can be predicted.

## Reproduce the evidence

From the project root, after the main pipeline:

```powershell
python -m energy_failure.robustness --root .
python -m pytest -q tests/test_robustness.py
```

The module refits the selected algorithm from the original training rows and
hyperparameters, keeps the validation-selected threshold of **0.90**, and first
checks that every baseline held-out score matches the main pipeline. It never
loads an archived pickle, changes the headline artifact, tunes on the test set,
or converts a stress result into an annual savings claim.

Machine-readable evidence:

- [Complete experiment record](../reports/robustness.json)
- [Classification stress results](../reports/robustness_classification.csv)
- [Failure-mode classification recall](../reports/robustness_mode_recall.csv)
- [Failure-mode policy outcomes and costs](../reports/robustness_failure_modes.csv)
- [Executable experiment](../src/energy_failure/robustness.py)
- [Boundary tests](../tests/test_robustness.py)

The figures below are the default seed-42 run. There are **4,880 labeled
asset-days**, including **854 positives**, from 1 April through 31 May 2025.
Event-policy results cover the full **91-day** replay through 30 June. Repeated
days for one event are correlated; the day counts are not independent failures.

## Incomplete maintenance history

The SQL stage is rerun on copies of the raw data. One challenge removes every
other recorded repair per asset, while retaining commissioning records. Another
removes all maintenance rows for every fourth asset in sorted asset-ID order
(20 of 80 units). Selection never uses an outcome or risk score. Sensors, labels
and all other model features are checked to remain identical.

| Frozen-model input | Records removed | Test recency values changed | Precision | Recall | False-positive asset-days |
|---|---:|---:|---:|---:|---:|
| Original history | 0 | 0 | 99.12% | 66.16% | 5 |
| Alternating repairs removed | 146 of 314 | 2,474 | 97.63% | 67.56% | 14 |
| No records for 20 assets | 80 of 314 | 1,220 | 98.82% | 68.50% | 7 |

The model still scores finite inputs, but incomplete records change its
decisions: 25 and 26 alert decisions differ from baseline, respectively. Higher
recall here is accompanied by additional false alarms; it is not evidence that
deleting maintenance data improves the system.

**Known limitation:** SQL falls back to time since commissioning when no earlier
maintenance record exists. That value does not prove no maintenance occurred.
There is currently no explicit `maintenance_history_unknown` predictor. A field
deployment should expose source coverage, add a validated unknown-history
indicator, retrain and reselect the threshold on validation, and reconcile the
maintenance system before creating work orders. This audit leaves the published
38-feature benchmark intact.

## Gradual versus abrupt failure signatures

The generator includes three different gradual mechanical modes and abrupt
electrical trips with no designed precursor. This tests more than one signature.
The following table separates classifier recall from successful policy catches:

| Failure mode | Positive asset-days / distinct events | Classifier recall | Predictive catches | Fixed-90-day catches |
|---|---:|---:|---:|---:|
| Bearing wear | 290 / 17 | 74.48% | 14 / 17 | 6 / 17 |
| Overheating | 339 / 16 | 68.73% | 15 / 16 | 5 / 16 |
| Seal leak | 160 / 8 | 72.50% | 8 / 8 | 2 / 8 |
| Abrupt electrical trip | 65 / 3 | **0.00%** | **0 / 3** | **0 / 3** |

The model detects patterns across all three gradual modes, but it misses abrupt
trips. The simulated intervention oracle also defines abrupt trips as
unpreventable, so catch rate alone would not establish classifier capability;
the separate 0/65 alerted-positive-day result confirms this blind spot. Three
abrupt events are a very small sample, and all modes are synthetic.

Missed abrupt trips contribute **190.2 unplanned hours** and **C$135,099.02 in
emergency repair costs** during this replay, under both fixed and predictive
policies. A practical reliability program still needs electrical protection,
inspection and reactive contingency planning. Predictive scores do not replace
these controls. The CSV contains the same nonannualized costs for every mode and
policy; stress-classification experiments do not estimate service costs.

## New unit installed less than 30 days ago

Six controlled units cross three equipment types with gradual and abrupt
signatures. Each is commissioned on the first observation date, starts runtime
at zero, has no inherited telemetry or maintenance, and fails on day 25. A
61-day observation window provides complete future labels when evaluating the
first 30 days. Missing readings at ages 0, 10, 11 and 12 also test first-reading
defaults and a subsequent communication outage.

The SQL and feature pipeline produces **180 finite scored rows** at ages **0–29**,
with **42 defaulted first-reading cells**. The classifier produces **zero alerts**
and **0% recall on 150 positive asset-days**, in both signature groups. Precision
is undefined because there are no alerts; it is reported as null, never 100%.

This is a failed model generalization check, even though the software handles the
input successfully. The youngest baseline training observation is **435 days
old**. The fixture is outside the training population, and its 83.3% positive
prevalence is deliberately artificial. It is not a new-equipment field-accuracy
estimate.

**Operational response:** route assets younger than 30 days to commissioning
review and display their low score with that qualification. The batch scorer
adds `requires_manual_review` and `review_reason` for this condition while
preserving the underlying risk and alert; this is a review guardrail, not a
recall improvement. Equipment aged 30–434 days is also outside the age range of
this training sample and requires separate validation. Collect representative
early-life histories, validate by installation cohort, and retrain before
claiming cold-start coverage. Do not silently assign a healthy state to a low
score on a new asset.

## What broke and how the fix is verified

**Controlled reproduction:** zero-filling a three-day communication outage in
an otherwise constant 3 mm/s vibration trace creates a fictitious **−3 mm/s/day**
drop. An illustrative rule that flags drops below −2 reports one false anomaly.
The actual causal SQL cleaning carries forward the earlier valid observation,
records all seven channels as missing, and produces **0 mm/s/day** change across
the outage. The artificial-drop count becomes **1 → 0**, while all three outage
rows remain explicitly flagged.

This recreates and tests a plausible ingestion defect. It is not evidence that
an earlier project model had a measured 15% false-alarm rate, nor is the simple
drop rule a trained ML classifier. The original reviewed pipeline already used
causal imputation; the final refinement adds the reproducible regression case.

A separate ablation tests the incremental value of three explicit gap
predictors, keeping causal imputation, algorithm, hyperparameters, training rows
and the baseline threshold fixed:

| Labeled test subset | Explicit gap predictors | False-positive asset-days | False discovery among alerts | Recall |
|---|---|---:|---:|---:|
| All 4,880 rows | Present | 5 | 0.877% | 66.16% |
| All 4,880 rows | Removed | 5 | 0.874% | 66.39% |
| 1,374 rows with imputation in trailing 7 days or current calendar gap | Present | 2 | 1.258% | 52.86% |
| Same 1,374 rows | Removed | 2 | 1.212% | 54.88% |

**No ML false-alarm reduction is demonstrated by adding the gap predictors in
this run.** Retain their data-quality and audit value without claiming an
unsupported predictive benefit. The ablation is diagnostic, not separately
optimized for policy cost; its threshold was not reselected for the alternative
feature set. One synthetic seed cannot establish a general effect.

False discovery is FP/(TP+FP), while false-positive rate is FP/(FP+TN). Both are
reported in the machine-readable results. Neither is the fraction of service
visits that fail to prevent an event; that is a different event-policy measure.

## Why this matters

**What:** a robustness audit tests whether a model still behaves sensibly when
data coverage, asset age or failure signature differs from its training sample.

**Use case:** a reliability engineer receives a low score for a newly installed
compressor, or an operator imports telemetry before its historical work orders.
A finite risk score is not sufficient evidence that the unit is safe.

**Real-world application:** the report makes data availability visible, separates
model alerts from successful maintenance interventions, routes commissioning
cases to review, and preserves protective maintenance for unobservable abrupt
faults. The exact percentages here remain synthetic demonstration results.
