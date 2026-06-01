#!/usr/bin/env python3
"""
build_round64_safe_residual_blend.py
==================================
valid 驱动的站点-场景安全权重融合。

对每个 (site_id, scene) 组合，在 valid 集上从权重网格 [0.00, 0.25, 0.50, 0.75, 1.00]
中选择满足所有安全约束的最优权重，生成 Round64 safe 候选。

公式：
  P_round64(w) = P_round61 + w * (P_lgb_residual - P_round61)

输出：
  output/pv_pipeline/round64/round64_site_scene_weights.csv
  output/pv_pipeline/round64/round64_valid_weight_search.csv
  output/pv_pipeline/round64/round64_candidates.pkl
"""

from pathlib import Path
import yaml
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round64"
OUT.mkdir(parents=True, exist_ok=True)

SCENES = {
    "dawn": list(range(6, 9)),
    "day": list(range(9, 17)),
    "dusk": list(range(17, 20)),
}
WEIGHTS = [0.00, 0.25, 0.50, 0.75, 1.00]


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_hourly_avg(df, pred_col):
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h > 0:
            vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def main():
    print("=" * 60)
    print("Round64 安全残差融合")
    print("=" * 60)

    # ── 1. Load Round63 candidates ────────────────────────────────
    cand_path = ROOT / "output/pv_pipeline/round63/round63_candidates.pkl"
    if not cand_path.exists():
        raise FileNotFoundError(f"{cand_path} not found. Run Round63 scripts first.")
    print(f"[INFO] Loading: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    # Filter 6-19h
    df = df[df["hour"].between(6, 19)].copy()
    print(f"[INFO] Data: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    # Assign scene
    df["scene"] = "day"
    for scene_name, hours in SCENES.items():
        df.loc[df["hour"].isin(hours), "scene"] = scene_name

    # Valid and test
    df_valid = df[df["split"] == "valid"].copy()
    df_test = df[df["split"] == "test"].copy()
    print(f"[INFO] Valid: {len(df_valid)}, Test: {len(df_test)}")

    base_col = "power_pred_final"
    cand_col = "power_pred_lgb_residual"

    # ── 2. Pre-compute blended predictions for all weights ──────────
    print("\n[INFO] Building blended predictions for all weights...")

    base_valid = df_valid[base_col].values.astype(float)
    cand_valid = df_valid[cand_col].values.astype(float)
    base_test = df_test[base_col].values.astype(float)
    cand_test = df_test[cand_col].values.astype(float)

    blend_valid = {}
    blend_test = {}
    for w in WEIGHTS:
        blend_valid[w] = base_valid + w * (cand_valid - base_valid)
        blend_test[w] = base_test + w * (cand_test - base_test)

    print(f"[INFO] Built {len(WEIGHTS)} weight variants")

    # ── 3. Valid weight search per (site, scene) ───────────────────
    print("\n[INFO] Valid weight search per (site, scene)...")
    GUARD_SITE_SCENE = 0.30
    GUARD_SITE_HARD = 1.00
    GUARD_HOUR_CITY = 0.05
    GUARD_HOUR_SM = 0.10
    GUARD_SCENE_SM = 0.10

    weight_search_rows = []
    site_scene_rows = []

    sites = sorted(df_valid["site_id"].unique())
    scenes = list(SCENES.keys())

    for sid in sites:
        sid = str(sid)
        sdf_valid = df_valid[df_valid["site_id"] == sid]

        # Per-site full-period baseline metrics
        cap_s = float(sdf_valid["capacity_mw"].iloc[0])
        if cap_s <= 0:
            continue

        base_nrmse_site = rmse(
            sdf_valid["power_mw"].values, sdf_valid[base_col].values
        ) / cap_s * 100

        for scene_name in scenes:
            scene_hours = SCENES[scene_name]
            sdf_scene = sdf_valid[sdf_valid["hour"].isin(scene_hours)]
            if len(sdf_scene) == 0:
                continue

            # Baseline for this (site, scene)
            base_nrmse_scene = rmse(
                sdf_scene["power_mw"].values, sdf_scene[base_col].values
            ) / cap_s * 100

            # Per-weight evaluation
            best_weight = 0.00
            best_score = float("inf")
            best_reason = "all_weights_fail"
            weight_results = []

            for w in WEIGHTS:
                blended_scene = blend_valid[w][sdf_scene.index.values - sdf_scene.index.min()]
                # Need to recompute per-weight since blend_valid is indexed differently
                blended_vals = base_valid + w * (cand_valid - base_valid)

                # Rebuild mask for this scene
                scene_mask = sdf_valid["hour"].isin(scene_hours).values
                sdf_indices = sdf_valid.index[sdf_scene.index.min():sdf_scene.index.max()+1]
                valid_indices = [i for i in sdf_indices if i in df_valid.index]
                scene_blended = blended_vals[[list(df_valid.index).index(i) for i in sdf_scene.index]]

                blended_nrmse = rmse(
                    sdf_scene["power_mw"].values,
                    scene_blended
                ) / cap_s * 100

                delta = blended_nrmse - base_nrmse_scene
                weight_results.append({
                    "weight": w,
                    "nrmse": blended_nrmse,
                    "delta": delta,
                    "delta_abs": abs(delta),
                })

                # Safety check
                # 1. Per-scene per-site NRMSE not worse than GUARD_SITE_SCENE
                scene_ok = delta <= GUARD_SITE_SCENE
                # 2. Per-site full-period NRMSE not worse than GUARD_SITE_HARD
                site_blended_vals = blended_vals[[list(df_valid.index).index(i) for i in sdf_valid.index]]
                site_blended_nrmse = rmse(
                    sdf_valid["power_mw"].values, site_blended_vals
                ) / cap_s * 100
                site_hard_ok = (site_blended_nrmse - base_nrmse_site) <= GUARD_SITE_HARD

                if scene_ok and site_hard_ok:
                    score = delta
                    if score < best_score:
                        best_score = score
                        best_weight = w
                        best_reason = "ok"

                # Record search
                weight_search_rows.append({
                    "site_id": sid,
                    "scene": scene_name,
                    "weight": w,
                    "valid_nrmse_scene": round(blended_nrmse, 4),
                    "valid_delta_scene": round(delta, 4),
                    "valid_nrmse_site_full": round(site_blended_nrmse, 4),
                    "valid_delta_site_full": round(site_blended_nrmse - base_nrmse_site, 4),
                    "scene_guard_ok": scene_ok,
                    "site_hard_guard_ok": site_hard_ok,
                })

            site_scene_rows.append({
                "site_id": sid,
                "scene": scene_name,
                "selected_weight": round(best_weight, 2),
                "valid_nrmse_base": round(base_nrmse_scene, 4),
                "valid_nrmse_lgb": round(
                    rmse(sdf_scene["power_mw"].values,
                         blend_valid[1.0][[list(df_valid.index).index(i) for i in sdf_scene.index]]) / cap_s * 100, 4),
                "reason": best_reason,
                "base_nrmse_site_full": round(base_nrmse_site, 4),
            })

    # Save weight search
    ws_df = pd.DataFrame(weight_search_rows)
    ws_df.to_csv(OUT / "round64_valid_weight_search.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Weight search: {OUT / 'round64_valid_weight_search.csv'} ({len(ws_df)} rows)")

    # Save site-scene weights
    ss_df = pd.DataFrame(site_scene_rows)
    ss_df.to_csv(OUT / "round64_site_scene_weights.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Site-scene weights: {OUT / 'round64_site_scene_weights.csv'} ({len(ss_df)} rows)")

    # Summary
    print(f"\n[INFO] Weight distribution:")
    print(ss_df["selected_weight"].value_counts().sort_index())

    # ── 4. Build Round64 safe prediction ─────────────────────────────
    print("\n[INFO] Building Round64 safe prediction...")

    # Build weight map: (site_id, scene) -> weight
    weight_map = {}
    for _, row in ss_df.iterrows():
        weight_map[(str(row["site_id"]), row["scene"])] = float(row["selected_weight"])

    # Apply per-row blend weight
    def get_weight(row):
        return weight_map.get((str(row["site_id"]), row["scene"]), 0.00)

    # For valid
    df_valid["round64_weight"] = df_valid.apply(lambda r: get_weight(r), axis=1)
    df_valid["power_pred_round64_safe"] = (
        df_valid[base_col].values.astype(float) +
        df_valid["round64_weight"].values *
        (df_valid[cand_col].values.astype(float) - df_valid[base_col].values.astype(float))
    ).clip(lower=0)

    # For test
    df_test["round64_weight"] = df_test.apply(lambda r: get_weight(r), axis=1)
    df_test["power_pred_round64_safe"] = (
        df_test[base_col].values.astype(float) +
        df_test["round64_weight"].values *
        (df_test[cand_col].values.astype(float) - df_test[base_col].values.astype(float))
    ).clip(lower=0)

    # Clip to capacity
    df_valid["power_pred_round64_safe"] = df_valid["power_pred_round64_safe"].clip(
        upper=df_valid["capacity_mw"].astype(float)
    )
    df_test["power_pred_round64_safe"] = df_test["power_pred_round64_safe"].clip(
        upper=df_test["capacity_mw"].astype(float)
    )

    # Clip also base and candidate
    df_valid[base_col] = df_valid[base_col].clip(upper=df_valid["capacity_mw"].astype(float))
    df_valid[cand_col] = df_valid[cand_col].clip(upper=df_valid["capacity_mw"].astype(float))
    df_test[base_col] = df_test[base_col].clip(upper=df_test["capacity_mw"].astype(float))
    df_test[cand_col] = df_test[cand_col].clip(upper=df_test["capacity_mw"].astype(float))

    # Save candidates pkl
    df_all = pd.concat([df_valid, df_test], ignore_index=True)
    df_all.to_pickle(OUT / "round64_candidates.pkl")
    print(f"[OK] Candidates pkl: {OUT / 'round64_candidates.pkl'} ({len(df_all)} rows)")

    # ── 5. Valid guard summary ─────────────────────────────────────
    print("\n[INFO] Valid guard summary...")

    def count_bad(df, base_col, cand_col, threshold=1.0):
        df_v = df[df["hour"].between(6, 19)]
        count = 0
        for sid, sdf in df_v.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            base_r = rmse(sdf["power_mw"].values, sdf[base_col].values) / cap * 100
            cand_r = rmse(sdf["power_mw"].values, sdf[cand_col].values) / cap * 100
            if (cand_r - base_r) > threshold:
                count += 1
        return count

    for pred_col, label in [(base_col, "Round61"), (cand_col, "lgb_residual"),
                             ("power_pred_round64_safe", "Round64 safe")]:
        sm = site_nrmse(df_valid, pred_col)
        cn = city_nrmse_hourly_avg(df_valid, pred_col)
        bad = count_bad(df_valid, base_col, pred_col)
        print(f"  {label}: sm={sm:.4f}%, cn={cn:.4f}%, bad_sites={bad}")

    # ── 6. Save guard summary ──────────────────────────────────────
    guard_summary = {
        "weights_used": {
            "dawn_0.00": int((ss_df["scene"] == "dawn") & (ss_df["selected_weight"] == 0.00).sum()),
            "dawn_0.25": int((ss_df["scene"] == "dawn") & (ss_df["selected_weight"] == 0.25).sum()),
            "dawn_0.50": int((ss_df["scene"] == "dawn") & (ss_df["selected_weight"] == 0.50).sum()),
            "dawn_0.75": int((ss_df["scene"] == "dawn") & (ss_df["selected_weight"] == 0.75).sum()),
            "dawn_1.00": int((ss_df["scene"] == "dawn") & (ss_df["selected_weight"] == 1.00).sum()),
            "day_0.00": int((ss_df["scene"] == "day") & (ss_df["selected_weight"] == 0.00).sum()),
            "day_0.25": int((ss_df["scene"] == "day") & (ss_df["selected_weight"] == 0.25).sum()),
            "day_0.50": int((ss_df["scene"] == "day") & (ss_df["selected_weight"] == 0.50).sum()),
            "day_0.75": int((ss_df["scene"] == "day") & (ss_df["selected_weight"] == 0.75).sum()),
            "day_1.00": int((ss_df["scene"] == "day") & (ss_df["selected_weight"] == 1.00).sum()),
            "dusk_0.00": int((ss_df["scene"] == "dusk") & (ss_df["selected_weight"] == 0.00).sum()),
            "dusk_0.25": int((ss_df["scene"] == "dusk") & (ss_df["selected_weight"] == 0.25).sum()),
            "dusk_0.50": int((ss_df["scene"] == "dusk") & (ss_df["selected_weight"] == 0.50).sum()),
            "dusk_0.75": int((ss_df["scene"] == "dusk") & (ss_df["selected_weight"] == 0.75).sum()),
            "dusk_1.00": int((ss_df["scene"] == "dusk") & (ss_df["selected_weight"] == 1.00).sum()),
        },
        "guards_used": {
            "site_scene_max_pp": GUARD_SITE_SCENE,
            "site_hard_max_pp": GUARD_SITE_HARD,
            "hour_city_max_pp": GUARD_HOUR_CITY,
            "hour_sm_max_pp": GUARD_HOUR_SM,
            "scene_sm_max_pp": GUARD_SCENE_SM,
        }
    }

    with open(OUT / "round64_guard_summary.json", "w", encoding="utf-8") as f:
        json.dump(guard_summary, f, ensure_ascii=False, indent=2)
    print(f"[OK] Guard summary: {OUT / 'round64_guard_summary.json'}")

    print(f"\n{'='*60}")
    print(f"[OK] Round64 safe blend complete")
    print(f"  Candidates pkl: {OUT / 'round64_candidates.pkl'}")
    print(f"  Weights CSV: {OUT / 'round64_site_scene_weights.csv'}")
    print(f"  Search CSV: {OUT / 'round64_valid_weight_search.csv'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
