"""
run_round36_full_retrain.py
==========================
Round36 完整重训流程调度脚本。

自动执行：
  1. pretrain_audit_round36.py      — 训练前数据审计
  2. train_distributed_model_v159.py — 完整训练
  3. build_round36_predictions.py   — 构建 final pkl
  4. build_site_validity_round36.py  — 站点有效性分层
  5. apply_round36_calibration.py     — 偏差校准
  6. compute_round36_metrics.py       — 指标重算
  7. export_interactive_dashboard_data.py — 可视化导出
  8. check_dashboard_prediction_values_round36.py — 可视化一致性
  9. posttrain_validation_round36.py  — 全链路验证
 10. regenerate_project_report_round36.py — 项目报告

Round44 修正（无需重训时使用 run_round44_training_logic_fix.py）：
  - round41_42_unified_daytime_and_site_calibration.py（valid-only daytime source + gated site cal）
  - update_dashboard_after_training.py（dashboard 自动刷新）
  - check_dashboard_auto_update_stamp.py
  - round44_dashboard_regression_check.py

用法：
  python scripts/run_round36_full_retrain.py
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

STEPS = [
    ("[1/10] 训练前数据审计",            "scripts/pretrain_audit_round36.py"),
    ("[2/10] 完整模型训练",             "stages/03_power/train_distributed_model_v159.py"),
    ("[3/10] 构建 final 预测文件",        "scripts/build_round36_predictions.py"),
    ("[4/10] 站点有效性分层",            "scripts/build_site_validity_round36.py"),
    ("[5/10] 偏差校准",                  "scripts/apply_round36_calibration.py"),
    ("[6/10] 指标重算",                  "scripts/compute_round36_metrics.py"),
    ("[7/10] 可视化数据导出",            "scripts/export_interactive_dashboard_data.py"),
    ("[8/10] 可视化一致性检查",         "scripts/check_dashboard_prediction_values_round36.py"),
    ("[9/10] 全链路验证",               "scripts/posttrain_validation_round36.py"),
    ("[10/10] 生成项目报告",            "scripts/regenerate_project_report_round36.py"),
]


def run_step(name, script, timeout_sec=None):
    print()
    print("=" * 60)
    print(f"开始: {name}")
    print("=" * 60)
    cmd = [sys.executable, str(PROJECT_ROOT / script)]
    kwargs = {"cwd": str(PROJECT_ROOT), "check": False}
    if timeout_sec:
        kwargs["timeout"] = timeout_sec
    result = subprocess.run(cmd, **kwargs)
    print(f"\n{'[OK]' if result.returncode == 0 else '[FAIL]'} {name} — exit {result.returncode}")
    if result.stdout:
        print(result.stdout.decode("utf-8", errors="replace")[-2000:])
    if result.returncode != 0:
        print(result.stderr.decode("utf-8", errors="replace")[-1000:])
        return False
    return True


def main():
    print("=" * 60)
    print("Round36 完整重训流程")
    print("=" * 60)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"共 {len(STEPS)} 步")
    print()
    print("注意: Step 2 (完整训练) 可能需要 10-30 分钟")
    print()

    for i, (name, script) in enumerate(STEPS):
        ok = run_step(name, script)
        if not ok:
            print(f"\n[STOP] Step {i+1} 失败: {name}")
            print("请修复后重新运行本脚本。")
            print("（已成功的步骤无需重复）")
            sys.exit(1)

    print()
    print("=" * 60)
    print("Round36 完整重训流程全部完成！")
    print("=" * 60)
    print("\n请运行: python scripts/posttrain_validation_round36.py")
    print("确认全链路验证通过后，提交 Git。")


if __name__ == "__main__":
    main()
