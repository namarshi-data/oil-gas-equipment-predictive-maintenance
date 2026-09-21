# Capacity and full-program economics

The extension asks a practical follow-up: **what can the same maintenance team
actually service this week?** It retains the original unconstrained benchmark
and evaluates eight additional scenarios, rather than replacing the headline
with the most favorable result.

## Planning without future knowledge

[`operations.py`](../src/energy_failure/operations.py) accepts equipment metadata,
known service calendars and the current day's raw risk scores. It cannot access
failure dates, future labels, realized repair costs or the simulator's oracle.

Each alternative policy receives the same limit of **3, 5, 10 or 1,000 planned
visits per ISO service week**, with predictive dispatch after **2 or 7 days**.
Fixed-calendar visits wait in due-date order when capacity is full. Predictive
appointments are booked using the current day's score multiplied by the
equipment type's assumed emergency repair and downtime consequence. Earlier
bookings are not displaced by future scores. An asset denied capacity is
reconsidered only if a later observed score still meets the threshold.

This is a transparent greedy ranking heuristic. The raw score is uncalibrated;
the priority index is **not expected monetary benefit**. It is not a route or
workforce optimizer. The locally generated `reports/operations_visits.csv` records
every booking, due date, service date and priority input.

## Measured capacity tradeoff

Two-day dispatch; same 44 event opportunities in each scenario:

| Weekly planned-visit capacity | Fixed caught / 44 | Predictive caught / 44 | Fixed unplanned hours | Predictive unplanned hours |
|---|---:|---:|---:|---:|
| 3 | 7 | 30 | 3,354.2 | 1,098.4 |
| 5 | 7 | 37 | 3,248.5 | 469.0 |
| 10 | 12 | 37 | 2,675.3 | 469.0 |
| 1,000, effectively unconstrained | 13 | 37 | 2,607.1 | 469.0 |

The unconstrained two-day scenario reconciles to the published policy costs,
visit counts, catches and downtime. Every booked week is checked against its
limit. Under tight capacity the fixed calendar also performs worse, so a larger
relative saving does not necessarily mean that predictive service improved.
See [all eight policy scenarios](../reports/operations_policies.csv), including
slower dispatch, and the [machine-readable audit](../reports/operations.json).

## Add the costs of operating the program

[`program_economics`](../src/energy_failure/operations.py) separates:

- Annual operating savings: fixed-policy annual cost minus predictive annual cost.
- Annual net program savings: operating savings minus incremental program costs.
- First-year net savings: annual net program savings minus one-time implementation.
- Payback: implementation cost divided by positive monthly net program savings;
  undefined when net savings are nonpositive.

The illustrative scenario adds **C$150,000/year incremental analytics/reliability
program staffing**, **C$12,000/year cloud**, **C$30,000/year support**, and
**C$75,000 one-time implementation**. These are authored sensitivity inputs, not
salary estimates, vendor quotes or incurred expenses. Program staffing is
separate from maintenance labor already represented by per-visit service costs.

For the unconstrained two-day reference, the C$13.42M annual operating saving
becomes **C$13.23M annual net program saving** and **C$13.15M first-year saving**
under these inputs. These remain enriched synthetic estimates. Extremely short
scenario paybacks are not evidence of a commercially realistic payback period.
The original C$4.93M avoided-emergency-repair component must not be added again.

The [24-row economics grid](../reports/operations_economics.csv) also varies
downtime rates by 0.5×, 1× and 1.5×. This grid is separate from the original
[actionability/intervention-success sensitivity](../reports/sensitivity.csv),
whose adverse scenario reverses the business case. Do not treat this grid as
a joint uncertainty distribution or a guarantee of positive ROI.

## Operational boundaries and assumptions

Capacity counts visits, not hours, travel, skills, parts or site access. Emergency
repairs do not consume the planned-visit slots. The fixed queue starts empty 30
days before the replay to include carry-in appointments; older backlog is not
modeled. Predictive booking starts at the test boundary. These different initial
states follow the original comparison and do not represent a steady-state
resource plan. Deferred predictive counts are qualifying **asset-days**, not
unique delayed work orders. Asset age, sensor quality and human approval would
also need to gate a real work-order system.

Future telemetry and failures are not regenerated after a simulated prevention.
Annualization uses 365.25/91 for the same fleet, with no claim about a full year's
seasonality or field causality.

## Reproduce

```powershell
python -m energy_failure.operations --root .
python -m pytest tests/test_operations.py tests/test_policies.py -q
```

Tests cover equal weekly capacity, future-score isolation, zero-capacity behavior,
cost-window validation and correct program-cost subtraction.
