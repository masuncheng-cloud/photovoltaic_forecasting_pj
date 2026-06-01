#!/usr/bin/env python3
"""
evaluate_round67_candidate_on_test.py
==================================
对 Round67 候选进行 test 集最终评估。

如果 selected_candidate == round64_final → test 只做基准对比报告。
如果 selected_candidate == round67 → test 评估候选表现。
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yaml
import pickle
import json

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"


def rmse(a, p):
    return float(np.sqrt(np.mean((np.asarray(a, float) - np.asarray(p, float)) ** 2)))


def mae(a, p):
    return float(np.mean(np.abs(np.asarray(a, float) - np.asarray(p, float))))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/round67_scene_main_model.yaml")
    args = parser.parse_args()

    cfg_path = ROOT / args.config
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    out_dir = OUT / "round67"

    # Load selection decision
    sel_path = out_dir / "round67_selected_candidate.json"
    if sel_path.exists():
        sel = json.loads(sel_path.read_text(encoding="utf-8"))
        selected = sel.get("selected_candidate", "round64_final")
        decision = sel.get("decision", "keep_round64_final")
    else:
        selected = "round64_final"
        decision = "keep_round64_final"

    baseline_col = cfg["baseline_col"]
    print("=" * 60)
    print(f"Round67 Test Evaluation — selected: {selected} — {decision}")
    print("=" * 60)

    # Load data
    tbl_path = out_dir / "round67_training_table.parquet"
    if not tbl_path.exists():
        print("[FAIL] Training table not found")
        return
    df = pd.read_parquet(tbl_path)
    df["time"] = pd.to_datetime(df["time"])
    test_df = df[df["split"] == "test"].copy()
    print(f"[INFO] Test: {len(test_df)} rows, {test_df['site_id'].nunique()} sites")

    # Load model store for predictions
    model_path = out_dir / "round67_model_files/model_store.pkl"
    if model_path.exists():
        with open(model_path, "rb") as f:
            store = pickle.load(f)
        models = store["models"]
        feat_cols = store["feat_cols"]
    else:
        models = {}
        feat_cols = []

    # Compute test predictions for each candidate
    test_results = {}

    for model_name, blocks in models.items():
        for block, model_obj in blocks.items():
            mask = test_df["time_block"] == block
            if mask.sum() == 0:
                continue
            X = np.nan_to_num(test_df.loc[mask, feat_cols].values.astype(float), nan=0.0)
            if model_name == "ridge":
                X = model_obj["scaler"].transform(X)
                pred = model_obj["model"].predict(X)
            elif model_name == "lgb":
                pred = model_obj.predict(X)
            else:
                pred = model_obj.predict(X)
            cap = test_df.loc[mask, "capacity_mw"].values
            test_df.loc[mask, f"pred_{model_name}_block_{block}"] = np.clip(pred * cap, 0, cap)

    # Build candidates dict
    candidates = {"round64_final": baseline_col}
    for mn in models:
        cols = [c for c in test_df.columns if c.startswith(f"pred_{mn}_block_")]
        if cols:
            test_df[f"pred_{mn}_combined"] = test_df[cols].mean(axis=1)
            candidates[mn] = f"pred_{mn}_combined"

    # Compute test metrics per candidate
    overall_rows = []
    hourly_rows = []
    site_rows = []

    for cand_name, pred_col in candidates.items():
        actual = test_df["power_mw"].values
        pred = test_df[pred_col].fillna(test_df[baseline_col]).values
        cap_arr = test_df["capacity_mw"].values

        # Overall
        sm_rmses = []
        for sid, sdf in test_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            r = rmse(sdf["power_mw"].values,
                     sdf[pred_col].fillna(sdf[baseline_col]).values)
            sm_rmses.append(r / cap * 100)
        sm_nrmse = float(np.mean(sm_rmses))

        city_rmse = rmse(actual, pred)
        city_cap = float(test_df.groupby("time")["capacity_mw"].sum().mean())
        city_nrmse = city_rmse / city_cap * 100
        bias = float((pred - actual).sum() / actual.sum() * 100)

        # 10-14h
        t10_14 = test_df[test_df["hour"].between(10, 14)]
        a14 = t10_14["power_mw"].values
        p14 = t10_14[pred_col].fillna(t10_14[baseline_col]).values
        cap14 = float(t10_14.groupby("time")["capacity_mw"].sum().mean())
        city_nrmse_10_14 = rmse(a14, p14) / cap14 * 100

        overall_rows.append({
            "candidate": cand_name,
            "site_mean_nrmse_6_19": round(sm_nrmse, 4),
            "city_nrmse_6_19": round(city_nrmse, 4),
            "city_nrmse_10_14": round(city_nrmse_10_14, 4),
            "bias_pct": round(bias, 4),
            "rmse_mw": round(rmse(actual, pred), 4),
            "mae_mw": round(mae(actual, pred), 4),
        })

        # Per-site
        for sid, sdf in test_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            a = sdf["power_mw"].values
            p = sdf[pred_col].fillna(sdf[baseline_col]).values
            r_nrmse = rmse(a, p) / cap * 100
            site_rows.append({
                "candidate": cand_name,
                "site_id": str(sid),
                "capacity_mw": round(cap, 4),
                "nrmse_pct": round(r_nrmse, 4),
                "mae": round(mae(a, p), 4),
                "rmse": round(rmse(a, p), 4),
                "bias_pct": round(float((p - a).sum() / a.sum() * 100) if a.sum() > 0 else 0, 4),
                "positive_samples": int((a > 0).sum()),
                "zero_ratio": round(float((a <= 0).sum() / len(a)), 4),
            })

        # Per-hour
        for hour, hdf in test_df.groupby("hour"):
            a = hdf["power_mw"].values
            p = hdf[pred_col].fillna(hdf[baseline_col]).values
            cap_h = float(hdf.groupby("time")["capacity_mw"].sum().mean())
            hourly_rows.append({
                "candidate": cand_name,
                "hour": hour,
                "city_nrmse": round(rmse(a, p) / cap_h * 100, 4),
                "bias_pct": round(float((p - a).sum() / a.sum() * 100) if a.sum() > 0 else 0, 4),
            })

    overall_df = pd.DataFrame(overall_rows)
    site_df = pd.DataFrame(site_rows)
    hourly_df = pd.DataFrame(hourly_rows)

    overall_path = out_dir / "round67_test_overall_compare.csv"
    overall_df.to_csv(overall_path, index=False, encoding="utf-8-sig")

    hourly_path = out_dir / "round67_test_hourly_compare.csv"
    hourly_df.to_csv(hourly_path, index=False, encoding="utf-8-sig")

    site_path = out_dir / "round67_test_site_compare.csv"
    site_df.to_csv(site_path, index=False, encoding="utf-8-sig")

    print(f"\n[OK] Overall: {overall_path}")
    print(f"[OK] Hourly: {hourly_path}")
    print(f"[OK] Sites: {site_path}")
    print(f"\n{overall_df.to_string(index=False)}")

    # High-error sites
    site_pivot = site_df.pivot(index="site_id", columns="candidate", values="nrmse_pct")
    if "round64_final" in site_pivot.columns and selected in site_pivot.columns:
        site_pivot["delta_vs_r64"] = site_pivot[selected] - site_pivot["round64_final"]
        high_err = site_pivot[site_pivot["delta_vs_r64"] > 1.0].reset_index()
        high_err_path = out_dir / "round67_high_error_site_compare.csv"
        high_err.to_csv(high_err_path, index=False, encoding="utf-8-sig")
        print(f"\n[OK] High error: {high_err_path} ({len(high_err)} sites >+1pp)")
    else:
        print(f"\n[INFO] Skipping high-error site compare (insufficient data)")

    print(f"\n[OK] Test evaluation complete")


if __name__ == "__main__":
    main()
