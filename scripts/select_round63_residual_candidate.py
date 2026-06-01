#!/usr/bin/env python3
"""
select_round63_residual_candidate.py
==================================
在 valid 集上评估残差候选，选择最优候选或回退 Round61。

候选：
  Round61 baseline
  ridge_residual
  lgb_residual

安全门控（相对于 Round61）：
  bad_site_count_gt_1pp == 0
  site_mean_nrmse_6_19 <= Round61 + 0.10pp
  city_nrmse_6_19 <= Round61 + 0.10pp
  city_nrmse_10_14 <= Round61

输出：
  output/pv_pipeline/round63/round63_valid_candidate_compare.csv
  output/pv_pipeline/round63/round63_selected_candidate.json
  output/pv_pipeline/round63/round63_candidates.pkl  (valid+test only, no overwrite of formal results)
"""

from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd
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

ALL_FEATURES = [
    "hour", "month", "dayofyear", "capacity_mw", "pred_norm",
    "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
    "scene_is_clear_peak", "scene_is_mid", "scene_is_low", "scene_is_night",
    "calibrated_ratio", "latitude", "longitude",
]


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse(df, pred_col):
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h <= 0:
            continue
        vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_10_14(df, pred_col):
    df14 = df[df["hour"].between(10, 14)]
    if len(df14) == 0:
        return np.nan
    return city_nrmse(df14, pred_col)


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if abs(a_sum) < 1e-9:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def count_bad_sites(df, pred_base, pred_cand, threshold=1.0):
    df_v = df[(df["split"] == "valid") & df["hour"].between(6, 19)].copy()
    count = 0
    details = []
    for sid, sdf in df_v.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        base_rmse = rmse(sdf["power_mw"].values, sdf[pred_base].values)
        cand_rmse = rmse(sdf["power_mw"].values, sdf[pred_cand].values)
        delta = (cand_rmse - base_rmse) / cap * 100
        if delta > threshold:
            count += 1
            details.append((str(sid), round(delta, 2)))
    return count, details


def build_features(df):
    """Build feature matrix for all rows."""
    feature_data = {}
    for feat in ALL_FEATURES:
        if feat in df.columns:
            vals = df[feat].values.astype(float)
            vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
        else:
            vals = np.zeros(len(df), dtype=float)
        feature_data[feat] = vals
    return np.column_stack([feature_data[f] for f in ALL_FEATURES])


def apply_residual(df, models_dict, pred_col_base, cand_col_name):
    """Apply residual models per scene and return candidate prediction column."""
    X = build_features(df)
    scene_col = np.full(len(df), "day", dtype=object)
    for scene_name, hours in SCENES.items():
        mask = df["hour"].isin(hours).values
        scene_col[mask] = scene_name

    pred_norm_base = df[pred_col_base].values / np.maximum(df["capacity_mw"].values, 1e-9)
    residual_pred_norm = np.zeros(len(df))

    for scene_name in SCENES:
        mask = (scene_col == scene_name)
        if not mask.any():
            continue
        X_scene = X[mask]
        cap_scene = df.loc[mask, "capacity_mw"].values

        for model_type in ["lgb", "ridge"]:
            model_info = models_dict.get(scene_name, {}).get(model_type)
            if model_info is None:
                continue
            model = model_info["model"]

            if model_type == "lgb":
                scene_residual = model.predict(X_scene)
            else:
                scaler = model_info["scaler"]
                Xs = scaler.transform(X_scene)
                scene_residual = model.predict(Xs)

            # Blend: use LGB for lgb_residual, Ridge for ridge_residual
            if model_type == "lgb" and "lgb" in cand_col_name:
                residual_pred_norm[mask] = scene_residual
            elif model_type == "ridge" and "ridge" in cand_col_name:
                residual_pred_norm[mask] = scene_residual

    # Final prediction
    cand_norm = pred_norm_base + residual_pred_norm
    cand_mw = cand_norm * df["capacity_mw"].values
    return np.clip(cand_mw, 0.0, df["capacity_mw"].values)


def main():
    print("=" * 60)
    print("Round63 候选选择（valid 集）")
    print("=" * 60)

    # Load models
    models_path = OUT / "round63_residual_models.pkl"
    print(f"[INFO] Loading models: {models_path}")
    with open(models_path, "rb") as f:
        models_data = pickle.load(f)
    all_models = models_data["all_models"]

    # Load baseline (only valid+test for memory, hours 6-19)
    print("[INFO] Loading baseline data...")
    base_path = ROOT / "output/pv_pipeline/baselines/round61/distributed_predictions_final_full.pkl"
    df_full = pd.read_pickle(base_path)
    df_full["time"] = pd.to_datetime(df_full["time"])

    # Build features
    print("[INFO] Building features...")
    df_full["month"] = df_full["time"].dt.month
    df_full["dayofyear"] = df_full["time"].dt.dayofyear
    df_full["pred_norm"] = df_full["power_pred_final"] / df_full["capacity_mw"].clip(lower=1e-9)
    df_full["clear_sky_index"] = np.where(
        df_full["clear_sky_ghi"] > 1.0,
        (df_full["g_blend_pred"] / df_full["clear_sky_ghi"]).clip(0, 2),
        0.0
    )
    for s in ["clear_peak", "mid", "low", "night"]:
        df_full[f"scene_is_{s}"] = (df_full["scene_v151"] == s).astype(float)
    df_full["latitude"] = 0.0
    df_full["longitude"] = 0.0

    # Filter to 6-19h
    df = df_full[df_full["hour"].between(6, 19)].copy()

    # Apply candidates
    print("[INFO] Applying Ridge residual candidate...")
    df["power_pred_ridge_residual"] = apply_residual(
        df, all_models, "power_pred_final", "ridge_residual"
    )

    print("[INFO] Applying LGB residual candidate...")
    df["power_pred_lgb_residual"] = apply_residual(
        df, all_models, "power_pred_final", "lgb_residual"
    )

    # Clip candidates to capacity
    df["power_pred_ridge_residual"] = df["power_pred_ridge_residual"].clip(
        upper=df["capacity_mw"]
    )
    df["power_pred_lgb_residual"] = df["power_pred_lgb_residual"].clip(
        upper=df["capacity_mw"]
    )

    # Evaluate on valid set
    df_valid = df[df["split"] == "valid"].copy()
    print(f"[INFO] Valid set: {len(df_valid)} rows")

    candidates = [
        ("power_pred_final", "Round61 baseline"),
        ("power_pred_ridge_residual", "ridge_residual"),
        ("power_pred_lgb_residual", "lgb_residual"),
    ]

    print(f"\n{'='*80}")
    print(f"{'Candidate':<26} {'sm_nrmse':>10} {'c_nrmse':>10} {'c_10_14':>10} {'bias_6_19':>10} {'bias_10_14':>10}")
    print(f"{'='*80}")

    results = []
    for pred_col, label in candidates:
        sm = site_mean_nrmse(df_valid, pred_col)
        cn = city_nrmse(df_valid, pred_col)
        cn14 = city_nrmse_10_14(df_valid, pred_col)
        b = bias_pct(df_valid, pred_col)
        b14 = bias_pct(df_valid[df_valid["hour"].between(10, 14)], pred_col)

        bad_count, bad_details = count_bad_sites(df, "power_pred_final", pred_col)
        results.append({
            "pred_col": pred_col,
            "label": label,
            "sm_nrmse_6_19": round(sm, 4),
            "city_nrmse_6_19": round(cn, 4),
            "city_nrmse_10_14": round(cn14, 4),
            "bias_6_19": round(b, 4),
            "bias_10_14": round(b14, 4),
            "abs_bias_6_19": round(abs(b), 4),
            "abs_bias_10_14": round(abs(b14), 4),
            "bad_site_count": bad_count,
            "bad_site_details": bad_details,
        })
        cn14_d = cn14 if not np.isnan(cn14) else 0
        print(
            f"{label:<26} {sm:>10.4f} {cn:>10.4f} "
            f"{cn14_d:>10.4f} {b:>10.4f} {b14:>10.4f}"
        )

    results_df = pd.DataFrame(results)

    # Baseline (Round61)
    bl = results_df[results_df["pred_col"] == "power_pred_final"].iloc[0]
    print(f"\n{'='*80}")
    print(f"安全门控检查（相对于 Round61）:")
    print(f"  bad_site_count == 0")
    print(f"  sm_nrmse_6_19 <= {bl['sm_nrmse_6_19'] + 0.10:.4f}")
    print(f"  city_nrmse_6_19 <= {bl['city_nrmse_6_19'] + 0.10:.4f}")
    print(f"  city_nrmse_10_14 <= {bl['city_nrmse_10_14']:.4f}")
    print(f"{'='*80}")

    # Safety check
    best_candidate = None
    best_score = None
    selected_row = None

    for _, row in results_df.iterrows():
        r = row.to_dict()
        pc = r["pred_col"]
        if pc == "power_pred_final":
            print(f"{r['label']:<26} = baseline (always safe)")
            continue

        sm_ok = r["sm_nrmse_6_19"] <= bl["sm_nrmse_6_19"] + 0.10
        cn_ok = r["city_nrmse_6_19"] <= bl["city_nrmse_6_19"] + 0.10
        cn14_ok = (r["city_nrmse_10_14"] <= bl["city_nrmse_10_14"]
                   if not np.isnan(r["city_nrmse_10_14"])
                   else True)
        sites_ok = r["bad_site_count"] == 0

        safe = sm_ok and cn_ok and cn14_ok and sites_ok

        # Score: weighted combination
        sm14_r61 = bl["sm_nrmse_6_19"]  # approximate
        score = (
            0.30 * r["sm_nrmse_6_19"] +
            0.30 * r["city_nrmse_6_19"] +
            0.25 * (r["city_nrmse_10_14"] if not np.isnan(r["city_nrmse_10_14"]) else r["city_nrmse_6_19"]) +
            0.15 * r["abs_bias_6_19"]
        )

        print(
            f"{r['label']:<26} "
            f"{'PASS' if safe else 'FAIL':>5} "
            f"sm={'OK' if sm_ok else 'FAIL':>4} "
            f"cn={'OK' if cn_ok else 'FAIL':>4} "
            f"cn14={'OK' if cn14_ok else 'FAIL':>5} "
            f"sites={r['bad_site_count']:>2} "
            f"score={score:.4f}"
        )
        cn14_delta = (r['city_nrmse_10_14'] - bl['city_nrmse_10_14']
                      if not (np.isnan(r['city_nrmse_10_14']) or np.isnan(bl['city_nrmse_10_14']))
                      else 0.0)
        print(
            f"  deltas: sm={r['sm_nrmse_6_19']-bl['sm_nrmse_6_19']:+.4f} "
            f"cn={r['city_nrmse_6_19']-bl['city_nrmse_6_19']:+.4f} "
            f"cn14={cn14_delta:+.4f} "
            f"bad={r['bad_site_count']}"
        )

        if safe:
            if best_score is None or score < best_score:
                best_candidate = pc
                best_score = score
                selected_row = r

    print(f"\n{'='*60}")
    if best_candidate is None:
        print("所有候选均不满足安全门控，保留 Round61 baseline。")
        final_cand = "power_pred_final"
        adopted = False
    else:
        print(f"选择: {best_candidate} (score={best_score:.4f})")
        final_cand = best_candidate
        adopted = True

    # Save candidate comparison CSV
    results_df.drop(columns=["bad_site_details"], inplace=True)
    results_df.to_csv(OUT / "round63_valid_candidate_compare.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round63_valid_candidate_compare.csv'}")

    # Save selected candidate JSON
    sel_json = {
        "selected_candidate": final_cand,
        "adopted": adopted,
        "valid_metrics": selected_row if selected_row else {},
        "baseline_metrics": dict(bl),
        "all_candidates": results,
    }
    with open(OUT / "round63_selected_candidate.json", "w", encoding="utf-8") as f:
        json.dump(sel_json, f, ensure_ascii=False, indent=2, default=str)
    print(f"[OK] {OUT / 'round63_selected_candidate.json'}")

    # Save candidates pkl (valid+test only, no overwrite of formal results)
    df_save = df[df["split"].isin(["valid", "test"])].copy()
    df_save["power_pred_final"] = df_save[final_cand].copy()
    df_save.to_pickle(OUT / "round63_candidates.pkl")
    print(f"[OK] {OUT / 'round63_candidates.pkl'} ({len(df_save)} rows)")

    print(f"\n最终选择: {final_cand}")
    print(f"是否替代 Round61: {adopted}")


if __name__ == "__main__":
    main()
