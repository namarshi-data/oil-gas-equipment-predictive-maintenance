# Methodology and limits of the business case

This is a reproducible **synthetic scenario**, designed to demonstrate a complete reliability analytics workflow. The baseline is operational maintenance: an existing 90-day service calendar and reactive repair. Neither a majority-class predictor nor a second ML algorithm stands in for that business baseline.

## 1. Equipment history

The seeded generator produces 80 assets (27 pumpjacks, 27 compressors, 26 pipeline pumping assets) across four fictional Alberta sites. Daily snapshots cover 1 January 2024–30 June 2025: 43,760 asset-days. Each snapshot contains vibration, bearing temperature, pressure, RPM, accumulated runtime, load and power. Daily cadence is a teaching reduction of a SCADA historian, not high-frequency vibration waveform analysis. Coordinates are illustrative, not real installations.

Slow bearing wear, seal leakage and overheating raise or alter multiple sensors over 42–75 days. Asset offsets, load variation, seasonality, random noise, recovering operating transients and abrupt electrical trips make the target imperfectly observable. About 16% of generated episodes have no actionable precursor. Failures cause a three-day shutdown signature and a recorded reactive repair. The sample deliberately has an enriched failure frequency; it does **not** estimate Alberta equipment failure rates.

Four communication outages of 2–5 days per asset remove all sensor values while preserving the expected daily row. Additional isolated missing values, extreme values, padded asset IDs and retransmitted rows exercise cleaning. `simulation_truth.csv` stores hidden preventability and shared repair-success draws. The model cannot access these columns.

The source history records reactive operations. Preventive alternatives are assessed against that shared history; generating raw data is independent of the ML fit and thresholds.

## 2. SQL cleaning and features

[`01_clean.sql`](../sql/01_clean.sql) normalizes identifiers, rejects invalid keys/dates, selects the latest ingestion for each asset/date, validates engineering ranges and records missing flags. A missing or invalid channel receives its most recent **earlier valid** value for the same asset, or a fixed engineering fallback at cold start. There is no backward filling or full-dataset mean imputation. Flags retain the difference between observed and imputed values.

[`02_features.sql`](../sql/02_features.sql) calculates trailing 7- and 30-calendar-day means, one-step rates of change, missing-day gaps and recent imputation counts. It joins installation metadata and the latest maintenance record available by that date. Features are end-of-day snapshots; current-day maintenance can be known. The first 30 days are excluded from training as a feature warm-up.

Seven-channel missing rows and absent calendar dates are different quality conditions. `sensor_missing_count` flags the former; `missing_gap_days` flags the latter. The generated default has communication outages but no absent date rows; tests cover both.

## 3. Leakage controls and model comparison

For day *t*, the binary target is a failure on days *t+1* through *t+30*, inclusive. Today's failure is excluded. `days_to_failure` is an audit/EDA field, never an input. Labels with incomplete 30-day follow-up are null, including all of June 2025. Even an observed failure within a partially censored horizon does not cause that row to be included selectively.

| Use | Reading dates | Latest outcome needed |
|---|---|---|
| Train | 31 Jan–31 Oct 2024 | 30 Nov 2024 |
| Purge | November 2024 | No rows used for fitting or selection |
| Validation | 1 Dec 2024–28 Feb 2025 | 30 Mar 2025 |
| Purge | March 2025 | No rows used for fitting or selection |
| Classification test | 1 Apr–31 May 2025 | 30 Jun 2025 |
| Policy test | 1 Apr–30 Jun 2025 | Events through 30 Jun 2025 |

An allowlist of 38 numerical features excludes identifiers, outcome dates, future labels, costs and simulation truth. Logistic regression uses training-fitted scaling and balanced class weights. Histogram gradient boosting learns nonlinear interactions. Each has a prespecified threshold grid of 0.10–0.90 in 0.05 increments. The model/threshold pair minimizing **validation predictive-policy total cost** wins; ties prefer the higher threshold within an algorithm. No refitting or tuning uses the test set. Both algorithms are reported on the same test rows at their own validation-selected thresholds.

Average precision, precision, recall, ROC AUC and Brier score are asset-day measures. One upcoming event can create 30 positive daily labels, so daily recall is different from event prevention recall. Probability outputs are presented as **risk scores**: calibration is diagnosed, not guaranteed. A future production study should fit calibration on a separate, chronologically appropriate calibration set.

This temporal split tests future observations on an existing fleet. It does not establish performance on new assets, sites or operators. Same-asset observations and failure windows are correlated; ordinary independent-row confidence intervals would overstate certainty.

## 4. The maintenance replay

All policies see the same assets and latent failure dates. Policy decisions use only dates or model scores. The hidden oracle is consulted **after** a visit date is chosen to adjudicate its effect.

| Policy | Decision | Failure prevention |
|---|---|---|
| Reactive | Repair after the failure occurs | None; zero advance warning |
| Fixed 90-day | Service at installation date + multiples of 90 days, regardless of condition | Service must fall 1–30 days before an actionable event and the intervention must succeed |
| Predictive | First score at or above the selected threshold outside cooldown | Service occurs two days after alert; same 1–30-day opportunity and success rule |

After predictive service, the asset has a 30-day cooldown before a new alert can book a visit. Fixed dates remain on their calendar after failures and repairs; no schedule reset is silently assumed. A service on the failure date is too late. Abrupt events cannot be prevented. A fixed, seeded per-event draw gives a 90% intervention success assumption for both policies; repeated visits do not get independent chances at the same intrinsically unsuccessful event. One event can be prevented at most once.

**Boundary accounting:** fixed-interval maintenance is the existing status quo, so the replay credits scheduled visits in the 30 days before evaluation that can protect an early evaluation failure. Their costs belong to the prior accounting period. These are explicit `carry_in_visits`; the service ledger marks `in_evaluation_window=0`. Predictive maintenance starts at the evaluation boundary with no earlier alerts. This favors the established baseline at entry. Visits during the evaluation period are all charged, even if they have no credited benefit before the period ends. Post-period benefits are not assumed. Alerts too late to dispatch within the window do not become charged visits. This finite-window accounting also applies to validation selection.

Each visit is classified as a prevented failure, an unsuccessful intervention, or no actionable failure. “Unnecessary services” means the last category; unsuccessful interventions are counted separately. Service counts in the policy summary count only visits within the accounting period. A fixed-policy prevention can therefore be credited to a carry-in visit.

Warning time is event date minus the alert that led to successful prevention. Fixed-policy warning is measured from its scheduled visit, when the fault is assumed discovered; planning the calendar itself is not a condition warning. The headline median uses prevented predictive events only. Misses are explicitly shown in the denominator and at zero useful warning in the README chart. Service lead time subtracts dispatch delay and is available separately.

## 5. Economics

All amounts are illustrative **Canadian dollars**. Per-failure emergency repair cost and downtime vary around the type-specific inputs below. Each planned visit incurs its cost and planned downtime, whether productive or not.

| Equipment | Planned visit | Planned hours | Base emergency repair | Base failure hours | Downtime CAD/hour |
|---|---:|---:|---:|---:|---:|
| Pumpjack | 1,600 | 4 | 18,000 | 72 | 650 |
| Compressor | 4,000 | 8 | 48,000 | 96 | 1,400 |
| Pipeline pump | 2,400 | 6 | 30,000 | 84 | 950 |

`total cost = emergency repairs + all planned visits + (planned + unplanned downtime) × type-specific hourly downtime cost`.

Net savings vs fixed subtract the predictive total from the fixed total. Avoided emergency repairs vs reactive are a separate **gross repair-only** comparison, already included in the net calculation; do not add the two. Annualized amounts multiply the 91-day evaluation result by 365.25 / 91 for the same 80-asset fleet. They are extrapolations, not measured yearly returns. Cloud, licensing, staffing and implementation costs are not included; a real project must subtract them before claiming ROI. Environmental consequences and regulatory penalties are not priced.

[`sensitivity.csv`](../reports/sensitivity.csv) holds the trained model and threshold fixed while varying the actionable window (14, 21, 30, 45 days) and repair success (70%, 90%, 100%). It retains adverse outcomes. These scenarios assess assumptions, not confidence intervals and not test-set retuning.

## 6. What the replay cannot prove

This is a **shared-history replay**, not a causal estimate or a digital twin. Preventing a latent failure does not regenerate later sensors, runtime, maintenance records or future failure dates. No policy observes its simulated intervention's effect in the features. Policies also have no crew-capacity, spare-part, road-access, weather-delay or simultaneous outage constraints. The financial result depends strongly on the synthetic degradation model, failure frequency, actionability and downtime prices.

A field pilot would begin in shadow scoring, validate calibrated event risk, review alerts with reliability engineers, and measure maintenance outcomes prospectively. It would replace assumed costs with work orders and production-loss data, learn intervention effectiveness, and simulate feedback before drawing deployment-scale conclusions.
