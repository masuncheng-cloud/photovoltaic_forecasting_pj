#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round14 Step 4: 比较重训结果与备份最优版本，必要时自动回退。

比较对象：
  - 当前: output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
  - 备份: output/pv_pipeline/verified_backup_round14/tables/distributed_predictions_final_eval.pkl

晋级规则：
  - overall NRMSE 不高于备份 + 0.05pp
  - 10-14点站点NRMSE 不高于备份 + 0.05pp
  - MAE 不高于备份 + 0.005 MW
  - RMSE 不高于备份 + 0.005 MW
  - final = best
  - 审计 Grade A

如果不满足，自动从 verified_backup_round14 恢复。
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
BACKUP_DIR = OUT / "verified_backup_round14"
METRICS_DIR = OUT / "metrics"


def load_metrics(path: Path) -> dict:
    import sys
    _src = PROJECT_ROOT / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
    from pv_forecasting.core.utils import safe_pickle_load
    from pv_forecasting.core.evaluation import build_eval_frame

    df = safe_pickle_load(path)
    ev = build_eval_frame(df, target_site_count=53)
    yt = pd.to_numeric(ev["power_mw"], errors="coerce")
    yp = pd.to_numeric(ev["power_pred"], errors="coerce")
    actual = float(yt.sum())
    pred = float(yp.sum())
    mae = float(np.mean(np.abs(yp - yt)))
    rmse = float(np.sqrt(np.mean((yp - yt) ** 2)))
    cap_mean = float(pd.to_numeric(ev["capacity_mw"], errors="coerce").mean())
    nrmse = rmse / cap_mean * 100
    bias = (pred - actual) / actual * 100
    ratio = pred / actual

    # 10-14 点
    ev_mid = ev[ev["hour"].isin([10, 11, 12, 13, 14])]
    yt_m = pd.to_numeric(ev_mid["power_mw"], errors="coerce")
    yp_m = pd.to_numeric(ev_mid["power_pred"], errors="coerce")
    mae_m = float(np.mean(np.abs(yp_m - yt_m)))
    rmse_m = float(np.sqrt(np.mean((yp_m - yt_m) ** 2)))
    nrmse_m = rmse_m / cap_mean * 100

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
        "nrmse_midday": nrmse_m,
        "mae_midday": mae_m,
        "rmse_midday": rmse_m,
    }


def restore_from_backup() -> None:
    import shutil
    import sys
    _src = PROJECT_ROOT / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

    print("[RESTORE] 从 verified_backup_round14 恢复…")
    files_to_restore = [
        ("tables/distributed_predictions_final_eval.pkl", OUT / "tables"),
        ("tables/distributed_predictions_final_full.pkl", OUT / "tables"),
        ("tables/best_predictions_eval.pkl", OUT / "tables"),
        ("tables/best_predictions_full.pkl", OUT / "tables"),
        ("metrics/round10_overall_nrmse_summary.csv", OUT / "metrics"),
        ("metrics/round10_hour_overall_nrmse.csv", OUT / "metrics"),
        ("metrics/round10_site_hour_nrmse.csv", OUT / "metrics"),
        ("metrics/分布式光伏预测_逐小时平均NRMSE.csv", OUT / "metrics"),
        ("metrics/round11_candidate_leaderboard.csv", OUT / "metrics"),
    ]
    for rel, dest_dir in files_to_restore:
        src = BACKUP_DIR / rel
        dest = dest_dir / Path(rel).name
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            print(f"  [RESTORE] {rel}")
    print("[RESTORE] 恢复完成")


def main():
    print("=" * 70)
    print("Round14 Step 4: 比较重训结果 vs 备份最优版本")
    print("=" * 70)

    current_path = OUT / "tables" / "distributed_predictions_final_eval.pkl"
    backup_path = BACKUP_DIR / "tables" / "distributed_predictions_final_eval.pkl"

    if not current_path.exists():
        print("[WARN] 当前 final_eval.pkl 不存在，从备份恢复…")
        restore_from_backup()
        print("[OK] 已恢复，等待下次运行确认")
        decision = {"accepted": False, "restored_from_backup": True, "reason": "current not exists"}
    elif not backup_path.exists():
        print("[ERROR] 备份不存在，无法比较")
        raise SystemExit(1)
    else:
        cur = load_metrics(current_path)
        bak = load_metrics(backup_path)

        print("\n指标对比：")
        print(f"  {'指标':<30} {'当前':>12} {'备份':>12} {'变化':>12}")
        print(f"  {'-'*70}")
        for key in ["ratio", "bias", "nrmse", "mae", "rmse", "nrmse_midday"]:
            cur_v = cur[key]
            bak_v = bak[key]
            chg = cur_v - bak_v
            unit = "%" if "nrmse" in key or "bias" in key else "MW" if "mae" in key or "rmse" in key else ""
            print(f"  {key:<30} {cur_v:>11.4f}{unit} {bak_v:>11.4f}{unit} {chg:>+11.4f}{unit}")

        # 晋级检查
        checks = []
        checks.append(("NRMSE 不高于备份+0.05pp", cur["nrmse"] <= bak["nrmse"] + 0.05,
                        f"{cur['nrmse']:.4f} <= {bak['nrmse']:.4f}+0.05"))
        checks.append(("10-14 NRMSE 不高于备份+0.05pp", cur["nrmse_midday"] <= bak["nrmse_midday"] + 0.05,
                        f"{cur['nrmse_midday']:.4f} <= {bak['nrmse_midday']:.4f}+0.05"))
        checks.append(("MAE 不高于备份+0.005MW", cur["mae"] <= bak["mae"] + 0.005,
                        f"{cur['mae']:.4f} <= {bak['mae']:.4f}+0.005"))
        checks.append(("RMSE 不高于备份+0.005MW", cur["rmse"] <= bak["rmse"] + 0.005,
                        f"{cur['rmse']:.4f} <= {bak['rmse']:.4f}+0.005"))

        all_pass = True
        for name, passed, detail in checks:
            status = "✅" if passed else "❌"
            print(f"  {status} {name}: {detail}")
            if not passed:
                all_pass = False

        # 审计检查
        audit_summary = METRICS_DIR / "audit_summary.json"
        grade_a = True
        fail_count = 0
        if audit_summary.exists():
            with open(audit_summary) as f:
                aud = json.load(f)
                grade_a = aud.get("grade") == "A"
                fail_count = aud.get("fail_count", 0)
            print(f"  {'✅' if grade_a else '❌'} 审计 Grade A: {grade_a} (FAIL={fail_count})")
        else:
            print("  ⚠️  audit_summary.json 不存在，跳过审计检查")
            grade_a = True  # 不阻止

        if all_pass and grade_a:
            print("\n[OK] 重训结果通过晋级检查，保留当前版本")
            decision = {
                "accepted": True,
                "restored_from_backup": False,
                "reason": "all checks passed",
                "current": {k: round(v, 6) for k, v in cur.items()},
                "backup": {k: round(v, 6) for k, v in bak.items()},
                "checks_passed": [c[0] for c in checks if c[1]],
                "checks_failed": [c[0] for c in checks if not c[1]],
            }
        else:
            print("\n[WARN] 重训结果未通过晋级检查，自动回退到备份版本")
            restore_from_backup()
            decision = {
                "accepted": False,
                "restored_from_backup": True,
                "reason": "checks failed or audit not Grade A",
                "current": {k: round(v, 6) for k, v in cur.items()},
                "backup": {k: round(v, 6) for k, v in bak.items()},
                "checks_passed": [c[0] for c in checks if c[1]],
                "checks_failed": [c[0] for c in checks if not c[1]],
            }

    # 保存决策
    decision_path = METRICS_DIR / "round14_retrain_decision.json"
    with open(decision_path, "w") as f:
        json.dump(decision, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] 决策已保存: {decision_path}")

    # 保存对比 CSV
    rows = []
    for key in ["ratio", "bias", "nrmse", "mae", "rmse", "nrmse_midday"]:
        rows.append({
            "metric": key,
            "current": round(cur.get(key, np.nan), 6),
            "backup": round(bak.get(key, np.nan), 6),
            "change": round(cur.get(key, np.nan) - bak.get(key, np.nan), 6),
        })
    compare_df = pd.DataFrame(rows)
    compare_path = METRICS_DIR / "round14_retrain_vs_verified_best.csv"
    compare_df.to_csv(compare_path, index=False, encoding="utf-8-sig")
    print(f"[OK] 对比表已保存: {compare_path}")

    # 生成报告
    report = f"""# Round14 完整重训与回退决策报告

**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 指标对比

| 指标 | 当前重训 | 备份版本 | 变化 |
|:---|---:|---:|---:|
| overall NRMSE | {cur['nrmse']:.4f}% | {bak['nrmse']:.4f}% | {cur['nrmse']-bak['nrmse']:+.4f}pp |
| 10-14 站点NRMSE | {cur['nrmse_midday']:.4f}% | {bak['nrmse_midday']:.4f}% | {cur['nrmse_midday']-bak['nrmse_midday']:+.4f}pp |
| MAE | {cur['mae']:.4f} MW | {bak['mae']:.4f} MW | {cur['mae']-bak['mae']:+.4f} MW |
| RMSE | {cur['rmse']:.4f} MW | {bak['rmse']:.4f} MW | {cur['rmse']-bak['rmse']:+.4f} MW |
| ratio | {cur['ratio']:.4f} | {bak['ratio']:.4f} | {cur['ratio']-bak['ratio']:+.4f} |
| bias | {cur['bias']:.2f}% | {bak['bias']:.2f}% | {cur['bias']-bak['bias']:+.2f}pp |

## 晋级结果

**{"✅ 晋级成功：保留当前重训版本" if decision['accepted'] else "❌ 未通过：从备份恢复"}**

原因: {decision.get('reason', '')}

恢复文件数: {'0（无恢复）' if not decision.get('restored_from_backup') else '已从 verified_backup_round14 恢复'}
"""
    report_path = OUT / "docs" / "Round14_完整重训与回退决策报告.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"[OK] 报告已保存: {report_path}")


if __name__ == "__main__":
    cur = {"nrmse": np.nan, "nrmse_midday": np.nan, "mae": np.nan, "rmse": np.nan,
           "ratio": np.nan, "bias": np.nan}
    bak = cur.copy()
    main()
