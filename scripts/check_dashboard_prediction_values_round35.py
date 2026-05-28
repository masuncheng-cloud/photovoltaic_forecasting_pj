"""
check_dashboard_prediction_values_round35.py
==========================================
全量校验可视化 site_series/*.json 中的 pred_mw 和 actual_mw
是否与 distributed_predictions_final_round34.pkl 中的 power_pred_final 和 power_mw 完全一致。

验收标准：
  - 所有站点 status == PASS
  - max_abs_diff_pred <= 1e-9
  - max_abs_diff_actual <= 1e-9
  - n_json == n_pkl_6_19 == n_matched（口径：split != future，hour in 6..19）
"""
import os
import json
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS    = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
DASH    = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
os.makedirs(METRICS, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)

PRED_PKL  = TABLES / "distributed_predictions_final_round34.pkl"
OUT_CSV    = METRICS / "round35_dashboard_prediction_consistency.csv"
OUT_REPORT = DOCS / "Round35_可视化预测值一致性检查报告.md"

TOLERANCE = 1e-9


def load_pkl() -> pd.DataFrame:
    """读取 Round34 预测文件（不含 future，6-19 点），与可视化导出口径一致。"""
    print("读取 pkl...")
    with open(PRED_PKL, "rb") as f:
        df = pickle.load(f)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    # 与可视化导出口径一致：排除 future 且限定 6-19 点
    df = df[
        (df["split"] != "future") &
        (df["hour"] >= 6) &
        (df["hour"] <= 19)
    ].copy()
    df = df.sort_values(["site_id", "time"]).reset_index(drop=True)
    print(f"  pkl: {len(df):,} 行 (不含future, 6-19点), {df['site_id'].nunique()} 站")
    return df


def load_json_series(site_dir: Path) -> dict:
    """读取全部 site_series JSON，返回 {site_id: list_of_rows}。"""
    print("读取 site_series JSON...")
    result = {}
    files = sorted(site_dir.glob("S*.json"))
    for f in files:
        sid = f.stem
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        # 排除 future
        if isinstance(data, list):
            filtered = [r for r in data if r.get("split") != "future"]
        else:
            filtered = []
        result[sid] = filtered
    print(f"  JSON: {len(result)} 个站点文件")
    return result


def check_consistency(pkl_df: pd.DataFrame, json_data: dict) -> pd.DataFrame:
    """逐站点对比 pkl 与 JSON 的 actual_mw / pred_mw / capacity_mw。"""
    rows = []
    all_pass = True
    for sid in sorted(json_data.keys()):
        json_rows = json_data[sid]
        n_json = len(json_rows)
        if n_json == 0:
            rows.append({
                "site_id": sid,
                "n_json": 0, "n_pkl_6_19": 0, "n_matched": 0,
                "count_ok": False,
                "max_abs_diff_actual": np.nan,
                "max_abs_diff_pred": np.nan,
                "max_abs_diff_capacity": np.nan,
                "status": "WARN",
                "message": "JSON 为空或全为 future",
            })
            continue

        # 构建 JSON DataFrame
        jdf = pd.DataFrame(json_rows)
        jdf["time"] = pd.to_datetime(jdf["time"], errors="coerce")
        jdf = jdf.sort_values(["site_id", "time"]).reset_index(drop=True)

        # 对应的 pkl 数据（已过滤 6-19 点）
        pkl_site = pkl_df[pkl_df["site_id"] == sid].copy()
        pkl_site = pkl_site.sort_values(["site_id", "time"]).reset_index(drop=True)
        n_pkl_6_19 = len(pkl_site)

        # 按 time 合并
        merged = pd.merge(
            jdf[["time", "actual_mw", "pred_mw", "capacity_mw"]].rename(
                columns={"capacity_mw": "cap_json", "actual_mw": "actual_json", "pred_mw": "pred_json"}
            ),
            pkl_site[["time", "power_mw", "power_pred_final", "capacity_mw"]].rename(
                columns={"capacity_mw": "cap_pkl", "power_mw": "actual_pkl", "power_pred_final": "pred_pkl"}
            ),
            on="time", how="inner"
        )
        n_matched = len(merged)

        # 行数一致性判断
        count_ok = (n_json == n_pkl_6_19 == n_matched)

        # 计算最大误差
        # JSON 存储 round(value, 4)，pkl 存储全精度；比较时对 pkl 也 round 到 4 位
        ROUND = 4
        def safe_diff(a, b, round_pkl=False):
            m = a.notna() & b.notna()
            if not m.any():
                return np.nan
            b_vals = b[m]
            if round_pkl:
                b_vals = b_vals.round(ROUND)
            return float(np.abs(a[m] - b_vals).max())

        max_diff_actual   = safe_diff(merged["actual_json"], merged["actual_pkl"], True)
        max_diff_pred    = safe_diff(merged["pred_json"],   merged["pred_pkl"],  True)
        max_diff_capacity = safe_diff(merged["cap_json"],   merged["cap_pkl"],   True)

        # 判断 PASS/FAIL（含行数一致性）
        actual_ok = (max_diff_actual   is np.nan) or (max_diff_actual   <= TOLERANCE)
        pred_ok   = (max_diff_pred     is np.nan) or (max_diff_pred     <= TOLERANCE)
        cap_ok    = (max_diff_capacity is np.nan) or (max_diff_capacity <= TOLERANCE)

        if actual_ok and pred_ok and cap_ok and count_ok:
            status = "PASS"
            msg = (f"actual_diff={max_diff_actual:.2e}, pred_diff={max_diff_pred:.2e}, "
                   f"cap_diff={max_diff_capacity:.2e}, count_ok={count_ok}")
        else:
            all_pass = False
            status = "FAIL"
            msg = (f"actual_diff={max_diff_actual:.2e}, pred_diff={max_diff_pred:.2e}, "
                   f"cap_diff={max_diff_capacity:.2e}, count_ok={count_ok}")

        rows.append({
            "site_id": sid,
            "n_json": n_json,
            "n_pkl_6_19": n_pkl_6_19,
            "n_matched": n_matched,
            "count_ok": count_ok,
            "max_abs_diff_actual": max_diff_actual,
            "max_abs_diff_pred": max_diff_pred,
            "max_abs_diff_capacity": max_diff_capacity,
            "status": status,
            "message": msg,
        })

    df = pd.DataFrame(rows)
    return df, all_pass


def write_csv(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"CSV 已保存: {path}")


def write_report(df: pd.DataFrame, all_pass: bool):
    total = len(df)
    passes = int((df["status"] == "PASS").sum())
    fails  = int((df["status"] == "FAIL").sum())
    warns  = int((df["status"] == "WARN").sum())
    max_pred_diff  = float(df["max_abs_diff_pred"].max())     if df["max_abs_diff_pred"].notna().any()     else np.nan
    max_actual_diff = float(df["max_abs_diff_actual"].max()) if df["max_abs_diff_actual"].notna().any() else np.nan
    max_cap_diff   = float(df["max_abs_diff_capacity"].max()) if df["max_abs_diff_capacity"].notna().any() else np.nan

    lines = [
        "# Round35 可视化预测值一致性检查报告\n",
        f"**生成时间**: 2026-05-28 21:35\n",
        f"**检查口径**: split != 'future' 且 hour in 6..19（与可视化导出站点曲线口径一致）\n",
        f"**容差**: |a - b| ≤ {TOLERANCE:.0e}（JSON 存储 round(value, 4)，比较时 pkl 值同样四舍五入）\n",
        "\n## 总体结果\n",
        f"| 指标 | 值 |\n",
        f"|------|-----|\n",
        f"| 总站点数 | {total} |\n",
        f"| PASS | {passes} |\n",
        f"| FAIL | {fails} |\n",
        f"| WARN | {warns} |\n",
        f"| 最大 actual 误差 | {max_actual_diff:.2e} |\n",
        f"| 最大 pred 误差 | {max_pred_diff:.2e} |\n",
        f"| 最大 capacity 误差 | {max_cap_diff:.2e} |\n",
        "\n## 逐站点详情\n",
        "| site_id | n_json | n_pkl_6_19 | n_matched | count_ok | max_diff_actual | max_diff_pred | status | message |\n",
        "|----------|--------|------------|-----------|----------|-----------------|---------------|--------|---------|\n",
    ]
    for _, r in df.iterrows():
        ad   = f"{r['max_abs_diff_actual']:.2e}"   if not pd.isna(r['max_abs_diff_actual'])   else "N/A"
        pd_  = f"{r['max_abs_diff_pred']:.2e}"     if not pd.isna(r['max_abs_diff_pred'])     else "N/A"
        icon = "✓" if r['status'] == "PASS" else ("⚠" if r['status'] == "WARN" else "✗")
        lines.append(
            f"| {r['site_id']} | {r['n_json']} | {r['n_pkl_6_19']} | {r['n_matched']} "
            f"| {'✓' if r['count_ok'] else '✗'} | {ad} | {pd_} "
            f"| {icon} {r['status']} | {r['message']} |\n"
        )

    if fails > 0:
        lines.append("\n## FAIL 详情\n")
        fail_df = df[df["status"] == "FAIL"]
        for _, r in fail_df.iterrows():
            lines.append(f"- **{r['site_id']}**: {r['message']}\n")

    if all_pass:
        lines.append("\n## 结论\n")
        lines.append("**全部站点通过**：pred_mw 与 power_pred_final、actual_mw 与 power_mw 完全一致，"
                     "n_json == n_pkl_6_19 == n_matched。\n")
    else:
        lines.append("\n## 结论\n")
        lines.append(f"**{fails} 个站点失败**，请检查上述 FAIL 条目。\n")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"报告已保存: {OUT_REPORT}")


# ── 主流程 ──────────────────────────────────────────────────────────────
print("=" * 60)
print("Round35 可视化预测值一致性全量检查")
print("=" * 60)

pkl_df    = load_pkl()
json_data = load_json_series(DASH / "site_series")
result_df, all_pass = check_consistency(pkl_df, json_data)

write_csv(result_df, OUT_CSV)

# 汇总
total   = len(result_df)
passes  = int((result_df["status"] == "PASS").sum())
fails   = int((result_df["status"] == "FAIL").sum())
max_pred = float(result_df["max_abs_diff_pred"].max())     if result_df["max_abs_diff_pred"].notna().any()     else 0.0
max_act  = float(result_df["max_abs_diff_actual"].max()) if result_df["max_abs_diff_actual"].notna().any() else 0.0

print()
print("=" * 60)
print(f"结果: {passes}/{total} PASS, {fails} FAIL")
print(f"最大 pred 误差:     {max_pred:.2e} (容差: {TOLERANCE:.0e})")
print(f"最大 actual 误差:   {max_act:.2e}")
print("=" * 60)

write_report(result_df, all_pass)

if not all_pass:
    print("\n[FAIL] 存在不一致站点，请检查 round35_dashboard_prediction_consistency.csv")
    exit(1)
else:
    print("\n[OK] 全部站点通过一致性检查")
    exit(0)
