"""Meaningful cleaning invariants: chronology, deduplication and validity."""

import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from energy_failure.cleaning import RAW_SCHEMAS, clean_data


class CleaningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.out = self.root / "processed"
        self._write("assets", [{
            "asset_id": " A1 ", "asset_type": "pump", "site": "test",
            "commissioned_date": "2020-01-01", "rated_power_kw": 200,
        }])
        self._write("events", [{
            "event_id": "E1", "asset_id": " A1 ", "event_date": "2025-01-05",
            "failure_mode": "bearing", "emergency_cost_cad": 10000,
            "emergency_downtime_hours": 24,
        }])
        self._write("maintenance", [{
            "maintenance_id": "M1", "asset_id": "A1", "service_date": "2025-01-03",
            "maintenance_type": "reactive_repair",
        }])

    def _write(self, name, rows):
        with (self.raw / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(RAW_SCHEMAS[name]))
            writer.writeheader()
            writer.writerows(rows)

    def _reading(self, day, ingestion_id, **overrides):
        row = {
            "ingestion_id": ingestion_id, "asset_id": "A1", "date": day,
            "vibration_mm_s": 3, "bearing_temperature_c": 65, "pressure_bar": 8,
            "power_kw": 100, "load_pct": 75, "rpm": 1800, "runtime_hours": 1000,
        }
        row.update(overrides)
        return row

    def _result(self):
        with (self.out / "readings.csv").open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_latest_duplicate_wins_and_invalid_values_are_flagged(self):
        self._write("readings", [
            self._reading("2025-01-01", 1, vibration_mm_s=4),
            self._reading("2025-01-02", 2, vibration_mm_s=8),
            self._reading("2025-01-02", 3, asset_id=" A1 ", vibration_mm_s=999, rpm="junk"),
        ])
        quality = clean_data(self.raw, self.out)
        second = self._result()[1]
        self.assertEqual(quality["duplicates_removed"], 1)
        self.assertEqual(second["ingestion_id"], "3")
        self.assertEqual(float(second["vibration_mm_s"]), 4)
        self.assertEqual(float(second["rpm"]), 1800)
        self.assertEqual(second["sensor_missing_count"], "2")
        self.assertEqual(quality["invalid_cells_by_sensor"]["rpm"], 1)

    def test_imputation_never_uses_future_readings_or_other_assets(self):
        self._write("assets", [
            {"asset_id": "A1", "asset_type": "pump", "site": "test", "commissioned_date": "2020-01-01", "rated_power_kw": 200},
            {"asset_id": "A2", "asset_type": "pump", "site": "test", "commissioned_date": "2020-01-01", "rated_power_kw": 200},
        ])
        self._write("readings", [
            self._reading("2024-12-31", 0, asset_id="A2", vibration_mm_s=55),
            self._reading("2025-01-03", 3, vibration_mm_s=20),
            self._reading("2025-01-01", 1, vibration_mm_s=""),
            self._reading("2025-01-02", 2, vibration_mm_s=""),
            self._reading("2025-01-04", 4, vibration_mm_s=""),
        ])
        quality = clean_data(self.raw, self.out)
        self.assertEqual([float(row["vibration_mm_s"]) for row in self._result() if row["asset_id"] == "A1"], [2, 2, 20, 20])
        self.assertEqual(quality["cold_start_default_cells_by_sensor"]["vibration_mm_s"], 2)
        self.assertEqual(quality["missing_cells_by_sensor"]["vibration_mm_s"], 3)

    def test_invalid_dates_and_unknown_assets_are_rejected(self):
        self._write("readings", [
            self._reading("2025-01-01", 1),
            self._reading("2025-02-30", 2),
            self._reading("2025-1-02", 3),
            self._reading("garbage", 4),
            self._reading("2025-01-02", 5, asset_id="UNKNOWN"),
            self._reading("2019-01-01", 6),
        ])
        quality = clean_data(self.raw, self.out)
        self.assertEqual(quality["clean_readings"], 1)
        self.assertEqual(quality["dropped_invalid_keys_or_dates"], 5)

    def test_outputs_are_auditable_and_repeatable(self):
        self._write("readings", [self._reading("2025-01-01", 1, pressure_bar=" ")])
        first = clean_data(self.raw, self.out)
        original = (self.out / "readings.csv").read_bytes()
        second = clean_data(self.raw, self.out)
        self.assertEqual(first, second)
        self.assertEqual(original, (self.out / "readings.csv").read_bytes())
        with closing(sqlite3.connect(self.out / "maintenance.sqlite")) as connection:
            self.assertEqual(connection.execute("SELECT pressure_bar FROM raw_readings").fetchone()[0], " ")
            self.assertEqual(connection.execute("SELECT asset_id FROM clean_events").fetchone()[0], "A1")
        self.assertEqual(json.loads((self.out / "cleaning_quality.json").read_text()), first)

    def test_features_use_calendar_windows_and_only_recorded_past_maintenance(self):
        self._write("readings", [
            self._reading("2025-01-01", 1, vibration_mm_s=2),
            self._reading("2025-01-02", 2, vibration_mm_s=4),
            self._reading("2025-01-10", 3, vibration_mm_s=20),
        ])
        quality = clean_data(self.raw, self.out)
        with (self.out / "daily_features.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(float(rows[1]["vibration_mm_s_mean_7d"]), 3)
        self.assertEqual(float(rows[2]["vibration_mm_s_mean_7d"]), 20)
        self.assertAlmostEqual(float(rows[2]["vibration_mm_s_mean_30d"]), 26 / 3)
        self.assertEqual(float(rows[2]["vibration_mm_s_change_per_day"]), 2)
        self.assertEqual(int(rows[2]["missing_gap_days"]), 7)
        self.assertEqual(quality["unobserved_calendar_days"], 7)
        self.assertGreater(int(rows[0]["days_since_last_recorded_maintenance"]), 365)
        self.assertEqual(int(rows[2]["days_since_last_recorded_maintenance"]), 7)

    def test_bad_runtime_is_imputed_and_outcomes_do_not_change_features(self):
        self._write("readings", [self._reading("2025-01-01", 1, runtime_hours="NaN")])
        clean_data(self.raw, self.out)
        before = (self.out / "daily_features.csv").read_bytes()
        self._write("events", [])
        clean_data(self.raw, self.out)
        self.assertEqual((self.out / "daily_features.csv").read_bytes(), before)
        row = self._result()[0]
        self.assertEqual(float(row["runtime_hours"]), 0)
        self.assertEqual(row["runtime_hours_missing"], "1")


if __name__ == "__main__":
    unittest.main()
