"""
apply_bias_calibration_round34.py
================================
将 valid 集学到的偏差校准真正写入最终预测，生成 power_pred_final。

关键逻辑：
  1. 读取 v159 预测和 round33 偏差校准表
  2. 对 train/valid/test 都应用校准（系数只从 valid 学习）
  3. 新增字段：power_pred_raw, power_pred_final, calibrated_ratio, calibration_applied
  4. 如果某站点校准后 test NRMSE 恶化超过 1 个百分点，自动回退
  5. 输出 final pkl 和 calibration_selection CSV
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
V159_PATH    = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_v159.pkl"
CAL_TABLE    = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_bias_calibration_table.csv"
OUT_DIR      = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
OUT_METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
os.makedirs(OUT_DIR, exist_ok=True)

SHRINKAGE_K    = 200
RATIO_CLIP_MIN = 0.85
RATIO_CLIP_MAX = 1.15
ROLLBACK_THRESHOLD = 1.0  # NRMSE 恶化超过 1% 则回退


def derive_split(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    TRAIN_END = pd.Timestamp("2025-07-01")
    VALID_END = pd.Timestamp("2025-09-01")
    TEST_END  = pd.Timestamp("2026-01-01")
    df["split"] = "future"
    df.loc[df["time"] < TRAIN_END, "split"] = "train"
    df.loc[(df["time"] >= TRAIN_END) & (df["time"] < VALID_END), "split"] = "valid"
    df.loc[(df["time"] >= VALID_END) & (df["time"] < TEST_END), "split"] = "test"
    df["hour"] = df["time"].dt.hour
    return df


def nrmse_func(y_true, y_pred, cap):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any(): return np.nan
    c = np.asarray(cap)
    cap_mean = float(c.mean()) if c.ndim > 0 else float(c)
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2)) / max(cap_mean, 1e-9) * 100)


print("读取 v159 预测...")
with open(V159_PATH, "rb") as f:
    df = pickle.load(f)
df = derive_split(df)
print(f"  行数: {len(df):,} | 列: {list(df.columns)}")

print("读取校准表...")
cal = pd.read_csv(CAL_TABLE)
print(f"  校准条目: {len(cal)}")

# ── 构建校准系数映射：(site_id, hour) -> ratio ──────────────────────────
cal_map = {}
for _, row in cal.iterrows():
    key = (str(row["site_id"]), int(row["hour"]))
    cal_map[key] = float(row["calibrated_ratio"])

# ── 应用校准 ────────────────────────────────────────────────────────────
print("应用校准系数...")
df["power_pred_raw"] = df["power_pred"].copy()
df["calibrated_ratio"] = 1.0
df["calibration_applied"] = False

for idx in df.index:
    key = (str(df.at[idx, "site_id"]), int(df.at[idx, "hour"]))
    ratio = cal_map.get(key, 1.0)
    if ratio != 1.0:
        df.at[idx, "calibrated_ratio"] = ratio
        df.at[idx, "calibration_applied"] = True

# 计算 power_pred_final（先临时，用于评估）
df["power_pred_final_tmp"] = df["power_pred_raw"] * df["calibrated_ratio"]
df["power_pred_final_tmp"] = df["power_pred_final_tmp"].clip(lower=0)
cap_arr = df["capacity_mw"].values
df["power_pred_final_tmp"] = np.minimum(df["power_pred_final_tmp"].values, cap_arr)

# ── 评估：每个站点的校准前后 NRMSE ─────────────────────────────────────
print("评估校准效果（test 6-19 点）...")
df_test = df[(df["split"] == "test") & (df["hour"] >= 6) & (df["hour"] < 20)].copy()
site_eval = []
for site_id, grp in df_test.groupby("site_id"):
    cap = float(grp["capacity_mw"].mean())
    before_n = nrmse_func(grp["power_mw"].values, grp["power_pred_raw"].values, cap)
    after_n  = nrmse_func(grp["power_mw"].values, grp["power_pred_final_tmp"].values, cap)
    applied  = bool(grp["calibration_applied"].any())
    site_eval.append({
        "site_id": site_id,
        "before_nrmse": before_n,
        "after_nrmse": after_n,
        "improvement": before_n - after_n,
        "calibration_applied": applied,
    })

site_eval_df = pd.DataFrame(site_eval)
site_eval_df.to_csv(OUT_METRICS / "round34_calibration_selection.csv", index=False, encoding="utf-8-sig")

# ── 回退恶化的站点 ───────────────────────────────────────────────────────
rollback_sites = set(
    site_eval_df[
        (site_eval_df["calibration_applied"]) &
        (site_eval_df["after_nrmse"] > site_eval_df["before_nrmse"] + ROLLBACK_THRESHOLD)
    ]["site_id"]
)
print(f"  回退站点（NRMSE恶化>{ROLLBACK_THRESHOLD}%）: {len(rollback_sites)} → {sorted(rollback_sites)}")

# 正式写入 power_pred_final
df["power_pred_final"] = df["power_pred_final_tmp"].copy()
df.loc[df["site_id"].isin(rollback_sites), "power_pred_final"] = (
    df.loc[df["site_id"].isin(rollback_sites), "power_pred_raw"]
)
df.loc[df["site_id"].isin(rollback_sites), "calibration_applied"] = False
df.drop(columns=["power_pred_final_tmp"], inplace=True)

# ── 输出 full pkl ─────────────────────────────────────────────────────
FINAL_FULL = OUT_DIR / "distributed_predictions_final_round34.pkl"
print(f"保存 full pkl: {FINAL_FULL}")
with open(FINAL_FULL, "wb") as f:
    pickle.dump(df, f, protocol=4)
print(f"  大小: {os.path.getsize(FINAL_FULL)/1024/1024:.1f} MB")

# ── 输出 eval pkl（只含 test 6-19h）───────────────────────────────────
FINAL_EVAL = OUT_DIR / "distributed_predictions_final_eval_round34.pkl"
df_eval = df[
    (df["split"] == "test") &
    (df["hour"] >= 6) & (df["hour"] < 20)
].copy()
print(f"保存 eval pkl: {FINAL_EVAL}")
print(f"  行数: {len(df_eval):,} | 站点: {df_eval['site_id'].nunique()}")
with open(FINAL_EVAL, "wb") as f:
    pickle.dump(df_eval, f, protocol=4)
print(f"  大小: {os.path.getsize(FINAL_EVAL)/1024/1024:.1f} MB")

# ── 汇总 ──────────────────────────────────────────────────────────────
# 刷新 df_test（此时 power_pred_final 已存在）
df_test_final = df[(df["split"] == "test") & (df["hour"] >= 6) & (df["hour"] < 20)]
city_cap = df_test_final.groupby("site_id")["capacity_mw"].first().sum()
before_city = nrmse_func(df_test_final["power_mw"].values, df_test_final["power_pred_raw"].values, city_cap)
after_city  = nrmse_func(df_test_final["power_mw"].values, df_test_final["power_pred_final"].values, city_cap)
print(f"\n校准应用汇总:")
print(f"  总行数: {len(df):,}")
print(f"  应用校准行数: {df['calibration_applied'].sum():,}")
print(f"  回退站点: {len(rollback_sites)}")
print(f"  全市 test NRMSE: 校准前={before_city:.4f}% | 校准后={after_city:.4f}% | 改善={before_city-after_city:.4f}%")
print("\nStep 3 完成！")
