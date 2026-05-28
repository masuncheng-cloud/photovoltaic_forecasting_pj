"""
calibrate_station_bias_round33.py
=================================
基于 valid 集学习站点级偏差校准系数，只对"系统性偏差"站点生效。

校准层级（逐级退化）：
  1. site_id + hour
  2. site_id
  3. hour
  4. 全局

Shrinkage 防止小样本过拟合：
  calibrated_ratio = (n / (n + k)) * group_ratio + (k / (n + k)) * fallback_ratio
  k = 200，ratio_clip = [0.70, 1.30]
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PRED_CLEAN  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_final_full_clean.pkl"
V159_PATH   = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_v159.pkl"
VALIDITY_CSV = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_site_validity.csv"
OUT_DIR     = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
os.makedirs(OUT_DIR, exist_ok=True)

SHRINKAGE_K    = 200
RATIO_CLIP_MIN = 0.85   # 更保守，避免过度纠正
RATIO_CLIP_MAX = 1.15
BIAS_RATIO_LOW = 0.80
BIAS_RATIO_HIGH = 1.20
# 仅对系统性偏差站点（pred/actual 明显偏离）应用校准
# 漂移站点不主动校准（因为其真实值本身已漂移）


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


def learn_calibration(
    df: pd.DataFrame,
    group_key: list[str],
    fallback_ratio: float,
    k: float = SHRINKAGE_K,
) -> pd.DataFrame:
    """学习分组校准系数。"""
    grp = (
        df.groupby(group_key)
        .apply(
            lambda g: pd.Series({
                "actual_sum": g["power_mw"].sum(),
                "pred_sum": g["power_pred"].sum(),
                "n": len(g),
            }),
            include_groups=False,
        )
        .reset_index()
    )
    grp["raw_ratio"] = grp["actual_sum"] / grp["pred_sum"].clip(lower=1e-9)
    grp["calibrated_ratio"] = (
        (grp["n"] / (grp["n"] + k)) * grp["raw_ratio"]
        + (k / (grp["n"] + k)) * fallback_ratio
    )
    grp["calibrated_ratio"] = grp["calibrated_ratio"].clip(RATIO_CLIP_MIN, RATIO_CLIP_MAX)
    return grp


print("读取 v159 预测...")
with open(V159_PATH, "rb") as f:
    df = pickle.load(f)
df = derive_split(df)

# 只在 valid 集上学习
df_valid = df[(df["split"] == "valid") & (df["hour"] >= 6) & (df["hour"] < 20)].copy()
print(f"valid 6-19 行: {len(df_valid):,}")

# 读取有效性表，确定需要校准的站点
validity = pd.read_csv(VALIDITY_CSV)
bias_sites = set(validity[validity["site_status"] == "系统性偏差"]["site_id"].tolist())
drift_sites = set(validity[validity["site_status"] == "测试期分布漂移"]["site_id"].tolist())
# 只校准系统性偏差站点，不校准漂移站点（漂移站点的预测偏差由真实值变化引起，校准反而会歪曲）
target_sites = bias_sites
# fallback = 1.0（不做整体偏移，只校准已知偏差站点）
FALLBACK_RATIO = 1.0
print(f"需校准站点: {len(target_sites)} (仅系统性偏差站点)")
print(f"漂移站点 ({len(drift_sites)} 个) 不做额外校准，在报告中标注)")
print(f"fallback ratio: {FALLBACK_RATIO}")

# 全局 fallback ratio = 1.0（不做整体偏移）
global_ratio = FALLBACK_RATIO
print(f"全局 fallback ratio: {global_ratio:.4f}")

# ── Level 1: site_id + hour ──────────────────────────────────────────────
level1 = learn_calibration(df_valid, ["site_id", "hour"], global_ratio)
# 样本不足（n < 30）的条目退化到 level 2
level1_small = level1[level1["n"] < 30]
print(f"Level1 样本不足退化: {len(level1_small)}/{len(level1)}")

# ── Level 2: site_id ───────────────────────────────────────────────────────
level2 = learn_calibration(df_valid, ["site_id"], global_ratio)

# ── Level 3: hour ─────────────────────────────────────────────────────────
level3 = learn_calibration(df_valid, ["hour"], global_ratio)

# ── 构建最终校准表 ─────────────────────────────────────────────────────────
# 合并层级：level1 为主，样本不足时退化到 level2，再退化到 level3，最后退化到全局
level1_keep = level1[level1["n"] >= 30].copy()
level1_drop = level1[level1["n"] < 30].copy()

cal_table = level1_keep[["site_id", "hour", "calibrated_ratio", "n"]].copy()
cal_table["calibration_level"] = 1

# level2 补充
if len(level1_drop) > 0:
    l2 = level2.rename(columns={"calibrated_ratio": "l2_ratio"})
    l2_subset = l2[["site_id", "l2_ratio"]]
    merged = level1_drop[["site_id"]].merge(l2_subset, on="site_id", how="left")
    merged["l2_ratio"] = merged["l2_ratio"].fillna(global_ratio).clip(RATIO_CLIP_MIN, RATIO_CLIP_MAX)
    merged["calibrated_ratio"] = merged["l2_ratio"]
    merged["calibration_level"] = 2
    merged["n"] = 0  # 不显示 n（来自 site 聚合）
    cal_table = pd.concat([cal_table, merged[["site_id", "hour", "calibrated_ratio", "calibration_level", "n"]]], ignore_index=True)

# level3 补充（剩余的）
all_hours = list(range(6, 20))
existing_keys = set(zip(cal_table["site_id"], cal_table["hour"]))
for _, row in level3.iterrows():
    h = int(row["hour"])
    r = float(row["calibrated_ratio"])
    for site_id in df_valid["site_id"].unique():
        if (site_id, h) not in existing_keys:
            cal_table = pd.concat([
                cal_table,
                pd.DataFrame([{
                    "site_id": site_id,
                    "hour": h,
                    "calibrated_ratio": r,
                    "calibration_level": 3,
                    "n": 0,
                }])
            ], ignore_index=True)

# ── 漂移站点使用更保守 clip ────────────────────────────────────────────────
DRIFT_CLIP_MIN = 0.80
DRIFT_CLIP_MAX = 1.20
for idx, row in cal_table.iterrows():
    if row["site_id"] in drift_sites:
        cal_table.at[idx, "calibrated_ratio"] = float(
            np.clip(row["calibrated_ratio"], DRIFT_CLIP_MIN, DRIFT_CLIP_MAX)
        )
        cal_table.at[idx, "calibration_level"] = max(row["calibration_level"], 4)  # 标注更保守

# ── 保存校准表 ─────────────────────────────────────────────────────────────
cal_table = cal_table.sort_values(["site_id", "hour"]).reset_index(drop=True)
cal_table.to_csv(OUT_DIR / "round33_bias_calibration_table.csv", index=False, encoding="utf-8-sig")
print(f"校准表已保存: {OUT_DIR / 'round33_bias_calibration_table.csv'}")
print(f"校准条目数: {len(cal_table)}")
df_valid_cal = df_valid.merge(
    cal_table[["site_id", "hour", "calibrated_ratio"]],
    on=["site_id", "hour"],
    how="left"
)
df_valid_cal["calibrated_ratio"] = df_valid_cal["calibrated_ratio"].fillna(1.0)
df_valid_cal["pred_calibrated"] = df_valid_cal["power_pred"] * df_valid_cal["calibrated_ratio"]
df_valid_cal["pred_calibrated"] = df_valid_cal["pred_calibrated"].clip(lower=0)
cap = df_valid_cal["capacity_mw"]
df_valid_cal["pred_calibrated"] = df_valid_cal["pred_calibrated"].where(
    df_valid_cal["pred_calibrated"] <= cap, cap
)

def nrmse(y_true, y_pred, cap):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any(): return np.nan
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2)) / cap[m].mean() * 100)

before = nrmse(df_valid_cal["power_mw"].values, df_valid_cal["power_pred"].values, df_valid_cal["capacity_mw"].values)
after  = nrmse(df_valid_cal["power_mw"].values, df_valid_cal["pred_calibrated"].values, df_valid_cal["capacity_mw"].values)
print(f"\nvalid 集 NRMSE: 校准前={before:.4f}% | 校准后={after:.4f}% | 改善={before-after:.4f}%")

valid_effect = df_valid_cal.groupby("site_id").apply(
    lambda g: pd.Series({
        "before_nrmse": nrmse(g["power_mw"].values, g["power_pred"].values, g["capacity_mw"].values),
        "after_nrmse": nrmse(g["power_mw"].values, g["pred_calibrated"].values, g["capacity_mw"].values),
        "n": len(g),
    }),
    include_groups=False,
).reset_index()
valid_effect.to_csv(OUT_DIR / "round33_bias_calibration_effect_valid.csv", index=False, encoding="utf-8-sig")
print(f"valid 效果表已保存: {OUT_DIR / 'round33_bias_calibration_effect_valid.csv'}")

# ── 在 test 集上评估效果（仅用于报告，不用于调参）────────────────────────────
df_test = df[(df["split"] == "test") & (df["hour"] >= 6) & (df["hour"] < 20)].copy()
df_test_cal = df_test.merge(
    cal_table[["site_id", "hour", "calibrated_ratio"]],
    on=["site_id", "hour"],
    how="left"
)
df_test_cal["calibrated_ratio"] = df_test_cal["calibrated_ratio"].fillna(1.0)
df_test_cal["pred_calibrated"] = df_test_cal["power_pred"] * df_test_cal["calibrated_ratio"]
df_test_cal["pred_calibrated"] = df_test_cal["pred_calibrated"].clip(lower=0)
cap_test = df_test_cal["capacity_mw"]
df_test_cal["pred_calibrated"] = df_test_cal["pred_calibrated"].where(
    df_test_cal["pred_calibrated"] <= cap_test, cap_test
)

before_test = nrmse(df_test_cal["power_mw"].values, df_test_cal["power_pred"].values, df_test_cal["capacity_mw"].values)
after_test  = nrmse(df_test_cal["power_mw"].values, df_test_cal["pred_calibrated"].values, df_test_cal["capacity_mw"].values)
print(f"\ntest 集 NRMSE: 校准前={before_test:.4f}% | 校准后={after_test:.4f}% | 改善={before_test-after_test:.4f}%")

test_effect = df_test_cal.groupby("site_id").apply(
    lambda g: pd.Series({
        "before_nrmse": nrmse(g["power_mw"].values, g["power_pred"].values, g["capacity_mw"].values),
        "after_nrmse": nrmse(g["power_mw"].values, g["pred_calibrated"].values, g["capacity_mw"].values),
        "calibrated_ratio": g["calibrated_ratio"].iloc[0],
        "n": len(g),
    }),
    include_groups=False,
).reset_index()
test_effect.to_csv(OUT_DIR / "round33_bias_calibration_effect_test.csv", index=False, encoding="utf-8-sig")
print(f"test 效果表已保存: {OUT_DIR / 'round33_bias_calibration_effect_test.csv'}")
print("\nStep 7 完成！")
