# Data dictionary and cleaning contract

Every reading and failure in this project is **synthetic**. The failure event table
contains the untreated equipment history used for retrospective policy simulation;
it is not an observation of what happens after an intervention.

The raw input files below are generated locally by the pipeline. The public repository includes curated dashboard facts; see the [data publication policy](../data/README.md).

## Inputs

`data/raw/assets.csv` has one intended record per asset.

| Field | Meaning |
| --- | --- |
| `asset_id` | Equipment identifier, trimmed before matching |
| `asset_type` | Simulated equipment class |
| `site` | Simulated facility |
| `commissioned_date` | ISO calendar date; readings before this are rejected |
| `rated_power_kw` | Positive equipment rating in kilowatts |
| `latitude`, `longitude` | Optional synthetic asset coordinates; bounds −90…90 / −180…180 |
| `synthetic_licence_id` | Optional fabricated licence-style identifier, never an actual facility licence |

`data/raw/readings.csv` has one intended record per asset per calendar day, plus
deliberately injected duplicate records and sensor quality problems.

| Field | Unit / acceptable range | Cold-start default |
| --- | --- | --- |
| `ingestion_id` | Source arrival sequence; higher ID wins a duplicate | - |
| `date` | ISO `YYYY-MM-DD` calendar date | - |
| `asset_id` | Must match a cleaned asset | - |
| `vibration_mm_s` | mm/s; 0-60 | 2.0 |
| `bearing_temperature_c` | °C; −30-180 | 65.0 |
| `pressure_bar` | bar; 0-40 | 7.0 |
| `power_kw` | kW; 0-10,000 | 100.0 |
| `load_pct` | %; 0-110 | 70.0 |
| `rpm` | revolutions/minute; 0-6,000 | 1,800.0 |
| `runtime_hours` | cumulative operating hours; 0-1,000,000 | 0.0 |

Bounds and defaults are explicit demonstration assumptions, not universal sensor
limits or equipment operating recommendations. Defaults are fixed in advance;
they are not calculated from train, validation or test observations.

`data/raw/events.csv` is an outcome table used for labels and policy evaluation.

| Field | Meaning |
| --- | --- |
| `event_id` | Unique synthetic failure identifier |
| `asset_id` | Equipment that would fail without intervention |
| `event_date` | Failure date in the untreated simulated history |
| `failure_mode` | Synthetic failure category |
| `emergency_cost_cad` | Assumed emergency repair cost; nonnegative CAD |
| `emergency_downtime_hours` | Assumed unplanned outage duration; nonnegative hours |
| `incident_type`, `cause_category` | Optional simulated incident classification |
| `synthetic_licence_id`, `field_area` | Optional fabricated regulatory-style context |

These names are inspired by SCADA telemetry and Alberta incident reporting
concepts. They are not a representation of an exact AER schema or public AER data.

`data/raw/maintenance.csv` records historical work: `maintenance_id`, `asset_id`,
`service_date` and `maintenance_type`. All identifiers are trimmed, dates are
validated and the last source row wins a duplicated maintenance ID. Dates before
commissioning and unknown assets are rejected. This table records the equipment
history (such as commissioning and reactive repairs); it is separate from the
downstream simulated maintenance policies.

## SQL processing and outputs

`src/energy_failure/cleaning.py` imports raw CSVs into SQLite and runs
`sql/01_clean.sql` followed by `sql/02_features.sql`. Numeric-affinity columns preserve invalid strings as text so
SQL can reject them instead of accidentally casting them to zero. The processing
order is:

1. Trim identifiers and validate asset metadata; keep the last raw asset record.
2. Reject unknown assets, malformed/impossible dates and readings predating commissioning.
3. Retain the reading with the largest ingestion ID for each asset and date; CSV
   row order breaks ties. A missing value in the winning record stays missing.
4. Convert empty, nonnumeric and out-of-range sensor values to SQL `NULL`.
5. Fill each missing cell using that asset's **last earlier valid original
   reading** of the same sensor. If none exists, use the fixed default above.
6. Independently validate outcome records and retain the last record per event ID.
7. Clean historical maintenance records and derive calendar-aware sensor features.

No sensor imputation query joins failure events, accesses generator truth, looks
at a later date, or computes a statistic across the full time series. Carry-forward
may become stale over a long data gap; this demonstration does not model a
production freshness timeout. Missingness flags let downstream consumers identify
the imputed readings. Generated data use daily measurements.

Outputs are `data/processed/assets.csv`, `readings.csv`, `events.csv`,
`maintenance.csv`, `daily_features.csv`, `maintenance.sqlite`, and
`cleaning_quality.json`. The database retains the raw,
key-validated, deduplicated, value-validated and final tables for inspection. Final
readings add the following columns:

| Field | Meaning |
| --- | --- |
| `<sensor>_missing` | 1 if that original winning sensor value was missing/invalid and imputed; otherwise 0 |
| `sensor_missing_count` | Sum of the seven sensor flags; 0-7 |

## Daily SQL features

`daily_features.csv` and the SQLite `daily_features` view contain every cleaned
reading field, all cleaned asset metadata, and the features below. SQL uses
calendar-date `RANGE` windows, so seven days does not accidentally mean seven
observations when records are absent. Means include the **current day** and
earlier days only, establishing an end-of-day scoring convention. Rates use the
elapsed number of calendar days between observations.

| Feature | Definition |
| --- | --- |
| `<sensor>_mean_7d` | Mean of cleaned readings over the current day and previous six days |
| `<sensor>_mean_30d` | Mean over the current day and previous 29 days |
| `<sensor>_change_per_day` | Current minus preceding reading, divided by elapsed days; first reading is 0 |
| `missing_gap_days` | Entirely absent calendar days between this row and its preceding asset row; first row is 0 |
| `sensor_missing_count_mean_7d` | Calendar-aware trailing mean of the missingness count |
| `days_since_last_recorded_maintenance` | Days since latest service on or before reading date; commissioning date fallback |

The `<sensor>` features exist for all seven sensors, including runtime. The
`quality_gaps` view exposes rows with an absent calendar interval or at least one
imputed sensor. Its `all_channels_imputed` flag identifies readings where all
seven channels were unavailable; this distinguishes a represented communications
outage from an entirely absent record. A maintenance entry on the current date is
available by end of day; consumers predicting before that day's activities must
shift this feature or use a strict prior-day maintenance cutoff.

The quality report distinguishes dropped keys/dates, removed duplicates, empty
cells, invalid nonempty cells, imputed cells and cold-start defaults. Sensor-cell
counts apply **after deduplication**. Dropped assets and events include both invalid
records and duplicates; their total counts are not a diagnosis of one error type.

The SQL can be inspected directly in the exported database, for example:

```sql
SELECT asset_id, date, sensor_missing_count
FROM clean_readings
WHERE sensor_missing_count > 0
ORDER BY asset_id, date;
```
