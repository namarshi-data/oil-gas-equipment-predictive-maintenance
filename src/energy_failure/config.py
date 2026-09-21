"""Declared assumptions, fixed before evaluating the held-out period."""
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class Config:
    seed: int = 42
    n_assets: int = 80
    start: str = "2024-01-01"
    end: str = "2025-06-30"
    train_start: str = "2024-01-31"
    train_end: str = "2024-10-31"
    validation_start: str = "2024-12-01"
    validation_end: str = "2025-02-28"
    test_start: str = "2025-04-01"
    test_end: str = "2025-06-30"
    horizon_days: int = 30
    fixed_interval_days: int = 90
    actionable_days: int = 30
    dispatch_delay_days: int = 2
    service_cooldown_days: int = 30
    intervention_success: float = 0.90

    def to_dict(self):
        return asdict(self)

# Illustrative CAD costs; these are scenario inputs, not operator estimates.
EQUIPMENT = {
    "pumpjack": dict(vibration=2.4, temperature=51, pressure=7, rpm=14, power=45,
                     planned_cost=1600, planned_hours=4, downtime_cost=650,
                     emergency_cost=18000, emergency_hours=72),
    "compressor": dict(vibration=3.1, temperature=70, pressure=17, rpm=1200, power=550,
                       planned_cost=4000, planned_hours=8, downtime_cost=1400,
                       emergency_cost=48000, emergency_hours=96),
    "pipeline_pump": dict(vibration=2.0, temperature=58, pressure=12, rpm=1750, power=280,
                          planned_cost=2400, planned_hours=6, downtime_cost=950,
                          emergency_cost=30000, emergency_hours=84),
}
