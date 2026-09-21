"""One reproducible entry point from raw generation through decision metrics."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import joblib
import numpy as np
import pandas as pd
import sklearn
from .config import Config
from .synthetic import generate
from .cleaning import clean_data
from .modeling import prepare_features, fit_compare, metrics
from .policies import replay, sensitivity
from .reporting import figures, write_result_notes, refresh_readme_headline
from .provenance import build_provenance, file_hash
from .input_quality import history_quality

def run(output_root: Path, config=Config()):
    root = Path(output_root).resolve()
    raw,processed,artifacts,reports = (root/p for p in ["data/raw","data/processed","artifacts","reports"])
    for path in [raw,processed,artifacts,reports]:
        path.mkdir(parents=True,exist_ok=True)
    print("1/7 Generating 18 months of synthetic field telemetry",flush=True)
    manifest = generate(raw,config)
    print("2/7 SQL cleaning, causal features and metadata joins",flush=True)
    quality = clean_data(raw,processed)
    assets = pd.read_csv(processed/"assets.csv")
    events = pd.read_csv(processed/"events.csv")
    # Isolated oracle merge. These columns are NEVER passed into the feature model.
    oracle_events = events.merge(pd.read_csv(raw/"simulation_truth.csv"),on="event_id",validate="one_to_one")
    frame,features = prepare_features(pd.read_csv(processed/"daily_features.csv"),events,config)
    frame = history_quality(frame, pd.read_csv(processed/"maintenance.csv"))
    print("3/7 Fitting two algorithms; selecting policy threshold on validation only",flush=True)
    models,selected,threshold,leaderboard,tradeoffs = fit_compare(frame,features,assets,oracle_events,config)
    test = frame[frame.date.between(config.test_start,config.test_end)].copy()
    test["risk_score"] = models[selected].predict_proba(test[features])[:,1]
    test["alert"] = (test.risk_score>=threshold).astype(int)
    labeled_test = test[test.target_failure_30d.notna()]
    comparisons = []
    for name,model in models.items():
        own_threshold = float(leaderboard.set_index("algorithm").loc[name,"threshold"])
        comparisons.append({"algorithm":name,**metrics(labeled_test.target_failure_30d.astype(int),model.predict_proba(labeled_test[features])[:,1],own_threshold)})
    comparisons = pd.DataFrame(comparisons)
    print("4/7 Replaying reactive, 90-day and predictive maintenance",flush=True)
    summary,outcomes,visits,detail = replay(assets,oracle_events,test,config.test_start,config.test_end,config,threshold)
    table = summary.set_index("policy")
    pred,fixed,reactive = table.loc["predictive"],table.loc["fixed_90_day"],table.loc["reactive"]
    factor = 1/float(pred.evaluation_years)
    provenance = build_provenance(Path(__file__).resolve().parents[2], raw, config.to_dict(), features, selected, threshold)
    metadata = dict(version=provenance["model_version"], model_version=provenance["model_version"],
                    target_horizon_days=30,training_end=config.train_end, provenance=provenance,
                    selected_model=selected,feature_schema_sha256=provenance["feature_schema_sha256"],
                    sklearn_version=sklearn.__version__,python_version=platform.python_version(),currency="CAD")
    result = dict(config=config.to_dict(),data=manifest,quality=quality,selected_model=selected,threshold=threshold,
                  classification_test_end=labeled_test.date.max().date().isoformat(),
                  annualization_factor=factor,feature_count=len(features),runtime=metadata,
                  validation_models=leaderboard.to_dict("records"),test_models=comparisons.to_dict("records"),
                  headline=dict(median_warning_days=float(pred.median_warning_days),
                                unplanned_downtime_reduction_pct=100*(1-pred.unplanned_downtime_hours/fixed.unplanned_downtime_hours),
                                annualized_net_savings_cad=float(fixed.annualized_cost_cad-pred.annualized_cost_cad),
                                annualized_emergency_repair_savings_cad=float((reactive.emergency_repair_cost_cad-pred.emergency_repair_cost_cad)*factor)),
                  policies=summary.to_dict("records"))
    joblib.dump(dict(model=models[selected],features=features,threshold=threshold,metadata=metadata),artifacts/"model.joblib")
    (artifacts/"provenance.json").write_text(json.dumps({**provenance, "model_artifact_sha256": file_hash(artifacts/"model.joblib")}, indent=2)+"\n", encoding="utf-8")
    (artifacts/"features.json").write_text(json.dumps(features,indent=2),encoding="utf-8")
    (artifacts/"metrics.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    leaderboard.to_csv(reports/"validation_models.csv",index=False)
    comparisons.to_csv(reports/"test_models.csv",index=False)
    tradeoffs.to_csv(reports/"validation_threshold_tradeoffs.csv",index=False)
    frame.to_csv(processed/"modeling_frame.csv",index=False)
    test[["asset_id","date","asset_type","site"]+features+["sensor_flatline", "telemetry_staleness_days", "maintenance_history_known"]].to_csv(processed/"batch_features.csv",index=False)
    dashboard = processed/"dashboard"
    dashboard.mkdir(parents=True,exist_ok=True)
    summary.to_csv(dashboard/"policy_summary.csv",index=False)
    outcomes.to_csv(dashboard/"event_outcomes.csv",index=False)
    visits.to_csv(dashboard/"service_visits.csv",index=False)
    detail.to_csv(dashboard/"policy_asset_detail.csv",index=False)
    dashboard_cols = ["date","asset_id","asset_type","site","vibration_mm_s","bearing_temperature_c","pressure_bar","power_kw","load_pct","rpm","runtime_hours","age_days","sensor_missing_count","risk_score","alert","target_failure_30d"]
    test[dashboard_cols].to_csv(dashboard/"scored_readings.csv",index=False)
    asset_summary = assets[["asset_id","asset_type","site"]].copy().set_index("asset_id")
    for policy,prefix in [("predictive","predictive"),("fixed_90_day","fixed")]:
        indexed = detail[detail.policy==policy].set_index("asset_id")
        asset_summary[f"{prefix}_caught"] = indexed.caught_failures
        asset_summary[f"{prefix}_unplanned_hours"] = indexed.unplanned_downtime_hours
    asset_summary["event_count"] = detail[detail.policy=="reactive"].set_index("asset_id").event_count
    asset_summary["latest_risk_score"] = test.sort_values("date").groupby("asset_id").tail(1).set_index("asset_id").risk_score
    asset_summary.reset_index().to_csv(dashboard/"asset_summary.csv",index=False)
    print("5/7 Writing EDA, model diagnostics, scenario sensitivity and business case",flush=True)
    sensitivity(assets,oracle_events,test,config.test_start,config.test_end,config,threshold).to_csv(reports/"sensitivity.csv",index=False)
    train = frame[frame.date.between(config.train_start,config.train_end)].copy()
    # Event-aligned EDA must also respect outcomes available at training time.
    last_training_outcome = pd.Timestamp(config.train_end)+pd.Timedelta(days=config.horizon_days)
    unavailable = train.date+pd.to_timedelta(train.days_to_failure,unit="D") > last_training_outcome
    train.loc[unavailable,"days_to_failure"] = np.nan
    figures(labeled_test,train,events,models,features,outcomes,summary,detail,comparisons,selected,threshold,reports/"figures")
    write_result_notes(root,result,summary,comparisons)
    refresh_readme_headline(root,result)
    print("6/7 Saved registered-model-ready artifact and batch feature contract",flush=True)
    model_exports = Path(__file__).resolve().parents[2]/"scripts"/"export_powerbi_model_data.py"
    if model_exports.exists():
        subprocess.run([sys.executable,str(model_exports),"--root",str(root)],check=True)
    script = Path(__file__).resolve().parents[2]/"scripts"/"build_dashboard.py"
    if script.exists():
        subprocess.run([sys.executable,str(script),"--root",str(root)],check=True)
    print("7/7 Dashboard exports ready. Azure deployment files are not executed locally.",flush=True)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root",type=Path,default=Path.cwd())
    args = parser.parse_args()
    result = run(args.output_root)
    print(json.dumps({"selected_model":result["selected_model"],"threshold":result["threshold"],**result["headline"]},indent=2))

if __name__ == "__main__":
    main()
