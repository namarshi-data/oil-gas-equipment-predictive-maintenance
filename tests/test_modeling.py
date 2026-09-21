"""Temporal label and feature contracts, independent of model fit quality."""

import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from energy_failure.config import Config
from energy_failure.modeling import SENSOR_FEATURES, prepare_features


class ModelingTests(unittest.TestCase):
    def frame(self, rows):
        output = []
        for aid, date in rows:
            row = dict(asset_id=aid, date=date, asset_type="pumpjack", commissioned_date="2020-01-01",
                       rated_power_kw=45, sensor_missing_count=0, sensor_missing_count_mean_7d=0,
                       missing_gap_days=0, days_since_last_recorded_maintenance=100)
            for sensor in SENSOR_FEATURES:
                row.update({sensor: 1, f"{sensor}_mean_7d": 1,
                            f"{sensor}_mean_30d": 1, f"{sensor}_change_per_day": 0})
            output.append(row)
        return pd.DataFrame(output)

    def events(self, rows):
        return pd.DataFrame(rows, columns=["asset_id", "event_date"])

    def test_target_includes_next_30_days_but_excludes_current_date(self):
        frame = self.frame([("day0", "2025-01-01"), ("day1", "2025-01-01"),
                            ("day30", "2025-01-01"), ("day31", "2025-01-01")])
        events = self.events([("day0", "2025-01-01"), ("day1", "2025-01-02"),
                              ("day30", "2025-01-31"), ("day31", "2025-02-01")])
        result, _ = prepare_features(frame, events, Config())
        self.assertEqual(result.target_failure_30d.tolist(), [0, 1, 1, 0])
        self.assertTrue(np.isnan(result.iloc[0].days_to_failure))
        self.assertEqual(result.days_to_failure.iloc[1:].tolist(), [1, 30, 31])

    def test_current_failure_is_skipped_when_a_later_failure_exists(self):
        result, _ = prepare_features(
            self.frame([("A1", "2025-01-01")]),
            self.events([("A1", "2025-01-01"), ("A1", "2025-01-20")]), Config())
        self.assertEqual(int(result.iloc[0].target_failure_30d), 1)
        self.assertEqual(int(result.iloc[0].days_to_failure), 19)

    def test_last_30_days_are_censored_even_with_an_observed_early_failure(self):
        config = replace(Config(), end="2025-06-30")
        result, _ = prepare_features(
            self.frame([("A1", "2025-05-31"), ("A1", "2025-06-01"), ("A1", "2025-06-30")]),
            self.events([("A1", "2025-06-02")]), config)
        self.assertEqual(int(result.iloc[0].target_failure_30d), 1)
        self.assertTrue(result.target_failure_30d.iloc[1:].isna().all())

    def test_failure_labels_do_not_cross_assets(self):
        result, _ = prepare_features(
            self.frame([("A1", "2025-01-01"), ("A2", "2025-01-01")]),
            self.events([("A1", "2025-01-10")]), Config())
        self.assertEqual(result.target_failure_30d.tolist(), [1, 0])

    def test_feature_allowlist_excludes_outcomes_oracle_and_identifiers(self):
        frame = self.frame([("A1", "2025-01-01")])
        forbidden = ["target_failure_30d", "days_to_failure", "event_date", "preventable",
                     "repair_success_draw", "emergency_cost_cad", "emergency_downtime_hours", "event_id"]
        for column in forbidden:
            frame[column] = 999
        result, features = prepare_features(frame, self.events([("A1", "2025-01-10")]), Config())
        self.assertTrue(set(forbidden + ["asset_id", "date"]).isdisjoint(features))
        self.assertEqual(len(features), len(set(features)))
        self.assertEqual(len(features), 38)
        self.assertEqual(int(result.iloc[0].target_failure_30d), 1)
        self.assertEqual(int(result.iloc[0].days_to_failure), 9)

    def test_changing_future_outcomes_does_not_change_predictor_values(self):
        frame = self.frame([("A1", "2025-01-01"), ("A1", "2025-01-02")])
        a, features = prepare_features(frame, self.events([("A1", "2025-01-10")]), Config())
        b, other_features = prepare_features(frame, self.events([("A1", "2025-05-10")]), Config())
        self.assertEqual(features, other_features)
        pd.testing.assert_frame_equal(a[features], b[features])
        self.assertNotEqual(a.target_failure_30d.tolist(), b.target_failure_30d.tolist())


if __name__ == "__main__":
    unittest.main()
