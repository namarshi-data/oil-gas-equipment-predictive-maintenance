"""Auditable CSV -> SQLite cleaning with causal, per-asset imputation.

No pandas or machine-learning dependency is required by this stage.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path


SENSORS = (
    "vibration_mm_s", "bearing_temperature_c", "pressure_bar",
    "power_kw", "load_pct", "rpm", "runtime_hours",
)

RAW_SCHEMAS = {
    "assets": {
        "asset_id": "TEXT", "asset_type": "TEXT", "site": "TEXT",
        "commissioned_date": "TEXT", "rated_power_kw": "REAL",
    },
    "readings": {
        "ingestion_id": "INTEGER", "date": "TEXT", "asset_id": "TEXT",
        **{sensor: "REAL" for sensor in SENSORS},
    },
    "events": {
        "event_id": "TEXT", "asset_id": "TEXT", "event_date": "TEXT",
        "failure_mode": "TEXT", "emergency_cost_cad": "REAL",
        "emergency_downtime_hours": "REAL",
    },
    "maintenance": {
        "maintenance_id": "TEXT", "asset_id": "TEXT", "service_date": "TEXT",
        "maintenance_type": "TEXT",
    },
}

OPTIONAL_SCHEMAS = {
    "assets": {"latitude": "REAL", "longitude": "REAL", "synthetic_licence_id": "TEXT"},
    "events": {"incident_type": "TEXT", "cause_category": "TEXT", "synthetic_licence_id": "TEXT", "field_area": "TEXT"},
}


def _load_csv(connection: sqlite3.Connection, path: Path, name: str) -> None:
    """Keep raw CSV values; SQLite affinity recognizes ordinary numeric literals."""
    schema = {**RAW_SCHEMAS[name], **OPTIONAL_SCHEMAS.get(name, {})}
    columns = ", ".join(f'"{column}" {kind}' for column, kind in schema.items())
    connection.execute(f'CREATE TABLE raw_{name} ({columns})')
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = set(RAW_SCHEMAS[name]) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(sorted(missing))}")
        placeholders = ", ".join("?" for _ in schema)
        connection.executemany(
            f"INSERT INTO raw_{name} VALUES ({placeholders})",
            ([row.get(column) for column in schema] for row in reader),
        )


def _export_csv(connection: sqlite3.Connection, query: str, path: Path) -> None:
    cursor = connection.execute(query)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(column[0] for column in cursor.description)
        writer.writerows(cursor)


def _quality_report(connection: sqlite3.Connection) -> dict:
    def count(table: str) -> int:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    raw_rows = count("raw_readings")
    key_valid = count("readings_key_valid")
    clean_rows = count("clean_readings")
    imputed = {
        sensor: int(connection.execute(
            f"SELECT COALESCE(SUM({sensor} IS NULL), 0) FROM readings_validated"
        ).fetchone()[0])
        for sensor in SENSORS
    }
    empty_cells = {
        sensor: int(connection.execute(
            f"SELECT COALESCE(SUM({sensor} IS NULL OR TRIM(CAST({sensor} AS TEXT)) = ''), 0) "
            "FROM readings_deduplicated"
        ).fetchone()[0])
        for sensor in SENSORS
    }
    fallback_cells = {
        sensor: int(connection.execute(
            f"SELECT COUNT(*) FROM readings_validated r WHERE r.{sensor} IS NULL "
            f"AND NOT EXISTS (SELECT 1 FROM readings_validated p "
            f"WHERE p.asset_id=r.asset_id AND p.date<r.date AND p.{sensor} IS NOT NULL)"
        ).fetchone()[0])
        for sensor in SENSORS
    }
    return {
        "raw_readings": raw_rows,
        "clean_readings": clean_rows,
        "dropped_invalid_keys_or_dates": raw_rows - key_valid,
        "duplicates_removed": key_valid - clean_rows,
        "raw_assets": count("raw_assets"),
        "clean_assets": count("clean_assets"),
        "dropped_assets": count("raw_assets") - count("clean_assets"),
        "raw_events": count("raw_events"),
        "clean_events": count("clean_events"),
        "dropped_events": count("raw_events") - count("clean_events"),
        "raw_maintenance": count("raw_maintenance"),
        "clean_maintenance": count("clean_maintenance"),
        "dropped_maintenance": count("raw_maintenance") - count("clean_maintenance"),
        "unobserved_calendar_days": int(connection.execute(
            "SELECT COALESCE(SUM(missing_gap_days), 0) FROM daily_features"
        ).fetchone()[0]),
        "rows_with_imputation": int(connection.execute(
            "SELECT COUNT(*) FROM clean_readings WHERE sensor_missing_count > 0"
        ).fetchone()[0]),
        "imputed_cells": sum(imputed.values()),
        "missing_cells_by_sensor": empty_cells,
        "invalid_cells_by_sensor": {sensor: imputed[sensor] - empty_cells[sensor] for sensor in SENSORS},
        "imputed_cells_by_sensor": imputed,
        "cold_start_default_cells_by_sensor": fallback_cells,
        "imputation": "Last earlier valid observation for the same asset; fixed cold-start defaults.",
    }


def clean_data(raw_dir: Path, processed_dir: Path) -> dict:
    """Clean assets, readings, events and maintenance CSVs; return quality counts.

    Outputs are sorted CSVs, maintenance.sqlite (including audit tables), and
    cleaning_quality.json. Re-running replaces these generated outputs. A failed
    clean leaves the prior database intact, rather than a partially built file.
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    database_path = processed_dir / "maintenance.sqlite"
    pending_path = processed_dir / "maintenance.pending.sqlite"
    if pending_path.exists():
        pending_path.unlink()
    script_path = Path(__file__).resolve().parents[2] / "sql" / "01_clean.sql"
    try:
        with sqlite3.connect(pending_path) as connection:
            for name in RAW_SCHEMAS:
                _load_csv(connection, raw_dir / f"{name}.csv", name)
            connection.executescript(script_path.read_text(encoding="utf-8"))
            feature_script = script_path.with_name("02_features.sql")
            connection.executescript(feature_script.read_text(encoding="utf-8"))
            quality = _quality_report(connection)
            connection.commit()
            for name, sort in (("assets", "asset_id"), ("readings", "asset_id, date"), ("events", "event_date, asset_id, event_id"), ("maintenance", "service_date, asset_id, maintenance_id")):
                _export_csv(connection, f"SELECT * FROM clean_{name} ORDER BY {sort}", processed_dir / f"{name}.csv")
            _export_csv(connection, "SELECT * FROM daily_features ORDER BY asset_id, date", processed_dir / "daily_features.csv")
        # sqlite Connection's context manager commits but does not close it.
        connection.close()
        pending_path.replace(database_path)
        (processed_dir / "cleaning_quality.json").write_text(
            json.dumps(quality, indent=2) + "\n", encoding="utf-8",
        )
        return quality
    except Exception:
        if "connection" in locals():
            connection.close()
        if pending_path.exists():
            pending_path.unlink()
        raise
