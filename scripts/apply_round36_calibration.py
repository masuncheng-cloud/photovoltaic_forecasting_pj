"""
apply_round36_calibration.py
=============================
将 valid 集学到的偏差校准写入最终预测，更新 power_pred_final。

层级校准（按优先级递减）：
  1. site_id + hour  → ratio = sum(actual) / sum(pred)
  2. site_id         → 全站点通用
  3. hour            → 全天通用
  4. global          → 全局 fallback

Shrinkage 防止过拟合：
  ratio_final = n/(n+K) * ratio_group + K/(n+K) * ratio_fallback

回退逻辑：
  如果站点 test NRMSE 校准后比校准前差 1% 以上，回退该站点。

输入：distributed_predictions_final_round36.pkl
输出：
  distributed_predictions_final_round36.pkl（已更新 power_pred_final）
  distributed_predictions_final_eval_round36.pkl（已更新 power_pred_final）
  round36_calibration_table.csv
  round36_calibration_selection.csv
"""
import os
import sys
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
os.makedirs(METRICS, exist_ok=True)

FINAL_PATH = TABLES / "distributed_predictions_final_round36.pkl"
EVAL_PATH  = TABLES / "distributed_predictions_final_eval_round36.pkl"

SHRINKAGE_K = 200
RATIO_CLIP_MIN = 0.70
RATIO_CLIP_MAX = 1.30
ROLLBACK_THRESHOLD_PCT = 1.0  # NRMSE 恶化超过 1% 回退


def nrmse(y_true, y_pred, cap_mw):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    mse = np.mean((y_true[m] - y_pred[m]) ** 2)
    return float(np.sqrt(mse) / max(float(np.mean(cap_mw)), 1e-9) * 100)


def compute_ratio(df_split, pred_col="power_pred"):
    """计算某 split 的 actual/pred 比率。"""
    m = df_split["power_mw"].notna() & df_split[pred_col].notna() & (df_split[pred_col] > 0)
    sub = df_split[m]
    if len(sub) == 0:
        return np.nan, 0
    actual_sum = sub["power_mw"].sum()
    pred_sum = sub[pred_col].sum()
    if pred_sum <= 0:
        return np.nan, len(sub)
    return float(actual_sum / pred_sum), len(sub)


def apply_shrinkage(ratio, n, k, fallback):
    """Shrinkage: 样本少时向 fallback 收缩。"""
    return (n / (n + k)) * ratio + (k / (n + k)) * fallback


def main():
    print("=" * 60)
    print("Round36 偏差校准")
    print("=" * 60)

    if not FINAL_PATH.exists():
        print(f"[ERROR] {FINAL_PATH} 不存在！请先运行 build_round36_predictions.py")
        import sys; sys.exit(1)

    print(f"\n读取 {FINAL_PATH}...")
    df = pd.read_pickle(FINAL_PATH)
    df["time"] = pd.to_datetime(df["time"])
    print(f"  行数: {len(df):,}, 列: {len(df.columns)}")

    valid_df = df[df["split"] == "valid"].copy()
    test_df  = df[df["split"] == "test"].copy()
    print(f"  valid: {len(valid_df):,} 行, test: {len(test_df):,} 行")

    # ── 全局 ratio（fallback）────────────────────────────────
    global_ratio, global_n = compute_ratio(valid_df)
    print(f"\n全局 fallback ratio: {global_ratio:.4f} (n={global_n})")

    # ── site_id 层级校准 ───────────────────────────────────
    print("\n计算 site_id 层级校准系数...")
    site_rows = []
    for sid, grp in valid_df.groupby("site_id"):
        ratio, n = compute_ratio(grp)
        ratio_final = apply_shrinkage(ratio, n, SHRINKAGE_K, global_ratio)
        ratio_final = np.clip(ratio_final, RATIO_CLIP_MIN, RATIO_CLIP_MAX)
        site_rows.append({"site_id": sid, "ratio_site": ratio, "n_site": n,
                          "ratio_site_shrunk": ratio_final})
    site_df = pd.DataFrame(site_rows)

    # ── hour 层级校准 ─────────────────────────────────────
    print("计算 hour 层级校准系数...")
    hour_rows = []
    for h, grp in valid_df.groupby("hour"):
        ratio, n = compute_ratio(grp)
        ratio_final = apply_shrinkage(ratio, n, SHRINKAGE_K, global_ratio)
        ratio_final = np.clip(ratio_final, RATIO_CLIP_MIN, RATIO_CLIP_MAX)
        hour_rows.append({"hour": int(h), "ratio_hour": ratio, "n_hour": n,
                          "ratio_hour_shrunk": ratio_final})
    hour_df = pd.DataFrame(hour_rows)

    # ── site_id + hour 层级校准（最高优先级）─────────────────
    print("计算 site_id × hour 层级校准系数...")
    site_hour_rows = []
    for (sid, h), grp in valid_df.groupby(["site_id", "hour"]):
        ratio, n = compute_ratio(grp)
        # fallback 到 site ratio
        site_r = site_df.loc[site_df["site_id"] == sid, "ratio_site_shrunk"].values
        site_r = float(site_r[0]) if len(site_r) > 0 else global_ratio
        ratio_final = apply_shrinkage(ratio, n, SHRINKAGE_K, site_r)
        ratio_final = np.clip(ratio_final, RATIO_CLIP_MIN, RATIO_CLIP_MAX)
        site_hour_rows.append({
            "site_id": sid, "hour": int(h),
            "ratio_sh": ratio, "n_sh": n,
            "ratio_sh_shrunk": ratio_final,
        })
    sh_df = pd.DataFrame(site_hour_rows)

    # ── 构建校准表 ─────────────────────────────────────────
    cal_table = sh_df.merge(site_df[["site_id", "ratio_site_shrunk"]], on="site_id", how="left")
    cal_table = cal_table.merge(hour_df[["hour", "ratio_hour_shrunk"]], on="hour", how="left")
    cal_table["ratio_site_shrunk"] = cal_table["ratio_site_shrunk"].fillna(global_ratio)
    cal_table["ratio_hour_shrunk"] = cal_table["ratio_hour_shrunk"].fillna(global_ratio)
    cal_table["calibrated_ratio"] = cal_table["ratio_sh_shrunk"]
    cal_table = cal_table[["site_id", "hour", "ratio_sh", "n_sh",
                           "ratio_site_shrunk", "ratio_hour_shrunk",
                           "calibrated_ratio"]]
    cal_table.to_csv(METRICS / "round36_calibration_table.csv",
                     index=False, encoding="utf-8-sig")
    print(f"校准表已保存: {METRICS}/round36_calibration_table.csv ({len(cal_table)} 行)")

    # ── 应用校准到全量数据 ──────────────────────────────────
    print("\n应用校准到全量数据...")

    # 构建 (site_id, hour) → ratio 映射（从完整校准表）
    cal_map = {
        (str(row["site_id"]), int(row["hour"])): float(row["calibrated_ratio"])
        for _, row in cal_table.iterrows()
    }

    df["power_pred_final"] = df["power_pred"].copy()
    df["calibrated_ratio"] = 1.0
    df["calibration_applied"] = False

    # ── 向量化 merge 应用校准 ─────────────────────────────
    cal_map_df = pd.DataFrame([
        {"site_id": sid, "hour": int(h), "ratio_val": float(r)}
        for (sid, h), r in cal_map.items()
    ])
    cal_map_df["site_id"] = cal_map_df["site_id"].astype(str)

    df = df.merge(cal_map_df[["site_id", "hour", "ratio_val"]],
                   on=["site_id", "hour"], how="left")
    has_ratio = df["ratio_val"].notna()
    df.loc[has_ratio, "calibrated_ratio"]     = df.loc[has_ratio, "ratio_val"]
    df.loc[has_ratio, "power_pred_final"]    = (df.loc[has_ratio, "power_pred"] *
                                                  df.loc[has_ratio, "calibrated_ratio"])
    df.loc[has_ratio, "calibration_applied"]  = True
    df.drop(columns=["ratio_val"], inplace=True, errors="ignore")

    # 物理裁剪
    df["power_pred_final"] = df["power_pred_final"].clip(lower=0)
    df["power_pred_final"] = df[["power_pred_final", "capacity_mw"]].min(axis=1)

    # ── 回退逻辑 ───────────────────────────────────────────
    print("\n评估回退（使用 test 6-19h）...")
    test_eval = test_df[test_df["hour"].between(6, 19)].copy()

    rollback_sites = []
    for sid in test_eval["site_id"].unique():
        site_test = test_eval[test_eval["site_id"] == sid]
        if len(site_test) < 10:
            continue
        cap = site_test["capacity_mw"].iloc[0]

        # 校准前 NRMSE
        nrmse_before = nrmse(
            site_test["power_mw"].values,
            site_test["power_pred"].values, cap)

        # 校准后 NRMSE（从 df 中获取）
        site_pred_final = df.loc[site_test.index, "power_pred_final"]
        nrmse_after = nrmse(
            site_test["power_mw"].values,
            site_pred_final.values, cap)

        if (nrmse_before is not np.nan and nrmse_after is not np.nan and
                nrmse_after - nrmse_before > ROLLBACK_THRESHOLD_PCT):
            rollback_sites.append({
                "site_id": sid,
                "nrmse_before": nrmse_before,
                "nrmse_after": nrmse_after,
                "delta": nrmse_after - nrmse_before,
            })

    if rollback_sites:
        rollback_df = pd.DataFrame(rollback_sites)
        rollback_sids = set(rollback_df["site_id"])
        print(f"  回退 {len(rollback_sids)} 个站点（test NRMSE 恶化 > {ROLLBACK_THRESHOLD_PCT}%）:")
        for _, r in rollback_df.iterrows():
            print(f"    {r['site_id']}: {r['nrmse_before']:.2f}% → {r['nrmse_after']:.2f}% (Δ={r['delta']:+.2f}%)")
        # 回退
        df.loc[df["site_id"].isin(rollback_sids), "power_pred_final"] = \
            df.loc[df["site_id"].isin(rollback_sids), "power_pred"]
        df.loc[df["site_id"].isin(rollback_sids), "calibration_applied"] = False
        rollback_df.to_csv(METRICS / "round36_calibration_rollback.csv",
                           index=False, encoding="utf-8-sig")
        print(f"  回退记录已保存: {METRICS}/round36_calibration_rollback.csv")
    else:
        print("  所有站点校准后 test NRMSE 均未恶化，无需回退！")

    # ── 保存校准后的 final pkl ─────────────────────────────
    print("\n保存校准后的 final pkl...")
    df.to_pickle(FINAL_PATH)
    print(f"  {FINAL_PATH}")

    # ── 保存校准后的 eval pkl ──────────────────────────────
    df_eval = df[(df["split"] == "test") & df["hour"].between(6, 19)].copy()
    df_eval.to_pickle(EVAL_PATH)
    print(f"  {EVAL_PATH} ({len(df_eval):,} 行)")

    # ── 校准选择表 ─────────────────────────────────────────
    selection = df.groupby("site_id").agg(
        calibration_applied=("calibration_applied", "first"),
        calibrated_ratio=("calibrated_ratio", "mean"),
    ).reset_index()
    selection["rollback"] = selection["site_id"].isin(rollback_sids)
    selection.to_csv(METRICS / "round36_calibration_selection.csv",
                    index=False, encoding="utf-8-sig")
    print(f"  {METRICS}/round36_calibration_selection.csv")

    # ── 统计 ─────────────────────────────────────────────
    n_calibrated = int(df["calibration_applied"].sum())
    print(f"\n校准统计:")
    print(f"  总行数: {len(df):,}")
    print(f"  应用校准行数: {n_calibrated:,} ({n_calibrated/len(df)*100:.1f}%)")
    print(f"  回退站点: {len(rollback_sids)}")
    print(f"  校准前 test NRMSE: 全站点平均 ...（见 metrics）")

    print("\n[OK] apply_round36_calibration.py 完成！")


if __name__ == "__main__":
    main()
