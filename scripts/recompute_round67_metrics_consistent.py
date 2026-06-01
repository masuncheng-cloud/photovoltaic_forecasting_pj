#!/usr/bin/env python3
"""
recompute_round67_metrics_consistent.py
==================================
用统一口径重新计算 Round67 候选的 valid 和 test 指标。

口径说明（来自 metrics_common.py）：
  - city_nrmse: RMSE(city_actual, city_pred) / capacity_sum_all_sites * 100
  - site_nrmse: RMSE(site_actual, site_pred) / site_capacity * 100
  - bias: (sum(pred) - sum(actual)) / sum(actual) * 100
  - capacity_sum = sum of unique site capacities (all sites participating in evaluation)
"""

from pathlib import Path
import os
import warnings
import math
import numpy as np
import pandas as pd
import pickle
import json

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
ROUND67_DIR = OUT / "round67"


# ── Metric helpers (mirroring metrics_common.py) ─────────────────────────────

def rmse(actual, pred):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    if len(a) == 0:
        return float("nan")
    return float(math.sqrt(float(np.mean((p - a) ** 2))))


def bias_percent(actual, pred):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    a_sum = float(np.nansum(a))
    p_sum = float(np.nansum(p))
    if abs(a_sum) < 1e-12:
        return float("nan")
    return (p_sum - a_sum) / a_sum * 100.0


def nrmse_pct(actual, pred, capacity_mw):
    if capacity_mw <= 0 or math.isnan(float(capacity_mw)):
        return float("nan")
    return rmse(actual, pred) / float(capacity_mw) * 100.0


def capacity_sum_unique_sites(df, site_col="site_id", cap_col="capacity_mw"):
    """Sum of unique site capacities."""
    return float(df[[site_col, cap_col]].drop_duplicates(subset=[site_col])[cap_col].sum())


def main():
    print("=" * 60)
    print("Round67 Metrics Recompute (Consistent Formula)")
    print("=" * 60)

    # Load data
    df = pd.read_parquet(ROUND67_DIR / "round67_training_table.parquet")
    df["time"] = pd.to_datetime(df["time"])
    print(f"[INFO] Loaded: {len(df)} rows, cols: {df.columns.tolist()}")

    # Feature columns for model prediction
    exclude = {"site_id", "time", "split", "hour", "time_block", "site_group",
               "y_norm", "power_mw", "capacity_mw", "power_pred_final",
               "baseline_norm", "cap_group", "zero_group"}
    feat_cols = [c for c in df.columns if c not in exclude]

    # Load model store
    with open(ROUND67_DIR / "round67_model_files/model_store.pkl", "rb") as f:
        store = pickle.load(f)
    models = store["models"]
    print(f"[INFO] Models: {list(models.keys())}")

    # ── Reconstruct predictions for all candidates ─────────────────────────
    print("\n[INFO] Reconstructing predictions...")

    # Initialize all candidate prediction columns with baseline
    df["pred_round64_final"] = df["power_pred_final"].values

    for model_name, blocks in models.items():
        df[f"pred_{model_name}_combined"] = np.nan
        for block, model_obj in blocks.items():
            mask = df["time_block"] == block
            if mask.sum() == 0:
                continue
            X = (pd.DataFrame(df.loc[mask, feat_cols])
                   .apply(pd.to_numeric, errors="coerce")
                   .fillna(0)
                   .values
                   .astype(float))
            if model_name == "ridge":
                X = model_obj["scaler"].transform(X)
                pred = model_obj["model"].predict(X)
            elif model_name == "lgb":
                pred = model_obj.predict(X)
            else:
                pred = model_obj.predict(X)
            cap = df.loc[mask, "capacity_mw"].values.astype(float)
            pred_mw = np.clip(pred * cap, 0, cap)
            df.loc[mask, f"pred_{model_name}_combined"] = pred_mw

        # Fallback missing blocks to baseline
        df[f"pred_{model_name}_combined"] = (
            df[f"pred_{model_name}_combined"].fillna(df["power_pred_final"])
        )

    # Candidates dict
    candidates = {
        "round64_final": "pred_round64_final",
        "ridge": "pred_ridge_combined",
        "hgb": "pred_hgb_combined",
        "lgb": "pred_lgb_combined",
    }

    # ── Compute metrics ───────────────────────────────────────────────────

    def compute_overall_metrics(sub_df, pred_col, label=""):
        actual = sub_df["power_mw"].values.astype(float)
        pred = sub_df[pred_col].values.astype(float)
        cap_sum = capacity_sum_unique_sites(sub_df)

        # city nrmse (6-19)
        agg = sub_df.groupby("time", as_index=False).agg(
            actual_mw=("power_mw", "sum"),
            pred_mw=(pred_col, "sum"),
        )
        city_nrmse_6_19 = nrmse_pct(agg["actual_mw"].values, agg["pred_mw"].values, cap_sum)

        # city nrmse (10-14)
        sub10 = sub_df[sub_df["hour"].between(10, 14)]
        agg10 = sub10.groupby("time", as_index=False).agg(
            actual_mw=("power_mw", "sum"),
            pred_mw=(pred_col, "sum"),
        )
        cap10 = capacity_sum_unique_sites(sub10)
        city_nrmse_10_14 = nrmse_pct(agg10["actual_mw"].values, agg10["pred_mw"].values, cap10)

        # site nrmse per site then mean
        site_rmses = []
        for sid, sdf in sub_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
            site_rmses.append(r)
        site_mean_nrmse_6_19 = float(np.mean(site_rmses))

        site_rmses_10_14 = []
        for sid, sdf in sub10.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
            site_rmses_10_14.append(r)
        site_mean_nrmse_10_14 = float(np.mean(site_rmses_10_14)) if site_rmses_10_14 else float("nan")

        # bias
        bias_6_19 = bias_percent(actual, pred)
        abs_bias_6_19 = abs(bias_6_19)

        sub10_actual = sub10["power_mw"].values.astype(float)
        sub10_pred = sub10[pred_col].values.astype(float)
        bias_10_14 = bias_percent(sub10_actual, sub10_pred)
        abs_bias_10_14 = abs(bias_10_14)

        # rmse/mae
        r_mw = rmse(actual, pred)
        m_mw = float(np.mean(np.abs(pred - actual)))

        return {
            "candidate": label,
            "pred_col": pred_col,
            "site_mean_nrmse_6_19_pct": round(site_mean_nrmse_6_19, 4),
            "site_mean_nrmse_10_14_pct": round(site_mean_nrmse_10_14, 4),
            "city_nrmse_6_19_pct": round(city_nrmse_6_19, 4),
            "city_nrmse_10_14_pct": round(city_nrmse_10_14, 4),
            "bias_6_19_pct": round(bias_6_19, 4),
            "abs_bias_6_19_pct": round(abs_bias_6_19, 4),
            "bias_10_14_pct": round(bias_10_14, 4),
            "abs_bias_10_14_pct": round(abs_bias_10_14, 4),
            "rmse_mw": round(r_mw, 4),
            "mae_mw": round(m_mw, 4),
        }

    def compute_bad_sites(sub_df, pred_col, baseline_col, threshold=1.0):
        """Count sites where candidate NRMSE > baseline NRMSE + threshold."""
        bad_05 = 0
        bad_10 = 0
        for sid, sdf in sub_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            base_r = rmse(sdf["power_mw"].values, sdf[baseline_col].values) / cap * 100
            cand_r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
            delta = cand_r - base_r
            if delta > 0.5:
                bad_05 += 1
            if delta > 1.0:
                bad_10 += 1
        return bad_05, bad_10

    def compute_extreme_count(sub_df, pred_col, threshold_pct=50):
        """Count samples where pred/actual ratio > threshold or < 1/threshold."""
        actual = sub_df["power_mw"].values.astype(float)
        pred = sub_df[pred_col].values.astype(float)
        ratio = pred / np.maximum(actual, 1e-6)
        return int(((ratio > threshold_pct) | (ratio < 1.0 / threshold_pct)).sum())

    # Compute per-split
    splits = {"valid": df[df["split"] == "valid"].copy(),
              "test": df[df["split"] == "test"].copy()}

    all_overall_rows = []
    all_hourly_rows = []
    all_site_rows = []

    for split_name, sub_df in splits.items():
        print(f"\n[INFO] {split_name}: {len(sub_df)} rows, {sub_df['site_id'].nunique()} sites")

        for cand_name, pred_col in candidates.items():
            row = compute_overall_metrics(sub_df, pred_col, label=cand_name)
            row["split"] = split_name
            bad_05, bad_10 = compute_bad_sites(
                sub_df, pred_col,
                candidates["round64_final"],
                threshold=1.0
            )
            row["bad_site_gt_1pp_count"] = bad_10
            row["bad_site_gt_0_5pp_count"] = bad_05
            row["pred_actual_extreme_count"] = compute_extreme_count(sub_df, pred_col, 50)
            all_overall_rows.append(row)
            print(f"  {cand_name}: sm_nrmse={row['site_mean_nrmse_6_19_pct']}%, "
                  f"city={row['city_nrmse_6_19_pct']}%, "
                  f"bias={row['bias_6_19_pct']}%, "
                  f"abs_bias={row['abs_bias_6_19_pct']}%, "
                  f"bad1pp={bad_10}")

            # Per-site
            for sid, sdf in sub_df.groupby("site_id"):
                cap = float(sdf["capacity_mw"].iloc[0])
                if cap <= 0:
                    continue
                a = sdf["power_mw"].values
                p = sdf[pred_col].values
                r_nrmse = rmse(a, p) / cap * 100
                all_site_rows.append({
                    "split": split_name, "candidate": cand_name,
                    "site_id": str(sid), "capacity_mw": round(cap, 4),
                    "nrmse_pct": round(r_nrmse, 4),
                    "mae": round(float(np.mean(np.abs(p - a))), 4),
                })

            # Per-hour
            for hour, hdf in sub_df.groupby("hour"):
                a = hdf["power_mw"].values
                p = hdf[pred_col].values
                cap_h = capacity_sum_unique_sites(hdf)
                all_hourly_rows.append({
                    "split": split_name, "candidate": cand_name,
                    "hour": int(hour),
                    "city_nrmse_pct": round(nrmse_pct(a, p, cap_h), 4),
                    "bias_pct": round(bias_percent(a, p), 4),
                })

    # Save CSV outputs
    os.makedirs(OUT / "round68", exist_ok=True)
    out = OUT / "round68"

    overall_df = pd.DataFrame(all_overall_rows)
    overall_df.to_csv(out / "round67_valid_metrics_recomputed.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] Valid/Test metrics: {out / 'round67_valid_metrics_recomputed.csv'}")

    hourly_df = pd.DataFrame(all_hourly_rows)
    hourly_df.to_csv(out / "round67_valid_hourly_recomputed.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Hourly: {out / 'round67_valid_hourly_recomputed.csv'}")

    site_df = pd.DataFrame(all_site_rows)
    site_df.to_csv(out / "round67_valid_site_recomputed.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Sites: {out / 'round67_valid_site_recomputed.csv'}")

    print("\n[Summary - Test]")
    print(overall_df[overall_df["split"]=="test"].to_string(index=False))

    print("\n[Summary - Valid]")
    print(overall_df[overall_df["split"]=="valid"].to_string(index=False))


if __name__ == "__main__":
    import os
    main()
