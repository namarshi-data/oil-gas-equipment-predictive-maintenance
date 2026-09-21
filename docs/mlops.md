# Operating the portfolio model

Version 3 adds executable engineering checks around the existing model. **Everything described as validated here ran locally. No GitHub-hosted workflow run, Azure environment build, cloud job, or deployment is claimed.** The GitHub workflows are ready to run after the repository is pushed and Actions is enabled.

## Reproduce the engineering evidence

```powershell
python -m pip install -e ".[dev]"
python -m energy_failure.pipeline --output-root .
python deployment/local_smoke.py
python -m energy_failure.monitoring --root .
python -m pytest tests/test_mlops.py tests/test_batch_score.py tests/test_azure_smoke.py -q
```

The focused engineering suite passes 32 cases. It fits a small real classifier in a temporary directory to test the Azure adapter from a clean checkout; it does not depend on a downloaded or committed `model.joblib`. Other cases cover record reconciliation, causal flatline detection, unknown maintenance, label maturity, schema/key failures and the deployment promotion gate. The full suite is recorded separately by the portfolio acceptance run.

Final local evidence: all 7,280 rows reconcile under model `energy-v3-a4bbde11ebed7e1afce7`; 432 rows require data-quality review (339 imputed only, 93 imputed and stale). The latest seven-day monitoring window contains 560 rows and no threshold breaches; its imputation/review share is 5.18%. The controlled quality-flag spike raises two findings, while the delivery-delay replay identifies all 80 assets as stale plus missing recent scores. Mature-label metrics use 4,880 rows. These observations are recorded in [MLOps validation](../reports/mlops-validation.json), [batch evidence](../artifacts/azure-local-smoke/validation.json), and [monitoring replay](../reports/monitoring_replay.json).

## What CI actually checks

| Workflow | Trigger and scope | Evidence retained |
|---|---|---|
| `.github/workflows/ci.yml` | Pull requests and main/master pushes: unit/SQL contracts, tiny fitted-model adapter integration, and offline Power BI schemas | JUnit results and schema report for 14 days |
| `.github/workflows/benchmark.yml` | Manual dispatch or Monday 07:17 UTC: full seeded experiment, adapter reconciliation, monitoring replay and full test suite | Metrics, provenance, scoring validation, monitoring findings and JUnit results for 30 days |

Both workflows use read-only repository permissions and require no Azure credentials. The fast workflow excludes tests that reconcile the delivered benchmark artifacts; the scheduled/manual workflow regenerates those artifacts before running them. Expensive repeated experiments and bootstrap analysis are deliberately not part of the pull-request loop. Static Power BI checks do not execute DAX/M or validate Desktop rendering.

A local clean-checkout simulation removed ignored raw data, serialized models and flat processed CSVs, then reran the suite against 123 Power BI schema files and 101 visual bindings to confirm the published tree is self-contained. See the [validation record](../reports/validation.md) for current counts; this is a local test, distinct from a GitHub-hosted execution.

## Model identity and provenance

`src/energy_failure/provenance.py` derives `energy-v3-<content-hash>` from code, raw data, configuration, ordered features, selected algorithm/threshold and environment/runtime hashes. The training artifact's `version` and `model_version`, metrics runtime metadata and `artifacts/provenance.json` use the same identity. Git commit is recorded when this directory is the repository root; an extracted archive honestly records null. Source-content hashes still capture its code.

The sidecar also records the final `model.joblib` SHA-256, and each scored row includes `model_artifact_sha256`. This distinguishes the exact serialized artifact from its reproducible training recipe. An explicit feature-schema hash preserves column ordering. Only trusted artifacts should be deserialized; hashes are integrity/lineage evidence, not permission to load an arbitrary pickle.

The Azure environment and component references now consistently use version 3. The base image is pinned by digest, verified against the official Microsoft Container Registry `Docker-Content-Digest` response; [deployment/image-lock.json](../deployment/image-lock.json) records the source and date. This verifies the image reference, not a successful Linux dependency build or vulnerability assessment. The registry exposes [published tags](https://mcr.microsoft.com/v2/azureml/openmpi4.1.0-ubuntu22.04/tags/list), while the deployment uses the immutable digest instead of the moving tag.

Local and cloud Python/NumPy versions differ as documented in [Azure integration](azure.md). Their environment hashes and model identities consequently differ. The cloud pipeline retrains and produces its own reference predictions; it does not silently reuse a local binary under a different environment.

## Advisory input quality

`input_quality.history_quality` runs on chronological cleaned history before batch export. It uses original-reading missing indicators, only current/past readings and only maintenance already recorded by that date. It adds quality columns without changing the classifier feature list, fitted model, threshold or raw alert.

| Review reason | Trigger | Interpretation |
|---|---|---|
| `cold_start_under_30_days` | Asset age below 30 days | Known commissioning limitation; send to a reliability engineer even for a low score |
| `age_unavailable` | Age omitted from a generic artifact that does not require it | Missing context requires review; the actual portfolio model still rejects a missing required age feature |
| `imputed_inputs` | At least one missing/invalid sensor channel was imputed | Inspect missingness and channel freshness |
| `recent_data_gap` | Current row follows absent calendar rows | Check telemetry delivery and intervening operating conditions |
| `stale_inputs` | An available original channel observation is over two days old | Carry-forward may hide new conditions |
| `maintenance_history_unknown` | No recorded service yet exists for the asset | Absence of records does not prove absence of work |
| `sensor_flatline_review` | Seven consecutive valid daily values of any tracked channel are exactly identical | An inspection cue; steady operation can also produce a flatline |

Combined reasons are separated by semicolons. `requires_manual_review` is independent of `alert`; no automatic service dispatch occurs. Optional quality fields that are absent are not silently treated as observed evidence. The flags cannot diagnose gradual in-range sensor bias. First-observation missingness is exposed by the imputation flag; a channel without any prior valid observation does not receive an invented staleness age. Supplied numerical fields must be finite and within their declared domains.

`risk_score` remains an exact alias of legacy `failure_probability_30d`; neither is a calibrated real-field probability. Existing score/alert fields retain their meaning. CSV consumers must accommodate the appended review and artifact-identity columns.

## Monitoring replay and response ownership

`monitoring.py` compares the latest seven days with the preceding 28 days using the same frozen model. It reports schema/key integrity, tracked assets, last-observation staleness, imputed-row share, mean score, alert share, review share, unknown-maintenance share, flatline share and a five-bin score-distribution PSI. These are investigation signals, not proof of bias, a sensor fault, or a need to retrain.

Only rows whose dates are at least 30 days before `as_of`, with a known binary label, enter precision/recall/Brier calculations. Even a prematurely supplied label is excluded until maturity. The monitor does not substitute a zero for unavailable metrics or pretend every asset-day corresponds to a unique physical failure event.

| Finding | Initial owner | Response |
|---|---|---|
| Assets stale by more than two days / no recent scores | SCADA/data engineer / ML engineer | Restore transport or batch delivery; mark unavailable condition explicitly |
| More than 10% of current rows imputed | SCADA/data engineer | Inspect missing-channel flags and sensor freshness |
| More than 20% of current rows require review | Reliability engineer | Triage commissioning and data-quality reasons |
| PSI above 0.20 or alert share shifts by more than 10 percentage points | Data scientist with reliability engineer | Inspect asset mix, sensor conditions and work demand before changing thresholds |
| Mature-label recall below 0.50 | Data scientist with reliability engineer | Audit missed opportunities and label quality; require fresh reviewed validation before retraining |

Thresholds are declared demonstration settings, not thresholds learned from operating service-level agreements. Review findings alongside maintenance cost and crew constraints. The monitor proposes neither retraining nor dispatch automatically.

The replay produces `reports/monitoring_replay.json` and `reports/monitoring_findings.csv` for three scenarios: the actual held-out batch, a controlled spike in missingness flags, and a seven-day delivery delay. The flag spike demonstrates alert routing and human-review handling; [sensor-fault tests](sensor-fault-tests.md) separately perturb physical sensor values. A hosted scheduler, alert destination, incident acknowledgement, and enterprise monitoring storage remain deployment work.

## Candidate validation, promotion and rollback

`deployment/deploy.ps1` now creates a uniquely named candidate deployment and explicitly invokes it while preserving any previous default. It verifies the downloaded artifact hash against provenance. The cloud training pipeline's `score_contract` output is the expected prediction reference; the local-model path produces its reference with the shared scorer.

`reconcile_cloud_output.py` assigns the expected column schema to Azure's headerless CSV and verifies complete unique source keys, exact identity/version/review values, and scores within a declared numerical tolerance. Reordered rows are supported. Missing rows, duplicate keys, changed asset identity, schema mismatch or score mismatch stop the release. Only after this gate succeeds does the script update the default. An intervening default change also stops promotion, and the final default is read back for confirmation. Microsoft's CLI supports [explicit deployment invocation and default updates](https://learn.microsoft.com/en-us/cli/azure/ml/batch-endpoint?view=azure-cli-latest).

Each release records `release.json`, `reconciliation.json`, downloaded evidence and the previous default under `artifacts/azure-releases/<release-id>/`. The previous deployment is retained. `rollback_arguments` records an argument array for `az` to restore it, including subscription/workspace scope; run that command only after reviewing the incident and release record. A first deployment has no previous default and says so explicitly. Serialize release jobs to avoid competing promotions; the pre-promotion read is a conflict check, not a transactional lock.

`deployment/model.yml` and the model field in `batch-deployment.yml` are explicit templates with `REPLACE_FROM_PROVENANCE`; `deploy.ps1` supplies the verified content-derived version. They must not be applied unchanged. No deployment or rollback command has been run for this portfolio. Azure CLI/Bicep compilation, package build, permissions, quota, live CSV format, job execution and post-promotion operations still need validation in an authorized workspace.
