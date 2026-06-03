#!/usr/bin/env python3
"""
select_round60_final_prediction.py
=================================
在 valid 集上评估所有候选，选择最优或回退 baseline。

候选：
  Round58 baseline
  Round59 current
  power_pred_round60_hour_scene
  power_pred_round60_site_conservative
  power_pred_round60_combined_conservative
  power_pred_round60_safe

评分（仅用 valid 集）：
  score = 0.35 * site_mean_nrmse_6_19
        + 0.25 * city_nrmse_6_19
        + 0.25 * site_mean_nrmse_10_14
        + 0.15 * abs(bias_6_19)

安全约束（相对于 Round58 baseline）：
  site_mean_nrmse_6_19 <= baseline + 0.2pp
  city_nrmse_6_19 <= baseline + 0.2pp
  site_mean_nrmse_10_14 <= baseline + 0.2pp
  city_nrmse_10_14 <= baseline + 0.2pp
  abs(bias_6_19) <= baseline + 1pp

输出：
  output/pv_pipeline/calibration/round60_model_selection_valid.csv
  更新 distributed_predictions_final_full.pkl 和 final_eval.pkl
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
CAL = OUT / "calibration"


def rmse(a, p=None):
    if p is None:
        p = np.zeros_like(a)
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    """Mean of per-site NRMSE, each normalized by its own capacity."""
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        vals.append(r)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse(df, pred_col):
    """Per-hour RMSE / per-hour mean capacity, averaged across hours."""
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values - agg["actual"].values)
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
    """Evaluate a prediction column on valid set 6-19h."""
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

    return {
        "pred_col": pred_col,
        "sm_nrmse_6_19": round(sm_nrmse, 4),
        "c_nrmse_6_19": round(c_nrmse, 4),
        "sm_nrmse_10_14": round(sm_nrmse_10_14, 4) if not np.isnan(sm_nrmse_10_14) else np.nan,
        "c_nrmse_10_14": round(c_nrmse_10_14, 4) if not np.isnan(c_nrmse_10_14) else np.nan,
        "bias_6_19": round(bias, 4),
        "abs_bias_6_19": round(abs(bias), 4),
    }


def compute_score(row, w_sm=0.35, w_c=0.25, w_sm14=0.25, w_ab=0.15):
    sm14 = row["sm_nrmse_10_14"] if not np.isnan(row["sm_nrmse_10_14"]) else row["sm_nrmse_6_19"]
    return round(
        w_sm * row["sm_nrmse_6_19"] +
        w_c * row["c_nrmse_6_19"] +
        w_sm14 * sm14 +
        w_ab * row["abs_bias_6_19"],
        6
    )


def main():
    print("=" * 60)
    print("Round60 候选选择（仅用 valid 集）")
    print("=" * 60)

    # Load candidates
    cand_path = OUT / "predictions/distributed_predictions_round60_candidates.pkl"
    if not cand_path.exists():
        raise FileNotFoundError(f"{cand_path} not found")
    print(f"[INFO] Loading: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    print(f"[INFO] {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    candidates = [
        ("power_pred_final", "Round58 baseline"),
        ("power_pred_final_round59", "Round59 current"),
        ("power_pred_round60_hour_scene", "Round60 hour_scene"),
        ("power_pred_round60_site_conservative", "Round60 site_conservative"),
        ("power_pred_round60_combined_conservative", "Round60 combined"),
        ("power_pred_round60_safe", "Round60 safe"),
    ]

    print(f"\n{'='*80}")
    print(f"{'Candidate':<32} {'sm_nrmse':>10} {'c_nrmse':>10} {'sm_10_14':>10} {'c_10_14':>10} {'bias':>8} {'score':>10}")
    print(f"{'='*80}")

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
        sm14 = ev["sm_nrmse_10_14"] if not np.isnan(ev["sm_nrmse_10_14"]) else 0
        c14 = ev["c_nrmse_10_14"] if not np.isnan(ev["c_nrmse_10_14"]) else 0
        print(
            f"{label:<32} {ev['sm_nrmse_6_19']:>10.4f} {ev['c_nrmse_6_19']:>10.4f} "
            f"{sm14:>10.4f} {c14:>10.4f} {ev['bias_6_19']:>8.2f} {ev['score']:>10.4f}"
        )

    results_df = pd.DataFrame(results)

    # Round58 baseline
    bl_row = results_df[results_df["pred_col"] == "power_pred_final"]
    if len(bl_row) == 0:
        raise ValueError("Round58 baseline not found!")
    bl = bl_row.iloc[0]
    bl_score = bl["score"]

    print(f"\n{'='*80}")
    print("Safety constraint check (relative to Round58 baseline)")
    print(f"{'Candidate':<32} {'safe?':>8} {'sm_safe':>10} {'c_safe':>10} {'sm14_safe':>10} {'c14_safe':>10} {'bias_safe':>10}")
    print("-" * 100)

    SAFETY_DELTA = 0.2
    SAFETY_BIAS = 1.0

    best_candidate = None
    best_score = bl_score
    best_pred_col = "power_pred_final"

    for _, row in results_df.iterrows():
        pc = row["pred_col"]
        sm_delta = row["sm_nrmse_6_19"] - bl["sm_nrmse_6_19"]
        c_delta = row["c_nrmse_6_19"] - bl["c_nrmse_6_19"]
        sm14_row = row["sm_nrmse_10_14"] if not np.isnan(row["sm_nrmse_10_14"]) else row["sm_nrmse_6_19"]
        sm14_bl = bl["sm_nrmse_10_14"] if not np.isnan(bl["sm_nrmse_10_14"]) else bl["sm_nrmse_6_19"]
        sm14_delta = sm14_row - sm14_bl
        c14_row = row["c_nrmse_10_14"] if not np.isnan(row["c_nrmse_10_14"]) else row["c_nrmse_6_19"]
        c14_bl = bl["c_nrmse_10_14"] if not np.isnan(bl["c_nrmse_10_14"]) else bl["c_nrmse_6_19"]
        c14_delta = c14_row - c14_bl
        bias_delta = abs(row["bias_6_19"]) - abs(bl["bias_6_19"])

        safe = (
            sm_delta <= SAFETY_DELTA and
            c_delta <= SAFETY_DELTA and
            sm14_delta <= SAFETY_DELTA and
            c14_delta <= SAFETY_DELTA and
            bias_delta <= SAFETY_BIAS
        )

        safe_str = "SAFE" if safe else "UNSAFE"
        print(
            f"{row['label']:<32} {safe_str:>8} "
            f"{'OK' if sm_delta <= SAFETY_DELTA else 'FAIL':>10} "
            f"{'OK' if c_delta <= SAFETY_DELTA else 'FAIL':>10} "
            f"{'OK' if sm14_delta <= SAFETY_DELTA else 'FAIL':>10} "
            f"{'OK' if c14_delta <= SAFETY_DELTA else 'FAIL':>10} "
            f"{'OK' if bias_delta <= SAFETY_BIAS else 'FAIL':>10}"
        )
        print(f"    deltas: sm={sm_delta:+.4f}, c={c_delta:+.4f}, sm14={sm14_delta:+.4f}, c14={c14_delta:+.4f}, bias_abs={bias_delta:+.3f}")

        if safe and pc != "power_pred_final" and row["score"] < bl_score:
            if best_candidate is None or row["score"] < best_score:
                best_candidate = pc
                best_score = row["score"]
                best_pred_col = pc

    print(f"\n{'='*60}")
    if best_candidate is None:
        print("所有候选均不满足安全约束或无改善，回退到 Round58 baseline。")
        final_pred_col = "power_pred_final"
        adopted = False
    else:
        print(f"采用候选: {best_candidate} (score={best_score:.4f} vs baseline={bl_score:.4f})")
        final_pred_col = best_candidate
        adopted = True

    # Update df with final prediction
    df["power_pred_final_round60"] = df[final_pred_col].copy()

    # Save updated full pkl
    full_out = OUT / "predictions/distributed_predictions_final_full.pkl"
    df.to_pickle(full_out)
    print(f"[INFO] Updated full pkl: {full_out}")

    # Save eval pkl
    eval_df = df[df["split"] == "test"].copy()
    eval_df["power_pred_final"] = eval_df[final_pred_col].copy()
    eval_df = eval_df[eval_df["hour"].between(6, 19)].copy()
    eval_out = OUT / "predictions/distributed_predictions_final_eval.pkl"
    eval_df.to_pickle(eval_out)
    print(f"[INFO] Updated eval pkl: {eval_out} ({len(eval_df)} rows)")

    # Save selection result
    results_df["selected"] = results_df["pred_col"] == final_pred_col
    results_df["score"] = results_df.apply(compute_score, axis=1)
    results_df.to_csv(CAL / "round60_model_selection_valid.csv", index=False, encoding="utf-8-sig")
    print(f"[INFO] Saved: round60_model_selection_valid.csv")

    print(f"\n{'='*60}")
    print(f"ROUND60 DECISION: {'ADOPTED' if adopted else 'REVERTED'}")
    print(f"  Final: {final_pred_col}")
    print(f"  Baseline score: {bl_score:.4f}")
    if adopted:
        print(f"  Selected score: {best_score:.4f} (delta={best_score - bl_score:+.4f})")
    print(f"  Valid sm_nrmse_6_19 baseline: {bl['sm_nrmse_6_19']:.4f}%")
    print(f"  Valid c_nrmse_6_19 baseline: {bl['c_nrmse_6_19']:.4f}%")
    print(f"  Valid bias_6_19 baseline: {bl['bias_6_19']:.4f}%")


if __name__ == "__main__":
    main()
