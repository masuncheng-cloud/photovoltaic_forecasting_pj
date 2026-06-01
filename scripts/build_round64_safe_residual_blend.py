#!/usr/bin/env python3
"""
build_round64_safe_residual_blend.py
==================================
valid 驱动的站点-场景安全权重融合。

对每个 (site_id, scene) 组合，在 valid 集上从权重网格 [0.00, 0.25, 0.50, 0.75, 1.00]
中选择满足所有安全约束的最优（最保守）权重，生成 Round64 safe 候选。

公式：
  P_round64(w) = P_round61 + w * (P_lgb_residual - P_round61)

输出：
  output/pv_pipeline/round64/round64_site_scene_weights.csv
  output/pv_pipeline/round64/round64_valid_weight_search.csv
  output/pv_pipeline/round64/round64_candidates.pkl
  output/pv_pipeline/round64/round64_guard_summary.json
"""

from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round64"
OUT.mkdir(parents=True, exist_ok=True)

SCENES = {"dawn": list(range(6, 9)), "day": list(range(9, 17)), "dusk": list(range(17, 20))}
WEIGHTS = [0.00, 0.25, 0.50, 0.75, 1.00]

# Guards
GUARD_SITE_SCENE = 0.30
GUARD_SITE_HARD = 1.00


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def main():
    print("=" * 60)
    print("Round64 安全残差融合")
    print("=" * 60)

    # ── 1. Load data ──────────────────────────────────────────────
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
    df = df.reset_index(drop=True)
    print(f"[INFO] Data: {len(df)} rows")

    # Assign scene
    def assign_scene(h):
        for name, hours in SCENES.items():
            if h in hours:
                return name
        return "day"

    df["scene"] = df["hour"].apply(assign_scene)

    df_valid = df[df["split"] == "valid"].copy().reset_index(drop=True)
    df_test = df[df["split"] == "test"].copy().reset_index(drop=True)
    print(f"[INFO] Valid: {len(df_valid)}, Test: {len(df_test)}")

    base_col = "power_pred_final"
    cand_col = "power_pred_lgb_residual"

    # Extract arrays
    base_v = df_valid[base_col].values.astype(float)
    cand_v = df_valid[cand_col].values.astype(float)
    actual_v = df_valid["power_mw"].values.astype(float)
    cap_v = df_valid["capacity_mw"].values.astype(float)
    site_v = df_valid["site_id"].values
    scene_v = df_valid["scene"].values
    hour_v = df_valid["hour"].values.astype(int)

    base_t = df_test[base_col].values.astype(float)
    cand_t = df_test[cand_col].values.astype(float)

    # ── 2. Compute baseline per-site NRMSE for valid ─────────────────
    print("\n[INFO] Computing baseline NRMSE per (site, scene)...")
    site_scenes = {}
    sites = sorted(df_valid["site_id"].unique())

    for sid in sites:
        mask = (site_v == sid)
        cap_s = float(cap_v[mask][0])
        if cap_s <= 0:
            continue
        base_nrmse_site = rmse(actual_v[mask], base_v[mask]) / cap_s * 100

        site_scenes[sid] = {"cap": cap_s, "base_nrmse_site": base_nrmse_site, "scenes": {}}
        for scene_name in SCENES:
            scene_hours = SCENES[scene_name]
            scene_mask = mask & np.isin(hour_v, scene_hours)
            if not scene_mask.any():
                continue
            base_nrmse_scene = rmse(actual_v[scene_mask], base_v[scene_mask]) / cap_s * 100
            site_scenes[sid]["scenes"][scene_name] = {
                "base_nrmse_scene": base_nrmse_scene,
                "indices": np.where(scene_mask)[0],
            }

    # ── 3. Weight search per (site, scene) ──────────────────────────
    print("\n[INFO] Searching optimal weight per (site, scene)...")
    weight_search_rows = []
    site_scene_rows = []

    for sid in sites:
        cap_s = site_scenes[sid]["cap"]
        base_nrmse_site = site_scenes[sid]["base_nrmse_site"]

        for scene_name, scene_info in site_scenes[sid]["scenes"].items():
            indices = scene_info["indices"]
            base_nrmse_scene = scene_info["base_nrmse_scene"]

            best_weight = 0.00
            best_reason = "all_fail"
            best_delta = 0.0

            weight_results = []
            for w in WEIGHTS:
                # Blend: P = base + w * (cand - base)
                blended = base_v[indices] + w * (cand_v[indices] - base_v[indices])
                blended_nrmse = rmse(actual_v[indices], blended) / cap_s * 100
                delta = blended_nrmse - base_nrmse_scene

                # Full-period site NRMSE for this weight
                site_blended = base_v + w * (cand_v - base_v)
                site_blended_nrmse = rmse(actual_v, site_blended) / cap_s * 100
                site_delta = site_blended_nrmse - base_nrmse_site

                scene_ok = delta <= GUARD_SITE_SCENE
                site_ok = site_delta <= GUARD_SITE_HARD

                weight_results.append({
                    "weight": w, "nrmse": blended_nrmse, "delta": delta,
                    "site_nrmse": site_blended_nrmse, "site_delta": site_delta,
                    "scene_guard_ok": scene_ok, "site_guard_ok": site_ok,
                })

                if scene_ok and site_ok:
                    if best_reason == "all_fail" or delta < best_delta:
                        best_weight = w
                        best_delta = delta
                        best_reason = "ok"

                weight_search_rows.append({
                    "site_id": sid, "scene": scene_name, "weight": w,
                    "valid_nrmse_scene": round(blended_nrmse, 4),
                    "valid_delta_scene": round(delta, 4),
                    "valid_nrmse_site_full": round(site_blended_nrmse, 4),
                    "valid_delta_site_full": round(site_delta, 4),
                    "scene_guard_ok": scene_ok, "site_guard_ok": site_ok,
                })

            # Compute LGB NRMSE for this scene
            lgb_nrmse = rmse(actual_v[indices], cand_v[indices]) / cap_s * 100

            site_scene_rows.append({
                "site_id": sid, "scene": scene_name,
                "selected_weight": best_weight,
                "valid_nrmse_base_scene": round(base_nrmse_scene, 4),
                "valid_nrmse_lgb_scene": round(lgb_nrmse, 4),
                "valid_delta_at_best": round(best_delta, 4),
                "valid_nrmse_base_site_full": round(base_nrmse_site, 4),
                "reason": best_reason,
            })

    # Save CSVs
    ws_df = pd.DataFrame(weight_search_rows)
    ws_df.to_csv(OUT / "round64_valid_weight_search.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Weight search: {OUT / 'round64_valid_weight_search.csv'} ({len(ws_df)} rows)")

    ss_df = pd.DataFrame(site_scene_rows)
    ss_df.to_csv(OUT / "round64_site_scene_weights.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Site-scene weights: {OUT / 'round64_site_scene_weights.csv'} ({len(ss_df)} rows)")

    print(f"\n[INFO] Weight distribution:")
    print(ss_df.groupby(["scene", "selected_weight"]).size().unstack(fill_value=0))

    # ── 4. Build Round64 safe prediction ─────────────────────────────
    print("\n[INFO] Building Round64 safe predictions...")

    # Build weight lookup
    weight_lookup = {}
    for _, row in ss_df.iterrows():
        weight_lookup[(str(row["site_id"]), row["scene"])] = float(row["selected_weight"])

    def safe_blend(base_arr, cand_arr, site_arr, scene_arr, weight_map, default_w=0.00):
        result = np.zeros(len(base_arr), dtype=float)
        for i in range(len(base_arr)):
            w = weight_map.get((str(site_arr[i]), scene_arr[i]), default_w)
            result[i] = base_arr[i] + w * (cand_arr[i] - base_arr[i])
        return result

    # Apply to valid
    site_valid = df_valid["site_id"].values
    scene_valid = df_valid["scene"].values
    safe_valid = safe_blend(base_v, cand_v, site_valid, scene_valid, weight_lookup)
    safe_valid = np.clip(safe_valid, 0, cap_v)
    df_valid["power_pred_round64_safe"] = safe_valid

    # Apply to test
    site_test = df_test["site_id"].values
    scene_test = df_test["scene"].values
    cap_test = df_test["capacity_mw"].values.astype(float)
    safe_test = safe_blend(base_t, cand_t, site_test, scene_test, weight_lookup)
    safe_test = np.clip(safe_test, 0, cap_test)
    df_test["power_pred_round64_safe"] = safe_test

    # Clip base and candidate to capacity
    df_valid[base_col] = np.clip(df_valid[base_col].values, 0, cap_v)
    df_valid[cand_col] = np.clip(df_valid[cand_col].values, 0, cap_v)
    df_test[base_col] = np.clip(df_test[base_col].values, 0, cap_test)
    df_test[cand_col] = np.clip(df_test[cand_col].values, 0, cap_test)

    # Save
    df_all = pd.concat([df_valid, df_test], ignore_index=True)
    df_all.to_pickle(OUT / "round64_candidates.pkl")
    print(f"[OK] Candidates: {OUT / 'round64_candidates.pkl'} ({len(df_all)} rows)")

    # ── 5. Valid guard summary ─────────────────────────────────────
    print("\n[INFO] Valid guard summary...")

    def count_bad(df_subset, base_c, cand_c, threshold=1.0):
        count = 0
        for sid, sdf in df_subset.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            b_nrmse = rmse(sdf["power_mw"].values, sdf[base_c].values) / cap * 100
            c_nrmse = rmse(sdf["power_mw"].values, sdf[cand_c].values) / cap * 100
            if (c_nrmse - b_nrmse) > threshold:
                count += 1
        return count

    def city_nrmse_avg(df_subset, pred_col):
        vals = []
        for _, hdf in df_subset.groupby("hour"):
            agg = hdf.groupby("time", as_index=False).agg(
                actual=("power_mw", "sum"), pred=(pred_col, "sum"),
                cap_sum=("capacity_mw", "sum"),
            )
            r = rmse(agg["pred"].values, agg["actual"].values)
            cap_h = float(agg["cap_sum"].mean())
            if cap_h > 0:
                vals.append(r / cap_h * 100)
        return float(np.mean(vals)) if vals else np.nan

    def sm_nrmse(df_subset, pred_col):
        vals = []
        for sid, sdf in df_subset.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
        return float(np.mean(vals)) if vals else np.nan

    for pred_col, label in [
        (base_col, "Round61"),
        (cand_col, "lgb_residual"),
        ("power_pred_round64_safe", "Round64 safe"),
    ]:
        sm = sm_nrmse(df_valid, pred_col)
        cn = city_nrmse_avg(df_valid, pred_col)
        bad = count_bad(df_valid, base_col, pred_col)
        print(f"  {label}: sm={sm:.4f}%, cn={cn:.4f}%, bad_sites={bad}")

    # Guard summary JSON
    guard_summary = {
        "weight_distribution": {
            f"{s}_{int(w*100):02d}": int(
                ((ss_df["scene"] == s) & (ss_df["selected_weight"] == w)
            ).sum()
            for s in SCENES for w in WEIGHTS
        },
        "guard_thresholds": {
            "site_scene_max_pp": GUARD_SITE_SCENE,
            "site_hard_max_pp": GUARD_SITE_HARD,
        },
    }
    with open(OUT / "round64_guard_summary.json", "w", encoding="utf-8") as f:
        json.dump(guard_summary, f, ensure_ascii=False, indent=2)
    print(f"[OK] Guard summary: {OUT / 'round64_guard_summary.json'}")

    print(f"\n{'='*60}")
    print(f"[OK] Round64 safe blend complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
