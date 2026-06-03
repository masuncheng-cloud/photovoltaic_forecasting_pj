#!/usr/bin/env python3
"""
select_round61_final_prediction.py
=================================
在 valid 集上评估候选，选择最优或回退 Round60。

候选（按优先级从低到高）：
  power_pred_final          - Round60 baseline (= power_pred_round60_safe)
  power_pred_round61_city   - Round61 城市校准（无保护）
  power_pred_round61_city_safe - Round61 城市校准 + 站点/小时保护

评分（仅用 valid 集）：
  score = 0.30 * site_mean_nrmse_6_19
        + 0.30 * city_nrmse_6_19
        + 0.25 * city_nrmse_10_14
        + 0.15 * abs(bias_10_14)

安全约束（相对于 Round60 baseline）：
  site_mean_nrmse_6_19 <= Round60 + 0.10pp
  site_mean_nrmse_10_14 <= Round60 + 0.10pp
  city_nrmse_6_19 <= Round58 + 0.05pp
  city_nrmse_10_14 <= Round58 + 0.05pp
  abs(bias_6_19) <= Round58 + 0.5pp
  abs(bias_10_14) <= Round58 + 0.5pp
  变差 > +1pp 的站点数 == 0

输出：
  output/pv_pipeline/calibration/round61_model_selection_valid.csv
  更新 distributed_predictions_final_full.pkl 和 final_eval.pkl
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
CAL = OUT / "calibration"


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


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if abs(a_sum) < 1e-9:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def evaluate_on_valid(df, pred_col, hour_range=(6, 19)):
    df_v = df[
        (df["split"] == "valid") & df["hour"].between(hour_range[0], hour_range[1])
    ].copy()
    if len(df_v) == 0:
        return None

    sm_nrmse = site_mean_nrmse(df_v, pred_col)
    c_nrmse = city_nrmse(df_v, pred_col)
    bias = bias_pct(df_v, pred_col)

    df_10_14 = df_v[df_v["hour"].between(10, 14)]
    c_nrmse_10_14 = city_nrmse(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan
    sm_nrmse_10_14 = site_mean_nrmse(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan
    bias_10_14 = bias_pct(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan

    return {
        "pred_col": pred_col,
        "sm_nrmse_6_19": round(sm_nrmse, 4),
        "c_nrmse_6_19": round(c_nrmse, 4),
        "sm_nrmse_10_14": round(sm_nrmse_10_14, 4) if not np.isnan(sm_nrmse_10_14) else np.nan,
        "c_nrmse_10_14": round(c_nrmse_10_14, 4) if not np.isnan(c_nrmse_10_14) else np.nan,
        "bias_6_19": round(bias, 4),
        "abs_bias_6_19": round(abs(bias), 4),
        "bias_10_14": round(bias_10_14, 4) if not np.isnan(bias_10_14) else np.nan,
        "abs_bias_10_14": round(abs(bias_10_14), 4) if not np.isnan(bias_10_14) else np.nan,
    }


def compute_score(row):
    c14 = row["c_nrmse_10_14"] if not np.isnan(row["c_nrmse_10_14"]) else row["c_nrmse_6_19"]
    ab14 = row["abs_bias_10_14"] if not np.isnan(row["abs_bias_10_14"]) else row["abs_bias_6_19"]
    return round(
        0.30 * row["sm_nrmse_6_19"] +
        0.30 * row["c_nrmse_6_19"] +
        0.25 * c14 +
        0.15 * ab14,
        6
    )


def check_site_degradation(df, pred_base, pred_cand, threshold=1.0):
    """Return number of sites where NRMSE degrades > threshold pp."""
    df_v = df[(df["split"] == "valid") & df["hour"].between(6, 19)].copy()
    count = 0
    for sid, sdf in df_v.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        base_rmse = rmse(sdf["power_mw"].values, sdf[pred_base].values)
        cand_rmse = rmse(sdf["power_mw"].values, sdf[pred_cand].values)
        delta = (cand_rmse - base_rmse) / cap * 100
        if delta > threshold:
            count += 1
    return count


def main():
    print("=" * 60)
    print("Round61 候选选择（仅用 valid 集）")
    print("=" * 60)

    # Load Round60 baselines
    r58_path = ROOT / "output/pv_pipeline/baselines/round58/distributed_predictions_final_full.pkl"
    r58 = pd.read_pickle(r58_path)
    r58["time"] = pd.to_datetime(r58["time"])
    if "hour" not in r58.columns:
        r58["hour"] = r58["time"].dt.hour
    r58_v = r58[(r58["split"] == "valid") & r58["hour"].between(6, 19)]
    r58_sm = site_mean_nrmse(r58_v, "power_pred_final")
    r58_c = city_nrmse(r58_v, "power_pred_final")
    r58_c14 = city_nrmse(r58_v[r58_v["hour"].between(10, 14)], "power_pred_final")
    r58_ab619 = abs(bias_pct(r58_v, "power_pred_final"))
    r58_ab1014 = abs(bias_pct(r58_v[r58_v["hour"].between(10, 14)], "power_pred_final"))

    print(f"[INFO] Round58 baseline on valid 6-19h:")
    print(f"  sm_nrmse={r58_sm:.4f}%, c_nrmse={r58_c:.4f}%, c_nrmse_10_14={r58_c14:.4f}%")
    print(f"  abs_bias_6_19={r58_ab619:.4f}%, abs_bias_10_14={r58_ab1014:.4f}%")

    # Load Round61 candidates
    cand_path = OUT / "predictions/distributed_predictions_round61_candidates.pkl"
    if not cand_path.exists():
        raise FileNotFoundError(f"{cand_path} not found")
    print(f"\n[INFO] Loading: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    candidates = [
        ("power_pred_final", "Round60 baseline"),
        ("power_pred_round61_city", "Round61 city"),
        ("power_pred_round61_city_safe", "Round61 city_safe"),
    ]

    print(f"\n{'='*90}")
    print(f"{'Candidate':<26} {'sm_6_19':>9} {'c_6_19':>9} {'c_10_14':>9} {'abs_b619':>9} {'abs_b1014':>10} {'score':>9}")
    print(f"{'='*90}")

    results = []
    for pred_col, label in candidates:
        if pred_col not in df.columns:
            print(f"[WARN] {pred_col} not found, skipping")
            continue
        ev = evaluate_on_valid(df, pred_col)
        if ev is None:
            continue
        ev["label"] = label
        ev["score"] = compute_score(ev)
        results.append(ev)
        c14 = ev["c_nrmse_10_14"] if not np.isnan(ev["c_nrmse_10_14"]) else 0
        b14 = ev["abs_bias_10_14"] if not np.isnan(ev["abs_bias_10_14"]) else 0
        print(
            f"{label:<26} {ev['sm_nrmse_6_19']:>9.4f} {ev['c_nrmse_6_19']:>9.4f} "
            f"{c14:>9.4f} {ev['abs_bias_6_19']:>9.4f} {b14:>10.4f} {ev['score']:>9.4f}"
        )

    results_df = pd.DataFrame(results)
    bl_row = results_df[results_df["pred_col"] == "power_pred_final"]
    if len(bl_row) == 0:
        raise ValueError("Round60 baseline not found!")
    bl = bl_row.iloc[0].to_dict()

    print(f"\n{'='*90}")
    print("Safety constraint check (relative to Round60 baseline)")
    print("  sm_6_19 <= Round60+0.10pp, sm_10_14 <= Round60+0.10pp")
    print("  c_6_19 <= Round58+0.05pp, c_10_14 <= Round58+0.05pp")
    print("  |bias_6_19| <= Round58+0.5pp, |bias_10_14| <= Round58+0.5pp")
    print("  变差>+1pp 站点数 == 0")
    print(f"{'='*90}")

    best_candidate = None
    best_score = bl["score"]
    adopted = False

    for _, row in results_df.iterrows():
        r = row.to_dict()
        pc = r["pred_col"]
        if pc == "power_pred_final":
            print(f"{r['label']:<26} = baseline (always safe)")
            continue

        sm_delta = r["sm_nrmse_6_19"] - bl["sm_nrmse_6_19"]
        sm14_delta = (r["sm_nrmse_10_14"] - bl["sm_nrmse_10_14"]
                      if not (np.isnan(r["sm_nrmse_10_14"]) or np.isnan(bl["sm_nrmse_10_14"]))
                      else r["sm_nrmse_6_19"] - bl["sm_nrmse_6_19"])
        c_delta = r["c_nrmse_6_19"] - r58_c
        c14_delta = (r["c_nrmse_10_14"] - r58_c14
                     if not (np.isnan(r["c_nrmse_10_14"]) or np.isnan(r58_c14))
                     else r["c_nrmse_6_19"] - r58_c)
        ab619_delta = r["abs_bias_6_19"] - r58_ab619
        ab1014_delta = (r["abs_bias_10_14"] - r58_ab1014
                        if not (np.isnan(r["abs_bias_10_14"]) or np.isnan(r58_ab1014))
                        else r["abs_bias_6_19"] - r58_ab619)

        safe_sm = sm_delta <= 0.10
        safe_sm14 = sm14_delta <= 0.10
        safe_c = c_delta <= 0.05
        safe_c14 = c14_delta <= 0.05
        safe_b619 = ab619_delta <= 0.5
        safe_b1014 = ab1014_delta <= 0.5

        n_bad_sites = check_site_degradation(df, "power_pred_final", pc, threshold=1.0)
        safe_sites = (n_bad_sites == 0)

        safe = (safe_sm and safe_sm14 and safe_c and safe_c14
                and safe_b619 and safe_b1014 and safe_sites)

        print(
            f"{r['label']:<26} "
            f"{'OK' if safe_sm else 'FAIL':>4} {'OK' if safe_sm14 else 'FAIL':>5} "
            f"{'OK' if safe_c else 'FAIL':>4} {'OK' if safe_c14 else 'FAIL':>5} "
            f"{'OK' if safe_b619 else 'FAIL':>4} {'OK' if safe_b1014 else 'FAIL':>6} "
            f"{'OK' if safe_sites else 'FAIL':>5} "
            f"score={r['score']:.4f}"
        )
        print(
            f"  deltas: sm={sm_delta:+.4f} sm14={sm14_delta:+.4f} "
            f"c={c_delta:+.4f} c14={c14_delta:+.4f} "
            f"ab619={ab619_delta:+.3f} ab1014={ab1014_delta:+.3f} "
            f"bad_sites={n_bad_sites}"
        )

        if safe and r["score"] < bl["score"]:
            if best_candidate is None or r["score"] < best_score:
                best_candidate = pc
                best_score = r["score"]
                adopted = True

    print(f"\n{'='*60}")
    if best_candidate is None:
        print("所有候选均不满足安全约束或无改善，保留 Round60 baseline。")
        final_pred_col = "power_pred_final"
        adopted = False
    else:
        print(f"采用候选: {best_candidate} (score={best_score:.4f} vs Round60={bl['score']:.4f})")
        final_pred_col = best_candidate
        adopted = True

    # Build results with safety info
    sel_df = results_df.copy()
    sel_df["final_adopted"] = (sel_df["pred_col"] == final_pred_col)
    sel_df.to_csv(CAL / "round61_model_selection_valid.csv", index=False, encoding="utf-8-sig")
    print(f"[INFO] Saved: {CAL / 'round61_model_selection_valid.csv'}")

    # Update final predictions
    df["power_pred_final_round61"] = df[final_pred_col].copy()
    df["power_pred_final"] = df[final_pred_col].copy()

    # Save full pkl
    full_out = OUT / "predictions/distributed_predictions_final_full.pkl"
    df.to_pickle(full_out)
    print(f"[INFO] Updated full pkl: {full_out}")

    # Save eval pkl (test split, 6-19h only)
    eval_df = df[(df["split"] == "test") & df["hour"].between(6, 19)].copy()
    eval_df["power_pred_final"] = eval_df[final_pred_col].copy()
    eval_out = OUT / "predictions/distributed_predictions_final_eval.pkl"
    eval_df.to_pickle(eval_out)
    print(f"[INFO] Updated eval pkl: {eval_out} ({len(eval_df)} rows)")

    # Summary
    print(f"\n{'='*60}")
    print(f"最终采用: {final_pred_col}")
    print(f"adopted: {adopted}")
    print(f"注意: Round61 的 power_pred_final_round60 列已不存在，")
    print(f"      原有 round60_safe 现保存在 baselines/round60/ 中。")


if __name__ == "__main__":
    main()
