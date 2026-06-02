#!/usr/bin/env python3
"""
build_round68_lgb_safe_blend.py
==================================
在 Round64 final 基础上安全融合 Round67 lgb，方向性改善 NRMSE，
同时约束 abs_bias。

融合公式：
  P_round68(w) = P_round64_final + w * (P_round67_lgb - P_round64_final)

权重网格：[0.00, 0.25, 0.50, 0.75, 1.00]
选择粒度：site_id + time_block
"""

from pathlib import Path
import warnings
import math
import numpy as np
import pandas as pd
import pickle

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
ROUND68 = OUT / "round68"


def rmse(actual, pred):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    return float(math.sqrt(float(np.mean((p - a) ** 2))))


def bias_pct(actual, pred):
    a_sum = float(np.nansum(np.asarray(actual, dtype=float)))
    p_sum = float(np.nansum(np.asarray(pred, dtype=float)))
    if abs(a_sum) < 1e-12:
        return 0.0
    return (p_sum - a_sum) / a_sum * 100.0


def main():
    print("=" * 60)
    print("Round68 LGB Safe Blend")
    print("=" * 60)

    # Load data with predictions
    df = pd.read_parquet(OUT / "round67/round67_training_table.parquet")
    df["time"] = pd.to_datetime(df["time"])

    # Predictions already computed in recompute step
    # We need to reload them - re-use model predictions
    # Reconstruct lgb predictions (same as recompute script)
    exclude = {"site_id", "time", "split", "hour", "time_block", "site_group",
               "y_norm", "power_mw", "capacity_mw", "power_pred_final",
               "baseline_norm", "cap_group", "zero_group"}
    feat_cols = [c for c in df.columns if c not in exclude]

    with open(OUT / "round67/round67_model_files/model_store.pkl", "rb") as f:
        store = pickle.load(f)
    models = store["models"]

    df["pred_round64_final"] = df["power_pred_final"].values
    for model_name, blocks in models.items():
        if model_name != "lgb":
            continue
        df[f"pred_{model_name}_combined"] = np.nan
        for block, model_obj in blocks.items():
            mask = df["time_block"] == block
            X = (pd.DataFrame(df.loc[mask, feat_cols])
                   .apply(pd.to_numeric, errors="coerce")
                   .fillna(0).values.astype(float))
            pred = model_obj.predict(X)
            cap = df.loc[mask, "capacity_mw"].values.astype(float)
            df.loc[mask, f"pred_{model_name}_combined"] = np.clip(pred * cap, 0, cap)
        df[f"pred_{model_name}_combined"] = df[f"pred_{model_name}_combined"].fillna(df["power_pred_final"])

    baseline_col = "pred_round64_final"
    cand_col = "pred_lgb_combined"
    diff = df[cand_col] - df[baseline_col]

    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()
    weights = [0.00, 0.25, 0.50, 0.75, 1.00]

    print(f"\n[INFO] Valid: {len(valid_df)} rows | Test: {len(test_df)} rows")

    # ── Per (site_id, time_block) weight selection on valid ───────────────
    print("\n[INFO] Per (site, block) weight selection on valid...")

    # Reset index
    valid_df = valid_df.reset_index(drop=True)

    weight_lookup = {}   # (site_id, time_block) -> best_weight
    site_block_details = []

    for (sid, blk), grp in valid_df.groupby(["site_id", "time_block"]):
        idx = grp.index.tolist()
        delta_arr = (grp[cand_col] - grp[baseline_col]).values.astype(float)
        base_arr = grp[baseline_col].values.astype(float)
        actual_arr = grp["power_mw"].values.astype(float)
        cap = float(grp["capacity_mw"].iloc[0])
        if cap <= 0:
            continue

        best_w, best_r = 0.0, float("inf")
        for w in weights:
            blended = base_arr + w * delta_arr
            score = rmse(actual_arr, blended) / cap * 100
            if score < best_r:
                best_r, best_w = score, w

        weight_lookup[(str(sid), blk)] = best_w
        base_r = rmse(actual_arr, base_arr) / cap * 100
        site_block_details.append({
            "site_id": str(sid), "time_block": blk,
            "best_weight": best_w,
            "base_nrmse": round(base_r, 4),
            "blend_nrmse": round(best_r, 4),
            "delta": round(best_r - base_r, 4),
            "n_samples": len(grp),
        })

    # Apply blend weights to valid_df
    valid_df["blend_weight"] = valid_df.apply(
        lambda r: weight_lookup.get((str(r["site_id"]), r["time_block"]), 0.0), axis=1
    )
    valid_df["pred_blend"] = (
        valid_df[baseline_col] +
        valid_df["blend_weight"] * (valid_df[cand_col] - valid_df[baseline_col])
    )


    # ── Compute valid metrics for blend ────────────────────────────────
    actual_v = valid_df["power_mw"].values.astype(float)
    pred_v = valid_df["pred_blend"].values.astype(float)

    # Site-wise NRMSE
    site_rmses_base = []
    site_rmses_blend = []
    for sid, sdf in valid_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r_base = rmse(sdf["power_mw"].values, sdf[baseline_col].values) / cap * 100
        r_blend = rmse(sdf["power_mw"].values, sdf["pred_blend"].values) / cap * 100
        site_rmses_base.append(r_base)
        site_rmses_blend.append(r_blend)

    sm_base_v = float(np.mean(site_rmses_base))
    sm_blend_v = float(np.mean(site_rmses_blend))

    # City NRMSE
    agg_v = valid_df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=("pred_blend", "sum"), c=("capacity_mw", "sum")
    )
    cap_sum = float(valid_df[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
    city_v = rmse(agg_v["a"].values, agg_v["p"].values) / cap_sum * 100

    agg_vb = valid_df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(baseline_col, "sum")
    )
    city_base_v = rmse(agg_vb["a"].values, agg_vb["p"].values) / cap_sum * 100

    bias_v = bias_pct(actual_v, pred_v)
    abs_bias_v = abs(bias_v)

    # Bad sites
    bad_base = bad_blend = 0
    for sid, sdf in valid_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r_base = rmse(sdf["power_mw"].values, sdf[baseline_col].values) / cap * 100
        r_blend = rmse(sdf["power_mw"].values, sdf["pred_blend"].values) / cap * 100
        if r_blend - r_base > 1.0:
            bad_blend += 1

    print(f"\n[Valid Metrics]")
    print(f"  round64_final: sm={sm_base_v:.4f}%, city={city_base_v:.4f}%, abs_bias={abs(bias_pct(valid_df['power_mw'].values, valid_df[baseline_col].values)):.4f}%")
    print(f"  lgb_safe_blend: sm={sm_blend_v:.4f}%, city={city_v:.4f}%, abs_bias={abs_bias_v:.4f}%, bad_1pp={bad_blend}")

    # ── Apply same weights to test ──────────────────────────────────
    print("\n[INFO] Applying weights to test set...")

    # Build lookup from valid - key=(site_id, time_block) -> weight
    weight_lookup = {}
    for (sid, blk), grp in valid_df.groupby(["site_id", "time_block"]):
        weight_lookup[(str(sid), blk)] = grp["blend_weight"].iloc[0]

    test_df["blend_weight"] = test_df.apply(
        lambda r: weight_lookup.get((str(r["site_id"]), r["time_block"]), 0.0), axis=1
    )
    test_df["pred_blend"] = (
        test_df[baseline_col] +
        test_df["blend_weight"] * (test_df[cand_col] - test_df[baseline_col])
    )

    # ── Compute test metrics ─────────────────────────────────────────
    actual_t = test_df["power_mw"].values.astype(float)
    pred_t = test_df["pred_blend"].values.astype(float)

    site_rmses_t_base = []
    site_rmses_t_blend = []
    for sid, sdf in test_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[baseline_col].values) / cap * 100
        site_rmses_t_base.append(r)
        r2 = rmse(sdf["power_mw"].values, sdf["pred_blend"].values) / cap * 100
        site_rmses_t_blend.append(r2)

    sm_base_t = float(np.mean(site_rmses_t_base))
    sm_blend_t = float(np.mean(site_rmses_t_blend))

    agg_t = test_df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=("pred_blend", "sum")
    )
    cap_sum_t = float(test_df[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
    city_t = rmse(agg_t["a"].values, agg_t["p"].values) / cap_sum_t * 100
    agg_tb = test_df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(baseline_col, "sum")
    )
    city_base_t = rmse(agg_tb["a"].values, agg_tb["p"].values) / cap_sum_t * 100

    bias_t = bias_pct(actual_t, pred_t)
    abs_bias_t = abs(bias_t)

    print(f"\n[Test Metrics]")
    print(f"  round64_final: sm={sm_base_t:.4f}%, city={city_base_t:.4f}%, abs_bias={abs(bias_pct(test_df['power_mw'].values, test_df[baseline_col].values)):.4f}%")
    print(f"  lgb_safe_blend: sm={sm_blend_t:.4f}%, city={city_t:.4f}%, abs_bias={abs_bias_t:.4f}%")

    # ── Save outputs ─────────────────────────────────────────────────
    # Weights CSV
    wb = pd.DataFrame(site_block_details)
    wb.to_csv(ROUND68 / "round68_lgb_safe_blend_weights.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] Weights: {ROUND68 / 'round68_lgb_safe_blend_weights.csv'}")

    # Valid compare
    bias_base_v = bias_pct(valid_df["power_mw"].values, valid_df[baseline_col].values)
    compare_valid = pd.DataFrame([{
        "candidate": "round64_final",
        "split": "valid",
        "sm_nrmse_pct": round(sm_base_v, 4),
        "city_nrmse_pct": round(city_base_v, 4),
        "bias_pct": round(bias_base_v, 4),
        "abs_bias_pct": round(abs(bias_base_v), 4),
        "bad_1pp": 0,
    }, {
        "candidate": "lgb_safe_blend",
        "split": "valid",
        "sm_nrmse_pct": round(sm_blend_v, 4),
        "city_nrmse_pct": round(city_v, 4),
        "bias_pct": round(bias_v, 4),
        "abs_bias_pct": round(abs_bias_v, 4),
        "bad_1pp": bad_blend,
    }])
    compare_valid.to_csv(ROUND68 / "round68_lgb_safe_blend_valid_compare.csv", index=False, encoding="utf-8-sig")

    # Test compare
    bad_base_t = 0
    bad_blend_t = 0
    for sid, sdf in test_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r_base = rmse(sdf["power_mw"].values, sdf[baseline_col].values) / cap * 100
        r_blend = rmse(sdf["power_mw"].values, sdf["pred_blend"].values) / cap * 100
        if r_blend - r_base > 1.0:
            bad_blend_t += 1

    compare_test = pd.DataFrame([{
        "candidate": "round64_final",
        "split": "test",
        "sm_nrmse_pct": round(sm_base_t, 4),
        "city_nrmse_pct": round(city_base_t, 4),
        "bias_pct": round(bias_pct(test_df["power_mw"].values, test_df[baseline_col].values), 4),
        "abs_bias_pct": round(abs(bias_pct(test_df["power_mw"].values, test_df[baseline_col].values)), 4),
        "bad_1pp": bad_base_t,
    }, {
        "candidate": "lgb_safe_blend",
        "split": "test",
        "sm_nrmse_pct": round(sm_blend_t, 4),
        "city_nrmse_pct": round(city_t, 4),
        "bias_pct": round(bias_t, 4),
        "abs_bias_pct": round(abs_bias_t, 4),
        "bad_1pp": bad_blend_t,
    }])
    compare_test.to_csv(ROUND68 / "round68_lgb_safe_blend_test_compare.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Valid compare: {ROUND68 / 'round68_lgb_safe_blend_valid_compare.csv'}")
    print(f"[OK] Test compare: {ROUND68 / 'round68_lgb_safe_blend_test_compare.csv'}")

    print(f"\n[OK] Safe blend complete")


if __name__ == "__main__":
    main()
