"""EDA and evaluation figures; headline copy is calculated, not manually asserted."""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import precision_recall_curve
from sklearn.calibration import calibration_curve

COLORS = {"reactive":"#96a7b5","fixed_90_day":"#e3a648","predictive":"#13b9a5"}
LABELS = {"reactive":"Reactive", "fixed_90_day":"Fixed 90-day", "predictive":"Predictive"}

def refresh_readme_headline(root, metrics):
    """Keep the opening evidence block synchronized when a local README exists."""
    import re
    path = Path(root)/"README.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    head = metrics["headline"]
    pred = next(row for row in metrics["policies"] if row["policy"]=="predictive")
    days = round(pred["evaluation_years"]*365.25)
    block = f"""<!-- HEADLINE:START -->
# Energy & Oil/Gas - Predictive Equipment Failure

Unplanned equipment failures force emergency repairs while calendar-based service misses developing faults.

*Synthetic held-out scenario · {metrics['data']['assets']} Alberta-style assets · {days}-day replay · CAD estimates*

- **{head['median_warning_days']:g}-day median warning vs. current reactive maintenance's 0 days**, among {int(pred['caught_failures'])} prevented failures out of {int(pred['event_count'])}.
- **{head['unplanned_downtime_reduction_pct']:.1f}% less unplanned downtime vs. current fixed-interval maintenance** (service every 90 days).
- **C${head['annualized_emergency_repair_savings_cad']/1e6:.2f}M/year in avoided emergency repairs vs. current reactive maintenance**, annualized gross estimate.
- **C${head['annualized_net_savings_cad']/1e6:.2f}M/year net operating-cost savings vs. current fixed-interval maintenance**, annualized scenario estimate.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white) ![SQL](https://img.shields.io/badge/SQL-SQLite-003B57?logo=sqlite&logoColor=white) ![scikit-learn](https://img.shields.io/badge/ML-scikit--learn-F7931E?logo=scikitlearn&logoColor=white) ![Azure ML](https://img.shields.io/badge/Azure-Machine%20Learning-0078D4) ![Power BI](https://img.shields.io/badge/Power%20BI-PBIP-F2C811)

![Warning lead times, including missed failures at zero](reports/figures/failure_lead_time.png)
<!-- HEADLINE:END -->"""
    path.write_text(re.sub(r"<!-- HEADLINE:START -->.*?<!-- HEADLINE:END -->",lambda _:block,text,flags=re.S),encoding="utf-8")

def figures(frame, train, events, models, features, outcomes, policy_summary, detail, comparison, selected, threshold, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,
                         "axes.spines.right":False,"figure.facecolor":"#ffffff","axes.titleweight":"bold"})
    def save(fig,name):
        fig.savefig(output_dir/name,dpi=160,bbox_inches="tight",facecolor=fig.get_facecolor())
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(12,2.65))
    bins = [-.5,.5,5.5,10.5,15.5,20.5,25.5,30.5,35.5]
    x = np.arange(len(bins)-1)
    for offset,policy in enumerate(COLORS):
        values = outcomes[outcomes.policy==policy].warning_days
        counts,_ = np.histogram(values,bins=bins)
        ax.bar(x+(offset-1)*.24,counts,width=.23,color=COLORS[policy],label=LABELS[policy])
    ax.set(xticks=x,xticklabels=["0 / missed","1–5","6–10","11–15","16–20","21–25","26–30","31–35"],
           ylabel="Failure events",xlabel="Days of warning before a prevented failure • same held-out event history",
           title="Who gets advance warning?  |  Synthetic policy replay")
    ax.legend(ncol=3,frameon=False,loc="upper right")
    save(fig,"failure_lead_time.png")
    # EDA uses training period only so exploratory decisions cannot inspect test.
    fig,axes = plt.subplots(1,3,figsize=(13,3.5))
    for ax,sensor,label in zip(axes,["vibration_mm_s","bearing_temperature_c","pressure_bar"],["Vibration (mm/s)","Bearing temperature (°C)","Pressure (bar)"]):
        subset = train[train.days_to_failure.between(1,60)].copy()
        # Remove cross-equipment level differences, using training-only type medians.
        subset["centered"] = subset[sensor]-train.groupby("asset_type")[sensor].transform("median").loc[subset.index]
        group = subset.groupby("days_to_failure").centered
        mean,lo,hi = group.mean(),group.quantile(.25),group.quantile(.75)
        ax.plot(mean.index,mean,color=COLORS["predictive"])
        ax.fill_between(mean.index,lo,hi,alpha=.18,color=COLORS["predictive"])
        ax.invert_xaxis()
        ax.set(xlabel="Days until failure",ylabel=f"{label}, centered",title=label)
    fig.suptitle("Training EDA: mean degradation and interquartile spread")
    fig.tight_layout()
    save(fig,"degradation_trends.png")
    sensors = ["vibration_mm_s","bearing_temperature_c","pressure_bar","power_kw","rpm","runtime_hours","sensor_missing_count","target_failure_30d"]
    corr = train[sensors].corr()
    fig,ax = plt.subplots(figsize=(8,6))
    im = ax.imshow(corr,vmin=-1,vmax=1,cmap="BrBG")
    ax.set(xticks=range(len(sensors)),yticks=range(len(sensors)),xticklabels=sensors,yticklabels=sensors,title="Training EDA: sensor / 30-day label correlation")
    plt.setp(ax.get_xticklabels(),rotation=45,ha="right",fontsize=8)
    for i in range(len(sensors)):
        for j in range(len(sensors)):
            ax.text(j,i,f"{corr.iloc[i,j]:.2f}",ha="center",va="center",fontsize=8,color="white" if abs(corr.iloc[i,j])>.65 else "#152633")
    fig.colorbar(im,ax=ax,shrink=.65)
    save(fig,"sensor_correlation.png")
    fig,axes = plt.subplots(1,2,figsize=(12,4))
    for name,model in models.items():
        p = model.predict_proba(frame[features])[:,1]
        precision,recall,_ = precision_recall_curve(frame.target_failure_30d,p)
        axes[0].plot(recall,precision,label=name.replace("_"," "))
        actual,predicted = calibration_curve(frame.target_failure_30d,p,n_bins=8,strategy="quantile")
        axes[1].plot(predicted,actual,marker="o",label=name.replace("_"," "))
    axes[0].axhline(frame.target_failure_30d.mean(),ls="--",color="#96a7b5",label="Positive prevalence")
    axes[0].set(xlabel="Recall",ylabel="Precision",title="Held-out 30-day classification",ylim=(0,1.03))
    axes[1].plot([0,1],[0,1],ls="--",color="#96a7b5")
    axes[1].set(xlabel="Predicted score",ylabel="Observed failure fraction",title="Calibration diagnostic",xlim=(0,1),ylim=(0,1))
    axes[0].legend(fontsize=8)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    save(fig,"model_tradeoffs.png")
    fig,axes = plt.subplots(1,2,figsize=(12,3.7))
    table = policy_summary.set_index("policy").loc[list(COLORS)]
    axes[0].bar(range(3),table.unplanned_downtime_hours,color=[COLORS[p] for p in table.index],label="Unplanned")
    axes[0].bar(range(3),table.planned_downtime_hours,bottom=table.unplanned_downtime_hours,color="#243f52",label="Planned")
    axes[0].set(xticks=range(3),xticklabels=list(LABELS.values()),ylabel="Fleet downtime hours",title="All maintenance downtime")
    axes[0].legend()
    cost_by_type = detail.pivot(index="asset_id",columns="policy",values="total_cost_cad").join(detail.drop_duplicates("asset_id").set_index("asset_id").asset_type).groupby("asset_type").sum()
    for i,p in enumerate(COLORS):
        axes[1].bar(np.arange(len(cost_by_type))+(i-1)*.24,cost_by_type[p]/1000,width=.23,color=COLORS[p],label=LABELS[p])
    axes[1].set(xticks=np.arange(len(cost_by_type)),xticklabels=[x.replace("_"," ") for x in cost_by_type.index],ylabel="Held-out cost (CAD thousands)",title="Repair + service + downtime cost")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    save(fig,"policy_business_case.png")

def write_result_notes(root, metrics, summary, comparison):
    root = Path(root)
    head = metrics["headline"]
    rows = []
    for r in summary.itertuples():
        rows.append(f"| {LABELS[r.policy]} | {int(r.caught_failures)}/{int(r.event_count)} | {int(r.service_visits)} | {r.unplanned_downtime_hours:,.1f} | {r.total_downtime_hours:,.1f} | ${r.total_cost_cad:,.0f} |")
    model_rows = []
    for r in comparison.itertuples():
        model_rows.append(f"| {r.algorithm.replace('_',' ')} | {r.threshold:.2f} | {r.average_precision:.3f} | {r.precision:.3f} | {r.recall:.3f} | {r.brier_score:.3f} |")
    (root/"reports"/"results.md").write_text(f"""# Reproduced results - synthetic scenario

Seed {metrics['config']['seed']}; {metrics['data']['assets']} assets; {metrics['data']['expected_asset_days']:,} daily snapshots. All currency CAD. Policy evaluation: {metrics['config']['test_start']} to {metrics['config']['test_end']} inclusive.

| Policy | Failures prevented / total | Planned visits | Unplanned hours | Total hours | Test-period total cost |
|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Selected model: **{metrics['selected_model']}**, threshold **{metrics['threshold']:.2f}**. Selection minimizes validation policy cost; no test retuning or post-selection refit. The table below evaluates each algorithm at its own validation-selected threshold.

| Algorithm | Threshold | Average precision | Precision | Recall | Brier score |
|---|---:|---:|---:|---:|---:|
{chr(10).join(model_rows)}

Classification includes only test dates with complete 30-day follow-up, through {metrics['classification_test_end']}. These are asset-day metrics; repeated positive days before one failure are not independent events. Event prevention recall is reported separately above. Scores are not independently calibrated; see the reliability diagram before interpreting them as precise probabilities.

## Business case arithmetic

- Median warning among prevented predictive events: **{head['median_warning_days']:.1f} days**; reactive maintenance: 0 days. Missed failures still receive zero useful warning.
- Unplanned-hours reduction vs fixed: **{head['unplanned_downtime_reduction_pct']:.1f}%** = 100 × (fixed hours − predictive hours) / fixed hours.
- Net scenario savings vs fixed: **CAD ${head['annualized_net_savings_cad']:,.0f}/year** for the whole fleet; includes planned service and downtime costs.
- Avoided emergency repair costs vs reactive: **CAD ${head['annualized_emergency_repair_savings_cad']:,.0f}/year** (gross repair-only savings; do not add to net savings).
- Annualization factor: **{metrics['annualization_factor']:.6f}** = 365.25 / test days. This extrapolates a short synthetic period; it is not a one-year observation.

See [methodology](../docs/methodology.md) for boundary handling and causal limits, [sensitivity.csv](sensitivity.csv) for alternative actionability/success assumptions, and [policy service ledger](../data/processed/dashboard/service_visits.csv) for every charged visit. When a sensitivity scenario reverses the benefit, retain that result.
""",encoding="utf-8")
