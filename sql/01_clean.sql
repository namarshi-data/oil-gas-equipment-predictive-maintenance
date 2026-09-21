-- SQLite 3.28+ for the full cleaning/features workflow (RANGE offsets in 02_features.sql).
-- Run by energy_failure.cleaning.clean_data.
-- Raw sensor columns have REAL affinity: valid numeric CSV strings become numeric,
-- while malformed strings stay TEXT and fail the type checks below.
-- Dates are ISO calendar dates. '+0 days' normalizes impossible dates for comparison.

CREATE TABLE clean_assets AS
WITH normalized AS (
    SELECT rowid AS source_row,
           TRIM(asset_id) AS asset_id, TRIM(asset_type) AS asset_type,
           TRIM(site) AS site, TRIM(commissioned_date) AS commissioned_date,
           rated_power_kw, latitude, longitude, TRIM(synthetic_licence_id) AS synthetic_licence_id
    FROM raw_assets
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY asset_id ORDER BY source_row DESC) AS rn
    FROM normalized
)
SELECT asset_id, asset_type, site, commissioned_date, CAST(rated_power_kw AS REAL) AS rated_power_kw,
       CASE WHEN TYPEOF(latitude) IN ('integer','real') AND latitude BETWEEN -90 AND 90 THEN latitude END AS latitude,
       CASE WHEN TYPEOF(longitude) IN ('integer','real') AND longitude BETWEEN -180 AND 180 THEN longitude END AS longitude,
       synthetic_licence_id
FROM ranked
WHERE rn = 1 AND asset_id <> '' AND asset_type <> '' AND site <> ''
  AND LENGTH(commissioned_date) = 10
  AND commissioned_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  AND DATE(commissioned_date, '+0 days') = commissioned_date
  AND TYPEOF(rated_power_kw) IN ('integer', 'real')
  AND rated_power_kw > 0 AND rated_power_kw < 100000;
CREATE UNIQUE INDEX clean_assets_key ON clean_assets(asset_id);

-- Normalize identifiers before deduplication; the last ingestion wins even when
-- its measurement is missing. Earlier valid days are available for imputation.
CREATE TABLE readings_key_valid AS
SELECT r.rowid AS source_row, r.ingestion_id, TRIM(r.date) AS date,
       TRIM(r.asset_id) AS asset_id, r.vibration_mm_s,
       r.bearing_temperature_c, r.pressure_bar, r.power_kw, r.load_pct, r.rpm, r.runtime_hours
FROM raw_readings r
JOIN clean_assets a ON a.asset_id = TRIM(r.asset_id)
WHERE LENGTH(TRIM(r.date)) = 10
  AND TRIM(r.date) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  AND DATE(TRIM(r.date), '+0 days') = TRIM(r.date)
  AND TRIM(r.date) >= a.commissioned_date;

CREATE TABLE readings_deduplicated AS
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY asset_id, date
        ORDER BY CAST(ingestion_id AS INTEGER) DESC, source_row DESC
    ) AS rn
    FROM readings_key_valid
)
SELECT ingestion_id, date, asset_id, vibration_mm_s, bearing_temperature_c,
       pressure_bar, power_kw, load_pct, rpm, runtime_hours
FROM ranked WHERE rn = 1;

-- Null denotes unavailable or physically invalid data. The original value remains
-- in the raw and deduplicated tables for audit. Bounds are engineering assumptions.
CREATE TABLE readings_validated AS
SELECT ingestion_id, date, asset_id,
    CASE WHEN TYPEOF(vibration_mm_s) IN ('integer','real') AND vibration_mm_s BETWEEN 0 AND 60
         THEN CAST(vibration_mm_s AS REAL) END AS vibration_mm_s,
    CASE WHEN TYPEOF(bearing_temperature_c) IN ('integer','real') AND bearing_temperature_c BETWEEN -30 AND 180
         THEN CAST(bearing_temperature_c AS REAL) END AS bearing_temperature_c,
    CASE WHEN TYPEOF(pressure_bar) IN ('integer','real') AND pressure_bar BETWEEN 0 AND 40
         THEN CAST(pressure_bar AS REAL) END AS pressure_bar,
    CASE WHEN TYPEOF(power_kw) IN ('integer','real') AND power_kw BETWEEN 0 AND 10000
         THEN CAST(power_kw AS REAL) END AS power_kw,
    CASE WHEN TYPEOF(load_pct) IN ('integer','real') AND load_pct BETWEEN 0 AND 110
         THEN CAST(load_pct AS REAL) END AS load_pct,
    CASE WHEN TYPEOF(rpm) IN ('integer','real') AND rpm BETWEEN 0 AND 6000
         THEN CAST(rpm AS REAL) END AS rpm,
    CASE WHEN TYPEOF(runtime_hours) IN ('integer','real') AND runtime_hours BETWEEN 0 AND 1000000
         THEN CAST(runtime_hours AS REAL) END AS runtime_hours
FROM readings_deduplicated;
CREATE UNIQUE INDEX readings_validated_key ON readings_validated(asset_id,date);

-- Causal last-observation carry-forward from VALID ORIGINAL readings only.
-- No backward fill, population statistic, maintenance outcome or failure date is
-- used. Cold-start values are fixed before simulation and documented separately.
CREATE TABLE clean_readings AS
SELECT r.ingestion_id, r.date, r.asset_id,
    COALESCE(r.vibration_mm_s, (SELECT p.vibration_mm_s FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.vibration_mm_s IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 2.0) AS vibration_mm_s,
    COALESCE(r.bearing_temperature_c, (SELECT p.bearing_temperature_c FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.bearing_temperature_c IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 65.0) AS bearing_temperature_c,
    COALESCE(r.pressure_bar, (SELECT p.pressure_bar FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.pressure_bar IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 7.0) AS pressure_bar,
    COALESCE(r.power_kw, (SELECT p.power_kw FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.power_kw IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 100.0) AS power_kw,
    COALESCE(r.load_pct, (SELECT p.load_pct FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.load_pct IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 70.0) AS load_pct,
    COALESCE(r.rpm, (SELECT p.rpm FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.rpm IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 1800.0) AS rpm,
    COALESCE(r.runtime_hours, (SELECT p.runtime_hours FROM readings_validated p
        WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.runtime_hours IS NOT NULL
        ORDER BY p.date DESC LIMIT 1), 0.0) AS runtime_hours,
    (r.vibration_mm_s IS NULL) AS vibration_mm_s_missing,
    (r.bearing_temperature_c IS NULL) AS bearing_temperature_c_missing,
    (r.pressure_bar IS NULL) AS pressure_bar_missing,
    (r.power_kw IS NULL) AS power_kw_missing,
    (r.load_pct IS NULL) AS load_pct_missing,
    (r.rpm IS NULL) AS rpm_missing,
    (r.runtime_hours IS NULL) AS runtime_hours_missing,
    ((r.vibration_mm_s IS NULL) + (r.bearing_temperature_c IS NULL)
     + (r.pressure_bar IS NULL) + (r.power_kw IS NULL)
     + (r.load_pct IS NULL) + (r.rpm IS NULL) + (r.runtime_hours IS NULL)) AS sensor_missing_count
FROM readings_validated r;
CREATE UNIQUE INDEX clean_readings_key ON clean_readings(asset_id,date);

-- Outcomes are cleaned independently, never joined to measurement imputation.
CREATE TABLE clean_events AS
WITH normalized AS (
    SELECT rowid AS source_row, TRIM(event_id) AS event_id,
           TRIM(asset_id) AS asset_id, TRIM(event_date) AS event_date,
           TRIM(failure_mode) AS failure_mode, emergency_cost_cad,
           emergency_downtime_hours, TRIM(incident_type) AS incident_type,
           TRIM(cause_category) AS cause_category,
           TRIM(synthetic_licence_id) AS synthetic_licence_id, TRIM(field_area) AS field_area
    FROM raw_events
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY source_row DESC) AS rn
    FROM normalized
)
SELECT r.event_id, r.asset_id, r.event_date, r.failure_mode,
       CAST(r.emergency_cost_cad AS REAL) AS emergency_cost_cad,
       CAST(r.emergency_downtime_hours AS REAL) AS emergency_downtime_hours,
       r.incident_type, r.cause_category, r.synthetic_licence_id, r.field_area
FROM ranked r JOIN clean_assets a ON a.asset_id = r.asset_id
WHERE r.rn = 1 AND r.event_id <> '' AND r.failure_mode <> ''
  AND LENGTH(r.event_date) = 10
  AND r.event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  AND DATE(r.event_date, '+0 days') = r.event_date
  AND r.event_date >= a.commissioned_date
  AND TYPEOF(r.emergency_cost_cad) IN ('integer','real')
  AND r.emergency_cost_cad >= 0 AND r.emergency_cost_cad < 1e12
  AND TYPEOF(r.emergency_downtime_hours) IN ('integer','real')
  AND r.emergency_downtime_hours >= 0 AND r.emergency_downtime_hours < 1e6;
CREATE UNIQUE INDEX clean_events_key ON clean_events(event_id);

-- Historical recorded work is input evidence, independent of the simulated
-- reactive, 90-day and predictive policy schedules generated downstream.
CREATE TABLE clean_maintenance AS
WITH normalized AS (
    SELECT rowid AS source_row, TRIM(maintenance_id) AS maintenance_id,
           TRIM(asset_id) AS asset_id, TRIM(service_date) AS service_date,
           TRIM(maintenance_type) AS maintenance_type
    FROM raw_maintenance
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY maintenance_id ORDER BY source_row DESC) AS rn
    FROM normalized
)
SELECT m.maintenance_id, m.asset_id, m.service_date, m.maintenance_type
FROM ranked m JOIN clean_assets a ON a.asset_id = m.asset_id
WHERE m.rn = 1 AND m.maintenance_id <> '' AND m.maintenance_type <> ''
  AND LENGTH(m.service_date) = 10
  AND m.service_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  AND DATE(m.service_date, '+0 days') = m.service_date
  AND m.service_date >= a.commissioned_date;
CREATE UNIQUE INDEX clean_maintenance_key ON clean_maintenance(maintenance_id);
CREATE INDEX clean_maintenance_asset_date ON clean_maintenance(asset_id,service_date);
