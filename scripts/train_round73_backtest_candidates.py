#!/usr/bin/env python3
"""
train_round73_backtest_candidates.py
基于回测窗口训练 Round73 候选模型。
候选:
    A: autumn_winter_residual
    B: noon_bias_guard
    C: high_error_shrinkage
"""

import argparse, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"
warnings.filterwarnings("ignore")


def _rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def _prep_X(df, feats):
    cols = [c for c in feats if c in df.columns]
    return pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)


def _city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    return _rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    ds_path = OUT / "training_v2_backtest_dataset.parquet"
    if not ds_path.exists():
        print("[FAIL] 回测数据集不存在，先运行 build_training_v2_backtest_dataset.py")
        return
    print(f"[INFO] 读取: {ds_path}")
    df = pd.read_parquet(ds_path)
    print(f"  总行数: {len(df):,}")

    cap_col = "capacity_mw"
    target_col = "power_mw"
    bl_col = "power_pred_final"
    bl_fallback = "power_pred_round61_city_safe"

    # 统一基线
    df["_bl_pred"] = df[bl_col].fillna(df.get(bl_fallback, df["power_pred"]))
    df["y_true_norm"] = (df[target_col] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["y_base_norm"] = (df["_bl_pred"] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["residual_norm"] = df["y_true_norm"] - df["y_base_norm"]
    df["residual_clip"] = df["residual_norm"].clip(-0.10, 0.10)

    # 窗口
    wA = df[df["window"] == "window_A"].copy()
    wB = df[df["window"] == "window_B"].copy()
    wC = df[df["window"] == "window_C"].copy()
    wT = df[df["window"] == "holdout_test"].copy()
    print(f"  wA={len(wA):,} wB={len(wB):,} wC={len(wC):,} wT={len(wT):,}")

    FEAT = [f for f in [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "scene_v151",
        "site_zero_ratio_6_19",
        "pr_median", "quality_score",
    ] if f in df.columns]

    lgb_base = dict(
        n_estimators=400, max_depth=7, num_leaves=63,
        learning_rate=0.05, reg_lambda=2.0, reg_alpha=0.5,
        min_child_samples=30, subsample=0.8, colsample_bytree=0.8,
        random_state=42, n_jobs=-1, verbose=-1,
    )

    summary_rows = []
    trained = []
    cand_results = {}

    # 辅助：对所有窗口应用残差模型
    def apply_residual(all_wdfs, model, cand_col, clip_val, noon_only=False):
        noon_hours = [10, 11, 12, 13, 14]
        results = {}
        for wname, wdf in all_wdfs:
            result = wdf.copy()
            if noon_only:
                mask = result["hour"].isin(noon_hours)
            else:
                mask = pd.Series(True, index=result.index)
            X = _prep_X(result[mask], FEAT)
            resid = np.clip(model.predict(X), -clip_val, clip_val)
            cap = result.loc[mask, cap_col].values.astype(float)
            bl = result.loc[mask, "_bl_pred"].values.astype(float)
            result.loc[mask, cand_col] = np.clip(bl + resid * cap, 0, cap)
            if noon_only:
                non_mask = ~mask
                result.loc[non_mask, cand_col] = result.loc[non_mask, "_bl_pred"].values
            results[wname] = result
        return results

    # ══ 候选A: 秋冬残差 ═══════════════════════════════════════
    CAND_A = "power_pred_round73_autumn_winter_residual"
    tr_A = pd.concat([wA, wB], ignore_index=True)
    tr_A = tr_A[tr_A[target_col].notna()].copy()
    if len(tr_A) >= 200:
        mdl = LGBMRegressor(**lgb_base)
        mdl.fit(_prep_X(tr_A, FEAT), tr_A["residual_clip"].values.astype(float))
        print(f"\n[A] 训练: {len(tr_A):,} 样本")
        cand_results[CAND_A] = apply_residual(
            [("wA", wA), ("wB", wB), ("wC", wC), ("wT", wT)],
            mdl, CAND_A, 0.10)
        for wname, rdf in cand_results[CAND_A].items():
            bn = _city_nrmse(rdf, "_bl_pred")
            cn = _city_nrmse(rdf, CAND_A)
            print(f"  [{wname}] {bn:.3f}% -> {cn:.3f}% ({cn-bn:+.3f}pp)")
        trained.append(CAND_A)
        summary_rows.append({"candidate": CAND_A, "condition": "autumn_winter",
                          "trained": True, "n_train": len(tr_A)})
    else:
        print(f"[A] 样本不足")
        summary_rows.append({"candidate": CAND_A, "trained": False})

    # ══ 候选B: noon_bias_guard ═══════════════════════════════════
    CAND_B = "power_pred_round73_noon_bias_guard"
    noon_h = [10, 11, 12, 13, 14]
    tr_B = pd.concat([wA, wB, wC], ignore_index=True)
    tr_B = tr_B[tr_B[target_col].notna() & tr_B["hour"].isin(noon_h)].copy()
    if len(tr_B) >= 200:
        mdl = LGBMRegressor(**{**lgb_base, "n_estimators": 200, "max_depth": 5})
        mdl.fit(_prep_X(tr_B, FEAT), tr_B["residual_clip"].values.astype(float))
        print(f"\n[B] 训练: {len(tr_B):,} noon样本")
        cand_results[CAND_B] = apply_residual(
            [("wA", wA), ("wB", wB), ("wC", wC), ("wT", wT)],
            mdl, CAND_B, 0.03, noon_only=True)
        for wname, rdf in cand_results[CAND_B].items():
            bn = _city_nrmse(rdf, "_bl_pred")
            cn = _city_nrmse(rdf, CAND_B)
            print(f"  [{wname}] {bn:.3f}% -> {cn:.3f}% ({cn-bn:+.3f}pp)")
        trained.append(CAND_B)
        summary_rows.append({"candidate": CAND_B, "condition": "noon_bias_guard",
                          "trained": True, "n_train": len(tr_B)})
    else:
        print(f"[B] 样本不足")
        summary_rows.append({"candidate": CAND_B, "trained": False})

    # ══ 候选C: 高误差shrinkage ══════════════════════════════════
    CAND_C = "power_pred_round73_high_error_shrinkage"
    ab = pd.concat([wA, wB], ignore_index=True)
    site_n = {}
    for sid, sdf in ab.groupby("site_id"):
        cap = float(sdf[cap_col].iloc[0])
        if cap <= 0:
            continue
        r = _rmse(sdf[target_col].values, sdf["_bl_pred"].values)
        site_n[sid] = r / cap * 100
    top_sites = {s[0] for s in sorted(site_n.items(), key=lambda x: x[1], reverse=True)[:20]}
    tr_C = ab[ab["site_id"].isin(top_sites) & ab[target_col].notna()].copy()
    if len(tr_C) >= 100:
        mdl = LGBMRegressor(**{**lgb_base, "n_estimators": 200, "max_depth": 5})
        mdl.fit(_prep_X(tr_C, FEAT), tr_C["residual_clip"].values.astype(float))
        print(f"\n[C] 训练: {len(tr_C):,} 高误差样本 站点数={len(top_sites)}")
        cand_results[CAND_C] = {}
        for wname, wdf in [("wA", wA), ("wB", wB), ("wC", wC), ("wT", wT)]:
            r = wdf.copy()
            he = wdf["site_id"].isin(top_sites)
            r[CAND_C] = r["_bl_pred"].values.copy()
            if he.any():
                X2 = _prep_X(wdf[he], FEAT)
                resid = np.clip(mdl.predict(X2), -0.10, 0.10)
                cap2 = wdf.loc[he, cap_col].values.astype(float)
                bl2 = wdf.loc[he, "_bl_pred"].values.astype(float)
                r.loc[he, CAND_C] = np.clip(bl2 + 0.3 * resid * cap2, 0, cap2)
            cand_results[CAND_C][wname] = r
            bn = _city_nrmse(r, "_bl_pred")
            cn = _city_nrmse(r, CAND_C)
            print(f"  [{wname}] {bn:.3f}% -> {cn:.3f}% ({cn-bn:+.3f}pp)")
        trained.append(CAND_C)
        summary_rows.append({"candidate": CAND_C, "condition": "high_error_shrinkage",
                          "trained": True, "n_train": len(tr_C),
                          "n_sites": len(top_sites), "alpha": 0.3})
    else:
        print(f"[C] 样本不足")
        summary_rows.append({"candidate": CAND_C, "trained": False})

    # ── 保存摘要 ────────────────────────────────────────────────
    pd.DataFrame(summary_rows).to_csv(
        OUT / "round73_candidate_training_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] {OUT / 'round73_candidate_training_summary.csv'}")

    # ── 保存 pkl ────────────────────────────────────────────────
    input_pkl = PROJECT_ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"
    full_df = pd.read_pickle(input_pkl)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df["hour"] = full_df["time"].dt.hour

    for cand in trained:
        if cand not in cand_results:
            continue
        for sname, src_name in [("valid", "wC"), ("test", "wT")]:
            src = cand_results[cand].get(src_name)
            if src is None:
                continue
            mask = full_df["split"] == sname
            update_map = (
                src[["time", "site_id", cand]]
                .drop_duplicates(["time", "site_id"])
                .set_index(["time", "site_id"])[cand]
            )
            update_map = update_map[~update_map.index.duplicated(keep="first")]
            idx = full_df.loc[mask].set_index(["time", "site_id"]).index
            if cand not in full_df.columns:
                full_df[cand] = np.nan
            full_df.loc[mask, cand] = update_map.reindex(idx).values

    full_df.to_pickle(OUT / "round73_candidates.pkl")
    print(f"[OK] {OUT / 'round73_candidates.pkl'} ({len(full_df):,}行)")
    print(f"  候选: {trained}")
    print("\n[OK] train_round73 完成!")


if __name__ == "__main__":
    main()
