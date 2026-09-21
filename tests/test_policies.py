"""Maintenance policies share history and account for every charged visit."""

import unittest
from dataclasses import replace

import pandas as pd

from energy_failure.config import Config, EQUIPMENT
from energy_failure.policies import replay


EVENT_COLUMNS = ["event_id", "asset_id", "event_date", "preventable", "repair_success_draw", "emergency_cost_cad", "emergency_downtime_hours"]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.assets = pd.DataFrame([{
            "asset_id": "A1", "asset_type": "pumpjack", "site": "test",
            "commissioned_date": "2025-01-01",
        }])

    def event(self, date, event_id="E1", **overrides):
        event = dict(event_id=event_id, asset_id="A1", event_date=date,
                     preventable=True, repair_success_draw=0.1,
                     emergency_cost_cad=18000, emergency_downtime_hours=72)
        event.update(overrides)
        return event

    def run_replay(self, events, scores=(), start="2025-04-01", end="2025-05-31", config=None):
        return replay(self.assets, pd.DataFrame(events, columns=EVENT_COLUMNS),
                      pd.DataFrame(scores, columns=["asset_id", "date", "risk_score"]),
                      start, end, config or self.config, threshold=0.5)

    def test_fixed_cadence_is_anchored_to_commissioning(self):
        _, _, visits, _ = self.run_replay(
            [self.event("2025-05-01")], start="2025-02-15", end="2025-08-15")
        dates = visits.loc[visits.policy.eq("fixed_90_day"), "service_date"].astype(str).tolist()
        self.assertEqual(dates, ["2025-04-01", "2025-06-30"])

    def test_actionable_window_excludes_same_day_and_includes_day_30(self):
        service = pd.Timestamp("2025-04-01")
        for offset, expected in [(0, 0), (1, 1), (30, 1), (31, 0)]:
            with self.subTest(offset=offset):
                _, outcomes, _, _ = self.run_replay([self.event(service + pd.Timedelta(days=offset))])
                fixed = outcomes[outcomes.policy.eq("fixed_90_day")].iloc[0]
                self.assertEqual(int(fixed.caught), expected)
                self.assertEqual(int(fixed.service_lead_days), offset if expected else 0)

    def test_unpreventable_failure_is_missed_even_when_visit_is_timely(self):
        _, outcomes, visits, _ = self.run_replay([self.event("2025-04-10", preventable=False)])
        fixed = outcomes[outcomes.policy.eq("fixed_90_day")].iloc[0]
        self.assertEqual(int(fixed.caught), 0)
        self.assertEqual(visits[visits.policy.eq("fixed_90_day")].iloc[0].outcome, "no_actionable_failure")

    def test_predictive_dispatch_requires_two_days_and_reports_both_lead_times(self):
        scores = [("A1", "2025-04-01", 0.8)]
        _, outcomes, visits, _ = self.run_replay([self.event("2025-04-10")], scores)
        predicted = outcomes[outcomes.policy.eq("predictive")].iloc[0]
        self.assertEqual(int(predicted.warning_days), 9)
        self.assertEqual(int(predicted.service_lead_days), 7)
        self.assertEqual(str(visits[visits.policy.eq("predictive")].iloc[0].service_date), "2025-04-03")
        for failure_date in ["2025-04-02", "2025-04-03"]:
            with self.subTest(failure_date=failure_date):
                _, outcomes, _, _ = self.run_replay([self.event(failure_date)], scores)
                self.assertEqual(int(outcomes[outcomes.policy.eq("predictive")].iloc[0].caught), 0)

    def test_cooldown_starts_at_service_and_reopens_on_day_30(self):
        scores = [("A1", day, 0.8) for day in ["2025-04-01", "2025-04-02", "2025-05-02", "2025-05-03"]]
        _, _, visits, _ = self.run_replay([self.event("2025-04-10")], scores)
        predicted = visits[visits.policy.eq("predictive")]
        self.assertEqual(predicted.alert_date.astype(str).tolist(), ["2025-04-01", "2025-05-03"])
        self.assertEqual(predicted.service_date.astype(str).tolist(), ["2025-04-03", "2025-05-05"])

    def test_failed_intervention_still_pays_planned_and_emergency_costs(self):
        summary, outcomes, visits, _ = self.run_replay(
            [self.event("2025-04-10", repair_success_draw=0.95)], [("A1", "2025-04-01", 0.8)])
        cost = EQUIPMENT["pumpjack"]
        predicted = summary.set_index("policy").loc["predictive"]
        self.assertEqual(int(predicted.caught_failures), 0)
        self.assertEqual(int(predicted.unsuccessful_services), 1)
        self.assertEqual(predicted.planned_service_cost_cad, cost["planned_cost"])
        self.assertEqual(predicted.emergency_repair_cost_cad, 18000)
        self.assertEqual(predicted.total_downtime_hours, cost["planned_hours"] + 72)
        self.assertEqual(predicted.total_cost_cad,
                         cost["planned_cost"] + 18000 + (cost["planned_hours"] + 72) * cost["downtime_cost"])

    def test_same_event_is_never_caught_twice_but_every_visit_is_charged(self):
        config = replace(self.config, service_cooldown_days=0)
        scores = [("A1", "2025-04-01", 0.8), ("A1", "2025-04-03", 0.8)]
        summary, outcomes, visits, _ = self.run_replay([self.event("2025-04-10")], scores, config=config)
        predicted = summary.set_index("policy").loc["predictive"]
        self.assertEqual(int(predicted.caught_failures), 1)
        self.assertEqual(int(predicted.service_visits), 2)
        self.assertEqual(int(predicted.unnecessary_services), 1)
        self.assertEqual(predicted.planned_service_cost_cad, 2 * EQUIPMENT["pumpjack"]["planned_cost"])
        self.assertEqual(visits[visits.policy.eq("predictive")].outcome.tolist(), ["prevented_failure", "no_actionable_failure"])

    def test_end_window_does_not_charge_service_that_cannot_be_dispatched(self):
        summary, _, visits, _ = self.run_replay(
            [self.event("2025-04-10")], [("A1", "2025-05-30", 0.8)])
        self.assertTrue(visits[visits.policy.eq("predictive")].empty)
        self.assertEqual(int(summary.set_index("policy").loc["predictive", "service_visits"]), 0)

    def test_zero_event_window_retains_service_costs(self):
        summary, outcomes, visits, _ = self.run_replay([], [("A1", "2025-04-01", 0.8)])
        self.assertTrue(outcomes.empty)
        predicted = summary.set_index("policy").loc["predictive"]
        self.assertEqual(int(predicted.event_count), 0)
        self.assertEqual(int(predicted.service_visits), 1)
        self.assertGreater(predicted.total_cost_cad, 0)
        self.assertEqual(float(predicted.mean_warning_days), 0)

    def test_existing_fixed_schedule_carries_pre_window_benefits(self):
        summary, outcomes, visits, _ = self.run_replay(
            [self.event("2025-04-20")], start="2025-04-10", end="2025-05-01")
        fixed = summary.set_index("policy").loc["fixed_90_day"]
        self.assertEqual(int(fixed.caught_failures), 1)
        self.assertEqual(int(fixed.service_visits), 0)
        self.assertEqual(int(fixed.carry_in_visits), 1)
        self.assertEqual(fixed.planned_service_cost_cad, 0)
        visit = visits[visits.policy.eq("fixed_90_day")].iloc[0]
        self.assertEqual(str(visit.service_date), "2025-04-01")
        self.assertEqual(int(visit.in_evaluation_window), 0)


if __name__ == "__main__":
    unittest.main()
