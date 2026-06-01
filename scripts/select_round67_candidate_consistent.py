#!/usr/bin/env python3
"""
select_round67_candidate_consistent.py
==================================
用统一口径复核 Round67 候选的有效性。

门控规则（对 valid）：
  bad_site_gt_1pp == 0
  city_nrmse_6_19 <= baseline + 0.05pp
  city_nrmse_10_14 <= baseline
  site_mean_nrmse <= baseline - 0.05pp
  pred_actual_extreme_count <= baseline
  abs_bias_6_19 <= baseline_abs_bias + 0.5pp
"""

from pathlib import Path
import pandas as pd
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
ROUND68 = OUT / "round68"


def main():
    print("=" * 60)
    print("Round67 Candidate Redetermination (Consistent)")
    print("=" * 60)

    # Load recomputed metrics
    metrics = pd.read_csv(ROUND68 / "round67_valid_metrics_recomputed.csv")

    baseline_row = metrics[
        (metrics["candidate"] == "round64_final") &
        (metrics["split"] == "valid")
    ].iloc[0]

    BL = {
        "sm_nrmse": float(baseline_row["site_mean_nrmse_6_19_pct"]),
        "city_nrmse": float(baseline_row["city_nrmse_6_19_pct"]),
        "city_10_14": float(baseline_row["city_nrmse_10_14_pct"]),
        "abs_bias": float(baseline_row["abs_bias_6_19_pct"]),
        "extreme": int(baseline_row["pred_actual_extreme_count"]),
    }
    print(f"\n[Baseline] round64_final on valid:")
    for k, v in BL.items():
        print(f"  {k}: {v}")

    print(f"\n[Gate thresholds]:")
    print(f"  city_nrmse <= {BL['city_nrmse'] + 0.05:.4f}")
    print(f"  city_10_14 <= {BL['city_10_14']:.4f}")
    print(f"  sm_nrmse <= {BL['sm_nrmse']:.4f} (need -0.05)")
    print(f"  abs_bias <= {BL['abs_bias'] + 0.5:.4f}")
    print(f"  bad_1pp == 0")
    print(f"  extreme_count <= {BL['extreme']}")

    candidates = [c for c in metrics["candidate"].unique() if c != "round64_final"]
    gate_detail_rows = []
    decisions = {}

    for cand in candidates:
        row = metrics[(metrics["candidate"] == cand) & (metrics["split"] == "valid")].iloc[0]
        checks = {
            "bad_site_gt_1pp == 0": (int(row["bad_site_gt_1pp_count"]) == 0,
                                      f"{int(row['bad_site_gt_1pp_count'])} bad sites"),
            f"city_nrmse <= {BL['city_nrmse'] + 0.05:.4f}": (
                float(row["city_nrmse_6_19_pct"]) <= BL["city_nrmse"] + 0.05,
                f"{float(row['city_nrmse_6_19_pct']):.4f}"
            ),
            f"city_10_14 <= {BL['city_10_14']:.4f}": (
                float(row["city_nrmse_10_14_pct"]) <= BL["city_10_14"],
                f"{float(row['city_nrmse_10_14_pct']):.4f}"
            ),
            f"sm_nrmse <= {BL['sm_nrmse']:.4f}": (
                float(row["site_mean_nrmse_6_19_pct"]) <= BL["sm_nrmse"] - 0.05,
                f"{float(row['site_mean_nrmse_6_19_pct']):.4f}"
            ),
            f"extreme_count <= {BL['extreme']}": (
                int(row["pred_actual_extreme_count"]) <= BL["extreme"],
                f"{int(row['pred_actual_extreme_count'])}"
            ),
            f"abs_bias <= {BL['abs_bias'] + 0.5:.4f}": (
                float(row["abs_bias_6_19_pct"]) <= BL["abs_bias"] + 0.5,
                f"{float(row['abs_bias_6_19_pct']):.4f}"
            ),
        }

        passed = all(v[0] for v in checks.values())
        failed = [k for k, v in checks.items() if not v[0]]

        decisions[cand] = {
            "passed": passed,
            "failed_checks": failed,
            "metrics": {
                "sm_nrmse": float(row["site_mean_nrmse_6_19_pct"]),
                "city_nrmse": float(row["city_nrmse_6_19_pct"]),
                "city_10_14": float(row["city_nrmse_10_14_pct"]),
                "bias": float(row["bias_6_19_pct"]),
                "abs_bias": float(row["abs_bias_6_19_pct"]),
                "bad_1pp": int(row["bad_site_gt_1pp_count"]),
                "extreme": int(row["pred_actual_extreme_count"]),
            }
        }

        print(f"\n{cand}:")
        for k, (ok, val) in checks.items():
            print(f"  {'[PASS]' if ok else '[FAIL]'} {k} | actual={val}")
        print(f"  --> {'PASS all gates' if passed else 'FAIL: ' + ', '.join(failed)}")

        gate_detail_rows.append({
            "candidate": cand,
            **{f"check_{k}": "PASS" if v[0] else "FAIL" for k, v in checks.items()},
            **{f"actual_{k}": v[1] for k, v in checks.items()},
            "overall": "PASS" if passed else "FAIL",
            "failed_checks": ", ".join(failed),
        })

    # Determine final decision
    passed_cands = [c for c, d in decisions.items() if d["passed"]]

    if not passed_cands:
        # All failed — check if any have potential (sm_nrmse better but bias/extreme bad)
        sm_better = [c for c, d in decisions.items()
                     if d["metrics"]["sm_nrmse"] < BL["sm_nrmse"]]
        if sm_better:
            print(f"\n[RESULT] No candidate passes all gates.")
            print(f"  sm_nrmse better than baseline: {sm_better}")
            print(f"  These candidates have better site-level NRMSE but fail gates.")
            selected = None
            decision = "keep_round64_final"  # Keep baseline
            reason = f"All candidates fail valid gates. sm_nrmse_better={sm_better}. Keeping round64_final."
        else:
            selected = None
            decision = "keep_round64_final"
            reason = "All candidates fail valid gates. Keeping round64_final."
    else:
        # Pick best by sm_nrmse
        best = min(passed_cands, key=lambda c: decisions[c]["metrics"]["sm_nrmse"])
        selected = best
        decision = "adopt_round67_candidate_for_review"
        reason = f"{best} passes all valid gates (sm_nrmse better)"

    print(f"\n{'='*60}")
    print(f"[RESULT] Selected: {selected}")
    print(f"[RESULT] Decision: {decision}")
    print(f"[RESULT] Reason: {reason}")

    # Save gate detail
    gate_df = pd.DataFrame(gate_detail_rows)
    gate_df.to_csv(ROUND68 / "round67_valid_gate_detail.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] Gate detail: {ROUND68 / 'round67_valid_gate_detail.csv'}")

    # Save decision
    result = {
        "baseline": "power_pred_final",
        "baseline_valid_metrics": BL,
        "selected_candidate": selected,
        "decision": decision,
        "reason": reason,
        "passed_candidates": passed_cands,
        "candidates_detail": decisions,
    }
    with open(ROUND68 / "round67_candidate_redecision.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] Decision: {ROUND68 / 'round67_candidate_redecision.json'}")


if __name__ == "__main__":
    main()
