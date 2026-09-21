# Generalization, calibration and uncertainty study

The independent synthetic fleets expose a limitation hidden by the original
single-seed headline: reference-model recall falls from **66.16%** to
**49.80%-55.49%** across three new fleets, while precision remains high. This
study adds evidence about that variability without replacing the seed-42
benchmark or claiming validation on Alberta field data.

## Protocol and separation of datasets

[The local prospective protocol](generalization-protocol.json) was written at
2026-09-18 before this study executed. It specifies every seed,
partition rule, model recipe, threshold grid, calibration method and bootstrap
setting. The output embeds its SHA-256. This is a locally recorded experiment
specification, not an externally registered or independently witnessed protocol.

| Dataset | Role | What can be fit or selected? |
|---|---|---|
| Seed 42, 80 assets, Jan-Oct 2024 training | Reproduce published reference | Original fixed HGB recipe |
| Seed 42, 60 SHA-256-selected training assets | Asset-holdout study model | Same fixed HGB recipe; no held-out asset training |
| Those same 60 assets, Dec 2024-Feb 2025 | Select study dispatch threshold | Minimum predictive replay cost on declared grid |
| Independent seed 77, 80 assets, Dec 2024-Feb 2025 | Development calibration | One Platt mapping per already fitted model |
| Seed 42, remaining 20 assets, Apr-May 2025 | Retrospective future/asset holdout | Evaluation only |
| Independent seeds 101, 202 and 303, Apr-May 2025 | New fleet evaluation | Evaluation only; every declared seed reported |

Training ends 31 October, with 30-day labels available by 30 November;
validation begins 1 December. Validation/calibration end 28 February, with their
labels available by 30 March; test scoring begins 1 April. June observations are
excluded from classifier evaluation because complete 30-day follow-up is not
available. Each new fleet has the same 18-month coverage, with freshly generated
equipment histories and random draws. Reused local IDs such as `AB-001` identify
different synthetic units across seeds; `cohort + asset_id` is the report key.

The asset split ranks IDs using SHA-256 of `energy-study-v1|asset_id`, independent
of site, score and outcome. The 20 held-out assets span all four sites: seven Red
Deer, six Lloydminster, five Grande Prairie and two Peace River. The study model
fits **16,500** rows from 60 assets; the reference fits **22,000** rows from 80.
The study's threshold is selected on the 60-asset validation replay only:
**0.80**, with total predictive scenario cost **C$1,313,421.36**. The reference
retains **0.90**. Held-out assets never enter the study fit or threshold search.

Seed 42 was already explored in the earlier portfolio. Therefore its split is a
**retrospective diagnostic**, even though these study model fits exclude the 20
assets. The stronger fresh evidence is the three previously unevaluated fleets.
Those fleets still share the same generator family, assumed costs and failure
signatures; they are not a test of a different field population.

## Results across all declared cohorts

| Cohort / model | Labeled rows | Positive days | Precision | Recall | Average precision | Raw Brier |
|---|---:|---:|---:|---:|---:|---:|
| Seed 42 held-out 20 / published reference* | 1,220 | 114 | 100.00% | 71.05% | 0.9603 | 0.01774 |
| Seed 42 held-out 20 / study 60 | 1,220 | 114 | 91.82% | 88.60% | 0.9563 | 0.01762 |
| New fleet 101 / published reference | 4,880 | 769 | 99.22% | 49.80% | 0.7995 | 0.06193 |
| New fleet 101 / study 60 | 4,880 | 769 | 96.94% | 57.61% | 0.7881 | 0.06292 |
| New fleet 202 / published reference | 4,880 | 839 | 99.32% | 52.09% | 0.8990 | 0.04834 |
| New fleet 202 / study 60 | 4,880 | 839 | 99.22% | 60.91% | 0.8782 | 0.04997 |
| New fleet 303 / published reference | 4,880 | 710 | 98.01% | 55.49% | 0.8864 | 0.04042 |
| New fleet 303 / study 60 | 4,880 | 710 | 92.87% | 66.06% | 0.8741 | 0.04163 |

*The published reference has seen the training history of these 20 assets; its
row is a comparison only, not an unseen-asset claim.*

The model recipes use different training-set sizes and independently chosen raw
thresholds. The study model's higher recall cannot be attributed solely to better
generalization: 0.80 also accepts more alerts than 0.90. The threshold-independent
average-precision and Brier columns make that tradeoff visible. Neither the
study model nor its threshold is promoted into the dashboard or deployed scorer.

Every failure mode is reported, including zero-support groups. The retrospective
20-asset cohort has **no electrical-trip positive windows**, so its high recall
does not demonstrate abrupt-failure coverage. New fleets 101/202/303 contain
229/111/83 electrical-trip positive asset-days; both models alert on **zero** of
them. Gradual-mode recall also varies across fleets. These counts are correlated
daily observations, not independent event counts.

## Independent calibration, with negative results retained

Each Platt calibrator fits a logistic mapping from clipped logit(raw risk) to the
label using **7,200 development rows from seed 77 only**. Its fitted coefficients
are recorded in the JSON. Both mappings are fitted before any new fleet is
generated or evaluated. The method and regularization were specified in advance;
no calibration method is selected by external-test performance.

| Model / external seed | Raw Brier | Calibrated Brier | Raw log loss | Calibrated log loss |
|---|---:|---:|---:|---:|
| Reference / 101 | 0.06193 | 0.06119 | 0.27245 | 0.21891 |
| Reference / 202 | 0.04834 | 0.04313 | 0.18499 | 0.15311 |
| Reference / 303 | 0.04042 | 0.03855 | 0.15733 | 0.14114 |
| Study 60 / 101 | 0.06292 | 0.06481 | 0.27488 | 0.22904 |
| Study 60 / 202 | 0.04997 | 0.05006 | 0.18903 | 0.17310 |
| Study 60 / 303 | 0.04163 | 0.04270 | 0.16090 | 0.15788 |

Calibration improves reference Brier on these three fleets but **worsens study
model Brier on all three**, despite reducing log loss. Both models' Brier also
worsens on the retrospective 20-asset cohort. Calibration is not universally
beneficial here. Fixed-width reliability bins, counts and mean outcomes are
exported so empty or sparse bins remain visible. The two mappings are monotonic,
so their average precision and ROC AUC stay unchanged.

Calibrated values are stored in a separate score column. **No dispatch threshold
is assigned to them.** The raw thresholds are never silently reused on that new
scale, and no calibrated policy cost or savings improvement is claimed. A future
promotion would need a separate development policy-selection period and another
untouched evaluation cohort.

## Asset-cluster uncertainty

The bootstrap samples **whole assets with replacement**, keeping all days from
each sampled asset together. For the baseline cost contrast, fixed and predictive
costs stay paired within the same asset. There are 2,000 replicates using the
declared seed, with 2.5th-97.5th percentile ranges. The classifier/model and
interventions are fixed; no fit or replay is rerun inside a replicate.

| Seed-42 reference quantity | Point estimate | Conditional 95% resampling range |
|---|---:|---:|
| Precision | 99.12% | 98.09%-99.84% |
| Recall | 66.16% | 57.27%-74.51% |
| Brier score | 0.03555 | 0.02182-0.05245 |
| Fixed-minus-predictive operating cost, 91 days | C$3.344M | C$2.249M-C$4.543M |
| Same difference annualized | C$13.420M | C$9.028M-C$18.234M |

The new-cohort classifier results also receive asset-cluster ranges in
`generalization.json`. The full baseline result is in `uncertainty.json`.
These are **conditional synthetic resampling ranges**, not confidence intervals
for Alberta operators. They do not include generator misspecification, model
fitting uncertainty, shared site shocks, uncertainty in cost inputs or the
intervention-success assumption. The annualization still extrapolates only
91 days. A fraction of positive-cost resamples is recorded for audit; it is not
the probability that a real deployment will be profitable. Independent scenario
sensitivity remains necessary even if all resampled fleets save money.

## Reproduction and artifacts

```powershell
python -m energy_failure.generalization --root .
python -m energy_failure.uncertainty --root .
python -m pytest -q tests/test_generalization.py tests/test_uncertainty.py
```

The generalization command also runs the uncertainty export. The second command
is available when only the fixed-benchmark intervals need rebuilding.

- [Study JSON, protocol hash, cohort evidence and intervals](../reports/generalization.json)
- [Metrics](../reports/generalization_metrics.csv), [failure-mode coverage](../reports/generalization_failure_modes.csv), [validation threshold costs](../reports/generalization_thresholds.csv)
- Raw and calibrated row-level scores are generated locally as `reports/generalization_scores.csv`; [reliability bins](../reports/generalization_calibration_bins.csv) remain published.
- [Baseline bootstrap JSON](../reports/uncertainty.json), [interval table](../reports/uncertainty_intervals.csv)
- [Study source](../src/energy_failure/generalization.py), [bootstrap source](../src/energy_failure/uncertainty.py)

Temporary raw fleets are removed after the run; their manifests and raw-data
hashes are retained, and the declared seeds regenerate them. Existing headline
data, model artifacts and reporting measures are not overwritten.
