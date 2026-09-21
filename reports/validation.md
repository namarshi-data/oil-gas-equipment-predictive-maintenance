# Validation Record

Local checks only. Desktop refresh, DAX interactions, actual-viewer Service RLS, live Azure deployment, live LLM evaluation and GitHub-hosted CI remain separate acceptance work, called out explicitly below and wherever a claim depends on them.

## Local verification

The regression suite passed **206 tests plus 6 subtests**. The [test results](test-results.json) record the execution command and scope. Provenance checks reconcile the published source/environment hashes and model artifact; independent dashboard checks compare 3,144 calculations across 12 scenarios.

Component records below describe their own recorded runs. A passing regression suite does not imply that every study was rerun, the model was retrained, or an external service was exercised.

## Evidence by component

| Check | Executed result | Evidence |
|---|---|---|
| Seeded seven-stage pipeline | 80 assets, 43,760 cleaned daily rows, 236 historical events; two models, three policy ledgers | [Metrics](../artifacts/metrics.json) |
| Full regression suite | **206 passed + 6 subtests** | [Test results](test-results.json) |
| Independent-fleet study | Seeds 101/202/303, separate 60-asset fit, calibration seed 77; reference scores reproduced | [Study](generalization.json) |
| Conditional uncertainty | 2,000 whole-asset bootstrap replicates with paired policy costs | [Ranges](uncertainty_intervals.csv) |
| Resource/economic scenarios | Eight capacity/dispatch cases and 24 economics rows; weekly limits and original unconstrained reconciliation pass | [Operations audit](operations.json) |
| Local batch scoring | 7,280 rows reconciled with unique complete identities, score/metadata agreement and 432 quality advisories | [Adapter result](../artifacts/azure-local-smoke/validation.json) |
| Published provenance | Recorded source/environment hashes, model artifact and mirrored model metadata match; raw training inputs are intentionally omitted from the public package | [Manifest](../artifacts/provenance.json), [regression guard](../tests/test_reference_provenance.py) |
| Monitoring replay | 0 baseline breaches, 2 controlled quality findings and 2 delivery-delay findings; 4,880 mature labels | [Monitoring](monitoring_replay.json) |
| Assistant evaluations | **41/41** local cases; numerical grounding, authorized citations, unsupported questions and access/injection cases | [Evaluation](assistant-evaluation.json) |
| Assistant regression tests | 83 cases within the full suite, including HTTP trust boundaries and optional-planner mocks | [Test source](../tests/test_assistant.py) |
| Notebook | All six code cells executed without cell errors | [Notebook result](notebook-validation.json) |
| Power BI source | TOM 19.114.8 parsed 16 tables, 75 measures, 11 relationships and one role; 123 official-schema documents, 101 visual bindings | [Parser](../powerbi/model_validation.json), [schema result](../powerbi/validation.json) |
| Power BI geometry | Nine total pages, six visible; 101 visuals, six mobile elements; zero static geometry/text-capacity errors | [Layout check](powerbi-layout-check.json) |
| Power BI reference accounting | Atomic-ledger cost reconciliation, parameter arithmetic, site/date exposure and deny-by-default identity cases | [Reference result](../powerbi/data_validation.json) |
| Offline dashboard calculations | 12 scenarios / 3,144 JavaScript-versus-Python assertions | [Calculation check](dashboard_validation.json) |
| Browser presentation | Four reviewer tabs fit 1280 × 720; mobile tour has no horizontal overflow; assistant policy answer, unsupported July request and cross-site refusal inspected | [Browser review](browser-review.json) |
| Deployment definitions | YAML and PowerShell syntax checked; official Microsoft base-image digest resolved; candidate-before-promotion gate tested locally | [Engineering scope](../docs/mlops.md), [image lock](../deployment/image-lock.json) |

The [robustness](../docs/robustness.md) and [sensor-fault](../docs/sensor-fault-tests.md) experiments document prediction failures under controlled challenges. The commissioning and quality advisories do not repair model recall or establish equipment safety.

The four headline values reconcile to the original event/service ledgers: 19-day median warning among 37 prevented events; 82.0107% less unplanned downtime versus fixed service; C$4,931,919.90/year gross avoided emergency repairs versus reactive; C$13,420,251.47/year operating savings versus fixed service. These are annualized synthetic estimates, extrapolated from a 91-day replay on a deliberately failure-enriched sample, not realized savings. Incremental program costs are explored separately in [operations](../docs/operations.md).

The model identifies itself as `energy-v3-a4bbde11ebed7e1afce7`. The [provenance manifest](../artifacts/provenance.json) records the exact artifact SHA-256 and its inputs. A new source/environment change requires regeneration; the content ID is not a marketing release number.

## Not executed

Eight supplied native Power BI screenshots document visible rendering of six main pages, Asset Detail and Asset Context. They do not independently verify refresh, every DAX/M interaction, mobile rendering, Key Influencers or published Viewer-account RLS. TOM/schema/layout/reference checks also cannot establish those outcomes. Sensor Associations has no supplied image. Asset Detail and Asset Context show aggregate context, and some native charts retain internal scrollbars from before the [source formatting corrections](../docs/powerbi-report-refinement.md). The separate 41 browser images document the HTML companions only. See [native evidence](../screenshots/powerbi-native/README.md) and the [image validation](screenshot-validation.json).

Live Azure deployment, GitHub-hosted workflow execution and live LLM evaluation are not part of the recorded validation. The container base-image digest was verified, but the Linux environment was not built. Local model/adapter tests and mocked API responses are not substitutes for those checks.

The desktop reviewer tour fits its tested viewport without scrolling. Its mobile HTML layout intentionally flows vertically. This does not claim a native Power BI phone rendering test or universal layout behavior at every viewport.

[Reproduction guide](../START_HERE.md)
