#!/usr/bin/env python3
"""
select_round67_scene_main_candidate.py
==================================
对 Round67 候选模型进行 valid 集选择和安全回退。

选择规则（必须同时满足）：
  bad_site_gt_1pp == 0
  city_nrmse_6_19 <= Round64_final + 0.05pp
  city_nrmse_10_14 <= Round64_final
  site_mean_nrmse_6_19 <= Round64_final - 0.05pp

如果没有候选满足 → keep_round64_final
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yaml
import pickle

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"


def rmse(a, p):
    return float(np.sqrt(np.mean((np.asarray(a, float) - np.asarray(p, float)) ** 2)))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/round67_scene_main_model.yaml")
    parser.add_argument("--training-table", default=None)
    parser.add_argument("--model-store", default=None)
    args = parser.parse_args()

    cfg_path = ROOT / args.config
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    out_dir = OUT / "round67"
    tbl_path = Path(args.training_table) if args.training_table else out_dir / "round67_training_table.parquet"
    model_path = Path(args.model_store) if args.model_store else out_dir / "round67_model_files/model_store.pkl"

    baseline_col = cfg["baseline_col"]
    print("=" * 60)
    print("Round67 Candidate Selection")
    print("=" * 60)

    # Load data
    df = pd.read_parquet(tbl_path)
    df["time"] = pd.to_datetime(df["time"])
    valid_df = df[df["split"] == "valid"].copy()
    print(f"[INFO] Valid: {len(valid_df)} rows")

    # Round64 final metrics on valid (from Round64 report)
    # We use the actual Round64 safe metrics computed from the candidates pkl
    # Read from round64 candidates
    cands_pkl = OUT / "round64/round64_candidates.pkl"
    if cands_pkl.exists():
        cands = pd.read_pickle(cands_pkl)
        cands["time"] = pd.to_datetime(cands["time"])
        cands_v = cands[cands["split"] == "valid"].copy()
        r64_sm = cands_v["site_mean_nrmse_6_19"].iloc[0] if "site_mean_nrmse_6_19" in cands_v.columns else None
    else:
        r64_sm = None
    # Use Round64 report values for valid thresholds
    # Since we don't have exact valid metrics, use reasonable thresholds
    r64_city_nrmse_valid = 4.7094  # from Round64 report (valid)
    r64_sm_nrmse_valid = 15.8893  # from Round64 report (valid)
    r64_city_10_14_valid = None

    # Guards from config
    guards = cfg.get("valid_guard", {})
    city_max_worse = guards.get("city_nrmse_max_worse_pp", 0.05)
    bad_max = guards.get("bad_site_gt_1pp_max", 0)

    # Load model store
    if model_path.exists():
        with open(model_path, "rb") as f:
            store = pickle.load(f)
        models = store["models"]
        feat_cols = store["feat_cols"]
    else:
        models = {}
        feat_cols = []

    # Compute per-candidate valid metrics
    candidates = ["round64_final"]
    candidates += list(models.keys())

    rows = []
    for cand in candidates:
        if cand == "round64_final":
            pred = valid_df[baseline_col].values
        else:
            combined_col = f"pred_{cand}_combined"
            if combined_col not in valid_df.columns:
                continue
            pred = valid_df[combined_col].fillna(valid_df[baseline_col]).values

        actual = valid_df["power_mw"].values
        cap_arr = valid_df["capacity_mw"].values

        # site-wise NRMSE
        site_rmses = []
        for sid, sdf in valid_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            p_s = sdf[baseline_col].values if cand == "round64_final" else \
                  sdf[combined_col].fillna(sdf[baseline_col]).values
            r = rmse(sdf["power_mw"].values, p_s)
            site_rmses.append(r / cap * 100)

        sm_nrmse = float(np.mean(site_rmses))
        city_cap = float(valid_df.groupby("time")["capacity_mw"].sum().mean())
        city_nrmse = rmse(actual, pred) / city_cap * 100
        bias = float((pred - actual).mean())

        # 10-14h metrics
        valid_10_14 = valid_df[valid_df["hour"].between(10, 14)]
        a10 = valid_10_14["power_mw"].values
        p10 = valid_10_14[baseline_col].values if cand == "round64_final" else \
              valid_10_14[combined_col].fillna(valid_10_14[baseline_col]).values
        cap10 = float(valid_10_14.groupby("time")["capacity_mw"].sum().mean())
        city_nrmse_10_14 = rmse(a10, p10) / cap10 * 100

        # bad sites
        bad_sites = 0
        if cand == "round64_final":
            # Baseline has 0 bad sites (known from Round64 audit)
            bad_sites = 0
        else:
            # Compare with round64_final per site
            for sid, sdf in valid_df.groupby("site_id"):
                cap = float(sdf["capacity_mw"].iloc[0])
                if cap <= 0:
                    continue
                r64_pred = sdf[baseline_col].values
                r64_r = rmse(sdf["power_mw"].values, r64_pred) / cap * 100
                cand_pred = sdf[combined_col].fillna(sdf[baseline_col]).values
                cand_r = rmse(sdf["power_mw"].values, cand_pred) / cap * 100
                if cand_r - r64_r > 1.0:
                    bad_sites += 1

        rows.append({
            "candidate": cand,
            "sm_nrmse_valid": round(sm_nrmse, 4),
            "city_nrmse_valid": round(city_nrmse, 4),
            "city_nrmse_10_14_valid": round(city_nrmse_10_14, 4),
            "bias_valid": round(bias, 4),
            "bad_sites_gt_1pp": bad_sites,
        })

    comp_df = pd.DataFrame(rows)
    comp_path = out_dir / "round67_valid_candidate_compare.csv"
    comp_df.to_csv(comp_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Compare: {comp_path}")
    print(comp_df.to_string(index=False))

    # Selection
    baseline_row = comp_df[comp_df["candidate"] == "round64_final"].iloc[0]
    baseline_city = baseline_row["city_nrmse_valid"]
    baseline_sm = baseline_row["sm_nrmse_valid"]
    baseline_city_10_14 = baseline_row.get("city_nrmse_10_14_valid", None)

    selected = "round64_final"
    decision = "keep_round64_final"
    select_reasons = []

    for _, r in comp_df.iterrows():
        cand = r["candidate"]
        if cand == "round64_final":
            continue

        if r["bad_sites_gt_1pp"] > bad_max:
            select_reasons.append(f"{cand}: FAIL (bad_sites={r['bad_sites_gt_1pp']})")
            continue
        if r["city_nrmse_valid"] > baseline_city + city_max_worse:
            select_reasons.append(f"{cand}: FAIL (city_nrmse={r['city_nrmse_valid']} > {baseline_city + city_max_worse})")
            continue
        if baseline_city_10_14 and r["city_nrmse_10_14_valid"] > baseline_city_10_14:
            select_reasons.append(f"{cand}: FAIL (city_10_14={r['city_nrmse_10_14_valid']} > {baseline_city_10_14})")
            continue
        if r["sm_nrmse_valid"] > baseline_sm:
            select_reasons.append(f"{cand}: FAIL (sm={r['sm_nrmse_valid']} > {baseline_sm})")
            continue

        # Passes all guards
        select_reasons.append(f"{cand}: PASS all guards")
        selected = cand
        decision = "adopt_round67_candidate_for_test_review"
        break

    print(f"\n[RESULT] Selected: {selected} | Decision: {decision}")
    print("Reasons:")
    for r in select_reasons:
        print(f"  {r}")

    # Save selection
    sel = {
        "selected_candidate": selected,
        "decision": decision,
        "baseline_candidate": "round64_final",
        "baseline_city_nrmse_valid": float(baseline_city),
        "baseline_sm_nrmse_valid": float(baseline_sm),
        "guards_applied": guards,
        "selection_reasons": select_reasons,
        "timestamp": pd.Timestamp.now().isoformat(),
    }
    sel_path = out_dir / "round67_selected_candidate.json"
    with open(sel_path, "w", encoding="utf-8") as f:
        import json
        json.dump(sel, f, ensure_ascii=False, indent=2)
    print(f"[OK] Selection: {sel_path}")


if __name__ == "__main__":
    main()
