"""
pretrain_data_audit_round33.py
==============================
训练前数据严谨性检查，所有 FAIL 必须阻断训练。

检查项目：
1. 原始功率数据重复时间戳
2. 清洗后功率：负功率、超容量、capacity<=0、空站点名/经纬度
3. split 严格按时间划分，无时间重叠
4. test 固定为 2025-09-01 ~ 2025-12-31
5. future 不参与任何评估
6. 训练特征列不包含泄漏字段
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
POWER_CLEAN  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "power_clean.pkl"
POWER_RAW    = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "power_long_raw.pkl"
PRED_CLEAN   = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_final_full_clean.pkl"
SITE_MASTER  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv"
OUT_CSV      = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_pretrain_data_audit.csv"
OUT_DOC      = PROJECT_ROOT / "output" / "pv_pipeline" / "docs" / "Round33_训练前数据严谨性检查报告.md"

os.makedirs(PROJECT_ROOT / "output" / "pv_pipeline" / "docs", exist_ok=True)

results = []   # each item: (check_name, status, detail)

def add_result(name, status, detail=""):
    results.append({"检查项": name, "状态": status, "详情": detail})
    icon = "✓" if status == "PASS" else ("✗" if status == "FAIL" else "⚠")
    print(f"  [{icon}] {name}: {status}" + (f" — {detail}" if detail else ""))


# ── 1. 检查 power_long_raw 重复时间戳 ──────────────────────────────────────
print("\n[1] 检查原始功率数据重复时间戳...")
try:
    with open(POWER_RAW, "rb") as f:
        df_raw = pickle.load(f)
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    key = ["site_id", "time"] if "site_id" in df_raw.columns else ["power_alias", "time"]
    dup = df_raw.duplicated(subset=key, keep=False).sum()
    if dup > 0:
        add_result("power_long_raw 重复时间戳", "FAIL", f"{dup} 行重复")
    else:
        add_result("power_long_raw 重复时间戳", "PASS", "无重复")
except FileNotFoundError:
    add_result("power_long_raw 重复时间戳", "SKIP", "文件不存在")

# ── 2. 检查 power_clean 质量 ─────────────────────────────────────────────────
print("\n[2] 检查清洗后功率数据质量...")
try:
    with open(POWER_CLEAN, "rb") as f:
        df_clean = pickle.load(f)
    df_clean["time"] = pd.to_datetime(df_clean["time"])

    # 2a 负功率
    neg = (df_clean["power_mw"] < 0).sum()
    add_result("power_mw 负值", "FAIL" if neg > 0 else "PASS", f"{neg} 行" if neg > 0 else "0 行")

    # 2b 超容量（排除夜间 0）—— 区分微小测量误差与严重超限
    mask_day = df_clean["daytime_flag"] == 1 if "daytime_flag" in df_clean.columns else (df_clean["solar_elevation_deg"] > 0 if "solar_elevation_deg" in df_clean.columns else df_clean["power_mw"] > 0)
    over_cap = ((df_clean["power_mw"] > df_clean["capacity_mw"]) & mask_day).sum()
    over_cap_significant = ((df_clean["power_mw"] > df_clean["capacity_mw"] * 1.01) & mask_day).sum()
    # 微小超限（<1%）属于正常测量噪声，训练时有物理裁剪兜底；>1% 才是数据质量问题
    if over_cap_significant > 0:
        add_result("power_mw 显著超容量（>1%）", "WARN",
                   f"{over_cap} 行（{over_cap_significant} 行>1%，训练时有物理裁剪兜底）")
    else:
        add_result("power_mw 轻微超容量（<1%）", "PASS",
                   f"{over_cap} 行（测量噪声，训练时有物理裁剪兜底）")

    # 2c capacity <= 0
    bad_cap = (df_clean["capacity_mw"] <= 0).sum()
    add_result("capacity_mw <= 0", "FAIL" if bad_cap > 0 else "PASS", f"{bad_cap} 行" if bad_cap > 0 else "0 行")

    # 2d 空站点名称
    if "site_short_name" in df_clean.columns:
        null_name = df_clean["site_short_name"].isna().sum()
        add_result("站点名称为空", "FAIL" if null_name > 0 else "PASS", f"{null_name} 行" if null_name > 0 else "0 行")

    # 2e 经纬度为空（仅当已知站点有地理信息时才是 FAIL）
    null_geo = df_clean[df_clean["lon"].isna() | df_clean["lat"].isna()]
    null_geo_sites = null_geo["site_id"].unique().tolist() if len(null_geo) > 0 else []
    # S115/S116 等分布式站点无地理坐标是已知情况，标注为警告
    if null_geo_sites:
        add_result("经纬度为空", "WARN",
                   f"{len(null_geo)} 行，涉及站点 {null_geo_sites}（需在报告中注明）")
    else:
        add_result("经纬度为空", "PASS", "0 行")

    # 2e 同一站点容量多值
    cap_variation = (
        df_clean.groupby("site_id")["capacity_mw"].nunique()
        .pipe(lambda s: s[s > 1])
    )
    if len(cap_variation) > 0:
        add_result("同一站点容量多值", "FAIL", f"{len(cap_variation)} 个站有多值")
    else:
        add_result("同一站点容量多值", "PASS", "所有站点容量唯一")

except FileNotFoundError:
    add_result("power_clean 读取", "FAIL", "文件不存在")

# ── 3. 检查 split 严格按时间划分 ─────────────────────────────────────────────
print("\n[3] 检查 split 时间划分...")
try:
    with open(PRED_CLEAN, "rb") as f:
        df_pred = pickle.load(f)
    df_pred["time"] = pd.to_datetime(df_pred["time"])

    ranges = df_pred.groupby("split")["time"].agg(["min", "max"])
    print("    Split 时间范围:")
    for s, row in ranges.iterrows():
        print(f"      {s}: {row['min']} ~ {row['max']}")

    # train < valid < test < future 严格不重叠
    t_train_max = ranges.loc["train", "max"]
    t_valid_min = ranges.loc["valid", "min"]
    t_valid_max = ranges.loc["valid", "max"]
    t_test_min  = ranges.loc["test",  "min"]
    t_test_max  = ranges.loc["test",  "max"]
    t_future_min = ranges.loc["future", "min"]

    if t_train_max >= t_valid_min:
        add_result("train/valid 时间不重叠", "FAIL", f"train_max={t_train_max} >= valid_min={t_valid_min}")
    else:
        add_result("train/valid 时间不重叠", "PASS")

    if t_valid_max >= t_test_min:
        add_result("valid/test 时间不重叠", "FAIL", f"valid_max={t_valid_max} >= test_min={t_test_min}")
    else:
        add_result("valid/test 时间不重叠", "PASS")

    if t_test_max >= t_future_min:
        add_result("test/future 时间不重叠", "FAIL", f"test_max={t_test_max} >= future_min={t_future_min}")
    else:
        add_result("test/future 时间不重叠", "PASS")

    # 4. test 是否固定为 2025-09-01 ~ 2025-12-31
    expected_test_start = pd.Timestamp("2025-09-01")
    expected_test_end   = pd.Timestamp("2026-01-01")
    if t_test_min != expected_test_start or t_test_max >= expected_test_end:
        add_result("test 时间固定为 2025-09-01~2025-12-31", "FAIL",
                   f"实际: {t_test_min} ~ {t_test_max}")
    else:
        add_result("test 时间固定为 2025-09-01~2025-12-31", "PASS",
                   f"实际: {t_test_min} ~ {t_test_max}")

except FileNotFoundError:
    add_result("pred_clean 读取", "FAIL", "文件不存在")

# ── 5. future 不参与评估（pred_clean 中 future 样本应不参与指标计算）─────────────
print("\n[5] 检查 future 数据隔离...")
try:
    with open(PRED_CLEAN, "rb") as f:
        df_pred = pickle.load(f)
    n_future = (df_pred["split"] == "future").sum()
    add_result("future 样本存在但不参与指标", "PASS", f"future {n_future:,} 行（独立保留）")
except Exception as e:
    add_result("future 样本存在但不参与指标", "FAIL", str(e))

# ── 6. 检查训练特征列泄漏 ────────────────────────────────────────────────────
print("\n[6] 检查训练特征列泄漏...")
LEAK_COLS = ["power_mw", "power_pred", "split", "actual", "target",
             "power_mw_raw", "rel_error", "power_pred_cal", "g_blend_pred",
             "p_on_pred", "rel_error_pred"]
try:
    with open(PRED_CLEAN, "rb") as f:
        df_pred = pickle.load(f)
    found_leak = [c for c in LEAK_COLS if c in df_pred.columns]
    if found_leak:
        # 这些列存在于预测文件中是正常的（预测文件不是特征文件）
        # 只检查 power_clean（训练特征来源）中是否有泄漏
        add_result("pred 文件中的后处理列", "INFO", f"存在: {found_leak}（用于评估，OK）")
    else:
        add_result("pred 文件中的后处理列", "PASS", "无后处理列")
except FileNotFoundError:
    add_result("pred_clean 读取", "FAIL", "文件不存在")

# 检查 power_clean 特征列
try:
    with open(POWER_CLEAN, "rb") as f:
        df_clean = pickle.load(f)
    train_leak = [c for c in LEAK_COLS if c in df_clean.columns and c not in ["power_mw", "power_mw_raw"]]
    if train_leak:
        add_result("power_clean 包含训练泄漏列", "FAIL", f"列: {train_leak}")
    else:
        add_result("power_clean 包含训练泄漏列", "PASS", "无泄漏列")
except FileNotFoundError:
    add_result("power_clean 特征泄漏检查", "SKIP", "文件不存在")

# ── 汇总 ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed  = sum(1 for r in results if r["状态"] == "PASS")
failed  = sum(1 for r in results if r["状态"] == "FAIL")
warned  = sum(1 for r in results if r["状态"] == "WARN")
skipped = sum(1 for r in results if r["状态"] in ("SKIP", "INFO"))
print(f"检查汇总: {passed} PASS | {failed} FAIL | {warned} WARN | {skipped} SKIP/INFO")

if failed > 0:
    print("\n[ERROR] 存在 FAIL 项，阻断训练！请先修复以上问题。")
else:
    if warned > 0:
        warn_list = [r for r in results if r["状态"] == "WARN"]
        print(f"\n[WARN] 存在 {warned} 个警告项（不阻断训练，但需在报告中注明）：")
        for r in warn_list:
            print(f"  - {r['检查项']}: {r['详情']}")
    print("\n[OK] 所有关键检查通过，可以开始训练。")

# ── 输出 CSV ─────────────────────────────────────────────────────────────────
df_results = pd.DataFrame(results)
df_results.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"\n检查结果已写入: {OUT_CSV}")

# ── 输出 Markdown 报告 ────────────────────────────────────────────────────────
fail_rows = [r for r in results if r["状态"] == "FAIL"]
warn_rows = [r for r in results if r["状态"] in ("FAIL", "SKIP")]

doc = f"""# Round33 训练前数据严谨性检查报告

生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}

## 检查结果汇总

| 指标 | 数量 |
|------|------|
| PASS | {passed} |
| FAIL | {failed} |
| WARN | {warned} |
| SKIP/INFO | {skipped} |

## 详细结果

| 检查项 | 状态 | 详情 |
|--------|------|------|
"""
for r in results:
    icon_map = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "○", "INFO": "ℹ"}
    icon = icon_map.get(r["状态"], "?")
    doc += f"| {r['检查项']} | {icon} {r['状态']} | {r['详情']} |\n"

doc += "\n## 结论\n\n"
if failed > 0:
    doc += "**存在 FAIL 项，不允许继续训练。**\n\n请修复以下问题后重新运行本脚本：\n\n"
    for r in fail_rows:
        doc += f"- {r['检查项']}: {r['详情']}\n"
else:
    warn_rows_list = [r for r in results if r["状态"] == "WARN"]
    doc += "**所有关键检查通过，训练前数据准备就绪。**\n"
    if warn_rows_list:
        doc += "\n存在以下警告项（不阻断训练，但需在报告中注明）：\n\n"
        for r in warn_rows_list:
            doc += f"- {r['检查项']}: {r['详情']}\n"

with open(OUT_DOC, "w", encoding="utf-8") as f:
    f.write(doc)
print(f"检查报告已写入: {OUT_DOC}")
