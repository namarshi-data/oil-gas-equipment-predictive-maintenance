"""Generate daily SCADA-like snapshots and a separate, inaccessible-to-model oracle."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .config import Config, EQUIPMENT

SENSORS = ["vibration_mm_s", "bearing_temperature_c", "pressure_bar", "power_kw", "load_pct", "rpm", "runtime_hours"]
SITES = [("Peace River", 56.23, -117.29), ("Grande Prairie", 55.17, -118.79),
         ("Red Deer", 52.27, -113.81), ("Lloydminster", 53.28, -110.01)]

def generate(raw_dir: Path, config: Config) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start, config.end)
    records, assets, events, truth, maintenance = [], [], [], [], []
    ingestion = 0
    for i in range(config.n_assets):
        asset_id = f"AB-{i+1:03d}"
        kind = list(EQUIPMENT)[i % 3]
        spec = EQUIPMENT[kind]
        site, lat, lon = SITES[i % len(SITES)]
        commissioned = dates[0] - pd.Timedelta(days=int(rng.integers(365, 3650)))
        licence = f"SYNTH-{i+1:05d}"
        assets.append(dict(asset_id=asset_id, asset_type=kind, site=site,
                           commissioned_date=commissioned.date(), rated_power_kw=spec["power"],
                           latitude=round(lat+rng.uniform(-.12,.12), 5),
                           longitude=round(lon+rng.uniform(-.12,.12), 5), synthetic_licence_id=licence))
        maintenance.append(dict(maintenance_id=f"M-{asset_id}-000", asset_id=asset_id,
                                service_date=commissioned.date(), maintenance_type="commissioning"))
        event_days = []
        day = int(rng.integers(45, 205))
        while day < len(dates) + 100:
            preventable = bool(rng.random() > .16)
            precursor = int(rng.integers(42, 76)) if preventable else 0
            mode = rng.choice(["bearing_wear", "seal_leak", "overheating"]) if preventable else "electrical_trip"
            event_days.append((day, precursor, mode))
            if day < len(dates):
                event_id = f"E-{asset_id}-{len(event_days):02d}"
                event_date = dates[0] + pd.Timedelta(days=day)
                events.append(dict(event_id=event_id, asset_id=asset_id, event_date=event_date.date(),
                                   failure_mode=mode, emergency_cost_cad=round(spec["emergency_cost"]*rng.uniform(.75,1.4),2),
                                   emergency_downtime_hours=round(spec["emergency_hours"]*rng.uniform(.6,1.5),1),
                                   incident_type="equipment_outage", cause_category="mechanical" if preventable else "electrical",
                                   synthetic_licence_id=licence, field_area=site))
                truth.append(dict(event_id=event_id, preventable=int(preventable), precursor_days=precursor,
                                  repair_success_draw=float(rng.random())))
                repaired = event_date + pd.Timedelta(days=3)
                if repaired <= dates[-1]:
                    maintenance.append(dict(maintenance_id=f"M-{asset_id}-{len(event_days):03d}", asset_id=asset_id,
                                            service_date=repaired.date(), maintenance_type="reactive_repair"))
            day += int(rng.integers(110, 241))
        bias = rng.normal(0, .20)
        runtime = (dates[0]-commissioned).days*17.5
        outage_days = set()
        for _ in range(4):
            first = int(rng.integers(0,len(dates)-5))
            outage_days.update(range(first, first+int(rng.integers(2,6))))
        # Operating transients resemble degradation but recover without failure.
        transients = [(int(rng.integers(15,len(dates)-15)), rng.uniform(.25,.85)) for _ in range(9)]
        for d, date in enumerate(dates):
            next_event = next((e for e in event_days if e[0] > d), None)
            wear = 0.
            mode = ""
            if next_event:
                ed, precursor, mode = next_event
                if precursor:
                    wear = max(0, 1-(ed-d)/precursor)**1.5
            transient = sum(amplitude*np.exp(-((d-center)/4)**2) for center, amplitude in transients)
            load = np.clip(73 + 11*np.sin(d/18+i) + rng.normal(0,7), 30, 100)
            down = any(0 <= d-e[0] < 3 for e in event_days)
            if down:
                load = 0.
            season = 9*np.sin(2*np.pi*(d-100)/365.25)
            vibration = spec["vibration"] + bias + .010*(load-70) + wear*(4.7 if mode=="bearing_wear" else 2.6) + 1.8*transient + rng.normal(0,.35)
            temp = spec["temperature"] + season + .13*(load-70) + wear*(34 if mode=="overheating" else 20) + 10*transient + rng.normal(0,2.2)
            pressure = spec["pressure"] + .016*(load-70) - wear*(3.5 if mode=="seal_leak" else 1.6) + rng.normal(0,.45) + .3*transient
            rpm = max(0,spec["rpm"]*(.85+.002*load) + spec["rpm"]*rng.normal(0,.018) - wear*spec["rpm"]*.07)
            power = max(0,spec["power"]*(load/100)*(1+wear*.18)+rng.normal(0,spec["power"]*.035))
            if down:
                rpm, power, vibration = 0., 0., max(0,rng.normal(.12,.06))
                pressure *= .30
            runtime += 0 if down else 24*load/100
            values = [max(0,vibration),temp,max(0,pressure),power,load,rpm,runtime]
            if d in outage_days:
                values = [None]*len(values)
            else:
                for j in range(len(values)):
                    if rng.random()<.004:
                        values[j] = None
                if rng.random()<.007:
                    values[int(rng.integers(0,6))] = 99999
            ingestion += 1
            row = dict(ingestion_id=ingestion,date=date.date(),asset_id=f" {asset_id} " if rng.random()<.005 else asset_id)
            row.update({sensor:round(float(value),3) if value is not None else None for sensor,value in zip(SENSORS,values)})
            records.append(row)
            if rng.random()<.006:
                ingestion += 1
                records.append({**row,"ingestion_id":ingestion})
    for name, rows in [("readings",records),("assets",assets),("events",events),("maintenance",maintenance),("simulation_truth",truth)]:
        pd.DataFrame(rows).to_csv(raw_dir/f"{name}.csv",index=False)
    manifest = dict(source="100% synthetic; no AER or operator records",seed=config.seed,assets=len(assets),
                    telemetry_start=config.start,telemetry_end=config.end,cadence="one daily snapshot per asset",
                    expected_asset_days=len(dates)*len(assets),raw_readings=len(records),failure_events=len(events),
                    currency="CAD",scenario="enriched-failure teaching sample; not Alberta failure-rate estimate")
    (raw_dir/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest
