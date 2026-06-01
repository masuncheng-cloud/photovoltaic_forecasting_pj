#!/usr/bin/env python3
"""
train_round69_performance_candidates.py
==================================
训练 Round69 性能提升候选模型。
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
    "dawn": [6, 7, 8], "morning": [9, 10],
    "noon": [11, 12, 13, 14], "afternoon": [15, 16], "dusk": [17, 18, 19],
}

FEAT_13 = ["month", "dayofyear", "pr_median", "bias", "zero_ratio",
           "clear_sky_ghi", "clear_sky_index", "g_blend_pred",
           "latitude", "longitude", "quality_score", "scene_v151"]

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
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    return float(math.sqrt(float(np.mean((p - a) ** 2))))


def compute_site_mean_nrmse(df, pred_col):
    rmses = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        rmses.append(r)
    return float(np.mean(rmses))


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum")
    )
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100


def train_lgb(df_train, feat_cols, target_col, weights=None, n_est=500, lr=0.05, extra_kw=None):
    X = prep_X(df_train, feat_cols)
    y = df_train[target_col].values.astype(float)
    params = dict(
        n_estimators=n_est, learning_rate=lr, num_leaves=31, max_depth=7,
        min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=0.1, random_state=42, n_jobs=-1, verbose=-1,
    )
    if extra_kw:
        params.update(extra_kw)
    model = LGBMRegressor(**params)
    model.fit(X, y, sample_weight=weights)
    return model


def main():
    print("=" * 60)
    print("Round69 Performance Candidate Training")
    print("=" * 60)

    df = pd.read_parquet(TBL)
    df["time"] = pd.to_datetime(df["time"])
    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()
    print(f"  Train: {len(train_df)}, Valid: {len(valid_df)}, Test: {len(test_df)}")

    pred_cols = {}   # name -> (col_name, model_or_models_dict)

    # ── Candidate 1: block lgb ─────────────────────────────────────────
    print("\n[CAND1] round69_block_lgb...")
    col1 = "power_pred_round69_block_lgb"
    train_df[col1] = train_df["power_pred_final"].values.copy()
    valid_df[col1] = valid_df["power_pred_final"].values.copy()
    test_df[col1] = test_df["power_pred_final"].values.copy()
    block_models = {}

    for blk in TIME_BLOCKS:
        blk_train = train_df[train_df["hour"].isin(BLOCK_HOURS[blk])].copy()
        blk_valid = valid_df[valid_df["hour"].isin(BLOCK_HOURS[blk])].copy()
        blk_test  = test_df[test_df["hour"].isin(BLOCK_HOURS[blk])].copy()

        model = train_lgb(blk_train, FEAT_13, "y_norm")
        p_valid = model.predict(prep_X(blk_valid, FEAT_13))
        p_test  = model.predict(prep_X(blk_test, FEAT_13))

        cap_v = blk_valid["capacity_mw"].values.astype(float)
        cap_t = blk_test["capacity_mw"].values.astype(float)

        valid_df.loc[blk_valid.index, col1] = np.clip(p_valid * cap_v, 0, cap_v)
        test_df.loc[blk_test.index, col1]  = np.clip(p_test  * cap_t, 0, cap_t)
        block_models[blk] = model
        print(f"  {blk}: n_train={len(blk_train)}")

    pred_cols[col1] = block_models
    print(f"  Block lgb done")

    # ── Candidate 2: noon-weighted lgb ─────────────────────────────────
    print("\n[CAND2] round69_noon_lgb...")
    col2 = "power_pred_round69_noon_lgb"
    weights = pd.Series(1.0, index=train_df.index)
    weights[train_df["hour"].between(10, 14)] = 2.0
    # high error sites also get extra weight
    weights[train_df["site_nrmse_train"] > 12] *= 1.5

    model_noon = train_lgb(train_df, FEAT_EXT, "y_norm", weights=weights.values)

    p_valid = model_noon.predict(prep_X(valid_df, FEAT_EXT))
    p_test  = model_noon.predict(prep_X(test_df, FEAT_EXT))
    cap_v = valid_df["capacity_mw"].values.astype(float)
    cap_t = test_df["capacity_mw"].values.astype(float)
    valid_df[col2] = np.clip(p_valid * cap_v, 0, cap_v)
    test_df[col2]  = np.clip(p_test  * cap_t, 0, cap_t)
    pred_cols[col2] = model_noon
    print(f"  Noon lgb done")

    # ── Candidate 3: residual lgb ───────────────────────────────────────
    print("\n[CAND3] round69_residual_lgb...")
    col3 = "power_pred_round69_residual_lgb"
    train_df["residual_tgt"] = (train_df["power_mw"] - train_df["power_pred_final"]) / train_df["capacity_mw"].clip(lower=0.1)
    valid_df["residual_tgt"] = (valid_df["power_mw"] - valid_df["power_pred_final"]) / valid_df["capacity_mw"].clip(lower=0.1)
    test_df["residual_tgt"]  = (test_df["power_mw"]  - test_df["power_pred_final"])  / test_df["capacity_mw"].clip(lower=0.1)

    model_res = train_lgb(train_df, FEAT_EXT, "residual_tgt")

    p_valid = model_res.predict(prep_X(valid_df, FEAT_EXT))
    p_test  = model_res.predict(prep_X(test_df, FEAT_EXT))
    cap_v = valid_df["capacity_mw"].values.astype(float)
    cap_t = test_df["capacity_mw"].values.astype(float)
    base_v = valid_df["power_pred_final"].values
    base_t = test_df["power_pred_final"].values
    valid_df[col3] = np.clip(base_v + p_valid * cap_v, 0, cap_v)
    test_df[col3]  = np.clip(base_t + p_test  * cap_t, 0, cap_t)
    pred_cols[col3] = model_res
    print(f"  Residual lgb done")

    # ── Candidate 4: high-error site expert ─────────────────────────────
    print("\n[CAND4] round69_high_error_lgb...")
    col4 = "power_pred_round69_high_error_lgb"
    train_df[col4] = train_df["power_pred_final"].values.copy()
    valid_df[col4] = valid_df["power_pred_final"].values.copy()
    test_df[col4]  = test_df["power_pred_final"].values.copy()

    # Identify high-error sites
    site_nrmse = {}
    for sid, sdf in train_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        site_nrmse[str(sid)] = rmse(sdf["power_mw"].values, sdf["power_pred_final"].values) / cap * 100
    he_sites = [s for s, n in site_nrmse.items() if n > 12]
    print(f"  High-error sites: {he_sites[:5]}... ({len(he_sites)} total)")

    if he_sites:
        train_he = train_df[train_df["site_id"].isin(he_sites)].copy()
        valid_he = valid_df[valid_df["site_id"].isin(he_sites)].copy()
        test_he  = test_df[test_df["site_id"].isin(he_sites)].copy()
        if len(train_he) > 1000:
            model_he = train_lgb(train_he, FEAT_EXT, "y_norm")
            p_valid = model_he.predict(prep_X(valid_he, FEAT_EXT))
            p_test  = model_he.predict(prep_X(test_he, FEAT_EXT))
            cap_v = valid_he["capacity_mw"].values.astype(float)
            cap_t = test_he["capacity_mw"].values.astype(float)
            valid_df.loc[valid_he.index, col4] = np.clip(p_valid * cap_v, 0, cap_v)
            test_df.loc[test_he.index, col4]   = np.clip(p_test  * cap_t, 0, cap_t)
            pred_cols[col4] = {"model": model_he, "high_error_sites": he_sites}
            print(f"  High-error expert trained ({len(train_he)} rows)")
    print(f"  High-error lgb done")

    # ── Feature importance ───────────────────────────────────────────────
    print("\n[Feature Importance]")
    for col, obj in pred_cols.items():
        if hasattr(obj, "feature_importances_"):
            fi = dict(zip(FEAT_EXT, obj.feature_importances_))
            top = sorted(fi.items(), key=lambda x: -x[1])[:5]
            print(f"  {col}: {top}")
            break

    fi_df = pd.DataFrame({"feature": FEAT_EXT, "importance": model_noon.feature_importances_})
    fi_df = fi_df.sort_values("importance", ascending=False)
    fi_df.to_csv(ROUND69 / "round69_feature_importance.csv", index=False, encoding="utf-8-sig")

    # Model training summary
    sum_rows = [{"candidate": "round69_block_lgb", "n_models": len(block_models)}]
    for col in [col2, col3, col4]:
        sum_rows.append({"candidate": col.replace("power_pred_", ""), "n_models": 1})
    pd.DataFrame(sum_rows).to_csv(ROUND69 / "round69_model_training_summary.csv", index=False, encoding="utf-8-sig")

    # ── Save candidates pkl ────────────────────────────────────────────
    cand_df = pd.concat([train_df, valid_df, test_df], ignore_index=True)
    pred_cols_to_save = {
        "power_pred_final": "power_pred_final",
        col1: col1, col2: col2, col3: col3, col4: col4,
    }
    # Only keep needed columns
    keep = ["site_id", "time", "split", "hour", "time_block", "site_group",
            "y_norm", "power_mw", "capacity_mw", "power_pred_final",
            col1, col2, col3, col4]
    keep = [c for c in keep if c in cand_df.columns]
    cand_df = cand_df[keep]
    cand_df.to_pickle(ROUND69 / "round69_candidates.pkl")
    print(f"\n[OK] Candidates: {ROUND69 / 'round69_candidates.pkl'} ({len(cand_df)} rows)")

    # ── Quick metrics ─────────────────────────────────────────────────
    print("\n[Valid Metrics Summary]")
    base_col = "power_pred_final"
    base_sm = compute_site_mean_nrmse(valid_df, base_col)
    base_city = compute_city_nrmse(valid_df, base_col)
    print(f"  Baseline: sm={base_sm:.4f}%, city={base_city:.4f}%")

    for col in [col1, col2, col3, col4]:
        sm = compute_site_mean_nrmse(valid_df, col)
        city = compute_city_nrmse(valid_df, col)
        delta_sm = sm - base_sm
        delta_city = city - base_city
        print(f"  {col}: sm={sm:.4f}% ({delta_sm:+.4f}), city={city:.4f}% ({delta_city:+.4f})")

    print("\n[DONE] Round69 training complete")


if __name__ == "__main__":
    main()
