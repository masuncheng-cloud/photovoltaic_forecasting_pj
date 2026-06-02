#!/usr/bin/env python3
"""
select_round69_performance_candidate.py
==================================
Round69 候选在 valid 上的选择逻辑。
"""

from pathlib import Path
import math
import numpy as np
import pandas as pd
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
ROUND69 = OUT / "round69"


def rmse(a, p):
    a = np.asarray(a, dtype=float); p = np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.mean((p - a) ** 2))))


def bias_pct(a, p):
    a = np.asarray(a, dtype=float); p = np.asarray(p, dtype=float)
    a_sum = float(np.nansum(a)); p_sum = float(np.nansum(p))
    if abs(a_sum) < 1e-12: return 0.0
    return (p_sum - a_sum) / a_sum * 100.0


def compute_metrics(df, pred_col):
    cap_sum = float(df[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())

    # Site mean NRMSE
    rmses = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        rmses.append(r)
    sm_nrmse = float(np.mean(rmses))

    # Site mean NRMSE 10-14
    sub10 = df[df["hour"].between(10, 14)]
    rmses10 = []
    for _, sdf in sub10.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        rmses10.append(r)
    sm_nrmse_10_14 = float(np.mean(rmses10)) if rmses10 else float("nan")

    # City NRMSE
    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    city_nrmse = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100

    # City NRMSE 10-14
    agg10 = sub10.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    cap_sum10 = float(sub10[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
    city_nrmse_10_14 = rmse(agg10["a"].values, agg10["p"].values) / cap_sum10 * 100

    # Bias
    actual = df["power_mw"].values.astype(float)
    pred = df[pred_col].values.astype(float)
    bias = bias_pct(actual, pred)
    abs_bias = abs(bias)

    # Bad sites (>1pp worse than baseline)
    base_col = "power_pred_final"
    bad_1pp = 0
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        r_base = rmse(sdf["power_mw"].values, sdf[base_col].values) / cap * 100
        r_cand = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        if r_cand - r_base > 1.0:
            bad_1pp += 1

    return {
        "sm_nrmse": round(sm_nrmse, 4),
        "sm_nrmse_10_14": round(sm_nrmse_10_14, 4),
        "city_nrmse": round(city_nrmse, 4),
        "city_nrmse_10_14": round(city_nrmse_10_14, 4),
        "bias": round(bias, 4),
        "abs_bias": round(abs_bias, 4),
        "bad_1pp": bad_1pp,
    }


def main():
    print("=" * 60)
    print("Round69 Candidate Selection")
    print("=" * 60)

    df = pd.read_pickle(ROUND69 / "round69_candidates.pkl")
    valid = df[df["split"] == "valid"].copy()
    test  = df[df["split"] == "test"].copy()

    candidates = [c for c in df.columns if c.startswith("power_pred_round69_")]
    print(f"\n[INFO] Candidates: {candidates}")
    print(f"[INFO] Baseline: power_pred_final (round68 lgb_safe_blend)")

    # Compute baseline metrics
    base = compute_metrics(valid, "power_pred_final")
    print(f"\n[Baseline on Valid]")
    print(f"  sm_nrmse: {base['sm_nrmse']}%")
    print(f"  city_nrmse: {base['city_nrmse']}%")
    print(f"  abs_bias: {base['abs_bias']}%")
    print(f"  bad_1pp: {base['bad_1pp']}")

    # Gate thresholds
    G_sm      = base["sm_nrmse"] - 0.10   # must improve by at least 0.10pp
    G_city    = base["city_nrmse"] + 0.05  # city_nrmse can be 0.05pp worse
    G_city14  = base["city_nrmse_10_14"]   # must not be worse
    G_bias    = base["abs_bias"] + 0.30     # abs_bias can be 0.30pp worse
    G_bad     = 0                            # bad_1pp must be 0
    print(f"\n[Gates]")
    print(f"  sm_nrmse <= {G_sm:.4f}")
    print(f"  city_nrmse <= {G_city:.4f}")
    print(f"  city_10_14 <= {G_city14:.4f}")
    print(f"  abs_bias <= {G_bias:.4f}")
    print(f"  bad_1pp == {G_bad}")

    # Evaluate each candidate
    rows = []
    for col in candidates:
        m = compute_metrics(valid, col)
        checks = {
            "sm_nrmse_improves": m["sm_nrmse"] <= G_sm,
            "city_not_too_bad": m["city_nrmse"] <= G_city,
            "city_10_14_ok": m["city_nrmse_10_14"] <= G_city14,
            "abs_bias_ok": m["abs_bias"] <= G_bias,
            "no_bad_sites": m["bad_1pp"] == G_bad,
        }
        passed = all(checks.values())
        rows.append({
            "candidate": col,
            "sm_nrmse": m["sm_nrmse"],
            "delta_sm": round(m["sm_nrmse"] - base["sm_nrmse"], 4),
            "city_nrmse": m["city_nrmse"],
            "delta_city": round(m["city_nrmse"] - base["city_nrmse"], 4),
            "sm_nrmse_10_14": m["sm_nrmse_10_14"],
            "city_nrmse_10_14": m["city_nrmse_10_14"],
            "bias": m["bias"],
            "abs_bias": m["abs_bias"],
            "bad_1pp": m["bad_1pp"],
            "passed": passed,
            "failed": ", ".join(k for k, v in checks.items() if not v),
        })
        status = "PASS" if passed else "FAIL"
        print(f"\n  {col}:")
        print(f"    sm={m['sm_nrmse']}% ({m['sm_nrmse']-base['sm_nrmse']:+.4f}), "
              f"city={m['city_nrmse']}% ({m['city_nrmse']-base['city_nrmse']:+.4f}), "
              f"abs_bias={m['abs_bias']}%, bad_1pp={m['bad_1pp']}")
        print(f"    --> [{status}]")

    df_result = pd.DataFrame(rows)
    df_result.to_csv(ROUND69 / "round69_valid_candidate_compare.csv", index=False, encoding="utf-8-sig")

    # Determine decision
    passed_cands = [r["candidate"] for r in rows if r["passed"]]
    if not passed_cands:
        decision = "keep_round68_final"
        reason = "No candidate passes all valid gates. Keeping round68_final as official baseline."
        selected = None
    else:
        # Pick best by sm_nrmse
        best = min(passed_cands, key=lambda c: next(r["sm_nrmse"] for r in rows if r["candidate"] == c))
        decision = "round69_candidate_for_review"
        reason = f"{best} passes all valid gates and has best sm_nrmse"
        selected = best

    print(f"\n{'='*60}")
    print(f"[RESULT] Selected: {selected}")
    print(f"[RESULT] Decision: {decision}")
    print(f"[RESULT] Reason: {reason}")

    result = {
        "baseline": "power_pred_final (round68 lgb_safe_blend)",
        "baseline_valid_metrics": base,
        "gate_thresholds": {
            "sm_nrmse_max": G_sm,
            "city_nrmse_max": G_city,
            "city_10_14_max": G_city14,
            "abs_bias_max": G_bias,
            "bad_1pp_max": G_bad,
        },
        "selected_candidate": selected,
        "decision": decision,
        "reason": reason,
        "passed_candidates": passed_cands,
        "all_candidates": rows,
    }
    with open(ROUND69 / "round69_candidate_decision.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Saved: {ROUND69 / 'round69_valid_candidate_compare.csv'}")
    print(f"[OK] Saved: {ROUND69 / 'round69_candidate_decision.json'}")


if __name__ == "__main__":
    main()
