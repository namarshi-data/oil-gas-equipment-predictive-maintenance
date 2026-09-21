# Model card - synthetic energy equipment failure risk

**Status:** portfolio demonstration with executable validation and explicitly
limited operating scope. It is not a field-approved reliability system.

## Intended decision and user

Rank operating equipment for a reliability engineer's review of possible failure
within the next 30 days. The scenario converts raw-score alerts into planned
service visits and compares them with actual simulated fixed-90-day and reactive
policies. Scores support investigation; they do not authorize autonomous shutdowns
or replace protective controls, statutory inspection or commissioning procedures.

## Published model and data

The published seed-42 model is histogram gradient boosting with 180 boosting
iterations, learning rate 0.055, at most 15 leaves, minimum leaf support 60 and L2
regularization 5. It uses 38 allowlisted predictors: seven sensor channels,
causal 7/30-day means and changes, missingness/gap indicators, age, recorded
maintenance recency, equipment indicators and seasonality. Identifiers, future
events, oracle preventability and repair-success draws are excluded.

Training data consists of 22,000 asset-days from 80 synthetic units, with a
30-day label purge before validation. The raw threshold **0.90** and model family
were selected using validation policy cost. The final 30 days of telemetry are
censored for classifier evaluation. Negative labels mean no recorded future
failure within an observed horizon; they do not certify that equipment is safe.

The dataset is fully synthetic and enriched with failures. AER/SCADA inspiration
concerns schema and reporting context, not the use of actual regulator or operator
records. The baseline training sample contains no newly commissioned units: its
youngest training observation is 435 days old. Values are daily snapshots rather
than high-frequency vibration waveforms.

## Evidence and tradeoffs

The original temporal test has 4,880 labeled asset-days and 854 positive days:
precision **99.12%**, recall **66.16%**, average precision **0.931** approximately,
and Brier **0.03555** at the selected raw threshold. These metrics are separate
from event-level policy catches. The replay prevents 37/44 failures versus
13/44 under fixed service, under the stated intervention assumptions.

The v3 [generalization study](generalization.md) keeps that benchmark intact.
Independent synthetic fleets 101/202/303 produce reference recall
**49.80%/52.09%/55.49%** and precision **99.22%/99.32%/98.01%**. A separately fitted
60-asset model uses only its own assets for validation threshold selection and
evaluates the 20 excluded assets in the future period. Because seed 42 had already
been explored, that asset split is labeled retrospective. Neither it nor the
fresh fleets establishes real-world transfer.

Asset-cluster resampling places baseline recall within **57.27%–74.51%** and
precision within **98.09%–99.84%** conditional ranges. These do not cover all
uncertainty, and correlated site shocks could invalidate asset independence.

## Known failure cases and review requirements

| Condition | Observed evidence | Decision implication |
|---|---|---|
| Abrupt electrical trips with no precursor | Zero positive-window alerts across all three new fleets | Retain electrical protection and reactive contingency planning |
| Newly installed assets | Six controlled units at ages 0–29 produce zero alerts on 150 positive days | Require commissioning review; finite low risk is not proof of health |
| Incomplete maintenance history | Alternating record removal increases false positives from 5 to 14 | Reconcile history and expose coverage; commissioning-date fallback does not establish absence of maintenance |
| Gradually biased vibration sensor | Affected-cohort false positives increase from 0 to 31 | Plausible measurements need sensor-health review, not only range validation |
| Abrupt stuck-zero vibration sensor | Affected-cohort recall falls from 72.41% to 18.97% | Low readings can hide equipment degradation |
| Missing vibration channel | Missingness is recognized, but affected-cohort recall falls to 50.00% | Long causal carry-forward cannot recover unobserved degradation |

See the [robustness audit](robustness.md) and [sensor hardware experiments](sensor-fault-tests.md)
for denominators and measured limits. The commissioning/manual-review flag is a
workflow guardrail; it is not a retrained model or proof that recall improved.

## Calibration and score interpretation

The deployed reference remains a **raw risk score**, not a demonstrated calibrated
field probability. V3 separately fits Platt mappings using an independent
development fleet and period. Reference Brier improves on the three new fleets,
but the 60-asset study model's Brier worsens on all three. Both mappings are
reported, without selecting a winner on those evaluation results.

Calibrated scores have their own column, no dispatch threshold and no savings
claim. Promoting either mapping requires development-only decision-rule selection
and a new untouched evaluation. Monotonic calibration does not improve ranking
metrics or create information about unobservable abrupt faults.

## Business estimates and scope

The published 91-day simulation reports 19-day median warning among successfully
prevented events, 82.0% less unplanned downtime than fixed service, C$4.93M/year
annualized avoided emergency repairs versus reactive, and C$13.42M/year
annualized net operating-cost savings versus fixed service. Gross emergency
repair savings are already part of operating savings and must not be added again.

The paired asset bootstrap gives a conditional annualized operating-cost
difference range of C$9.03M–C$18.23M. This is neither a field confidence interval
nor guaranteed ROI. The core replay holds subsequent telemetry fixed after a
simulated prevention. Cost, intervention success, dispatch constraints,
implementation expenditure and operating assumptions need separate scenario
analysis; adverse assumptions can reverse savings.

## Reproducibility and change control

The [study protocol](generalization-protocol.json) records the planned cohorts and
selection rules. Executable modules publish row-level scores, raw-data hashes,
calibration parameters, every declared cohort and undefined denominators. Tests
check temporal purging, disjoint asset partitions, calibration bounds, whole-asset
resampling and paired policy costs.

Keep the original temporal test and v3 external results as evaluation evidence.
If a developer uses them to change features, model recipes or rules, those cohorts
have become development data. Claim fresh final performance only on another
untouched cohort defined before examining its results. Real deployment also needs
operator data validation, reliability-engineer acceptance, monitored sensor
coverage and explicit model/rule versioning.
