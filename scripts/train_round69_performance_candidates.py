#!/usr/bin/env python3
"""
train_round69_performance_candidates.py
==================================
训练 Round69 性能提升候选模型。

候选：
  1. round69_block_lgb     — 分时段 lgb (5 blocks)，使用 round67 原始特征
  2. round69_noon_lgb      — 10-14h 加权 lgb，使用扩展特征
  3. round69_residual_lgb  — 预测残差，round68 blend 作为 base
  4. round69_high_error_lgb — 高误差站点专用 lgb
"""

from pathlib import Path
import math
import numpy as np
import pandas as pd
import pickle
import warnings
from lightgbm import LGBMRegressor

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
ROUND69 = OUT / "round69"
TBL = ROUND69 / "round69_training_table.parquet"
MODEL_DIR = ROUND69 / "round69_model_files"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

TIME_BLOCKS = ["dawn", "morning", "noon", "afternoon", "dusk"]
BLOCK_HOURS = {
    "dawn": [6, 7, 8],
    "morning": [9, 10],
    "noon": [11, 12, 13, 14],
    "afternoon": [15, 16],
    "dusk": [17, 18, 19],
}

# Round67 original 13 features (for block model)
FEAT_13 = ["month", "dayofyear", "pr_median", "bias", "zero_ratio",
           "clear_sky_ghi", "clear_sky_index", "g_blend_pred",
           "latitude", "longitude", "quality_score", "scene_v151"]

# Extended features (for noon model)
FEAT_EXT = ["month", "dayofyear", "latitude", "longitude",
            "hour_sin", "hour_cos", "month_sin", "month_cos",
            "clear_sky_ghi", "clear_sky_index", "g_blend_pred",
            "solar_elevation", "ghi_ratio",
            "pr_median", "quality_score", "bias", "zero_ratio",
            "site_nrmse_train", "site_bias_train", "site_zero_ratio_train",
            "hour_x_clear_sky", "hour_x_gblend",
            "pred_lgb_norm", "pred_hgb_norm", "pred_ridge_norm",
            "scene_v151", "scene_v151_low", "scene_v151_mid",
            "scene_v151_night", "scene_v151_unknown"]


def prep_X(df, feat_cols):
    X = pd.DataFrame(df[feat_cols]).apply(pd.to_numeric, errors="coerce").fillna(0)
    return X.values.astype(float)


def rmse(actual, pred):
    return float(math.sqrt(float(np.mean((np.asarray(actual, dtype=float) - np.asarray(pred, dtype=float)) ** 2))))


def train_and_predict(df_train, df_eval, feat_cols, target_col, weights=None, lgb_kw=None):
    """Train lgb on train, predict eval separately."""
    X_train = prep_X(df_train, feat_cols)
    y_train = df_train[target_col].values.astype(float)
    X_eval = prep_X(df_eval, feat_cols)

    params = dict(
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=7,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    if lgb_kw:
        params.update(lgb_kw)

    model = LGBMRegressor(**params)
    model.fit(X_train, y_train, sample_weight=weights)
    pred_eval = model.predict(X_eval)
    return model, pred_eval


def main():
    print("=" * 60)
    print("Round69 Performance Candidate Training")
    print("=" * 60)

    # Load training table
    print("\n[INFO] Loading training table...")
    df = pd.read_parquet(TBL)
    df["time"] = pd.to_datetime(df["time"])
    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()
    print(f"  Train: {len(train_df)}, Valid: {len(valid_df)}, Test: {len(test_df)}")

    results = {}
    training_rows = []

    # ── Candidate 1: round69_block_lgb (分时段专家) ───────────────────
    print("\n[CAND1] round69_block_lgb (block experts)...")
    pred_block_train = train_df["power_pred_final"].values.copy()
    pred_block_valid = valid_df["power_pred_final"].values.copy()
    pred_block_test = test_df["power_pred_final"].values.copy()

    block_models = {}
    for blk in TIME_BLOCKS:
        blk_hours = BLOCK_HOURS[blk]
        blk_train = train_df[train_df["hour"].isin(blk_hours)].copy()
        blk_valid = valid_df[valid_df["hour"].isin(blk_hours)].copy()
        blk_test = test_df[test_df["hour"].isin(blk_hours)].copy()

        model, p_train, p_valid = train_and_predict(
            blk_train, pd.concat([blk_valid, blk_test]),
            FEAT_13, "y_norm"
        )
        p_valid = p_valid[:len(blk_valid)]
        p_test = p_valid[len(blk_valid):] if False else p_valid[len(blk_valid):]
        # Re-predict
        blk_test2 = test_df[test_df["hour"].isin(blk_hours)].copy()
        X_test = prep_X(blk_test2, FEAT_13)
        p_test = model.predict(X_test)

        # Convert to MW
        cap_train = blk_train["capacity_mw"].values.astype(float)
        cap_valid = blk_valid["capacity_mw"].values.astype(float)
        cap_test = blk_test2["capacity_mw"].values.astype(float)

        pred_train_blk = np.clip(p_train * cap_train, 0, cap_train)
        pred_valid_blk = np.clip(p_valid * cap_valid, 0, cap_valid)
        pred_test_blk = np.clip(p_test * cap_test, 0, cap_test)

        # Assign back
        train_idx = train_df.index[train_df["hour"].isin(blk_hours)]
        valid_idx = valid_df.index[valid_df["hour"].isin(blk_hours)]
        test_idx = test_df.index[test_df["hour"].isin(blk_hours)]

        pred_block_train[train_idx] = pred_train_blk
        pred_block_valid[valid_idx] = pred_valid_blk
        pred_block_test[test_idx] = pred_test_blk

        block_models[blk] = model
        tr_rmse = rmse(blk_train["power_mw"].values, pred_train_blk)
        print(f"  {blk}: train_rmse={tr_rmse:.4f}")

    # Store
    col1 = "power_pred_round69_block_lgb"
    train_df[col1] = pred_block_train
    valid_df[col1] = pred_block_valid
    test_df[col1] = pred_block_test
    results[col1] = {"models": block_models}
    print(f"  Block lgb done")

    # ── Candidate 2: round69_noon_lgb (10-14h 加权) ─────────────────
    print("\n[CAND2] round69_noon_lgb (noon weighted)...")
    train_df["sample_weight"] = 1.0
    is_noon = train_df["hour"].between(10, 14)
    train_df.loc[is_noon, "sample_weight"] = 2.0
    is_high_error = train_df["site_nrmse_train"] > 12
    train_df.loc[is_high_error, "sample_weight"] *= 1.5

    model_noon, p_train_noon, _ = train_and_predict(
        train_df,
        pd.concat([valid_df, test_df]),
        FEAT_EXT, "y_norm",
        weights=train_df["sample_weight"].values
    )
    n_train = len(train_df)
    n_valid = len(valid_df)
    p_valid_noon = p_train_noon[n_train:n_train + n_valid]
    p_test_noon = p_train_noon[n_train + n_valid:]

    cap_train = train_df["capacity_mw"].values.astype(float)
    cap_valid = valid_df["capacity_mw"].values.astype(float)
    cap_test = test_df["capacity_mw"].values.astype(float)

    col2 = "power_pred_round69_noon_lgb"
    train_df[col2] = np.clip(p_train_noon[:n_train] * cap_train, 0, cap_train)
    valid_df[col2] = np.clip(p_valid_noon * cap_valid, 0, cap_valid)
    test_df[col2] = np.clip(p_test_noon * cap_test, 0, cap_test)
    results[col2] = {"model": model_noon}
    tr_rmse = rmse(train_df["power_mw"].values, train_df[col2].values)
    print(f"  Noon lgb: train_rmse={tr_rmse:.4f}")

    # ── Candidate 3: round69_residual_lgb ───────────────────────────
    print("\n[CAND3] round69_residual_lgb (residual modeling)...")
    # Predict residual_norm using round68 blend as implicit baseline
    train_df["residual_target"] = (train_df["power_mw"] - train_df["power_pred_final"]) / train_df["capacity_mw"].clip(lower=0.1)
    valid_df["residual_target"] = (valid_df["power_mw"] - valid_df["power_pred_final"]) / valid_df["capacity_mw"].clip(lower=0.1)
    test_df["residual_target"] = (test_df["power_mw"] - test_df["power_pred_final"]) / test_df["capacity_mw"].clip(lower=0.1)

    model_res, p_train_res, _ = train_and_predict(
        train_df,
        pd.concat([valid_df, test_df]),
        FEAT_EXT, "residual_target"
    )
    n_train = len(train_df)
    n_valid = len(valid_df)
    p_valid_res = p_train_res[n_train:n_train + n_valid]
    p_test_res = p_train_res[n_train + n_valid:]

    col3 = "power_pred_round69_residual_lgb"
    train_df[col3] = np.clip(
        train_df["power_pred_final"].values + p_train_res[:n_train] * train_df["capacity_mw"].values.clip(lower=0.1),
        0, train_df["capacity_mw"].values
    )
    valid_df[col3] = np.clip(
        valid_df["power_pred_final"].values + p_valid_res * valid_df["capacity_mw"].values.clip(lower=0.1),
        0, valid_df["capacity_mw"].values
    )
    test_df[col3] = np.clip(
        test_df["power_pred_final"].values + p_test_res * test_df["capacity_mw"].values.clip(lower=0.1),
        0, test_df["capacity_mw"].values
    )
    results[col3] = {"model": model_res}
    tr_rmse = rmse(train_df["power_mw"].values, train_df[col3].values)
    print(f"  Residual lgb: train_rmse={tr_rmse:.4f}")

    # ── Candidate 4: round69_high_error_lgb ────────────────────────
    print("\n[CAND4] round69_high_error_lgb (high error site experts)...")

    # Identify high error sites from training stats
    site_nrmse = train_df.groupby("site_id").apply(
        lambda s: rmse(s["power_mw"].values, s["power_pred_final"].values) /
                  float(s["capacity_mw"].iloc[0]) * 100
    )
    high_error_sites = set(site_nrmse[site_nrmse > 12].index)
    print(f"  High error sites: {len(high_error_sites)}")

    col4 = "power_pred_round69_high_error_lgb"
    train_df[col4] = train_df["power_pred_final"].values.copy()
    valid_df[col4] = valid_df["power_pred_final"].values.copy()
    test_df[col4] = test_df["power_pred_final"].values.copy()

    # Train high-error expert on high-error sites
    train_he = train_df[train_df["site_id"].isin(high_error_sites)].copy()
    valid_he = valid_df[valid_df["site_id"].isin(high_error_sites)].copy()
    test_he = test_df[test_df["site_id"].isin(high_error_sites)].copy()

    if len(train_he) > 1000:
        model_he, p_train_he, _ = train_and_predict(
            train_he, pd.concat([valid_he, test_he]),
            FEAT_EXT, "y_norm"
        )
        n_he = len(train_he)
        n_vhe = len(valid_he)
        p_vhe = p_train_he[n_he:n_he + n_vhe]
        p_the = p_train_he[n_he + n_vhe:]

        cap_he_train = train_he["capacity_mw"].values.astype(float)
        cap_he_valid = valid_he["capacity_mw"].values.astype(float)
        cap_he_test = test_he["capacity_mw"].values.astype(float)

        pred_he_train = np.clip(p_train_he[:n_he] * cap_he_train, 0, cap_he_train)
        pred_he_valid = np.clip(p_vhe * cap_he_valid, 0, cap_he_valid)
        pred_he_test = np.clip(p_the * cap_he_test, 0, cap_he_test)

        train_df.loc[train_df["site_id"].isin(high_error_sites), col4] = pred_he_train
        valid_df.loc[valid_df["site_id"].isin(high_error_sites), col4] = pred_he_valid
        test_df.loc[test_df["site_id"].isin(high_error_sites), col4] = pred_he_test
        results[col4] = {"model": model_he, "high_error_sites": list(high_error_sites)}
        tr_rmse = rmse(train_he["power_mw"].values, pred_he_train)
        print(f"  High-error lgb: train_rmse={tr_rmse:.4f}")
    else:
        print("  Skipped: not enough high-error training data")
        results[col4] = {}

    # ── Save training summary ──────────────────────────────────────
    print("\n[INFO] Computing training summaries...")

    train_summary = []
    for col, res in results.items():
        if not res:
            continue
        label = col.replace("power_pred_", "")
        for blk, mdl in res.get("models", {}).items():
            if hasattr(mdl, "feature_importances_"):
                fi = dict(zip(FEAT_13, mdl.feature_importances_))
                top_feat = sorted(fi.items(), key=lambda x: -x[1])[:5]
                train_summary.append({
                    "candidate": label,
                    "time_block": blk,
                    "n_train": len(train_df[train_df["hour"].isin(BLOCK_HOURS.get(blk, []))]),
                    "top_feature": top_feat[0][0] if top_feat else "N/A",
                    "top_importance": top_feat[0][1] if top_feat else 0,
                })
        if "model" in res:
            if hasattr(res["model"], "feature_importances_"):
                fi = dict(zip(FEAT_EXT, res["model"].feature_importances_))
                top_feat = sorted(fi.items(), key=lambda x: -x[1])[:5]
                train_summary.append({
                    "candidate": label,
                    "time_block": "global",
                    "n_train": len(train_df),
                    "top_feature": top_feat[0][0] if top_feat else "N/A",
                    "top_importance": top_feat[0][1] if top_feat else 0,
                })

    summary_df = pd.DataFrame(train_summary)
    summary_df.to_csv(ROUND69 / "round69_model_training_summary.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Training summary: {ROUND69 / 'round69_model_training_summary.csv'}")

    # Feature importance for noon model
    if "model" in results.get(col2, {}):
        fi_df = pd.DataFrame({
            "feature": FEAT_EXT,
            "importance": results[col2]["model"].feature_importances_
        }).sort_values("importance", ascending=False)
        fi_df.to_csv(ROUND69 / "round69_feature_importance.csv", index=False, encoding="utf-8-sig")
        print(f"[OK] Feature importance: {ROUND69 / 'round69_feature_importance.csv'}")

    # ── Save model store ──────────────────────────────────────────
    store = {
        "baseline_col": "power_pred_final",
        "feat_cols_13": FEAT_13,
        "feat_cols_ext": FEAT_EXT,
        "candidates": {
            col: {k: v for k, v in r.items() if k != "model"}
            for col, r in results.items()
        },
    }
    with open(MODEL_DIR / "model_store.pkl", "wb") as f:
        pickle.dump(store, f)
    print(f"[OK] Model store: {MODEL_DIR / 'model_store.pkl'}")

    # ── Quick valid metrics ───────────────────────────────────────
    print("\n[Valid Metrics Summary]")
    base_col = "power_pred_final"
    for col in [c for c in results if results[c]]:
        valid_actual = valid_df["power_mw"].values.astype(float)
        valid_pred = valid_df[col].values.astype(float)
        cap_sum = float(valid_df[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
        agg = valid_df.groupby("time", as_index=False).agg(
            a=("power_mw", "sum"), p=(col, "sum")
        )
        city_rmse = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100
        site_rmses = []
        for sid, sdf in valid_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            r = rmse(sdf["power_mw"].values, sdf[col].values) / cap * 100
            site_rmses.append(r)
        sm_nrmse = float(np.mean(site_rmses))
        base_actual = valid_df[base_col].values
        base_rmse = rmse(valid_actual, base_actual)
        delta = sm_nrmse - (float(np.mean([
            rmse(sdf["power_mw"].values, sdf[base_col].values) / float(sdf["capacity_mw"].iloc[0]) * 100
            for _, sdf in valid_df.groupby("site_id") if float(sdf["capacity_mw"].iloc[0]) > 0
        ])))
        print(f"  {col}: sm_nrmse={sm_nrmse:.4f}%, city_nrmse={city_rmse:.4f}%, delta={delta:+.4f}pp")

    print("\n[DONE] Round69 training complete")


if __name__ == "__main__":
    main()
