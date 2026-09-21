# Natural-language analytics and site security

The report uses explicit business measures and a Key Influencers visual for exploration. Its Fleet Risk page answers a defined business question with a standard chart; it has no active natural-language question box or deployed Copilot integration. This document separates the source-controlled implementation from environment-specific work that must be verified in Power BI Desktop and the Service.

## What is delivered and what still needs runtime evidence

| Capability | Repository implementation | Required evidence before claiming it works in deployment |
|---|---|---|
| Dynamic site security | `Dim_UserSite`, the `Site Manager` role and dimension-to-fact relationships | Refresh; Desktop identity tests; actual Service Viewer tests; role membership review |
| Fleet breakdown analysis | Standard bar chart of `Missed Events` by site, with an explicit predictive-policy filter | Desktop refresh/render; total of seven at full default scope; site/asset/date filtering and actual Viewer security |
| Legacy Q&A vocabulary | Retained linguistic metadata and `Breakdowns` alias only; Q&A visual removed | Reference material, not an active question-answering feature |
| Key Influencers | Target and sensor bindings in the dedicated analysis view opened from Model Performance | Confirm categorical target behavior, blank-label exclusion, usable sample and rendered output |
| Copilot / general chat | Architecture and acceptance plan only | Appropriate tenant/capacity/region configuration, access, semantic preparation and an evaluated pilot |
| Scheduled cloud refresh | Deployment guidance only | Accessible source, credentials/gateway where applicable, schedule and recorded refresh history |

The user's Desktop notice says **December 2026**, matching Microsoft's en-SG consumer guidance. As checked on **17 September 2026**, Microsoft's en-US limitations and tooling pages instead say **February 2027**. These Microsoft surfaces disagree; the project does not infer an extension date or claim the displayed notice is wrong. Both announce retirement, so the report now works without Q&A. No expiry date is embedded in the report canvas. [Microsoft consumer notice](https://learn.microsoft.com/en-sg/power-bi/explore-reports/end-user-q-and-a), [Microsoft en-US limitations](https://learn.microsoft.com/en-us/power-bi/natural-language/q-and-a-limitations)

The retirement dialog is a feature notice, not evidence that project files or data were deleted. Its **Remove Q&A visuals** action edits the report; dismissing the notice does not perform that removal. The checked-in replacement already removes the Q&A dependency while preserving the Fleet Risk chart's layout slot and mobile references.

## Security architecture

`Dim_UserSite` maps a normalized user principal name to one or more sites. The [Site Manager role](../powerbi/EnergyPredictiveMaintenance.SemanticModel/definition/roles/Site%20Manager.tmdl) restricts the mapping to the current `USERPRINCIPALNAME()`, then tests membership for `Dim_Site` and `Dim_Asset`. Both dimensions have single-direction relationships to `Fact_Readings`, `Fact_Events` and `Fact_ServiceVisits`. Filtering the asset dimension also prevents unauthorized asset names from appearing in slicers. There is no broad fallback for an unmapped identity and no bidirectional security bridge required by this design.

The static site assignment is suitable for this fixed synthetic fleet. In a real implementation, decide whether permissions apply to the current site, historical site at observation time, or both. A moving asset requires a deliberate effective-dated model and authorization policy; changing its current-site label must not accidentally reassign its history.

The checked-in [sample mapping](../data/processed/dashboard/dim_user_site.csv) demonstrates authorization logic; it does not create real Microsoft Entra users or assign Service role membership. For Desktop simulation, `peace.manager@portfolio.example` has Peace River; `multi.manager@portfolio.example` has Peace River and Grande Prairie; `fleet.reviewer@portfolio.example` has all four sites. Use `unknown@portfolio.example` for the negative case. These addresses are fixtures, not sign-in accounts. Replace examples with a governed source during deployment. Normalize identifiers in that source and test aliases, guests and actual tenant UPN formats rather than assuming email text always matches the sign-in identifier.

Consumers should receive Viewer/app access and the intended semantic-model role. Admin, Member and Contributor workspace roles are outside the normal RLS consumer boundary. Test a real consuming identity; testing as the report author is insufficient. [Microsoft workspace roles](https://learn.microsoft.com/en-us/power-bi/collaborate-share/service-roles-new-workspaces)

## Security acceptance matrix

Run the same assertions against all three facts, not only an executive card. A Python reconciliation is a useful independent expected result; it is not a Power BI authorization test.

For the checked-in dataset, these are independent CSV-derived expected raw row counts with **no additional date or policy filters**. Event rows include all three alternative policies; all-visit rows include carry-in visits. They are not the report's default predictive-scope measures. Compare them with simple `COUNTROWS` queries under the role when the model engine is available.

| Synthetic UPN | Assets | Reading rows | Event-policy rows | All visit rows | In-period visit rows |
|---|---:|---:|---:|---:|---:|
| `peace.manager@portfolio.example` | 20 | 1,820 | 30 | 34 | 29 |
| `multi.manager@portfolio.example` | 40 | 3,640 | 48 | 74 | 62 |
| `fleet.reviewer@portfolio.example` | 80 | 7,280 | 132 | 157 | 132 |
| `unknown@portfolio.example` | 0 | 0 | 0 | 0 | 0 |

| Case | Expected scope | Checks |
|---|---|---|
| One mapped site | Only the mapped site | Site/asset slicers, readings count, event outcomes, visits, costs and asset details match that site's ledger subset |
| Several mapped sites | Union of exactly the mapped sites | All facts and visible asset labels agree; no duplicates introduced by multiple mapping rows |
| Unmapped identity | No authorized assets or facts | No fallback to fleet totals; no site/asset labels leaked from protected dimensions |
| Case-normalized UPN | Same authorization as its canonical mapping | Confirm actual tenant sign-in behavior and normalization |
| Explicit unauthorized-site request | No unauthorized data | Direct page navigation, drillthrough, tooltip and the predictive missed-failure chart cannot broaden scope |
| Different policy or cost scenario | Same authorized sites | Reactive baseline and parameter controls change analytical context only |
| Export or downstream consumption, if permitted | Same row restrictions for the consuming identity | Inspect exported rows and a downstream query; separately review export/Build permissions |
| Extra role or elevated workspace access | Review expanded privileges | Avoid accidentally combining a broad role with `Site Manager`; test privileged users separately |

RLS roles can combine permissively: adding another role is not a reliable way to impose a stricter intersection. The unknown-user case should deny access. A hidden table/page is not a security control. [Microsoft RLS design guidance](https://learn.microsoft.com/en-us/power-bi/guidance/rls-guidance)

**Any future chat rollout requires actual-user tests.** Microsoft's “Test as role” feature does not validate Q&A or Copilot end to end. If Copilot is introduced, use separate signed-in Viewer sessions and check both generated answers and exposed names/suggestions. Record the effective identity, report/model version, authorized sites, question, expected result and actual result. A normal visual passing a simulated role test does not establish chat security. [Microsoft RLS validation limitations](https://learn.microsoft.com/en-us/fabric/security/service-admin-row-level-security)

## Business vocabulary and retained legacy metadata

Each business term needs an unambiguous measure. Naming a Boolean field “breakdown” does not mean “count only rows where caught is false.” The `Breakdowns` alias resolves to `Missed Events`, which supplies that predicate and the policy scope; retained legacy synonyms refer to the measure. The active Fleet chart binds `Missed Events` directly and explicitly selects predictive maintenance. Retained linguistic metadata does not enable Copilot and is not evidence of natural-language answer quality.

| Term | Intended object / definition | Guardrail |
|---|---|---|
| breakdown, breakdowns, missed failure | `Breakdowns`: event outcomes with `caught = 0` for the selected policy | Unfiltered default is predictive; explicit multiple-policy totals are blank; name the policy in important questions |
| caught failure, prevented failure | Caught event count | One event per policy; never sum all alternative policies as if they occurred together |
| asset, equipment | `Dim_Asset` | Use asset ID for reliable disambiguation |
| site, location | `Dim_Site` | RLS determines which locations are visible |
| latest risk, current risk | `Latest Risk Score` | Latest in selected date scope; not maximum historical score or a calibrated probability |
| warning days | `Mean Warning Days` | Caught-event mean; distinguish from the README median and zero-day misses |
| annual cost | `Annualized Cost` | CAD scenario estimate, scoped period and assets |
| false alarm | `False Alarm Rate` | Unnecessary charged visits divided by charged visits; not classifier FPR |

Inspect [KPI_Measures.tmdl](../powerbi/EnergyPredictiveMaintenance.SemanticModel/definition/tables/KPI_Measures.tmdl) for the implemented measures and [en-US.tmdl](../powerbi/EnergyPredictiveMaintenance.SemanticModel/definition/cultures/en-US.tmdl) for legacy vocabulary. For a future chat pilot, prefer explicit phrases such as “breakdowns by site for predictive” over ambiguous requests such as “show failures.” Do not expose fact foreign keys, redundant date columns or the authorization mapping as suggested analytical vocabulary.

Field parameters drive the Policy Comparison chart axes. Key Influencers and the Fleet missed-failure chart bind actual columns; drillthrough and tooltip links also use actual model columns. AI visuals do not support field parameters. [Microsoft field-parameter limitations](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-field-parameters)

## Business questions and deterministic acceptance results

Use the unfiltered, full-fleet default dataset first: **1 April–30 June 2025**, asset-specific base downtime rates. These are acceptance targets calculated from the CSV ledgers. Demonstrate them with the report's charts, measures and slicers; they are also candidate prompts for a future evaluated Copilot pilot. No current chat engine is claimed to return them. Then repeat with authorized site subsets and explicit dates.

| Business question / interaction | Expected meaning or result |
|---|---|
| “Breakdowns for predictive” | 7 missed event outcomes |
| “Breakdowns for reactive” | 44 missed event outcomes |
| “Breakdowns for fixed 90 day” | 31 missed event outcomes on Policy Comparison |
| “Breakdowns by site for predictive” | Fleet Risk chart's per-site missed counts sum to 7 at full-fleet scope; its fixed predictive filter is independent of any other page's policy selection |
| “Catch rate by policy” | Reactive 0/44; fixed 13/44; predictive 37/44 |
| “False alarm rate for predictive” | 10 unnecessary visits / 51 charged visits, about 19.6% |
| “Mean warning days for predictive” | Equal to the explicit caught-event mean measure; not assumed to be the 19-day median |
| “Annualized cost by policy” | Matches the ordinary policy cost table under identical rate, date and identity scope |
| Select one asset and inspect its latest risk | Matches the last observation in that selected date interval |
| Try an unauthorized site as a site-only Viewer | No unauthorized numerical result or asset details |
| “Why did this pump physically fail?” | The report cannot establish physical causation; use sensor/event evidence and engineering investigation |
| “What will production revenue be next year?” | Unsupported: revenue forecasts, prices and production volumes are not modeled |

For a future chat pilot, inspect recognized fields, policy/date scope and generated queries when an answer is wrong; refine semantic preparation and retest. A synonym alone cannot substitute for a reviewed measure definition. Record only questions that consistently match explicit measures as verified examples. For the current demo, use the normal report measures and the predictive missed-failure chart.

## Key Influencers setup and interpretation

Open **Model Performance → Explore sensor drivers** for the dedicated analysis view. Use its Back action to return. The main model page keeps its summary charts readable.

The **Analyze** target is `Fact_Readings[target_failure_30d]`, interpreted categorically (failure in the next 30 days: 1 versus 0). The explanatory fields are sensor values such as vibration, bearing temperature, pressure, RPM, runtime, power and load. Unknown labels must be excluded; the default scoring export's labeled cohort is April–May 2025. Inspect the target's aggregation/category configuration in the running visual before demonstrating it. [Microsoft Key Influencers tutorial](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-influencers)

Keep future outcomes, event dates, days-to-failure, policy catch results, model alerts and model scores out of the explanatory inputs. These would either leak the answer or explain the predictor with its own output. Sensor units differ by equipment type, so repeat the exploration within pumpjacks, compressors or pipeline pumps. Repeated daily rows from the same machine are correlated, and the generator intentionally encodes degradation patterns. The visual is exploratory association in synthetic data, not independent causal evidence or the trained model's feature attribution. A small filtered cohort can legitimately produce no useful influencer result.

## A supported generative-AI extension

Copilot is **not deployed or tested** in this project. As reviewed on 17 September 2026, Microsoft requires paid **Fabric F2 or higher** or **Power BI Premium P1 or higher** capacity, enabled admin settings, a supported region and appropriate access. A Pro/PPU license alone or a trial capacity is insufficient. Desktop also requires write access to an eligible workspace; a local PBIP file does not provide Copilot. Check the chosen experience's exact requirements and regional processing settings before a pilot. [Microsoft Copilot requirements](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-introduction)

For a future pilot:

1. Publish a reviewed semantic model to a controlled development workspace and verify refresh and actual-user RLS first.
2. Define a small business vocabulary, meaningful measure descriptions, currency/period metadata and explicit handling of unknown labels.
3. Prepare tested questions for breakdowns, policy cost, visit waste and latest-risk triage. Where supported, configure verified answers for stable business questions and review their limitations. [Microsoft verified-answer preparation](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-verified-answers)
4. Evaluate ordinary questions, ambiguous questions, unauthorized-site requests and unsupported causal/revenue questions using actual consuming identities. Specify policy, dates and cost assumptions in the question; do not assume every natural-language experience inherits every page slicer.
5. Require results to identify their measure, scope and observation freshness. Compare numerical results to deterministic visuals and preserve the source calculation.
6. Record answer correctness, unsupported claims, scope failures and response latency. Release only the tested use cases, with an engineer retaining maintenance decisions.

A custom chat extension would likewise need authenticated, authorized access through the semantic model or a secured service that applies equivalent rules. Feeding unrestricted CSVs to a chat model and asking it to “respect the user's site” is not RLS. No new chatbot, endpoint, tenant change or paid-capacity resource is created by this repository.
