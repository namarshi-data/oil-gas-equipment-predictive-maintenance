# Gradual and abrupt sensor hardware faults

This experiment tests the existing **equipment-failure model when a sensor
malfunctions**. It complements the gradual mechanical/abrupt electrical event
checks in [the robustness audit](robustness.md). It does not train or claim a
sensor-fault diagnostic classifier.

## Controlled experiment

Select every fourth sorted asset ID: 20 of 80 assets. Inject one vibration-channel
fault at a time from **15 April through 15 May 2025**, inclusive:

1. **Gradual bias:** add a linear offset from 0 to +5 mm/s to originally valid,
   observed vibration readings.
2. **Abrupt stuck-at-zero:** replace originally valid, observed vibration
   readings with zero throughout the fault window.
3. **Abrupt dropout:** replace vibration readings with missing values throughout
   the same window.

The first two scenarios retain existing missing/invalid readings; a
communication outage cannot deliver a stuck sensor value. Other channels,
equipment events, maintenance history and asset metadata are unchanged. Readings
return to the original values on 16 May. Both fault onset and restoration can
therefore affect rate-of-change features; rolling-window effects persist after
the fault ends.

The deterministic selection happens to contain **20 Peace River assets** because
the synthetic generator assigns sites cyclically. This is an intentionally
bounded diagnostic cohort, not a site-representative fleet sample. Selection is
independent of labels and scores, and it is not changed after inspecting results.

Each scenario runs through the actual SQL cleaning and feature pipeline in a
temporary directory. The selected model is fit once on the unchanged original
training set with its original hyperparameters. Baseline scores are reconciled
against all 4,880 published held-out scores, then the model and **0.90 threshold
remain frozen**. There is no fitting or threshold selection on corrupted data.

## Measured results

The affected cohort contains **620 labeled asset-days**, including **116 positive
days**. These are repeated observations, not 116 independent failures.

| Input during the fault window | False positives | False negatives | Precision | Recall | Alert decisions changed |
|---|---:|---:|---:|---:|---:|
| Original readings | 0 | 32 | 100.00% | 72.41% | 0 |
| Gradual +0 to +5 mm/s bias | 31 | 21 | 75.40% | 81.90% | 42 |
| Abrupt stuck-at-zero | 0 | 94 | 100.00% | 18.97% | 62 |
| Abrupt missing-channel dropout | 0 | 58 | 100.00% | 50.00% | 26 |

Higher recall under bias does not mean improved reliability: the added signal
creates **31 false positives** and lowers precision. Stuck-zero readings suppress
real warnings: affected-cohort recall falls from **72.41% to 18.97%**. Even a
correctly recognized dropout lowers recall to **50.00%** because stale
carry-forward readings cannot represent new degradation.

Across **all 4,880 labeled test rows**, including unaffected equipment and rolling
carryover after 15 May:

| Scenario | FP | FN | Precision | Recall | Alert decisions changed |
|---|---:|---:|---:|---:|---:|
| Baseline | 5 | 289 | 99.12% | 66.16% | 0 |
| Gradual bias | 37 | 280 | 93.94% | 67.21% | 45 |
| Stuck-at-zero | 5 | 358 | 99.00% | 58.08% | 69 |
| Dropout | 5 | 317 | 99.08% | 62.88% | 28 |

## What cleaning detects, and what it misses

During the 620-row fault window, the original data contains 20 missing/invalid
vibration flags. Gradual bias and stuck-zero leave this count at **20**, because
the injected values remain inside the current engineering limits. Dropout
increases it to **620**, and SQL imputes each missing value from the last earlier
valid reading for that asset. The recorded maximum changes to the seven-day
vibration mean are **4.643**, **6.578** and **3.683 mm/s**, respectively.

Bounds checks and missing flags cannot diagnose every hardware fault. A value of
zero is valid during a genuine shutdown, and a plausible biased value can
resemble equipment degradation. Production improvements would require validation
of flatline duration, sensor calibration drift, cross-channel consistency and
maximum acceptable measurement staleness. They are **proposed next steps**, not
implemented sensor-diagnostic capabilities or proven improvements. Raw data and
sensor-health status should accompany model alerts in a reliability workflow.

The executable tests verify that:

- Only vibration changes at the raw-data layer; events and maintenance files do
  not change.
- All features before fault onset remain unchanged, and all other assets and
  other sensor features remain unchanged in the full experiment.
- Equipment-failure labels stay identical.
- Missing dropouts become explicit flags and finite causal imputations.
- In-range bias and stuck-zero values pass current physical-bound validation;
  the test deliberately preserves this known limitation.

## Reproduce and inspect

```powershell
python -m energy_failure.sensor_faults --root .
python -m pytest -q tests/test_sensor_faults.py
```

- [Experiment source](../src/energy_failure/sensor_faults.py)
- [Four passing test cases](../tests/test_sensor_faults.py)
- [Full JSON record and limitations](../reports/sensor_faults.json)
- [Classifier metrics with denominators](../reports/sensor_faults_metrics.csv)
- [Cleaning flags and rolling-feature changes](../reports/sensor_faults_quality.csv)

These default seed-42 results are sensitivity measurements on synthetic
asset-days. There is no intervention-policy replay or cost-savings estimate for
these fault injections, and the project's headline metrics remain unchanged.
The experiment demonstrates failure modes of the current model; it does not
establish production robustness, sensor diagnosis accuracy or successful
mitigation.
