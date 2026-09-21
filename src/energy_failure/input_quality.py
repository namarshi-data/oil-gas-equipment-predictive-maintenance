"""Explicit advisory quality evidence; flags do not change classifier decisions."""
from __future__ import annotations
import numpy as np
import pandas as pd

SENSORS = ("vibration_mm_s", "bearing_temperature_c", "pressure_bar", "rpm", "power_kw", "load_pct", "runtime_hours")


def numeric(frame, name, maximum=None):
    values = frame[name]
    if (not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values)
            or pd.api.types.is_complex_dtype(values)):
        raise ValueError(f"{name} must contain finite nonnegative numeric values")
    array = values.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(array).all() or (array < 0).any() or (maximum is not None and (array > maximum).any()):
        raise ValueError(f"{name} must contain finite nonnegative numeric values within its declared range")
    return array


def review_flags(frame: pd.DataFrame) -> pd.DataFrame:
    reasons = [[] for _ in range(len(frame))]
    def add(mask, reason):
        for i in np.flatnonzero(mask):
            reasons[i].append(reason)
    if "age_days" in frame:
        add(numeric(frame, "age_days") < 30, "cold_start_under_30_days")
    else:
        add(np.ones(len(frame), dtype=bool), "age_unavailable")
    for name, maximum, label in (("sensor_missing_count", 7, "imputed_inputs"),
                                  ("missing_gap_days", None, "recent_data_gap"),
                                  ("telemetry_staleness_days", None, "stale_inputs")):
        if name in frame:
            values = numeric(frame, name, maximum)
            add(values > (2 if name == "telemetry_staleness_days" else 0), label)
    for name, label, trigger in (("maintenance_history_known", "maintenance_history_unknown", 0),
                                  ("sensor_flatline", "sensor_flatline_review", 1)):
        if name in frame:
            values = frame[name]
            if not values.isin([0, 1, False, True]).all():
                raise ValueError(f"{name} must be a complete binary flag")
            add(values.to_numpy() == trigger, label)
    return pd.DataFrame({"requires_manual_review": [bool(r) for r in reasons],
                         "review_reason": [";".join(r) for r in reasons]})


def history_quality(frame: pd.DataFrame, maintenance: pd.DataFrame) -> pd.DataFrame:
    """Add causal flags using original-reading missing indicators and prior dates.

    Flatline means seven exact identical, valid, consecutive daily readings; it
    is an inspection cue, not a diagnosis. Missing/imputed channels cannot qualify.
    """
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    if result[["asset_id", "date"]].duplicated().any():
        raise ValueError("History requires unique asset/date rows")
    result["sensor_flatline"] = False
    result["telemetry_staleness_days"] = 0.0
    result["maintenance_history_known"] = False
    work = maintenance.copy()
    work["service_date"] = pd.to_datetime(work["service_date"])
    for asset, group in result.groupby("asset_id", sort=False):
        group = group.sort_values("date")
        consecutive = group.date.diff(6).dt.days.eq(6)
        flag = pd.Series(False, index=group.index)
        staleness = pd.Series(0.0, index=group.index)
        for sensor in SENSORS:
            missing = sensor + "_missing"
            if sensor not in group or missing not in group:
                continue
            original = group[sensor].where(group[missing].eq(0))
            window = original.rolling(7, min_periods=7)
            # Runtime may legitimately stay constant when idle; all flags are advisory.
            flag |= consecutive & window.max().eq(window.min()) & window.count().eq(7)
            last_valid = group.date.where(original.notna()).ffill()
            elapsed = (group.date-last_valid).dt.days.fillna(0)
            staleness = pd.concat([staleness, elapsed], axis=1).max(axis=1)
        service_dates = work.loc[work.asset_id.eq(asset), "service_date"]
        if len(service_dates):
            result.loc[group.index, "maintenance_history_known"] = group.date.ge(service_dates.min()).to_numpy()
        result.loc[group.index, "sensor_flatline"] = flag.to_numpy()
        result.loc[group.index, "telemetry_staleness_days"] = staleness.to_numpy()
    return result
