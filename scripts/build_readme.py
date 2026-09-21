"""Refresh evidence blocks without replacing the authored project narrative.

Run after the pipeline: python scripts/build_readme.py
Check without writing: python scripts/build_readme.py --check

Only the three PORTFOLIO_* regions are generated. Missing, duplicated, nested or
reversed markers are an error, never a reason to replace the whole README.
Source data, model weights and Power BI definitions are not changed.
"""
from pathlib import Path
import argparse
import json
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGIONS = ("PORTFOLIO_HEADLINE", "PORTFOLIO_MODELS", "PORTFOLIO_POLICIES")
POLICIES = (("reactive", "Reactive", "#64748B"),
            ("fixed_90_day", "Fixed 90-day", "#B7791F"),
            ("predictive", "Predictive", "#087F8C"))
MODELS = (("logistic_regression", "Logistic regression"),
          ("hist_gradient_boosting", "**Gradient boosting**"))
CHART_PATH = Path("reports/figures/failure_warning_summary.png")
CHART_DATA_PATH = Path("reports/readme_chart_data.csv")


def validate_regions(text):
    """Return content spans only after validating every marker together."""
    spans = {}
    expected = {f"<!-- {name}:{edge} -->"
                for name in REGIONS for edge in ("START", "END")}
    found = re.findall(r"<!--\s*PORTFOLIO_[^<>]*?-->", text)
    if len(found) != len(expected) or set(found) != expected:
        raise ValueError("README requires exactly one START/END pair for each "
                         "PORTFOLIO_HEADLINE, PORTFOLIO_MODELS and PORTFOLIO_POLICIES region.")
    full_spans = []
    for name in REGIONS:
        start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f"Missing or duplicated README markers: {name}")
        content_start = text.index(start) + len(start)
        content_end = text.index(end)
        if content_start >= content_end:
            raise ValueError(f"Reversed or malformed README markers: {name}")
        spans[name] = (content_start, content_end)
        full_spans.append((text.index(start), content_end + len(end)))
    ordered = sorted(full_spans)
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("README generated regions must not overlap or nest.")
    return spans


def update_regions(text, sections):
    """Preserve all authored bytes outside the generated content spans."""
    spans = validate_regions(text)
    if set(sections) != set(REGIONS):
        raise ValueError("Generated sections do not match the three README regions.")
    # Work backwards so earlier offsets stay valid. Retain the document's line
    # ending convention while leaving all surrounding text completely untouched.
    newline = "\r\n" if "\r\n" in text else "\n"
    for name, (start, end) in sorted(spans.items(), key=lambda item: item[1][0], reverse=True):
        body = sections[name].strip("\r\n").replace("\r\n", "\n").replace("\n", newline)
        text = text[:start] + newline + body + newline + text[end:]
    return text


def load_evidence(root):
    metrics = json.loads((root / "artifacts/metrics.json").read_text(encoding="utf-8"))
    table = pd.DataFrame(metrics["policies"]).set_index("policy")
    models = pd.read_csv(root / "reports/test_models.csv").set_index("algorithm")
    events = pd.read_csv(root / "data/processed/dashboard/event_outcomes.csv")
    for policy, _, _ in POLICIES:
        subset = events[events.policy.eq(policy)]
        row = table.loc[policy]
        if (len(subset) != row.event_count or int(subset.caught.sum()) != row.caught_failures
                or int(subset.caught.eq(0).sum()) != row.missed_failures):
            raise ValueError(f"Policy headline does not reconcile to event outcomes: {policy}")
    pred, fixed, reactive = (table.loc[name] for name in ("predictive", "fixed_90_day", "reactive"))
    caught = events.loc[events.policy.eq("predictive") & events.caught.eq(1), "warning_days"]
    derived = {
        "median_warning_days": float(caught.median()),
        "unplanned_downtime_reduction_pct": 100 * (1 - pred.unplanned_downtime_hours / fixed.unplanned_downtime_hours),
        "annualized_net_savings_cad": fixed.annualized_cost_cad - pred.annualized_cost_cad,
        "annualized_emergency_repair_savings_cad": (reactive.emergency_repair_cost_cad - pred.emergency_repair_cost_cad) / pred.evaluation_years,
    }
    for name, value in derived.items():
        if not np.isclose(metrics["headline"][name], value, rtol=1e-9, atol=1e-6):
            raise ValueError(f"Headline does not reconcile to recorded results: {name}")
    for record in metrics["test_models"]:
        for name in ("threshold", "average_precision", "precision", "recall", "brier_score", "rows"):
            if not np.isclose(models.loc[record["algorithm"], name], record[name]):
                raise ValueError(f"Model CSV and metrics disagree: {record['algorithm']} / {name}")
    return metrics, table, models, events


def render_sections(metrics, table, models):
    head = metrics["headline"]
    pred = table.loc["predictive"]
    headline = f"""# Predictive Maintenance for Oil & Gas Operations

A reproducible maintenance decision workflow that classifies **next-30-day equipment failure** from **daily synthetic SCADA-style telemetry**, then compares predictive service with reactive repairs and fixed 90-day servicing.

*Synthetic Alberta-inspired scenario · {metrics['data']['assets']} assets · 18 months of history · {round(pred.evaluation_years * 365.25)}-day held-out replay · CAD estimates*

**Simulation results, not field-validated savings.** Annual costs extrapolate a deliberately failure-rich replay of the same fleet. Gross avoided repairs are already included in operating savings; incremental program costs are considered separately.

- **C${head['annualized_net_savings_cad'] / 1e6:.2f}M/year modeled operating savings vs. current fixed-interval maintenance.**
- **{head['unplanned_downtime_reduction_pct']:.1f}% less unplanned downtime vs. current fixed-interval maintenance** (90-day servicing).
- **{head['median_warning_days']:g}-day median warning vs. current reactive maintenance's 0 days**, among {int(pred.caught_failures)} of {int(pred.event_count)} failures caught in simulation.
- **C${head['annualized_emergency_repair_savings_cad'] / 1e6:.2f}M/year modeled emergency-repair avoidance vs. current reactive maintenance** (an included cost component).

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white) ![SQL](https://img.shields.io/badge/SQL-003B57?logo=sqlite&logoColor=white) ![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?logo=scikitlearn&logoColor=white) ![Azure ML templates](https://img.shields.io/badge/Azure_ML-templates-0078D4) ![Power BI](https://img.shields.io/badge/Power_BI-PBIP-F2C811)

<img src="reports/figures/failure_warning_summary.png" width="860" alt="Failure warning distribution for reactive, fixed 90-day and predictive maintenance on the same synthetic history; missed events are retained in the first band.">
"""
    model_rows = "\n".join(
        f"| {label} | {models.loc[name].threshold:.2f} | {models.loc[name].average_precision:.3f} | {models.loc[name].precision:.1%} | {models.loc[name].recall:.1%} | {models.loc[name].brier_score:.3f} |"
        for name, label in MODELS)
    policy_rows = "\n".join(
        f"| {label} | {int(table.loc[name].caught_failures)} / {int(table.loc[name].missed_failures)} | {int(table.loc[name].service_visits)} | {table.loc[name].unplanned_downtime_hours:,.1f} | {table.loc[name].total_downtime_hours:,.1f} | C${table.loc[name].total_cost_cad:,.0f} |"
        for name, label, _ in POLICIES)
    return {
        "PORTFOLIO_HEADLINE": headline,
        "PORTFOLIO_MODELS": "| Model | Selected threshold | Average precision | Precision | Recall | Brier score |\n|---|---:|---:|---:|---:|---:|\n" + model_rows,
        "PORTFOLIO_POLICIES": "| Policy | Prevented / missed failures | Planned visits in period | Unplanned hours | Total downtime hours | Total period cost, CAD |\n|---|---:|---:|---:|---:|---:|\n" + policy_rows,
    }


def chart_records(events):
    bands = ["Missed / 0", "1-7", "8-14", "15-21", "22-30", "31+"]
    records = []
    for policy, _, _ in POLICIES:
        subset = events[events.policy.eq(policy)]
        caught = subset.loc[subset.caught.eq(1), "warning_days"]
        counts = [int(subset.caught.eq(0).sum()), int(caught.between(1, 7).sum()),
                  int(caught.between(8, 14).sum()), int(caught.between(15, 21).sum()),
                  int(caught.between(22, 30).sum()), int(caught.ge(31).sum())]
        if sum(counts) != len(subset):
            raise ValueError(f"Warning bands do not account for every event: {policy}")
        records.extend({"policy": policy, "warning_band": band, "events": count}
                       for band, count in zip(bands, counts))
    return pd.DataFrame(records)


def write_chart(root, records):
    """Render only after markers and all numerical inputs have been validated."""
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": "#17324D",
                         "axes.labelcolor": "#526579", "xtick.color": "#526579", "ytick.color": "#526579"})
    fig, ax = plt.subplots(figsize=(10, 2.3), layout="constrained")
    bands = records.loc[records.policy.eq("predictive"), "warning_band"].tolist()
    x = np.arange(len(bands))
    for offset, (policy, label, color) in enumerate(POLICIES):
        counts = records.loc[records.policy.eq(policy), "events"].tolist()
        bars = ax.bar(x + (offset - 1) * .24, counts, width=.22, color=color, label=label, zorder=3)
        ax.bar_label(bars, labels=[str(n) if n else "" for n in counts], padding=2, fontsize=8)
    event_count = int(records.loc[records.policy.eq("predictive"), "events"].sum())
    ax.set_xticks(x, bands)
    ax.set_ylim(0, records.groupby("policy").events.sum().max() * 1.2)
    ax.set_yticks([0, 20, 40])
    ax.set_ylabel("Failure events")
    ax.set_xlabel("Days of warning before a prevented failure", labelpad=4)
    ax.set_title(f"Same {event_count} failure opportunities. Earlier warning changes the service decision.",
                 loc="left", fontsize=10, weight="bold", pad=8)
    ax.legend(loc="upper right", ncol=3, frameon=False, fontsize=8)
    ax.grid(axis="y", color="#E2E8F0", linewidth=.6, zorder=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    image = root / CHART_PATH
    image.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(image, dpi=160, facecolor="white")
    finally:
        plt.close(fig)
    records.to_csv(root / CHART_DATA_PATH, index=False)


def build(root=ROOT, *, check=False):
    root = Path(root)
    readme = root / "README.md"
    original = readme.read_bytes().decode("utf-8")
    validate_regions(original)  # Fail before reading evidence or writing any output.
    metrics, table, models, events = load_evidence(root)
    updated = update_regions(original, render_sections(metrics, table, models))
    records = chart_records(events)
    stale = []
    if updated != original:
        stale.append("README.md generated regions")
    if not (root / CHART_PATH).is_file():
        stale.append(CHART_PATH.as_posix())
    try:
        pd.testing.assert_frame_equal(pd.read_csv(root / CHART_DATA_PATH), records)
    except (OSError, AssertionError, ValueError):
        stale.append(CHART_DATA_PATH.as_posix())
    if not check:
        write_chart(root, records)
        if updated != original:
            readme.write_bytes(updated.encode("utf-8"))
    return {"mode": "check" if check else "update", "current": not stale if check else True,
            "stale": stale if check else [], "readme_words": len(updated.split()),
            "generated_regions": list(REGIONS), "chart": CHART_PATH.as_posix(),
            "chart_rows": len(records), "headline_metrics": 4, "source": "artifacts/metrics.json"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate generated regions and chart inputs without writing.")
    args = parser.parse_args()
    try:
        result = build(check=args.check)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"README refresh refused: {error}\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["current"] else 1)
