"""Purged calendar splits; validation-only algorithm/threshold selection."""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score, roc_auc_score
from .config import Config
from .policies import replay

SENSOR_FEATURES = ["vibration_mm_s","bearing_temperature_c","pressure_bar","power_kw","load_pct","rpm","runtime_hours"]

def prepare_features(frame, events, config: Config):
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame.date)
    frame["age_days"] = (frame.date-pd.to_datetime(frame.commissioned_date)).dt.days
    frame["is_compressor"] = frame.asset_type.eq("compressor").astype(int)
    frame["is_pipeline_pump"] = frame.asset_type.eq("pipeline_pump").astype(int)
    frame["day_of_year_sin"] = np.sin(2*np.pi*frame.date.dt.dayofyear/365.25)
    frame["day_of_year_cos"] = np.cos(2*np.pi*frame.date.dt.dayofyear/365.25)
    features = SENSOR_FEATURES + [f"{c}_mean_7d" for c in SENSOR_FEATURES] + [f"{c}_mean_30d" for c in SENSOR_FEATURES] + [f"{c}_change_per_day" for c in SENSOR_FEATURES]
    features += ["sensor_missing_count","sensor_missing_count_mean_7d","missing_gap_days","days_since_last_recorded_maintenance",
                 "age_days","rated_power_kw","is_compressor","is_pipeline_pump","day_of_year_sin","day_of_year_cos"]
    assert np.isfinite(frame[features].to_numpy(dtype=float)).all(), "Features must be numeric and finite"
    frame["target_failure_30d"] = np.nan
    frame["days_to_failure"] = np.nan  # Audit only; explicitly never a predictor.
    for aid, ix in frame.groupby("asset_id").groups.items():
        dates = frame.loc[ix,"date"].to_numpy(dtype="datetime64[D]")
        event_dates = np.sort(pd.to_datetime(events.loc[events.asset_id.eq(aid),"event_date"]).to_numpy(dtype="datetime64[D]"))
        insertion = np.searchsorted(event_dates,dates,side="right")
        future = np.full(len(dates),np.inf)
        has_event = insertion < len(event_dates)
        future[has_event] = (event_dates[insertion[has_event]]-dates[has_event]).astype(int)
        observed = dates+np.timedelta64(config.horizon_days,"D") <= np.datetime64(config.end)
        frame.loc[ix,"target_failure_30d"] = np.where(observed,(future<=config.horizon_days).astype(float),np.nan)
        frame.loc[ix,"days_to_failure"] = np.where(np.isfinite(future),future,np.nan)
    return frame,features

def metrics(y, scores, threshold):
    predicted = scores>=threshold
    return dict(average_precision=float(average_precision_score(y,scores)),
                roc_auc=float(roc_auc_score(y,scores)),brier_score=float(brier_score_loss(y,scores)),
                precision=float(precision_score(y,predicted,zero_division=0)),
                recall=float(recall_score(y,predicted,zero_division=0)),
                positive_rate=float(np.mean(y)),rows=len(y),threshold=float(threshold))

def fit_compare(frame, features, assets, events, config: Config):
    train = frame[frame.date.between(config.train_start,config.train_end)]
    validation = frame[frame.date.between(config.validation_start,config.validation_end)]
    candidates = {
        "logistic_regression": make_pipeline(StandardScaler(),LogisticRegression(C=.15,class_weight="balanced",max_iter=1500,random_state=config.seed)),
        "hist_gradient_boosting": make_pipeline(HistGradientBoostingClassifier(max_iter=180,learning_rate=.055,max_leaf_nodes=15,min_samples_leaf=60,l2_regularization=5,random_state=config.seed)),
    }
    leaderboard, tradeoffs, fitted, selection = [],[],{},[]
    for name,model in candidates.items():
        model.fit(train[features],train.target_failure_30d.astype(int))
        scores = model.predict_proba(validation[features])[:,1]
        scored = validation[["date","asset_id"]].assign(risk_score=scores)
        model_options = []
        for threshold in np.round(np.arange(.10,.91,.05),2):
            summary,_,_,_ = replay(assets,events,scored,config.validation_start,config.validation_end,config,float(threshold))
            cost = float(summary.set_index("policy").loc["predictive","total_cost_cad"])
            row = {"algorithm":name,**metrics(validation.target_failure_30d.astype(int),scores,threshold),"validation_policy_cost_cad":cost}
            tradeoffs.append(row)
            model_options.append(row)
        # Tie: higher threshold has fewer interventions; all criteria validation-only.
        best = min(model_options,key=lambda x:(x["validation_policy_cost_cad"],-x["threshold"]))
        leaderboard.append(best)
        selection.append((best["validation_policy_cost_cad"],name,best["threshold"]))
        fitted[name] = model
    _,selected,threshold = min(selection)
    # No refit: hold training set and model constant after choosing on validation.
    return fitted,selected,float(threshold),pd.DataFrame(leaderboard),pd.DataFrame(tradeoffs)
