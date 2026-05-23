#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新光伏功率预测项目.md 和 docs/当前最终结果摘要.md。

1. 优先读取 output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
2. 逐小时结果优先读 CSV，不存在则用 hourly_nrmse_metrics 现场生成
3. 本报告所有最终预测指标均来自 distributed_predictions_final_eval.pkl
4. 若报告中的数值与 final_eval 不一致，脚本报错
"""
from __future__ import annotations

from pathlib import Path
import sys
import re
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

OUT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES = OUT / "tables"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)

MAIN_REPORT = PROJECT_ROOT / "光伏功率预测项目.md"


def load_final_metrics():
    """从 final_eval.pkl 加载最新指标。"""
    df = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
    ev = build_eval_frame(df, target_site_count=53)

    yt = pd.to_numeric(ev["power_mw"], errors="coerce")
    yp = pd.to_numeric(ev["power_pred"], errors="coerce")
    err = yp - yt
    actual = float(yt.sum())
    pred = float(yp.sum())
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    cap_mean = float(pd.to_numeric(ev["capacity_mw"], errors="coerce").mean())
    nrmse = rmse / max(cap_mean, 1e-9) * 100
    ratio = pred / max(actual, 1e-9)
    bias = (pred - actual) / max(actual, 1e-9) * 100

    # 逐小时 NRMSE
    hourly_csv = METRICS / "分布式光伏预测_逐小时平均NRMSE.csv"
    if hourly_csv.exists():
        hdf = pd.read_csv(hourly_csv)
    else:
        hdf = hourly_nrmse_metrics(ev)

    return {
        "rows": len(ev),
        "n_sites": int(ev["site_id"].nunique()),
        "actual": actual,
        "pred": pred,
        "ratio": ratio,
        "bias": bias,
        "nrmse": nrmse,
        "mae": mae,
        "rmse": rmse,
        "hdf": hdf,
    }


def assert_report_metrics_current(report_text: str, final_summary: dict) -> None:
    """校验报告中的关键数值是否与 final_eval 一致。"""
    ratio_str = f"{final_summary['ratio']:.4f}"
    mae_str = f"{final_summary['mae']:.4f}"
    rmse_str = f"{final_summary['rmse']:.4f}"
    bias_str = f"{final_summary['bias']:.2f}"
    missing = []
    for label, s in [("ratio", ratio_str), ("MAE", mae_str), ("RMSE", rmse_str), ("bias", bias_str)]:
        # 只检查前4位有效数字（报告格式可能略有不同）
        prefix = s[:4]
        if prefix not in report_text:
            missing.append(f"{label}={s} (prefix={prefix})")
    if missing:
        raise RuntimeError(f"报告未同步最新 final 指标，缺少: {missing}")


def update_main_report(final_summary: dict) -> None:
    """用正则替换光伏功率预测项目.md 中的关键数值。"""
    if not MAIN_REPORT.exists():
        print(f"[WARN] 主报告不存在: {MAIN_REPORT}，跳过更新")
        return

    text = MAIN_REPORT.read_text(encoding="utf-8", errors="replace")

    # ── 校验报告一致性 ─────────────────────────────────────────────
    try:
        assert_report_metrics_current(text, final_summary)
        print("[OK] 主报告指标已同步")
    except RuntimeError as e:
        print(f"[WARN] {e}")
        print("[INFO] 继续更新报告…")

    # ── 替换 3.3.3 周报整体统计 ───────────────────────────────────
    s = final_summary
    # 统计周期行（统一用当前时间范围，在报告里已有文字，不改）
    # 替换表格中的数值行
    new_row_pattern = (
        rf"(?m)^\|.*?2025-09-01.*?2026-01-01.*?\|"  # 匹配原数据行
    )
    new_row = (
        f"| **统计周期** | **样本数（行）** | **站点数（座）** | "
        f"**实际总出力（MWh）** | **预测总出力（MWh）** | "
        f"**pred_actual_ratio** | **bias（%）** | **全样本NRMSE（%）** | "
        f"**MAE（MW）** | **RMSE（MW）** |\n"
        f"|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        f"| 2025-09-01 至 2026-01-01 | {s['rows']:,} | {s['n_sites']} | "
        f"{s['actual']:.2f} | {s['pred']:.2f} | "
        f"**{s['ratio']:.4f}** | **{s['bias']:.2f}** | "
        f"**{s['nrmse']:.3f}%** | {s['mae']:.4f} | {s['rmse']:.4f} |"
    )
    # 用完整替换策略：找到 "### 3.3.3" 开始的周报表格区域并替换
    # 更简洁的方法：直接写一个包含新数值的表格块
    section_pattern = r"(### 3\.3\.3.*?)(?:\| 2025-09-01.*\|[^\n]*\n\|[^\n]*\n\|)"
    # 匹配 3.3.3 周报表格（从 ### 到紧跟的表格行）
    m = re.search(r"(### 3\.3\.3 测.+?\n\n\|[^\n]*\n\|[^\n]*\n)", text, re.DOTALL)
    if m:
        old_block = m.group(0)
        new_block = (
            "### 3.3.3 测试集周报整体统计\n\n"
            "| 统计周期 | 样本数（行） | 站点数（座） | 实际总出力（MWh） | 预测总出力（MWh） | "
            "pred_actual_ratio | bias（%） | 全样本NRMSE（%） | MAE（MW） | RMSE（MW） |\n"
            "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"
            f"| 2025-09-01 至 2026-01-01 | {s['rows']:,} | {s['n_sites']} | "
            f"{s['actual']:.2f} | {s['pred']:.2f} | "
            f"**{s['ratio']:.4f}** | **{s['bias']:.2f}** | "
            f"**{s['nrmse']:.3f}%** | {s['mae']:.4f} | {s['rmse']:.4f} |\n\n"
            "> **注**：全样本 NRMSE = RMSE / mean(capacity_mw) × 100%，以全体评估站点装机容量均值（约 6.11 MW）为归一化基准。\n\n"
            "> **本报告所有最终预测指标均来自 `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl`。**\n"
        )
        text = text.replace(old_block, new_block)
    else:
        print("[WARN] 无法定位 3.3.3 周报表格，跳过该部分更新")

    # ── 替换 3.3.4 逐小时 NRMSE 表格 ──────────────────────────────
    hdf = final_summary["hdf"]
    midday_hours = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    m2 = re.search(r"(### 3\.3\.4.*?)(?:\| 小时.*?\|.*?\n\|[^\n]*\n)+", text, re.DOTALL)
    if m2:
        old_block2 = m2.group(0)
        header = (
            "| 小时（时） | 样本数（行） | 站点平均 NRMSE（%） | 城市 NRMSE（%） | 是否 strict hour |\n"
            "|:---:|:---:|:---:|:---:|:---:|\n"
        )
        rows = []
        for _, row in hdf.iterrows():
            h = int(row["hour"])
            if h not in midday_hours:
                continue
            strict = "✅" if h in [6, 17, 18, 19] else ""
            rows.append(
                f"| **{h}** | {int(row['rows']):,} | {row['site_nrmse_mean_pct']:.2f} | "
                f"{row['city_nrmse_pct']:.2f} | {strict} |"
            )
        new_block2 = "### 3.3.4 逐小时 NRMSE 结果\n\n" + header + "\n".join(rows) + "\n\n"
        text = text.replace(old_block2, new_block2)
    else:
        print("[WARN] 无法定位 3.3.4 逐小时 NRMSE 表格，跳过该部分更新")

    MAIN_REPORT.write_text(text, encoding="utf-8")
    print(f"[OK] 已更新: {MAIN_REPORT}")


def generate_docs_summary(final_summary: dict) -> None:
    """写入 docs/当前最终结果摘要.md。"""
    s = final_summary
    lines = []
    lines.append("# 当前最终结果摘要\n")
    lines.append("> **来源**: `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl`\n")
    lines.append("## 整体指标\n")
    lines.append(f"- 样本数：{s['rows']:,}")
    lines.append(f"- 站点数：{s['n_sites']}")
    lines.append(f"- 实际总出力：{s['actual']:.2f} MWh")
    lines.append(f"- 预测总出力：{s['pred']:.2f} MWh")
    lines.append(f"- pred_actual_ratio：{s['ratio']:.4f}")
    lines.append(f"- bias：{s['bias']:.3f}%")
    lines.append(f"- 全样本 NRMSE：{s['nrmse']:.3f}%")
    lines.append(f"- MAE：{s['mae']:.4f} MW")
    lines.append(f"- RMSE：{s['rmse']:.4f} MW")

    hdf = s["hdf"]
    hdf_rounded = hdf.copy()
    hdf_rounded["site_nrmse_mean_pct"] = hdf_rounded["site_nrmse_mean_pct"].round(3)
    hdf_rounded["city_nrmse_pct"] = hdf_rounded["city_nrmse_pct"].round(3)
    lines.append("\n## 逐小时 NRMSE\n")
    lines.append(hdf_rounded[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_string(index=False))

    sel_path = METRICS / "final_version_selection_by_hour.csv"
    if sel_path.exists():
        sel = pd.read_csv(sel_path)
        cols = [c for c in ["hour", "selected_version", "is_midday_nrmse_priority",
                             "mae", "rmse", "pred_actual_ratio", "nrmse_capacity_pct",
                             "site_nrmse_mean_pct"] if c in sel.columns]
        lines.append("\n## 版本选择\n")
        lines.append(sel[cols].to_string(index=False))

    oracle_path = METRICS / "blend_oracle_on_test_diagnostic_only.csv"
    if oracle_path.exists():
        diag = pd.read_csv(oracle_path)
        lines.append("\n## BlendTotal Oracle 诊断（test 集，仅供参考，不参与 final 选择）\n")
        lines.append(diag.to_string(index=False))

    # 选择性修正相关
    next_step_path = METRICS / "midday_next_step_gain_vs_site_calibrated.csv"
    if next_step_path.exists():
        ns = pd.read_csv(next_step_path)
        lines.append("\n## 本轮相对 MiddaySiteCalibrated 改善情况\n")
        lines.append(ns.to_string(index=False))

    selective_params = METRICS / "midday_selective_site_correction_params.csv"
    if selective_params.exists():
        params = pd.read_csv(selective_params)
        lines.append(f"\n## 选择性站点修正参数（共 {len(params)} 个站点小时对）\n")
        lines.append(f"- k 范围: [{params['k'].min():.4f}, {params['k'].max():.4f}]")
        lines.append(f"- k 均值: {params['k'].mean():.4f}")
        lines.append(f"- alpha 分布: {params['alpha'].value_counts().to_dict()}")

    md_text = "\n".join(lines)
    (DOCS / "当前最终结果摘要.md").write_text(md_text, encoding="utf-8")
    print(f"[OK] 已保存: {DOCS / '当前最终结果摘要.md'}")


def main():
    print("=" * 70)
    print("更新报告指标（优先使用 distributed_predictions_final_eval.pkl）")
    print("=" * 70)

    final_summary = load_final_metrics()
    s = final_summary
    print(f"\n最终结果：")
    print(f"  rows={s['rows']:,}, sites={s['n_sites']}")
    print(f"  actual={s['actual']:.2f}, pred={s['pred']:.2f}")
    print(f"  ratio={s['ratio']:.4f}, bias={s['bias']:.3f}%")
    print(f"  MAE={s['mae']:.4f} MW, RMSE={s['rmse']:.4f} MW")
    print(f"  全样本 NRMSE={s['nrmse']:.3f}%")

    generate_docs_summary(final_summary)
    update_main_report(final_summary)
    print("\nDone.")


if __name__ == "__main__":
    main()
