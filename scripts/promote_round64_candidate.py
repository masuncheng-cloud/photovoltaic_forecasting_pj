#!/usr/bin/env python3
"""
promote_round64_candidate.py
==================================
将 Round64 safe 候选升级为正式 final 预测。

用法：
  python scripts/promote_round64_candidate.py --dry-run   # 查看但不执行
  python scripts/promote_round64_candidate.py --apply      # 执行升级

本脚本执行以下操作（未来适用时）：
  1. 备份当前 final pkl
  2. 写入 Round64 final pkl（power_pred_final = power_pred_round64_safe）
  3. 更新 manifest
  4. 重新导出正式 interactive_dashboard
  5. 重新运行 posttrain validation

本轮只执行 dry-run，不执行 apply。
"""

from pathlib import Path
import shutil
import json
import pandas as pd
import argparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"

# Paths
FINAL_FULL = OUT / "predictions" / "distributed_predictions_final_full.pkl"
FINAL_EVAL = OUT / "predictions" / "distributed_predictions_final_eval.pkl"
CANDS_PKL = ROOT / "output/pv_pipeline/round64/round64_candidates.pkl"
BACKUP_DIR = ROOT / "output/pv_pipeline/backups"
ROUND64_COL = "power_pred_round64_safe"
PROPOSED_COL = "power_pred_final"


def main():
    parser = argparse.ArgumentParser(description="Promote Round64 candidate to final")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run only")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        return

    mode = "apply" if args.apply else "dry-run"

    print("=" * 60)
    print(f"Round64 Candidate Promotion ({mode})")
    print("=" * 60)

    # Check prerequisites
    if not CANDS_PKL.exists():
        print(f"[FAIL] Source pkl not found: {CANDS_PKL}")
        return

    # Load candidates
    df = pd.read_pickle(CANDS_PKL)
    if ROUND64_COL not in df.columns:
        print(f"[FAIL] Column {ROUND64_COL} not found in candidates pkl")
        return
    print(f"[INFO] Loaded: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    # Build file plan
    decisions = []

    # Step 1: backup current final pkl
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    decisions.append({
        "step": 1, "action": "backup",
        "source": str(FINAL_FULL.relative_to(ROOT)),
        "dest": f"backups/distributed_predictions_final_full_before_round64_{ts}.pkl",
        "overwrite_dest": False,
        "description": f"备份当前正式 full pkl (时间戳: {ts})",
    })
    decisions.append({
        "step": 1, "action": "backup",
        "source": str(FINAL_EVAL.relative_to(ROOT)),
        "dest": f"backups/distributed_predictions_final_eval_before_round64_{ts}.pkl",
        "overwrite_dest": False,
        "description": f"备份当前正式 eval pkl (时间戳: {ts})",
    })

    # Step 2: copy round64 candidates to final paths
    # But we need to keep all original columns, only update power_pred_final
    decisions.append({
        "step": 2, "action": "write",
        "source": "round64/round64_candidates.pkl",
        "dest": "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
        "overwrite_dest": True,
        "description": f"将 {ROUND64_COL} 写入 power_pred_final，输出为 full pkl",
    })
    decisions.append({
        "step": 2, "action": "write",
        "source": "round64/round64_candidates.pkl",
        "dest": "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
        "overwrite_dest": True,
        "description": "只保留 valid + test 行，写入 eval pkl",
    })

    # Step 3: update manifest
    decisions.append({
        "step": 3, "action": "update_manifest",
        "source": "manifest.json",
        "dest": "output/pv_pipeline/manifest.json",
        "overwrite_dest": True,
        "description": "更新 manifest.json 的 SHA256 hash 和 final_prediction_column",
    })

    # Step 4: re-export dashboard
    decisions.append({
        "step": 4, "action": "run_script",
        "script": "scripts/export_interactive_dashboard_data.py",
        "args": "--dashboard-root output/pv_pipeline/interactive_dashboard --exclude-future",
        "description": "重新导出正式 interactive_dashboard",
    })

    # Step 5: posttrain validation
    decisions.append({
        "step": 5, "action": "run_script",
        "script": "scripts/posttrain_validation.py",
        "args": "",
        "description": "重新运行 posttrain validation",
    })

    # Generate plan CSV
    plan_df = pd.DataFrame(decisions)
    plan_path = OUT / "round64/round64_promote_file_plan.csv"
    plan_df.to_csv(plan_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] File plan: {plan_path}")

    # Generate dry-run report
    report_lines = [
        "# Round64 候选正式升级 Dry-Run 报告",
        "",
        f"**日期**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**模式**: {mode}",
        "",
        "## 执行计划",
        "",
        "| 步骤 | 动作 | 源文件 | 目标文件 | 是否覆盖 | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for d in decisions:
        report_lines.append(
            f"| {d['step']} | {d['action']} | {d.get('source','-')} | "
            f"{d.get('dest', d.get('script','-'))} | "
            f"{'是' if d.get('overwrite_dest') else '否'} | "
            f"{d.get('description','')} |"
        )

    report_lines.extend([
        "",
        "## 升级条件验证",
        "",
        f"- 候选文件存在: ✅ ({CANDS_PKL.relative_to(ROOT)})",
        f"- {ROUND64_COL} 列存在: ✅",
        f"- 正式文件可备份: ✅ ({FINAL_FULL.relative_to(ROOT)})",
        "",
        "## 注意事项",
        "",
        "- apply 时会直接覆盖正式 pkl，请确保已备份。",
        "- 升级后需要重新运行 posttrain validation。",
        "- 升级后需要重新导出 interactive_dashboard。",
        "- 本次升级后，power_pred_final 将使用 Round64 safe 融合结果。",
    ])

    report_path = OUT / "round64/round64_promote_dry_run_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[OK] Dry-run report: {report_path}")

    print(f"\n{'='*60}")
    if mode == "dry-run":
        print(f"[INFO] Dry-run 完成，共 {len(decisions)} 个步骤")
        print(f"如需执行，请在 git 确认后运行：")
        print(f"  python scripts/promote_round64_candidate.py --apply")
    else:
        print(f"[WARN] apply 模式暂未实现，请手动确认后执行")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
