"""Paired asset-cluster uncertainty, conditional on one fixed synthetic benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def cluster_totals(scored: pd.DataFrame, threshold: float) -> pd.DataFrame:
    required = ["asset_id", "target_failure_30d", "risk_score"]
    if scored[required].isna().any().any() or not scored.target_failure_30d.isin([0, 1]).all():
        raise ValueError("Provide only complete binary-labeled observations")
    if not np.isfinite(scored.risk_score).all() or not scored.risk_score.between(0, 1).all():
        raise ValueError("Scores must be finite and between zero and one")
    y, p = scored.target_failure_30d.to_numpy(), scored.risk_score.to_numpy()
    alert = p >= threshold
    rows = pd.DataFrame(dict(asset_id=scored.asset_id, n=1,
        tp=((y == 1) & alert).astype(int), fp=((y == 0) & alert).astype(int),
        fn=((y == 1) & ~alert).astype(int), tn=((y == 0) & ~alert).astype(int),
        squared_error=(p - y) ** 2))
    return rows.groupby("asset_id", sort=True).sum()


def _ratio(numerator, denominator):
    return np.divide(numerator, denominator, out=np.full(np.shape(numerator), np.nan, dtype=float), where=denominator != 0)


def _interval(point: float, samples: np.ndarray) -> dict:
    valid = samples[np.isfinite(samples)]
    return dict(point=float(point) if np.isfinite(point) else None,
        lower_95=float(np.quantile(valid, .025)) if len(valid) else None,
        upper_95=float(np.quantile(valid, .975)) if len(valid) else None,
        valid_replicates=len(valid))


def bootstrap_classification(scored: pd.DataFrame, threshold: float, replicates=2000, seed=20260918) -> dict:
    totals = cluster_totals(scored, threshold)
    if not len(totals) or replicates < 1:
        raise ValueError("At least one asset and one replicate are required")
    values = totals[["n", "tp", "fp", "fn", "tn", "squared_error"]].to_numpy(dtype=float)
    index = np.random.default_rng(seed).integers(0, len(values), size=(replicates, len(values)))
    draws = values[index].sum(axis=1)
    point = values.sum(axis=0, keepdims=True)
    metrics = {
        "precision": lambda v: _ratio(v[:, 1], v[:, 1] + v[:, 2]),
        "recall": lambda v: _ratio(v[:, 1], v[:, 1] + v[:, 3]),
        "false_positive_rate": lambda v: _ratio(v[:, 2], v[:, 2] + v[:, 4]),
        "brier_score": lambda v: _ratio(v[:, 5], v[:, 0]),
    }
    return dict(assets=len(values), rows=len(scored), replicates=replicates, rng_seed=seed,
        metrics={name: _interval(function(point)[0], function(draws)) for name, function in metrics.items()})


def bootstrap_paired_policy_cost(detail: pd.DataFrame, annualization_factor: float,
                                replicates=2000, seed=20260918) -> dict:
    selected = detail[detail.policy.isin(["fixed_90_day", "predictive"])]
    if selected.duplicated(["asset_id", "policy"]).any():
        raise ValueError("Each asset-policy pair must have exactly one cost row")
    paired = selected.pivot(index="asset_id", columns="policy", values="total_cost_cad")
    if set(paired.columns) != {"fixed_90_day", "predictive"} or paired.isna().any().any() or paired.empty:
        raise ValueError("Both policy costs are required for every asset")
    differences = (paired.fixed_90_day - paired.predictive).to_numpy(dtype=float)
    if not np.isfinite(differences).all() or not np.isfinite(annualization_factor) or annualization_factor <= 0:
        raise ValueError("Costs and annualization must be finite and valid")
    indexes = np.random.default_rng(seed).integers(0, len(differences), size=(replicates, len(differences)))
    sums = differences[indexes].sum(axis=1)
    point = differences.sum()
    return dict(assets=len(differences), replicates=replicates, rng_seed=seed,
        window_cost_difference_cad=_interval(point, sums),
        annualized_cost_difference_cad=_interval(point * annualization_factor, sums * annualization_factor),
        fraction_resampled_fleets_with_positive_difference=float(np.mean(sums > 0)),
        interpretation="Conditional paired synthetic fleet resampling; fraction positive is not a forecast probability of real-world ROI.")


def run(root: Path) -> dict:
    protocol_path = root / "docs/generalization-protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    settings = protocol["bootstrap"]
    metrics = json.loads((root / "artifacts/metrics.json").read_text(encoding="utf-8"))
    scores = pd.read_csv(root / "data/processed/dashboard/scored_readings.csv")
    labeled = scores[scores.target_failure_30d.notna()].copy()
    result = dict(protocol_sha256=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        scope="Fixed seed42 model, threshold and replay; complete assets resampled with replacement; no refitting.",
        classification=bootstrap_classification(labeled, metrics["threshold"], settings["replicates"], settings["rng_seed"]),
        policy_cost=bootstrap_paired_policy_cost(pd.read_csv(root / "data/processed/dashboard/policy_asset_detail.csv"),
            metrics["annualization_factor"], settings["replicates"], settings["rng_seed"]),
        limitations=["Same-generator synthetic sampling variability only; not a field confidence interval.",
            "No model-fitting, generator, parameter-cost, intervention-success or temporal-regime uncertainty is resampled.",
            "Shared site shocks or correlated assets can invalidate asset independence; only four fictional sites exist.",
            "Annualization extrapolates a 91-day scenario; it does not create a year of observed evidence."])
    (root / "reports/uncertainty.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    rows = [dict(measure=name, **interval) for name, interval in result["classification"]["metrics"].items()]
    rows += [dict(measure=name, **result["policy_cost"][name]) for name in ("window_cost_difference_cad", "annualized_cost_difference_cad")]
    pd.DataFrame(rows).to_csv(root / "reports/uncertainty_intervals.csv", index=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
