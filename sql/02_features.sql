-- Calendar-aware, causal daily features. Windows include the current day's
-- observation and only earlier observations, so scores are end-of-day scores.
-- A date gap does not become an artificial sequence of fabricated observations.
CREATE VIEW daily_features AS
WITH lagged AS (
    SELECT r.*,
           JULIANDAY(date) - JULIANDAY(LAG(date) OVER history) AS elapsed_days,
           LAG(vibration_mm_s) OVER history AS previous_vibration_mm_s,
           LAG(bearing_temperature_c) OVER history AS previous_bearing_temperature_c,
           LAG(pressure_bar) OVER history AS previous_pressure_bar,
           LAG(power_kw) OVER history AS previous_power_kw,
           LAG(load_pct) OVER history AS previous_load_pct,
           LAG(rpm) OVER history AS previous_rpm,
           LAG(runtime_hours) OVER history AS previous_runtime_hours
    FROM clean_readings r
    WINDOW history AS (PARTITION BY asset_id ORDER BY date)
)
SELECT r.ingestion_id, r.date, r.asset_id, r.vibration_mm_s, r.bearing_temperature_c, r.pressure_bar, r.power_kw, r.load_pct, r.rpm, r.runtime_hours, r.vibration_mm_s_missing, r.bearing_temperature_c_missing, r.pressure_bar_missing, r.power_kw_missing, r.load_pct_missing, r.rpm_missing, r.runtime_hours_missing, r.sensor_missing_count,
       a.asset_type, a.site, a.commissioned_date, a.rated_power_kw,
       a.latitude, a.longitude, a.synthetic_licence_id,
       AVG(r.vibration_mm_s) OVER week AS vibration_mm_s_mean_7d,
       AVG(r.vibration_mm_s) OVER month AS vibration_mm_s_mean_30d,
       COALESCE((r.vibration_mm_s - r.previous_vibration_mm_s) / r.elapsed_days, 0.0) AS vibration_mm_s_change_per_day,
       AVG(r.bearing_temperature_c) OVER week AS bearing_temperature_c_mean_7d,
       AVG(r.bearing_temperature_c) OVER month AS bearing_temperature_c_mean_30d,
       COALESCE((r.bearing_temperature_c - r.previous_bearing_temperature_c) / r.elapsed_days, 0.0) AS bearing_temperature_c_change_per_day,
       AVG(r.pressure_bar) OVER week AS pressure_bar_mean_7d,
       AVG(r.pressure_bar) OVER month AS pressure_bar_mean_30d,
       COALESCE((r.pressure_bar - r.previous_pressure_bar) / r.elapsed_days, 0.0) AS pressure_bar_change_per_day,
       AVG(r.power_kw) OVER week AS power_kw_mean_7d,
       AVG(r.power_kw) OVER month AS power_kw_mean_30d,
       COALESCE((r.power_kw - r.previous_power_kw) / r.elapsed_days, 0.0) AS power_kw_change_per_day,
       AVG(r.load_pct) OVER week AS load_pct_mean_7d,
       AVG(r.load_pct) OVER month AS load_pct_mean_30d,
       COALESCE((r.load_pct - r.previous_load_pct) / r.elapsed_days, 0.0) AS load_pct_change_per_day,
       AVG(r.rpm) OVER week AS rpm_mean_7d,
       AVG(r.rpm) OVER month AS rpm_mean_30d,
       COALESCE((r.rpm - r.previous_rpm) / r.elapsed_days, 0.0) AS rpm_change_per_day,
       AVG(r.runtime_hours) OVER week AS runtime_hours_mean_7d,
       AVG(r.runtime_hours) OVER month AS runtime_hours_mean_30d,
       COALESCE((r.runtime_hours - r.previous_runtime_hours) / r.elapsed_days, 0.0) AS runtime_hours_change_per_day,
       CAST(MAX(COALESCE(r.elapsed_days, 1) - 1, 0) AS INTEGER) AS missing_gap_days,
       AVG(r.sensor_missing_count) OVER week AS sensor_missing_count_mean_7d,
       CAST(JULIANDAY(r.date) - JULIANDAY(COALESCE(
           (SELECT MAX(m.service_date) FROM clean_maintenance m
            WHERE m.asset_id=r.asset_id AND m.service_date<=r.date),
           a.commissioned_date)) AS INTEGER) AS days_since_last_recorded_maintenance
FROM lagged r JOIN clean_assets a ON a.asset_id=r.asset_id
WINDOW week AS (PARTITION BY r.asset_id ORDER BY JULIANDAY(r.date) RANGE BETWEEN 6 PRECEDING AND CURRENT ROW),
       month AS (PARTITION BY r.asset_id ORDER BY JULIANDAY(r.date) RANGE BETWEEN 29 PRECEDING AND CURRENT ROW);

-- A communication outage represented by a row has all seven raw channels absent.
-- A calendar gap is an entirely absent row; distinguish these from partial loss.
CREATE VIEW quality_gaps AS
SELECT asset_id, date, missing_gap_days, sensor_missing_count,
       CASE WHEN sensor_missing_count=7 THEN 1 ELSE 0 END AS all_channels_imputed
FROM daily_features
WHERE missing_gap_days > 0 OR sensor_missing_count > 0;

