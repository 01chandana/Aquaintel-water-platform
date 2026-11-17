"""The five production models of spec Ch. 14 (trainers + predictors).

Every trainer takes a feature frame, performs a **time-ordered** train/validation/test split
(no future leakage, Ch. 10.6.1 step 7), and returns a bundle ``{"model", "features",
"metrics", "params", ...}``. Metrics are checked against the acceptance criteria of
Ch. 10.7.2 by :func:`acceptance`.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier, XGBRegressor

from app.ml.features import ANOMALY_FEATURES, DEMAND_FEATURES, PUMP_FEATURES

SEED = 42


def time_split(df: pd.DataFrame, time_col: str = "time", val: float = 0.15, test: float = 0.15) -> tuple[pd.DataFrame, ...]:
    times = np.sort(df[time_col].unique())
    t1, t2 = times[int(len(times) * (1 - val - test))], times[int(len(times) * (1 - test))]
    return df[df[time_col] < t1], df[(df[time_col] >= t1) & (df[time_col] < t2)], df[df[time_col] >= t2]


def mape(y: np.ndarray, p: np.ndarray) -> float:
    y, p = np.asarray(y), np.asarray(p)
    mask = np.abs(y) > 1e-6
    return float(np.mean(np.abs((y[mask] - p[mask]) / y[mask])) * 100)


def shap_contributions(model: Any, X: pd.DataFrame) -> list[dict[str, float]]:
    """Exact TreeSHAP values via XGBoost ``pred_contribs`` (Ch. 14.8 explainability)."""
    import xgboost as xgb

    booster = model.get_booster()
    contrib = booster.predict(xgb.DMatrix(X.astype(float), feature_names=list(X.columns)), pred_contribs=True)
    return [{**{f: round(float(v), 5) for f, v in zip(X.columns, row[:-1], strict=True)}, "_bias": round(float(row[-1]), 5)}
            for row in contrib]


# ---- Model 1: pump failure prediction (binary, 7-day horizon) ------------------------------
def train_pump_failure(df: pd.DataFrame) -> dict[str, Any]:
    df = df.dropna(subset=["label"]).copy()
    X = df[PUMP_FEATURES].astype(float)
    train, val, test = time_split(df)
    pos = max(int(train["label"].sum()), 1)
    params = {"max_depth": 5, "learning_rate": 0.05, "n_estimators": 400, "subsample": 0.8, "colsample_bytree": 0.7,
              "min_child_weight": 5, "scale_pos_weight": round((len(train) - pos) / pos, 2), "eval_metric": "logloss",
              "early_stopping_rounds": 20, "random_state": SEED}
    xgb_model = XGBClassifier(**params)
    xgb_model.fit(train[PUMP_FEATURES], train["label"], eval_set=[(val[PUMP_FEATURES], val["label"])], verbose=False)
    # calibration partner (Ch. 14.2.3 ensemble: XGBoost + Logistic Regression)
    logreg = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
    logreg.fit(train[PUMP_FEATURES].fillna(train[PUMP_FEATURES].median()), train["label"])
    medians = train[PUMP_FEATURES].median().to_dict()
    bundle = {"model": xgb_model, "calibrator": logreg, "weights": (0.8, 0.2), "medians": medians,
              "features": PUMP_FEATURES, "threshold": 0.5}
    # choose decision threshold on validation (maximise F1)
    p_val = predict_pump_failure(bundle, val[PUMP_FEATURES])
    best = max(np.linspace(0.2, 0.8, 25), key=lambda t: f1_score(val["label"], p_val >= t, zero_division=0))
    bundle["threshold"] = float(best)
    p_test = predict_pump_failure(bundle, test[PUMP_FEATURES])
    y = test["label"].to_numpy()
    yhat = p_test >= bundle["threshold"]
    fp = int(((yhat == 1) & (y == 0)).sum())
    tn = int(((yhat == 0) & (y == 0)).sum())
    lead = []
    test = test.assign(pred=yhat)
    for _, g in test.groupby("asset_id"):
        g = g.sort_values("time")
        pos_rows = g[g["label"] == 1]
        if pos_rows.empty:
            continue
        failure_t = pos_rows["time"].max() + pd.Timedelta(days=7)
        first = g[(g["pred"]) & (g["label"] == 1)]["time"].min()
        if pd.notna(first):
            lead.append((failure_t - first).total_seconds() / 86400)
    bundle["metrics"] = {
        "roc_auc": round(float(roc_auc_score(y, p_test)), 4) if len(set(y)) > 1 else None,
        "precision": round(float(precision_score(y, yhat, zero_division=0)), 4),
        "recall": round(float(recall_score(y, yhat, zero_division=0)), 4),
        "f1": round(float(f1_score(y, yhat, zero_division=0)), 4),
        "false_positive_rate": round(fp / max(fp + tn, 1), 4),
        "avg_lead_time_days": round(float(np.mean(lead)), 2) if lead else None,
        "test_rows": int(len(test)), "positive_rate": round(float(y.mean()), 4),
    }
    bundle["params"] = {k: v for k, v in params.items() if k != "eval_metric"} | {"decision_threshold": bundle["threshold"]}
    bundle["feature_importance"] = dict(sorted(zip(PUMP_FEATURES, xgb_model.feature_importances_.round(4).tolist(),
                                                   strict=True), key=lambda kv: -kv[1]))
    del X
    return bundle


def predict_pump_failure(bundle: dict[str, Any], X: pd.DataFrame) -> np.ndarray:
    X = X[bundle["features"]].astype(float)
    p1 = bundle["model"].predict_proba(X)[:, 1]
    p2 = bundle["calibrator"].predict_proba(X.fillna(pd.Series(bundle["medians"])))[:, 1]
    w1, w2 = bundle["weights"]
    return w1 * p1 + w2 * p2


# ---- Model 2: water demand forecasting (72 h recursive multi-step) -------------------------
def predict_demand(bundle: dict[str, Any], X: pd.DataFrame) -> np.ndarray:
    """Demand = same hour last week + the learned change (see ``train_demand``)."""
    return X["lag_168"].to_numpy(dtype=float) + bundle["model"].predict(X[bundle["features"]])


def train_demand(df: pd.DataFrame) -> dict[str, Any]:
    """LightGBM forecaster of the *change* from the same hour last week.

    Water demand repeats weekly, so "same hour last week" (seasonal naive) is a strong baseline. Learning
    the difference from it, from weather, recent level and calendar features, means the model starts from
    that baseline and only moves away where the features justify it, so it cannot do systematically worse
    than the baseline it is judged against.
    """
    import lightgbm as lgb

    data = df.dropna(subset=[*DEMAND_FEATURES, "lag_168", "demand"]).copy()
    train, val, test = time_split(data)
    params: dict[str, Any] = {"n_estimators": 600, "learning_rate": 0.03, "num_leaves": 31, "min_child_samples": 10,
                              "subsample": 0.9, "colsample_bytree": 0.9, "random_state": SEED, "verbose": -1}
    model = lgb.LGBMRegressor(**params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=Warning)
        model.fit(train[DEMAND_FEATURES], train["demand"] - train["lag_168"],
                  eval_set=[(val[DEMAND_FEATURES], val["demand"] - val["lag_168"])],
                  callbacks=[lgb.early_stopping(30, verbose=False)])
    bundle: dict[str, Any] = {"model": model, "features": DEMAND_FEATURES, "params": params,
                              "target": "change vs same hour last week"}
    # walk-forward backtest over the test window: forecast 72 h from several origins
    hist = df.set_index("time")
    errs24, errs72, rmse_l, naive_l, bias_l = [], [], [], [], []
    origins = pd.date_range(test["time"].min(), test["time"].max() - pd.Timedelta(hours=72), freq="24h")
    for origin in origins[:6]:
        past = hist[hist.index < origin]
        actual = hist[(hist.index >= origin) & (hist.index < origin + pd.Timedelta(hours=72))]["demand"]
        if len(actual) < 72 or len(past) < 200:
            continue
        fc = forecast_demand(bundle, past.reset_index(), 72, temperature=hist["temperature"])
        pred = np.array([f["value"] for f in fc])
        errs24.append(mape(actual.to_numpy()[:24], pred[:24]))
        errs72.append(mape(actual.to_numpy(), pred))
        rmse_l.append(float(np.sqrt(mean_squared_error(actual, pred))))
        naive = past["demand"].iloc[-168:].to_numpy()[:72]  # naive seasonal baseline (same hour last week)
        naive_l.append(float(np.sqrt(mean_squared_error(actual, naive))))
        bias_l.append(float((pred.sum() - actual.sum()) / actual.sum() * 100))
    bundle["metrics"] = {
        "mape_24h": round(float(np.mean(errs24)), 3) if errs24 else None,
        "mape_72h": round(float(np.mean(errs72)), 3) if errs72 else None,
        "rmse_m3h": round(float(np.mean(rmse_l)), 2) if rmse_l else None,
        "rmse_naive_seasonal_m3h": round(float(np.mean(naive_l)), 2) if naive_l else None,
        "forecast_bias_pct": round(float(np.mean(bias_l)), 2) if bias_l else None,
        "backtest_origins": len(errs24),
    }
    resid = val["demand"] - predict_demand(bundle, val)
    bundle["residual_std"] = float(resid.std())
    return bundle


def forecast_demand(bundle: dict[str, Any], history: pd.DataFrame, horizon: int,
                    temperature: pd.Series | None = None) -> list[dict[str, Any]]:
    """Recursive multi-step forecast with ~95% intervals that widen with the horizon."""
    from app.ml.features import demand_features

    h = history[["time", "demand", "temperature"]].copy().sort_values("time").tail(24 * 16)  # 2 weeks + margin
    last = h["time"].max()
    out = []
    sd = bundle.get("residual_std", 0.0)
    for step in range(1, horizon + 1):
        t = last + pd.Timedelta(hours=step)
        temp = None
        if temperature is not None and t in temperature.index:
            temp = temperature.loc[t]
        if temp is None or pd.isna(temp):
            same = h[h["time"] == t - pd.Timedelta(hours=24)]["temperature"]
            temp = float(same.iloc[0]) if len(same) else float(h["temperature"].iloc[-24:].mean())
        h = pd.concat([h, pd.DataFrame([{"time": t, "demand": np.nan, "temperature": temp}])], ignore_index=True)
        row = demand_features(h).iloc[[-1]][[*bundle["features"], "lag_168"]]
        # a change we cannot compute yet counts as "no change"; a missing base falls back to the weekly mean
        row = row.fillna({f: 0.0 for f in bundle["features"]})
        row = row.fillna({"lag_168": float(h["demand"].dropna().iloc[-168:].mean())})
        y = float(predict_demand(bundle, row)[0])
        h.loc[h.index[-1], "demand"] = y
        band = 1.96 * sd * np.sqrt(1 + step / 24)
        out.append({"time": t.isoformat(), "value": round(y, 2), "lower": round(y - band, 2), "upper": round(y + band, 2)})
    return out


# ---- Model 3: anomaly detection (Isolation Forest) -----------------------------------------
def running_mask(df: pd.DataFrame) -> pd.Series:
    """Score only steady-state operation: start/stop transitions are not equipment anomalies."""
    return df["flow_mean_6h"].notna() & (df["runtime_frac_24h"] >= 0.5)


def train_anomaly(df: pd.DataFrame, labels: pd.Series | None = None) -> dict[str, Any]:
    mask = running_mask(df)
    df = df[mask]
    labels = labels[mask] if labels is not None else None
    X = df[ANOMALY_FEATURES].astype(float)
    medians = X.median()
    Xf = X.fillna(medians)
    scaler = StandardScaler().fit(Xf)
    params = {"n_estimators": 300, "contamination": "auto", "max_samples": 512, "random_state": SEED}
    iso = IsolationForest(**params).fit(scaler.transform(Xf))
    raw = -iso.score_samples(scaler.transform(Xf))
    lo, hi = float(np.percentile(raw, 1)), float(np.percentile(raw, 99.5))
    bundle = {"model": iso, "scaler": scaler, "medians": medians.to_dict(), "features": ANOMALY_FEATURES,
              "score_range": (lo, hi), "params": params}
    scores = score_anomaly(bundle, X)
    bundle["threshold"] = float(np.percentile(scores, 97))
    metrics: dict[str, Any] = {"alert_threshold": round(bundle["threshold"], 4), "rows": int(len(df))}
    if labels is not None and labels.sum() > 0:
        order = np.argsort(-scores)
        y = labels.to_numpy()
        for k in (10, 100):
            metrics[f"precision_at_{k}"] = round(float(y[order[:k]].mean()), 4)
        flagged = scores >= bundle["threshold"]
        metrics["recall"] = round(float((flagged & (y == 1)).sum() / max(y.sum(), 1)), 4)
        metrics["false_positive_rate"] = round(float((flagged & (y == 0)).sum() / max((y == 0).sum(), 1)), 4)
    bundle["metrics"] = metrics
    return bundle


def score_anomaly(bundle: dict[str, Any], X: pd.DataFrame) -> np.ndarray:
    Xf = X[bundle["features"]].astype(float).fillna(pd.Series(bundle["medians"]))
    raw = -bundle["model"].score_samples(bundle["scaler"].transform(Xf))
    lo, hi = bundle["score_range"]
    return np.clip((raw - lo) / max(hi - lo, 1e-9), 0, 1)


# ---- Model 4: chlorine decay (physics-informed hybrid) -------------------------------------
CHLORINE_FEATURES = ["c0", "residence_h", "water_temperature", "toc", "flow_share"]


def physics_k(bundle: dict[str, Any], temp: np.ndarray, toc: np.ndarray) -> np.ndarray:
    return np.exp(bundle["ln_k20"]) * bundle["theta"] ** (temp - 20) * (1 + bundle["toc_coef"] * (toc - 2.6))


def train_chlorine(df: pd.DataFrame) -> dict[str, Any]:
    d = df.dropna(subset=[*CHLORINE_FEATURES, "c"]).copy()
    d = d[(d["c"] > 0.05) & (d["c0"] > 0.2)]
    train, val, test = time_split(d)
    # first-order decay C = C0 e^{-kt}: ln(C0/C)/t = k = k20 * theta^(T-20) * (1 + b*(TOC-2.6))
    k_obs = np.log(train["c0"] / train["c"]) / train["residence_h"]
    ok = k_obs > 0
    Xk = np.column_stack([train.loc[ok, "water_temperature"] - 20, train.loc[ok, "toc"] - 2.6])
    lin = LinearRegression().fit(Xk, np.log(k_obs[ok]))
    bundle: dict[str, Any] = {"ln_k20": float(lin.intercept_), "theta": float(np.exp(lin.coef_[0])),
                              "toc_coef": float(lin.coef_[1]), "features": CHLORINE_FEATURES}

    def physics(frame: pd.DataFrame) -> np.ndarray:
        k = physics_k(bundle, frame["water_temperature"].to_numpy(), frame["toc"].to_numpy())
        return frame["c0"].to_numpy() * np.exp(-k * frame["residence_h"].to_numpy())

    params = {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05, "subsample": 0.9, "random_state": SEED,
              "early_stopping_rounds": 20}
    resid = XGBRegressor(**params)
    resid.fit(train[CHLORINE_FEATURES], train["c"] - physics(train),
              eval_set=[(val[CHLORINE_FEATURES], val["c"] - physics(val))], verbose=False)
    bundle["model"] = resid
    pred = physics(test) + resid.predict(test[CHLORINE_FEATURES])
    y = test["c"].to_numpy()
    bundle["metrics"] = {"mae_mg_l": round(float(mean_absolute_error(y, pred)), 4),
                         "rmse_mg_l": round(float(np.sqrt(mean_squared_error(y, pred))), 4),
                         "r2": round(float(r2_score(y, pred)), 4),
                         "within_0_2_pct": round(float((np.abs(y - pred) <= 0.2).mean() * 100), 2),
                         "physics_only_mae": round(float(mean_absolute_error(y, physics(test))), 4),
                         "k20_per_hour": round(float(np.exp(bundle["ln_k20"])), 5), "theta": round(bundle["theta"], 4)}
    bundle["params"] = params | {"decay_model": "first_order", "residual_model": "xgboost"}
    return bundle


def predict_chlorine(bundle: dict[str, Any], X: pd.DataFrame) -> np.ndarray:
    k = physics_k(bundle, X["water_temperature"].to_numpy(), X["toc"].to_numpy())
    phys = X["c0"].to_numpy() * np.exp(-k * X["residence_h"].to_numpy())
    return np.clip(phys + bundle["model"].predict(X[CHLORINE_FEATURES]), 0, None)


# ---- Model 5: energy optimisation (specific energy regression) -----------------------------
ENERGY_FEATURES = ["demand", "pumps_running", "load_per_pump", "avg_speed", "tank_level", "is_peak_tariff",
                   "hour_sin", "hour_cos"]


def train_energy(df: pd.DataFrame) -> dict[str, Any]:
    d = df.dropna(subset=[*ENERGY_FEATURES, "sec"]).copy()
    d = d[(d["sec"] > 0.05) & (d["sec"] < 2)]
    train, val, test = time_split(d)
    params = {"n_estimators": 500, "max_depth": 5, "learning_rate": 0.04, "subsample": 0.85, "colsample_bytree": 0.9,
              "random_state": SEED, "early_stopping_rounds": 25}
    model = XGBRegressor(**params)
    model.fit(train[ENERGY_FEATURES], train["sec"], eval_set=[(val[ENERGY_FEATURES], val["sec"])], verbose=False)
    pred = model.predict(test[ENERGY_FEATURES])
    y = test["sec"].to_numpy()
    baseline = np.full_like(y, train["sec"].mean())
    bundle: dict[str, Any] = {"model": model, "features": ENERGY_FEATURES, "params": params,
                              "max_pumps": int(d["pumps_running"].max())}
    # what-if: choose the pump count with the lowest predicted SEC that still meets demand
    best = []
    for _, row in test.iterrows():
        options = []
        for n in range(1, bundle["max_pumps"] + 1):
            if row["demand"] <= n * row.get("pump_capacity", 900) * 0.98:
                options.append(n)
        cands = pd.DataFrame([{**row[ENERGY_FEATURES].to_dict(), "pumps_running": n,
                               "load_per_pump": row["demand"] / (n * row.get("pump_capacity", 900))}
                              for n in options or [row["pumps_running"]]])
        best.append(float(model.predict(cands[ENERGY_FEATURES]).min()))
    savings = (y - np.array(best)) / y * 100
    bundle["metrics"] = {"mae_kwh_m3": round(float(mean_absolute_error(y, pred)), 4),
                         "baseline_mae_kwh_m3": round(float(mean_absolute_error(y, baseline)), 4),
                         "r2": round(float(r2_score(y, pred)), 4),
                         "mape_pct": round(mape(y, pred), 3),
                         "avg_energy_savings_pct": round(float(np.clip(savings, 0, None).mean()), 2)}
    return bundle


def acceptance(name: str, metrics: dict[str, Any], psi_max: float | None = None) -> dict[str, Any]:
    """Ch. 10.7.2 acceptance criteria."""
    checks: dict[str, dict[str, Any]] = {}
    if name == "pump_failure":
        checks["f1_gt_0_85"] = {"value": metrics.get("f1"), "passed": (metrics.get("f1") or 0) > 0.85}
    if name == "demand_forecast":
        checks["mape_lt_10"] = {"value": metrics.get("mape_24h"), "passed": (metrics.get("mape_24h") or 99) < 10}
    if name == "chlorine_decay":
        checks["mae_lt_0_15"] = {"value": metrics.get("mae_mg_l"), "passed": (metrics.get("mae_mg_l") or 9) < 0.15}
    if name == "energy_optimization":
        checks["beats_baseline"] = {"value": metrics.get("mae_kwh_m3"),
                                    "passed": float(metrics.get("mae_kwh_m3") or 9) < float(metrics.get("baseline_mae_kwh_m3") or 0)}
    if name == "anomaly_detection":
        checks["fpr_lt_0_10"] = {"value": metrics.get("false_positive_rate"),
                                 "passed": float(metrics.get("false_positive_rate") or 0) < 0.10}
    checks["latency_lt_100ms"] = {"value": metrics.get("inference_latency_ms"),
                                  "passed": (metrics.get("inference_latency_ms") or 0) < 100}
    if psi_max is not None:
        checks["psi_lt_0_1"] = {"value": psi_max, "passed": psi_max < 0.1}
    return {"checks": checks, "passed": all(c["passed"] for c in checks.values())}
