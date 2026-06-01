#!/usr/bin/env python3
"""
train_round63_scene_residual_models.py
===================================
分场景残差模型训练。

场景：
  dawn: 6-8h
  day:  9-16h
  dusk: 17-19h

候选：
  ridge_residual: Ridge 回归（线性、稳定）
  lgb_residual: LightGBM（捕捉非线性）

输出：
  output/pv_pipeline/round63/round63_residual_models.pkl
  output/pv_pipeline/round63/round63_feature_list.json
"""

from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd
import yaml
import lightgbm as lgb
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import pickle

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round63"
OUT.mkdir(parents=True, exist_ok=True)

SCENES = {
    "dawn": list(range(6, 9)),
    "day": list(range(9, 17)),
    "dusk": list(range(17, 20)),
}

# All available features
ALL_FEATURES = [
    "hour",
    "month",
    "dayofyear",
    "capacity_mw",
    "pred_norm",          # power_pred_final / capacity_mw
    "g_blend_pred",
    "clear_sky_ghi",
    "clear_sky_index",
    "scene_is_clear_peak",
    "scene_is_mid",
    "scene_is_low",
    "scene_is_night",
    "calibrated_ratio",
    "latitude",
    "longitude",
]

REQUIRED_FEATURES = ["hour", "month", "capacity_mw", "pred_norm"]


def load_baseline():
    """Load Round61 baseline with needed columns."""
    path = ROOT / "output/pv_pipeline/baselines/round61/distributed_predictions_final_full.pkl"
    print(f"[INFO] Loading baseline: {path}")
    cols_needed = [
        "time", "site_id", "split", "hour", "capacity_mw",
        "power_mw", "power_pred_final",
        "scene_v151", "g_blend_pred", "clear_sky_ghi",
        "calibrated_ratio",
    ]
    df = pd.read_pickle(path)
    # Keep only needed columns + add derivations
    for c in df.columns:
        if c not in cols_needed:
            df.drop(columns=[c], inplace=True)
    df["time"] = pd.to_datetime(df["time"])
    if "month" not in df.columns:
        df["month"] = df["time"].dt.month
    if "dayofyear" not in df.columns:
        df["dayofyear"] = df["time"].dt.dayofyear
    df["pred_norm"] = df["power_pred_final"] / df["capacity_mw"].clip(lower=1e-9)
    df["clear_sky_index"] = np.where(
        df["clear_sky_ghi"] > 1.0,
        (df["g_blend_pred"] / df["clear_sky_ghi"]).clip(0, 2),
        0.0
    )
    # Scene one-hot
    for s in ["clear_peak", "mid", "low", "night"]:
        df[f"scene_is_{s}"] = (df["scene_v151"] == s).astype(float)

    # Latitude/longitude from calibration_valid if available
    cal_path = ROOT / "output/pv_pipeline/calibration/calibration_valid.pkl"
    if cal_path.exists():
        try:
            cal = pd.read_pickle(cal_path)
            if "latitude" in cal.columns and "longitude" in cal.columns:
                site_geo = cal.groupby("site_id")[["latitude", "longitude"]].first()
                site_geo["latitude"] = site_geo["latitude"].fillna(0.0)
                site_geo["longitude"] = site_geo["longitude"].fillna(0.0)
                df = df.merge(site_geo, on="site_id", how="left")
                df["latitude"] = df["latitude"].fillna(0.0)
                df["longitude"] = df["longitude"].fillna(0.0)
        except Exception as e:
            print(f"  [WARN] Could not load site geo: {e}")
            df["latitude"] = 0.0
            df["longitude"] = 0.0
    else:
        df["latitude"] = 0.0
        df["longitude"] = 0.0

    # Residual target: capacity-normalized
    df["target_norm"] = df["power_mw"] / df["capacity_mw"].clip(lower=1e-9)
    df["residual_norm"] = df["target_norm"] - df["pred_norm"]

    print(f"[INFO] Baseline loaded: {len(df)} rows")
    return df


def build_features(df):
    """Build feature matrix."""
    feature_data = {}
    missing_features = []

    for feat in ALL_FEATURES:
        if feat in df.columns:
            vals = df[feat].values.astype(float)
            vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
            feature_data[feat] = vals
        else:
            missing_features.append(feat)
            feature_data[feat] = np.zeros(len(df), dtype=float)

    X = np.column_stack([feature_data[f] for f in ALL_FEATURES])
    used_features = [f for f in ALL_FEATURES if f not in missing_features]
    return X, used_features, missing_features


def train_ridge(X_train, y_train, X_valid, y_valid):
    """Train Ridge with scaling."""
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_valid_s = scaler.transform(X_valid)

    model = Ridge(alpha=1.0)
    model.fit(X_train_s, y_train)

    # Evaluate
    pred_train = model.predict(X_train_s)
    pred_valid = model.predict(X_valid_s)

    return {
        "model": model,
        "scaler": scaler,
        "train_mae": float(np.mean(np.abs(pred_train - y_train))),
        "valid_mae": float(np.mean(np.abs(pred_valid - y_valid))),
        "train_rmse": float(np.sqrt(np.mean((pred_train - y_train) ** 2))),
        "valid_rmse": float(np.sqrt(np.mean((pred_valid - y_valid) ** 2))),
    }


def train_lgb(X_train, y_train, X_valid, y_valid, feature_names):
    """Train LightGBM with early stopping."""
    dtrain = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
    dvalid = lgb.Dataset(X_valid, label=y_valid, feature_name=feature_names, reference=dtrain)

    params = {
        "objective": "regression",
        "metric": "mae",
        "n_estimators": 100,
        "num_leaves": 15,
        "max_depth": 4,
        "learning_rate": 0.05,
        "min_child_samples": 100,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 1.0,
        "reg_lambda": 1.0,
        "verbosity": -1,
        "force_row_wise": True,
        "n_jobs": -1,
    }

    callbacks = [lgb.early_stopping(20, verbose=False)]

    model = lgb.train(
        params,
        dtrain,
        valid_sets=[dvalid],
        callbacks=callbacks,
    )

    pred_train = model.predict(X_train)
    pred_valid = model.predict(X_valid)

    return {
        "model": model,
        "train_mae": float(np.mean(np.abs(pred_train - y_train))),
        "valid_mae": float(np.mean(np.abs(pred_valid - y_valid))),
        "train_rmse": float(np.sqrt(np.mean((pred_train - y_train) ** 2))),
        "valid_rmse": float(np.sqrt(np.mean((pred_valid - y_valid) ** 2))),
        "best_iteration": model.best_iteration,
    }


def main():
    print("=" * 60)
    print("Round63 分场景残差模型训练")
    print("=" * 60)

    # Load data
    df = load_baseline()

    # Filter to train+valid split and eval hours
    df_tv = df[df["split"].isin(["train", "valid"])].copy()
    df_tv = df_tv[df_tv["hour"].between(6, 19)].copy()
    print(f"[INFO] Train+Valid 6-19h: {len(df_tv)} rows")

    # Split train/valid
    df_train = df_tv[df_tv["split"] == "train"].copy()
    df_valid = df_tv[df_tv["split"] == "valid"].copy()
    print(f"[INFO] Train: {len(df_train)}, Valid: {len(df_valid)}")

    # Build features
    X_all, used_features, missing_features = build_features(df_tv)

    # Split indices
    train_idx = df_tv["split"] == "train"
    valid_idx = df_tv["split"] == "valid"

    X_train = X_all[train_idx.values]
    X_valid = X_all[valid_idx.values]
    residual_norm = df_tv["residual_norm"].values
    y_train = residual_norm[train_idx.values]
    y_valid = residual_norm[valid_idx.values]

    print(f"\n[INFO] Used features ({len(used_features)}): {used_features}")
    if missing_features:
        print(f"[WARN] Missing features (filled with 0): {missing_features}")

    # Save feature list
    feature_list = {
        "used_features": used_features,
        "missing_features": missing_features,
        "scenes": SCENES,
        "target": "residual_norm (capacity_normalized)",
        "base_prediction": "power_pred_final",
    }
    feature_path = OUT / "round63_feature_list.json"
    with open(feature_path, "w", encoding="utf-8") as f:
        json.dump(feature_list, f, ensure_ascii=False, indent=2)
    print(f"[OK] Feature list: {feature_path}")

    # Train per scene
    all_models = {}
    scene_summary = []

    for scene_name, scene_hours in SCENES.items():
        print(f"\n{'='*50}")
        print(f"Scene: {scene_name} (hours {scene_hours})")
        print(f"{'='*50}")

        # Filter for this scene
        mask_train = df_train["hour"].isin(scene_hours)
        mask_valid = df_valid["hour"].isin(scene_hours)

        X_tr = X_train[df_train["hour"].isin(scene_hours).values]
        X_va = X_valid[df_valid["hour"].isin(scene_hours).values]
        y_tr = y_train[df_train["hour"].isin(scene_hours).values]
        y_va = y_valid[df_valid["hour"].isin(scene_hours).values]

        n_tr = len(y_tr)
        n_va = len(y_va)
        print(f"  Train: {n_tr}, Valid: {n_va}")

        # Ridge
        print(f"  Training Ridge...")
        ridge_result = train_ridge(X_tr, y_tr, X_va, y_va)
        print(f"    train_mae={ridge_result['train_mae']:.4f}, valid_mae={ridge_result['valid_mae']:.4f}")
        print(f"    train_rmse={ridge_result['train_rmse']:.4f}, valid_rmse={ridge_result['valid_rmse']:.4f}")

        # LightGBM
        print(f"  Training LightGBM...")
        lgb_result = train_lgb(X_tr, y_tr, X_va, y_va, used_features)
        print(f"    train_mae={lgb_result['train_mae']:.4f}, valid_mae={lgb_result['valid_mae']:.4f}")
        print(f"    train_rmse={lgb_result['train_rmse']:.4f}, valid_rmse={lgb_result['valid_rmse']:.4f}")
        print(f"    best_iteration={lgb_result['best_iteration']}")

        # Feature importance (LightGBM)
        if scene_name == "day":
            importance = lgb_result["model"].feature_importance(importance_type="gain")
            feat_imp = sorted(zip(used_features, importance), key=lambda x: x[1], reverse=True)
            print(f"\n  Top 5 features (day scene, by gain):")
            for fname, imp in feat_imp[:5]:
                print(f"    {fname}: {imp:.1f}")

        scene_summary.append({
            "scene": scene_name,
            "hours": scene_hours,
            "train_samples": n_tr,
            "valid_samples": n_va,
            "ridge_train_mae": ridge_result["train_mae"],
            "ridge_valid_mae": ridge_result["valid_mae"],
            "ridge_valid_rmse": ridge_result["valid_rmse"],
            "lgb_train_mae": lgb_result["train_mae"],
            "lgb_valid_mae": lgb_result["valid_mae"],
            "lgb_valid_rmse": lgb_result["valid_rmse"],
            "lgb_best_iteration": lgb_result["best_iteration"],
        })

        all_models[scene_name] = {
            "ridge": ridge_result,
            "lgb": lgb_result,
        }

    # Save models
    models_path = OUT / "round63_residual_models.pkl"
    save_obj = {
        "all_models": all_models,
        "used_features": used_features,
        "scenes": SCENES,
    }
    with open(models_path, "wb") as f:
        pickle.dump(save_obj, f)
    print(f"\n[OK] Models saved: {models_path}")

    # Print summary table
    print(f"\n{'='*60}")
    print(f"{'Scene':<8} {'RidgeMAE':>10} {'RidgeRMSE':>11} {'LGBMAE':>10} {'LGBRMSE':>11} {'BestIter':>9}")
    print(f"{'='*60}")
    for row in scene_summary:
        print(
            f"{row['scene']:<8} "
            f"{row['ridge_valid_mae']:>10.4f} {row['ridge_valid_rmse']:>11.4f} "
            f"{row['lgb_valid_mae']:>10.4f} {row['lgb_valid_rmse']:>11.4f} "
            f"{row['lgb_best_iteration']:>9}"
        )
    print(f"{'='*60}")

    # Save scene summary
    pd.DataFrame(scene_summary).to_csv(
        OUT / "round63_scene_training_summary.csv", index=False, encoding="utf-8-sig"
    )
    print(f"[OK] Scene summary: {OUT / 'round63_scene_training_summary.csv'}")


if __name__ == "__main__":
    main()
