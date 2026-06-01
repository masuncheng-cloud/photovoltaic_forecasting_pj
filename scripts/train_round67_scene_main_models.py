#!/usr/bin/env python3
"""
train_round67_scene_main_models.py
==================================
训练 Round67 场景分组主模型候选。

候选模型：
  1. ridge_scene_main — 线性稳健模型（按 time_block 分组）
  2. hgb_scene_main — sklearn HistGradientBoosting（非线性，按 time_block 分组）
  3. lgb_scene_main — LightGBM（非线性，按 time_block 分组）
  4. scene_blend — valid 上场景融合
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yaml
import pickle
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
TRAINING_PKL = OUT / "round67" / "round67_training_table.parquet"


def rmse(y_true, y_pred):
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/round67_scene_main_model.yaml")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    cfg_path = ROOT / args.config
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    out_dir = Path(args.output_dir) if args.output_dir else OUT / "round67"
    model_dir = out_dir / "round67_model_files"
    model_dir.mkdir(parents=True, exist_ok=True)

    baseline_col = cfg["baseline_col"]

    print("=" * 60)
    print("Round67 Scene Main Model Training")
    print("=" * 60)

    # Load training data
    print(f"[INFO] Loading: {TRAINING_PKL}")
    df = pd.read_parquet(TRAINING_PKL)
    df["time"] = pd.to_datetime(df["time"])
    print(f"[INFO] Data: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    # Define feature columns (exclude identifiers, target, baseline)
    exclude = {"site_id", "time", "split", "hour", "time_block", "site_group",
               "y_norm", "power_mw", "capacity_mw", baseline_col, "baseline_norm",
               "cap_group", "zero_group"}
    feat_cols = [c for c in df.columns if c not in exclude]
    print(f"[INFO] Features ({len(feat_cols)}): {feat_cols}")

    # Prepare train/valid
    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()

    if len(train_df) == 0:
        print("[FAIL] No training data found")
        return

    time_blocks = list(cfg.get("time_blocks", {}).keys())
    print(f"[INFO] Time blocks: {time_blocks}")

    results = []
    model_store = {}  # name -> {block -> model}

    # ── Sample weights ───────────────────────────────────────────────
    w_cfg = cfg.get("sample_weights", {})
    noon_hrs = set(cfg.get("time_blocks", {}).get("noon", []))
    dawn_dusk_hrs = set(cfg.get("time_blocks", {}).get("dawn", [])
                        + cfg.get("time_blocks", {}).get("dusk", []))

    def compute_weight(row):
        w = w_cfg.get("base", 1.0)
        if row.get("hour", -1) in noon_hrs:
            w *= w_cfg.get("noon_hours_weight", 1.0)
        if row.get("time_block") in ("dawn", "dusk"):
            w *= w_cfg.get("dawn_dusk_weight", 1.0)
        if row.get("is_high_zero_site", 0) == 1:
            w *= w_cfg.get("high_zero_site_weight", 1.0)
        w = min(w, w_cfg.get("max_weight", 3.0))
        w = max(w, w_cfg.get("min_weight", 0.3))
        return w

    train_df["sample_weight"] = train_df.apply(compute_weight, axis=1)

    # ── Train per time_block ────────────────────────────────────────
    for block in time_blocks:
        block_train = train_df[train_df["time_block"] == block]
        block_valid = valid_df[valid_df["time_block"] == block]

        if len(block_train) < 100:
            print(f"[WARN] Block '{block}' has only {len(block_train)} train samples — skipping")
            continue

        print(f"\n[INFO] Block '{block}': train={len(block_train)}, valid={len(block_valid)}")

        # Convert features to numeric using pandas (handles NaT gracefully)
        X_train = pd.DataFrame(block_train[feat_cols]).apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)
        X_valid = pd.DataFrame(block_valid[feat_cols]).apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)

        y_train = np.asarray(block_train["y_norm"].values, dtype=float)
        w_train = np.asarray(block_train["sample_weight"].values, dtype=float)
        y_valid = np.asarray(block_valid["y_norm"].values, dtype=float)

        for model_name in ["ridge", "hgb", "lgb"]:
            if not cfg.get("models", {}).get(model_name, {}).get("enabled", False):
                continue

            key = f"{model_name}_{block}"
            print(f"  Training {key}...")

            try:
                if model_name == "ridge":
                    scaler = StandardScaler()
                    X_tr_s = scaler.fit_transform(X_train)
                    X_va_s = scaler.transform(X_valid)
                    model = Ridge(alpha=1.0)
                    model.fit(X_tr_s, y_train, sample_weight=w_train)
                    pred_tr = model.predict(X_tr_s)
                    pred_va = model.predict(X_va_s)
                    model_store.setdefault("ridge", {})[block] = {"model": model, "scaler": scaler}

                elif model_name == "hgb":
                    model = HistGradientBoostingRegressor(
                        max_iter=300, max_depth=6, learning_rate=0.05,
                        l2_regularization=0.1, random_state=42,
                        early_stopping=True, validation_fraction=0.1,
                        n_iter_no_change=20
                    )
                    model.fit(X_train, y_train, sample_weight=w_train)
                    pred_tr = model.predict(X_train)
                    pred_va = model.predict(X_valid)
                    model_store.setdefault("hgb", {})[block] = model

                elif model_name == "lgb":
                    lgb_data = lgb.Dataset(X_train, label=y_train, weight=w_train)
                    lgb_val = lgb.Dataset(X_valid, label=y_valid, reference=lgb_data)
                    params = {
                        "objective": "regression",
                        "metric": "rmse",
                        "learning_rate": 0.05,
                        "num_leaves": 31,
                        "max_depth": 6,
                        "reg_lambda": 0.1,
                        "verbosity": -1,
                    }
                    callbacks = [lgb.early_stopping(20), lgb.log_evaluation(0)]
                    model = lgb.train(
                        params, lgb_data, num_boost_round=300,
                        valid_sets=[lgb_val], callbacks=callbacks
                    )
                    pred_tr = model.predict(X_train)
                    pred_va = model.predict(X_valid)
                    model_store.setdefault("lgb", {})[block] = model

                rmse_tr = rmse(y_train, pred_tr)
                rmse_va = rmse(y_valid, pred_va)
                print(f"    {key}: train_RMSE={rmse_tr:.4f}, valid_RMSE={rmse_va:.4f}")

                results.append({
                    "model": model_name, "block": block,
                    "train_rmse_norm": rmse_tr, "valid_rmse_norm": rmse_va,
                    "n_train": len(block_train), "n_valid": len(block_valid),
                })

            except Exception as e:
                print(f"  [FAIL] {key}: {e}")
                results.append({
                    "model": model_name, "block": block,
                    "train_rmse_norm": None, "valid_rmse_norm": None,
                    "error": str(e),
                })

    # ── Evaluate candidates on valid ────────────────────────────────
    print("\n[INFO] Evaluating candidates on valid set...")

    # Apply predictions to valid_df for each candidate
    for model_name, blocks in model_store.items():
        for block, model_obj in blocks.items():
            block_valid = valid_df[valid_df["time_block"] == block].copy()
            X_v = np.nan_to_num(block_valid[feat_cols].values.astype(float), nan=0.0)
            if model_name == "ridge":
                X_v = model_obj["scaler"].transform(X_v)
                pred = model_obj["model"].predict(X_v)
            elif model_name == "lgb":
                pred = model_obj.predict(X_v)
            else:
                pred = model_obj.predict(X_v)

            cap = block_valid["capacity_mw"].values
            block_valid["pred_mw"] = np.clip(pred * cap, 0, cap)
            mask = valid_df["time_block"] == block
            col = f"pred_{model_name}_block_{block}"
            if col not in valid_df.columns:
                valid_df[col] = np.nan
            valid_df.loc[mask, col] = block_valid["pred_mw"].values

    # Compute full valid metrics for each candidate
    for model_name in model_store:
        pred_cols = [c for c in valid_df.columns if c.startswith(f"pred_{model_name}_block_")]
        if not pred_cols:
            continue
        valid_df[f"pred_{model_name}_combined"] = valid_df[pred_cols].mean(axis=1)

    # Compute metrics for each candidate
    candidate_metrics = []
    cap_col = "capacity_mw"
    actual = valid_df["power_mw"].values

    for model_name in model_store:
        combined_col = f"pred_{model_name}_combined"
        if combined_col not in valid_df.columns:
            continue
        pred = valid_df[combined_col].fillna(valid_df[baseline_col]).values

        # Compute site-wise NRMSE
        site_rmses = []
        for sid, sdf in valid_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            r = rmse(sdf["power_mw"].values, sdf[combined_col].fillna(valid_df.loc[sdf.index, baseline_col]).values)
            site_rmses.append(r / cap * 100)
        sm_nrmse = float(np.mean(site_rmses))

        city_rmse = rmse(actual, pred)
        city_cap = float(valid_df.groupby("time")["capacity_mw"].sum().mean())
        city_nrmse = city_rmse / city_cap * 100 if city_cap > 0 else 0

        bias = float((pred - actual).mean())

        candidate_metrics.append({
            "candidate": model_name,
            "sm_nrmse_valid": round(sm_nrmse, 4),
            "city_nrmse_valid": round(city_nrmse, 4),
            "bias_valid": round(bias, 4),
        })

    # Also compute baseline metrics on valid
    baseline_pred = valid_df[baseline_col].values
    bl_rmse = rmse(actual, baseline_pred)
    bl_cap = float(valid_df.groupby("time")["capacity_mw"].sum().mean())
    bl_sm_nrmse = None
    bl_city_nrmse = bl_rmse / bl_cap * 100 if bl_cap > 0 else 0
    bl_bias = float((baseline_pred - actual).mean())

    candidate_metrics.insert(0, {
        "candidate": "round64_final",
        "sm_nrmse_valid": bl_sm_nrmse,
        "city_nrmse_valid": round(bl_city_nrmse, 4),
        "bias_valid": round(bl_bias, 4),
    })

    # Select best model
    best = min(
        [m for m in candidate_metrics if m["city_nrmse_valid"] is not None],
        key=lambda x: x["city_nrmse_valid"]
    )
    print(f"\n[INFO] Best candidate on valid: {best['candidate']} (city_nrmse={best['city_nrmse_valid']:.4f})")

    # Save model store
    model_path = model_dir / "model_store.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "models": model_store,
            "feat_cols": feat_cols,
            "cfg": cfg,
            "baseline_col": baseline_col,
        }, f)
    print(f"[OK] Model store: {model_path}")

    # Save results
    sum_df = pd.DataFrame(results)
    sum_path = out_dir / "round67_model_training_summary.csv"
    sum_df.to_csv(sum_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Training summary: {sum_path}")

    metrics_df = pd.DataFrame(candidate_metrics)
    metrics_path = out_dir / "round67_valid_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Valid metrics: {metrics_path}")

    print(f"\n[OK] Training complete")
    print(f"\nCandidate Metrics on Valid:")
    print(metrics_df.to_string(index=False))


if __name__ == "__main__":
    main()
