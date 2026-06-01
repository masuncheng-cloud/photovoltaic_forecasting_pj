#!/usr/bin/env python3
"""
select_round59_final_prediction.py
===================================
在 valid 集上评估所有候选预测，选择最优或回退 baseline。

候选列：
  power_pred_final         -> baseline Round58
  power_pred_round59_hour_scene  -> only hour×scene
  power_pred_round59_site        -> only site
  power_pred_round59_combined    -> hour_scene + site

评分（仅用 valid 集）：
  score = 0.40 * valid_site_mean_nrmse_6_19
        + 0.25 * valid_city_nrmse_6_19
        + 0.20 * valid_site_mean_nrmse_10_14
        + 0.15 * abs(valid_bias_6_19)

安全约束（相对于 baseline）：
  valid_city_nrmse_6_19    不得高于 baseline + 0.5pp
  valid_site_mean_nrmse_6_19 不得高于 baseline + 0.5pp
  valid_10_14_city_nrmse  不得高于 baseline + 0.5pp
  valid_bias_abs           不得高于 baseline + 2pp

如果候选不满足安全约束，回退 baseline。

输出：
  output/pv_pipeline/calibration/round59_model_selection_valid.csv
  output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
  (with power_pred_final_round59 and power_pred_final updated)
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
OUT.mkdir(parents=True, exist_ok=True)


def load_quality_policy():
    p = ROOT / "configs" / "site_quality_policy.yaml"
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f)
    return {}


def _rmse(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col, actual_col="power_mw"):
    """Mean of per-site NRMSE, each normalized by its own capacity."""
    rows = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        a = sdf[actual_col].values
        p = sdf[pred_col].values
        r = _rmse(a, p) / cap * 100
        rows.append(r)
    if not rows:
        return np.nan
    return float(np.mean(rows))


def city_nrmse(df, pred_col, actual_col="power_mw"):
    """NRMSE of city-aggregated values, normalized by total city capacity."""
    cap_total = float(df.groupby("site_id")["capacity_mw"].first().sum())
    if cap_total <= 0:
        return np.nan
    a = df[actual_col].values
    p = df[pred_col].values
    return _rmse(a, p) / cap_total * 100


def bias_pct(df, pred_col, actual_col="power_mw"):
    a_sum = float(df[actual_col].sum())
    p_sum = float(df[pred_col].sum())
    if a_sum <= 0:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def evaluate_on_valid(candidates_df, pred_col, hour_range=(6, 19)):
    """Evaluate a prediction column on valid set 6-19 hours."""
    df_v = candidates_df[
        (candidates_df["split"] == "valid") &
        (candidates_df["hour"].between(hour_range[0], hour_range[1]))
    ].copy()
    if len(df_v) == 0:
        return None

    sm_nrmse_6_19 = site_mean_nrmse(df_v, pred_col)
    c_nrmse_6_19 = city_nrmse(df_v, pred_col)
    bias = bias_pct(df_v, pred_col)

    # 10-14 subset
    df_10_14 = df_v[df_v["hour"].between(10, 14)]
    c_nrmse_10_14 = city_nrmse(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan

    return {
        "pred_col": pred_col,
        "sm_nrmse_6_19": round(sm_nrmse_6_19, 4),
        "c_nrmse_6_19": round(c_nrmse_6_19, 4),
        "c_nrmse_10_14": round(c_nrmse_10_14, 4) if not np.isnan(c_nrmse_10_14) else np.nan,
        "bias_6_19": round(bias, 4),
        "abs_bias_6_19": round(abs(bias), 4),
    }


def compute_score(row, w_sm_nrmse=0.40, w_c_nrmse=0.25, w_sm_nrmse_10_14=0.20, w_abs_bias=0.15):
    """Weighted score. Lower is better."""
    score = (
        w_sm_nrmse * row["sm_nrmse_6_19"] +
        w_c_nrmse * row["c_nrmse_6_19"] +
        w_sm_nrmse_10_14 * row["sm_nrmse_10_14"] +
        w_abs_bias * row["abs_bias_6_19"]
    )
    return round(score, 6)


def main():
    print("=" * 60)
    print("Round59 候选选择（仅用 valid 集）")
    print("=" * 60)

    # Load candidates
    cand_path = OUT / "predictions" / "distributed_predictions_round59_candidates.pkl"
    if not cand_path.exists():
        raise FileNotFoundError(f"{cand_path} not found")
    print(f"[INFO] Loading candidates: {cand_path}")
    df = pd.read_pickle(cand_path)
    print(f"[INFO] {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    candidates = [
        ("power_pred_final", "baseline Round58"),
        ("power_pred_round59_hour_scene", "hour_scene only"),
        ("power_pred_round59_site", "site only"),
        ("power_pred_round59_combined", "combined"),
    ]

    print(f"\n{'='*60}")
    print(f"{'Candidate':<30} {'sm_nrmse_6_19':>14} {'c_nrmse_6_19':>14} {'c_nrmse_10_14':>14} {'bias_6_19':>10} {'abs_bias':>10} {'score':>10}")
    print(f"{'='*60}")

    results = []
    for pred_col, label in candidates:
        if pred_col not in df.columns:
            print(f"[WARN] {pred_col} not found, skipping")
            continue
        eval_result = evaluate_on_valid(df, pred_col)
        if eval_result is None:
            continue
        eval_result["label"] = label
        eval_result["score"] = compute_score(eval_result)
        results.append(eval_result)
        print(
            f"{label:<30} {eval_result['sm_nrmse_6_19']:>14.4f} "
            f"{eval_result['c_nrmse_6_19']:>14.4f} "
            f"{eval_result['c_nrmse_10_14']:>14.4f} "
            f"{eval_result['bias_6_19']:>10.2f} "
            f"{eval_result['abs_bias_6_19']:>10.2f} "
            f"{eval_result['score']:>10.4f}"
        )

    results_df = pd.DataFrame(results)
    results_df.to_csv(
        OUT / "calibration" / "round59_model_selection_valid.csv",
        index=False, encoding="utf-8-sig"
    )
    print(f"\n[INFO] Saved: round59_model_selection_valid.csv")

    # Baseline row
    baseline_row = results_df[results_df["pred_col"] == "power_pred_final"]
    if len(baseline_row) == 0:
        raise ValueError("Baseline row not found!")
    bl = baseline_row.iloc[0]

    # Safety constraints
    SAFETY_DELTA_NRMSE = 0.5
    SAFETY_DELTA_BIAS = 2.0

    print(f"\n{'='*60}")
    print("安全约束检查（相对于 baseline）")
    print(f"{'='*60}")
    print(f"{'Candidate':<30} {'safe?':>8} {'c_nrmse_safe':>12} {'sm_nrmse_safe':>12} {'10_14_safe':>12} {'bias_safe':>10}")
    print("-" * 90)

    best_candidate = None
    best_score = bl["score"]
    best_pred_col = "power_pred_final"

    for _, row in results_df.iterrows():
        pc = row["pred_col"]
        c_nrmse_delta = row["c_nrmse_6_19"] - bl["c_nrmse_6_19"]
        sm_nrmse_delta = row["sm_nrmse_6_19"] - bl["sm_nrmse_6_19"]
        nrmse_10_14_delta = (
            (row["c_nrmse_10_14"] - bl["c_nrmse_10_14"]) if (
                not np.isnan(row["c_nrmse_10_14"]) and not np.isnan(bl["c_nrmse_10_14"])
            ) else 0.0
        )
        bias_delta = abs(row["bias_6_19"]) - abs(bl["bias_6_19"])

        safe = (
            c_nrmse_delta <= SAFETY_DELTA_NRMSE and
            sm_nrmse_delta <= SAFETY_DELTA_NRMSE and
            nrmse_10_14_delta <= SAFETY_DELTA_NRMSE and
            bias_delta <= SAFETY_DELTA_BIAS
        )

        safe_str = "SAFE" if safe else "UNSAFE"
        print(
            f"{row['label']:<30} {safe_str:>8} "
            f"{'OK' if c_nrmse_delta <= SAFETY_DELTA_NRMSE else 'FAIL':>12} "
            f"{'OK' if sm_nrmse_delta <= SAFETY_DELTA_NRMSE else 'FAIL':>12} "
            f"{'OK' if nrmse_10_14_delta <= SAFETY_DELTA_NRMSE else 'FAIL':>12} "
            f"{'OK' if bias_delta <= SAFETY_DELTA_BIAS else 'FAIL':>10}"
        )
        print(f"    deltas: c_nrmse={c_nrmse_delta:+.3f}, sm_nrmse={sm_nrmse_delta:+.3f}, "
              f"10_14={nrmse_10_14_delta:+.3f}, bias_abs={bias_delta:+.3f}")

        if safe and pc != "power_pred_final" and row["score"] < best_score:
            best_candidate = pc
            best_score = row["score"]
            best_pred_col = pc

    # Decision
    print(f"\n{'='*60}")
    if best_candidate is None:
        print("所有候选均不满足安全约束或无改善，回退到 baseline Round58。")
        final_pred_col = "power_pred_final"
        adopted = False
    else:
        print(f"采用候选: {best_candidate} (score={best_score:.4f})")
        final_pred_col = best_candidate
        adopted = True

    # Update df with final prediction
    df["power_pred_final_round59"] = df[final_pred_col].copy()

    # Also create eval pkl with round59 final
    eval_df = df[df["split"] == "test"].copy()
    eval_df["power_pred_final"] = eval_df[final_pred_col].copy()

    # Save updated full pkl
    full_out = OUT / "predictions" / "distributed_predictions_final_full.pkl"
    df.to_pickle(full_out)
    print(f"[INFO] Updated full pkl: {full_out}")

    # Save eval pkl
    eval_out = OUT / "predictions" / "distributed_predictions_final_eval.pkl"
    eval_df.to_pickle(eval_out)
    print(f"[INFO] Updated eval pkl: {eval_out}")

    # Save selection result
    sel_df = results_df.copy()
    sel_df["selected"] = sel_df["pred_col"] == final_pred_col
    sel_df["score"] = sel_df.apply(compute_score, axis=1)
    sel_df.to_csv(
        OUT / "calibration" / "round59_model_selection_valid.csv",
        index=False, encoding="utf-8-sig"
    )

    print(f"\n{'='*60}")
    print(f"ROUND59 DECISION: {'ADOPTED' if adopted else 'REVERTED'}")
    print(f"  Final prediction column: {final_pred_col}")
    print(f"  Baseline valid score: {bl['score']:.4f}")
    if adopted:
        sel_row = results_df[results_df["pred_col"] == final_pred_col].iloc[0]
        print(f"  Selected score: {sel_row['score']:.4f}")
        print(f"  Delta: {sel_row['score'] - bl['score']:+.4f}")
    print(f"  Valid c_nrmse_6_19: {bl['c_nrmse_6_19']:.4f}%")
    print(f"  Valid sm_nrmse_6_19: {bl['sm_nrmse_6_19']:.4f}%")
    print(f"  Valid c_nrmse_10_14: {bl['c_nrmse_10_14']:.4f}%")
    print(f"  Valid bias_6_19: {bl['bias_6_19']:.4f}%")


if __name__ == "__main__":
    main()
