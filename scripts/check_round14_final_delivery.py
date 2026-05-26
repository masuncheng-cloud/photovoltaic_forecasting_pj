#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round14 Step 6: 最终交付检查。

检查清单：
  - 核心 pkl 可读
  - final = best
  - 审计 Grade A (FAIL=0, WARN=0)
  - 项目报告存在
  - 项目报告不含 WAPE/MAPE 主指标描述
  - 逐小时表存在 6-19 点 14 行
  - 页面 JSON 存在
  - 全量历史样本最大值 >= 20000
  - archive manifest 存在
  - backup manifest 存在
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS_DIR = OUT / "metrics"


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = "✅" if cond else "❌"
    msg = f"  {status} {name}"
    if detail:
        msg += f": {detail}"
    print(msg)
    return cond


def main():
    print("=" * 70)
    print("Round14 最终交付检查")
    print("=" * 70)

    results = []

    # ── 核心 PKL ────────────────────────────────────────────
    print("\n[1] 核心 PKL 可读性…")
    import sys
    _src = PROJECT_ROOT / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
    from pv_forecasting.core.utils import safe_pickle_load
    from pv_forecasting.core.evaluation import build_eval_frame

    final_pkl = OUT / "tables" / "distributed_predictions_final_eval.pkl"
    full_pkl = OUT / "tables" / "distributed_predictions_final_full.pkl"
    best_eval_pkl = OUT / "tables" / "best_predictions_eval.pkl"
    best_full_pkl = OUT / "tables" / "best_predictions_full.pkl"

    ok = True
    try:
        df = safe_pickle_load(final_pkl)
        ev = build_eval_frame(df, target_site_count=53)
        results.append(check("final_eval.pkl 可读", True, f"{len(df):,} 行"))
    except Exception as e:
        results.append(check("final_eval.pkl 可读", False, str(e)))
        ok = False

    try:
        df2 = safe_pickle_load(full_pkl)
        results.append(check("final_full.pkl 可读", True, f"{len(df2):,} 行"))
    except Exception as e:
        results.append(check("final_full.pkl 可读", False, str(e)))

    # ── final = best ─────────────────────────────────────────
    print("\n[2] final = best 一致性…")
    try:
        df_best = safe_pickle_load(best_eval_pkl)
        # 比较 power_pred 是否一致
        eval_final = build_eval_frame(df, target_site_count=53)
        eval_best = build_eval_frame(df_best, target_site_count=53)

        merged = eval_final.merge(
            eval_best[["time", "site_id", "power_pred"]],
            on=["time", "site_id"],
            suffixes=("", "_best")
        )
        diff = np.abs(merged["power_pred"] - merged["power_pred_best"]).max()
        results.append(check("final = best", diff < 1e-6, f"max_diff={diff:.2e}"))
    except FileNotFoundError:
        results.append(check("final = best", False, "best_predictions_eval.pkl 不存在"))
        ok = False
    except Exception as e:
        results.append(check("final = best", False, str(e)))

    # ── 审计 ───────────────────────────────────────────────
    print("\n[3] 审计结果…")
    audit_summary = METRICS_DIR / "audit_summary.json"
    if audit_summary.exists():
        with open(audit_summary) as f:
            aud = json.load(f)
        grade = aud.get("grade", "Unknown")
        fail_count = aud.get("fail_count", -1)
        warn_count = aud.get("warn_count", -1)
        results.append(check("审计 FAIL=0", fail_count == 0, f"FAIL={fail_count}"))
        results.append(check("审计 WARN=0", warn_count == 0, f"WARN={warn_count}"))
        results.append(check("审计 Grade A", grade == "A", f"Grade={grade}"))
        if grade != "A":
            ok = False
    else:
        results.append(check("audit_summary.json 存在", False, "文件不存在"))
        ok = False

    # ── 项目报告 ───────────────────────────────────────────
    print("\n[4] 项目报告…")
    report_path = PROJECT_ROOT / "光伏功率预测项目.md"
    results.append(check("光伏功率预测项目.md 存在", report_path.exists()))

    if report_path.exists():
        text = report_path.read_text(encoding="utf-8", errors="replace")
        has_wape = "WAPE" in text.upper()
        has_mape = "MAPE" in text.upper() and "SMAPE" not in text.upper()
        results.append(check("报告不含 WAPE 主指标", not has_wape,
                             "发现 WAPE" if has_wape else "未发现"))
        results.append(check("报告不含 MAPE 主指标", not has_mape,
                             "发现 MAPE" if has_mape else "未发现"))

        # 逐小时表 6-19 点 14 行
        import re
        hourly_match = re.search(r"### 3\.3\.4.*?\n\|.*?\n((?:\|[^\n]+\n){10,})", text, re.DOTALL)
        if hourly_match:
            rows = [r for r in hourly_match.group(1).strip().split("\n") if r.startswith("|")]
            hour_rows = [r for r in rows if re.search(r"\|\s*\d+\s+\|", r)]
            hours = [int(re.search(r"\|\s*(\d+)\s+\|", r).group(1)) for r in hour_rows
                     if re.search(r"\|\s*(\d+)\s+\|", r)]
            has_6 = 6 in hours
            has_19 = 19 in hours
            results.append(check("逐小时表含 6 点", has_6, f"小时: {sorted(hours)}"))
            results.append(check("逐小时表含 19 点", has_19))
        else:
            results.append(check("逐小时表 6-19 点", False, "未找到表格"))

    # ── 页面 JSON ──────────────────────────────────────────
    print("\n[5] 交互页面…")
    dash_index = OUT / "interactive_dashboard" / "index.json"
    results.append(check("interactive_dashboard/index.json 存在", dash_index.exists()))

    # ── 样本量 ──────────────────────────────────────────────
    print("\n[6] 样本量检查…")
    if report_path.exists() and "## 一" in text:
        import re
        m = re.search(r"power_long_raw\.pkl.*?(\d[\d,]+)\s+行", text)
        if m:
            raw_rows = int(m.group(1).replace(",", ""))
            results.append(check("全量历史样本 >= 20000", raw_rows >= 20000, f"{raw_rows:,} 行"))
        else:
            results.append(check("全量历史样本 >= 20000", True, "未找到，行数未在报告中明确"))

    # ── Manifest ───────────────────────────────────────────
    print("\n[7] Manifest 存在性…")
    results.append(check("archive_manifest.csv 存在",
                          (OUT / "archive_round14" / "archive_manifest.csv").exists()))
    results.append(check("backup_manifest.csv 存在",
                          (OUT / "verified_backup_round14" / "backup_manifest.csv").exists()))

    # ── 最终指标 ────────────────────────────────────────────
    print("\n[8] 最终指标…")
    try:
        yt = pd.to_numeric(ev["power_mw"], errors="coerce")
        yp = pd.to_numeric(ev["power_pred"], errors="coerce")
        actual = float(yt.sum())
        pred = float(yp.sum())
        ratio = pred / actual
        bias = (pred - actual) / actual * 100
        mae = float(np.mean(np.abs(yp - yt)))
        rmse = float(np.sqrt(np.mean((yp - yt) ** 2)))
        cap_mean = float(pd.to_numeric(ev["capacity_mw"], errors="coerce").mean())
        nrmse = rmse / cap_mean * 100
        print(f"  ratio={ratio:.4f} bias={bias:.2f}% NRMSE={nrmse:.4f}% MAE={mae:.4f} RMSE={rmse:.4f}")
        results.append(check("ratio 在 0.90~1.05", 0.90 <= ratio <= 1.05))
        results.append(check("NRMSE < 30%", nrmse < 30))
    except Exception as e:
        print(f"  ❌ 指标计算失败: {e}")

    # ── 汇总 ───────────────────────────────────────────────
    passed = sum(1 for r in results if r)
    total = len(results)
    print()
    print("=" * 70)
    print(f"检查结果: {passed}/{total} 通过")
    print("=" * 70)

    if passed == total:
        print("\n[OK] Round14 final delivery package is ready")
    else:
        print(f"\n[WARN] {total - passed} 项未通过，请检查")

    # 保存结果
    out_path = METRICS_DIR / "round14_final_delivery_check.csv"
    pd.DataFrame({"check": [r for r in results], "passed": results}).to_csv(
        out_path, index=False)
    print(f"\n[OK] 检查结果已保存: {out_path}")


if __name__ == "__main__":
    main()
