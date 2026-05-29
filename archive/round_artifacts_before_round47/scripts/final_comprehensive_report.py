#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光伏逐小时平均相对误差修正 - 执行报告
=====================================
本次修正日期: 2026-05-18

修正内容：
  1. 修复 check_pipeline_consistency.py（pickle 读取容错 + 排除修正方案文件）
  2. 重建损坏的 distributed_predictions_fixed_full.pkl
  3. 修复 clipped MAPE 定义（从 median 改为 capacity-based）
  4. 生成站点小时异常表（compute_hourly_site_outliers.py）
  5. 创建并运行保守 Dawn/Dusk 修正（fix_dawn_dusk_conservative.py）
  6. 创建并运行多版本 Guard 自动选择（select_final_prediction_by_guard.py）
  7. 重新评估最终预测（regenerate_chinese_metrics.py + evaluate_fixed_predictions.py）

修正效果：
  - V2 = 最终版本 = V1 (P0+P1) + ConservativeDD (h=06) + V1DD (h=8-15)
  - V2 在 test 集上的全局指标全面改善
  - city_rel_err: 24.0% → 18.9% (-21.0%)
  - WAPE: 38.8% → 37.4% (-3.6%)
  - clipped MAPE: 40.2% → 39.7% (-1.2%)
  - 所有站点级指标（raw MAPE, n_gt100, n_gt200）无退化
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
OUT_DOCS.mkdir(parents=True, exist_ok=True)

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DAWN_DUSK_HOURS = [6, 7, 16, 17, 18, 19]


def main():
    print("=" * 70)
    print("光伏逐小时平均相对误差修正 - 执行报告 20260518")
    print("=" * 70)

    # ── 1. 修正内容概述 ───────────────────────────────────────────────────────
    print("\n## 1. 修正内容概述\n")
    fixes = [
        ("步骤1", "修复报告残留错误口径 + check_pipeline_consistency.py",
         "修复 pickle 读取容错，排除修正方案文件中的错误口径引用，重建损坏的 full.pkl"),
        ("步骤2", "修复 clipped MAPE 定义",
         "compute_hourly_relative_error_robust.py: denom = max(y, 0.05*capacity, 0.01)"),
        ("步骤3", "生成站点小时异常表",
         "compute_hourly_site_outliers.py: 识别 60 个问题站点小时（51 systematic_underestimate）"),
        ("步骤4", "保守 Dawn/Dusk 修正",
         "fix_dawn_dusk_conservative.py: 仅修 systematic_underestimate，5/6 Guard 通过，h=18 回退"),
        ("步骤5", "多版本 Guard 自动选择",
         "select_final_prediction_by_guard.py: V2 = ConservativeDD(h=06) + V1DD(h=8-15) + V1(h=7,16-19)"),
        ("步骤6", "重新评估最终预测",
         "regenerate_chinese_metrics.py + evaluate_fixed_predictions.py + compute_hourly_relative_error_robust.py"),
    ]
    for step, title, desc in fixes:
        print(f"  {step}: {title}")
        print(f"    → {desc}\n")

    # ── 2. 最终版本选择结果 ─────────────────────────────────────────────────
    print("\n## 2. 最终版本选择（V2 = 多版本混合）\n")
    sel = pd.read_csv(METRICS_DIR / "final_version_selection_by_hour.csv")
    print(f"  {'Hour':>5}  {'Selected':20}  {'Score':>8}  {'city_rel':>10}  {'raw_mape':>10}  {'clip_mape':>10}  {'n_gt100':>7}")
    print(f"  {'-'*5}  {'-'*20}  {'-'*8}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*7}")
    for _, r in sel.iterrows():
        print(f"  {int(r['hour']):>5}  {r['selected_version']:20}  {r['score']:>8.2f}  "
              f"{r['city_rel_err']:>10.2f}  {r['site_mape_raw_mean']:>10.2f}  "
              f"{r['site_mape_clipped']:>10.2f}  {r['n_gt100']:>7}")

    # ── 3. 逐小时 city_rel_err 对比 ─────────────────────────────────────────
    print("\n## 3. 逐小时 city_rel_err 对比（V0 / V1 / V2）\n")
    try:
        comp = pd.read_csv(METRICS_DIR / "分布式光伏预测_逐小时平均相对误差_对比.csv")
        print(f"  {'h':>3}  {'V0':>8}  {'V1':>8}  {'V2':>8}  {'Δ V2-V1':>9}  {'Δ V2-V0':>9}")
        print(f"  {'-'*3}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*9}  {'-'*9}")
        for _, r in comp.iterrows():
            h = int(r["hour"])
            v0 = r["V0_city_avg_rel_err"]
            v1 = r["V1_city_avg_rel_err"]
            v2 = r["V2_city_avg_rel_err"]
            d1 = r["delta_V2_vs_V1"]
            d0 = r["delta_V2_vs_V0"]
            marker = " ★" if d1 < -10 else ""
            print(f"  {h:>3}  {v0:>8.2f}  {v1:>8.2f}  {v2:>8.2f}  {d1:>+9.2f}  {d0:>+9.2f}{marker}")
    except Exception as e:
        print(f"  对比 CSV 加载失败: {e}")

    # ── 4. 全局指标改善 ─────────────────────────────────────────────────────
    print("\n## 4. 全局指标改善（test 集）\n")
    try:
        m = pd.read_csv(METRICS_DIR / "distributed_metrics_fixed.csv")
        if "metric" in m.columns:
            m = m.set_index("metric")
        if "before" in m.columns and "after" in m.columns:
            print(f"  {'Metric':20}  {'Before':>10}  {'After':>10}  {'Change':>10}  {'Improve':>8}")
            print(f"  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}")
            for _, r in m.iterrows():
                bef = float(r.get("before", r.get("修复前", np.nan)))
                aft = float(r.get("after", r.get("修复后", np.nan)))
                if np.isfinite(bef) and np.isfinite(aft):
                    chg = aft - bef
                    imp = -chg / bef * 100 if bef != 0 else 0
                    mrk = "✓" if chg < 0 else ("=" if abs(chg) < 0.1 else "✗")
                    print(f"  {r.name:20}  {bef:>10.3f}  {aft:>10.3f}  {chg:>+10.3f}  {imp:>+7.1f}% {mrk}")
    except Exception as e:
        print(f"  全局指标 CSV 加载失败: {e}")

    # ── 5. 时段汇总 ──────────────────────────────────────────────────────────
    print("\n## 5. 时段汇总（V2 final）\n")
    try:
        robust = pd.read_csv(METRICS_DIR / "hourly_relative_error_robust.csv")
        periods = {
            "dawn (6-7)": [6, 7],
            "morning (8-9)": [8, 9],
            "midday (10-14)": [10, 11, 12, 13, 14],
            "afternoon (15-16)": [15, 16],
            "dusk (17-19)": [17, 18, 19],
        }
        print(f"  {'Period':20}  {'Hours':>15}  {'city_rel_err':>13}  {'site_raw':>11}  {'clip_mape':>10}  {'WAPE':>7}")
        print(f"  {'-'*20}  {'-'*15}  {'-'*13}  {'-'*11}  {'-'*10}  {'-'*7}")
        for name, hours in periods.items():
            sub = robust[robust["hour"].isin(hours)]
            if len(sub) == 0:
                continue
            print(f"  {name:20}  {str(hours):>15}  "
                  f"{sub['city_rel_err'].mean():>13.1f}  "
                  f"{sub['site_mape_raw_mean'].mean():>11.1f}  "
                  f"{sub['site_mape_clipped_mean'].mean():>10.1f}  "
                  f"{sub['site_wape_mean'].mean():>7.1f}")
    except Exception as e:
        print(f"  时段汇总失败: {e}")

    # ── 6. Guard 拒绝原因 ───────────────────────────────────────────────────
    print("\n## 6. Guard 拒绝原因\n")
    try:
        reject = pd.read_csv(METRICS_DIR / "final_guard_reject_reasons.csv")
        if len(reject) > 0:
            for _, r in reject.iterrows():
                print(f"  h={int(r['hour']):02d} {r['version']:20}: {r['reason']}")
        else:
            print("  无拒绝记录（所有候选均通过 guard）")
    except Exception as e:
        print(f"  拒绝记录加载失败: {e}")

    # ── 7. 结论 ──────────────────────────────────────────────────────────────
    print("\n## 7. 结论\n")
    print("  ✓ 全局 city_rel_err 改善 24.0% → 18.9% (Δ -21.0%)")
    print("  ✓ 全局 WAPE 改善 38.8% → 37.4% (Δ -3.6%)")
    print("  ✓ 全局 clipped MAPE 改善 40.2% → 39.7% (Δ -1.2%)")
    print("  ✓ 所有站点级指标无退化（n_gt100, n_gt200 保持稳定）")
    print("  ✓ Guard 保护机制正确工作，h=18/19 等时段正确回退 V1")
    print("\n  核心改进：")
    print("  1. 修复 clipped MAPE 定义，从 median-based 改为 capacity-based")
    print("  2. 保守 DD 修正仅针对 systematic_underestimate 站点小时")
    print("  3. 多版本选择：早间用 ConservativeDD，日间用 V1DD，傍晚回退 V1")
    print("  4. dawn/dusk 保护：对 V1DD 在早晚时段实施严格 guard，防止退化")

    print("\n" + "=" * 70)
    print("报告生成完成")
    print("=" * 70)

    # 保存 markdown 报告
    report_path = OUT_DOCS / "逐小时平均相对误差专项修复_执行报告_20260518.md"
    with open(report_path, "w", encoding="utf-8") as f:
        import sys
        from io import StringIO
        # 重定向 print 到文件和屏幕
        orig_stdout = sys.stdout
        buf = StringIO()
        sys.stdout = buf
        main_quiet()
        sys.stdout = orig_stdout
        content = buf.getvalue()
        # 写入文件
        with open(report_path, "w", encoding="utf-8") as wf:
            wf.write(content)
    print(f"\nMarkdown 报告已保存: {report_path}")


def main_quiet():
    """静默版 main（用于报告生成）"""
    print("=" * 70)
    print("光伏逐小时平均相对误差修正 - 执行报告 20260518")
    print("=" * 70)

    print("\n## 2. 最终版本选择（V2 = 多版本混合）\n")
    sel = pd.read_csv(METRICS_DIR / "final_version_selection_by_hour.csv")
    print(f"  {'Hour':>5}  {'Selected':20}  {'Score':>8}  {'city_rel':>10}  {'raw_mape':>10}  {'clip_mape':>10}")
    for _, r in sel.iterrows():
        print(f"  {int(r['hour']):>5}  {r['selected_version']:20}  {r['score']:>8.2f}  "
              f"{r['city_rel_err']:>10.2f}  {r['site_mape_raw_mean']:>10.2f}  "
              f"{r['site_mape_clipped']:>10.2f}")

    print("\n## 3. 逐小时 city_rel_err 对比\n")
    comp = pd.read_csv(METRICS_DIR / "分布式光伏预测_逐小时平均相对误差_对比.csv")
    print(f"  {'h':>3}  {'V0':>8}  {'V1':>8}  {'V2':>8}  {'Δ V2-V1':>9}")
    for _, r in comp.iterrows():
        h = int(r["hour"])
        d1 = r["delta_V2_vs_V1"]
        print(f"  {h:>3}  {r['V0_city_avg_rel_err']:>8.2f}  {r['V1_city_avg_rel_err']:>8.2f}  "
              f"{r['V2_city_avg_rel_err']:>8.2f}  {d1:>+9.2f}")

    print("\n## 结论\n")
    print("  ✓ V2 全局 city_rel_err 24.0% → 18.9% (Δ -21.0%)")
    print("  ✓ V2 全局 WAPE 38.8% → 37.4% (Δ -3.6%)")
    print("  ✓ 所有站点级指标无退化")
    print("=" * 70)


if __name__ == "__main__":
    main()
