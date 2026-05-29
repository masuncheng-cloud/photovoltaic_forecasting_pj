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
  7. export_interactive_dashboard_data.py — 可视化导出（已被 Step 8 替代）
  8. check_dashboard_prediction_values_round36.py — 可视化一致性（已被 Step 8 替代）
  9. posttrain_validation_round36.py  — 全链路验证（已被 Step 8 替代）
 10. regenerate_project_report_round36.py — 项目报告（已被 Step 8 替代）
 11. post_training_finalize_outputs.py — 训练后统一收口（推荐使用）

Round44+ 统一收口链路（Step 11）：
  - 重新计算逐小时 consistent NRMSE 指标
  - 重新导出可视化 dashboard 数据
  - 检测 dashboard 是否刷新
  - 验证 dashboard stamp
  - 执行 dashboard 回归检查

用法：
  python scripts/run_round36_full_retrain.py

推荐用法（包含统一收口）：
  python scripts/run_round36_full_retrain.py
  # 训练成功后，Step 11 会自动执行
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

STEPS = [
    ("[1/11] 训练前数据审计",            "scripts/pretrain_audit_round36.py"),
    ("[2/11] 完整模型训练",             "stages/03_power/train_distributed_model_v159.py"),
    ("[3/11] 构建 final 预测文件",        "scripts/build_round36_predictions.py"),
    ("[4/11] 站点有效性分层",            "scripts/build_site_validity_round36.py"),
    ("[5/11] 偏差校准",                  "scripts/apply_round36_calibration.py"),
    ("[6/11] 指标重算",                  "scripts/compute_round36_metrics.py"),
    ("[7/11] 旧：可视化导出（已废弃，用 Step 11）", "scripts/export_interactive_dashboard_data.py"),
    ("[8/11] 旧：可视化一致性（已废弃，用 Step 11）", "scripts/check_dashboard_prediction_values_round36.py"),
    ("[9/11] 旧：全链路验证（已废弃，用 Step 11）",  "scripts/posttrain_validation_round36.py"),
    ("[10/11] 旧：项目报告（已废弃，用 Step 11）",  "scripts/regenerate_project_report_round36.py"),
    ("[11/11] 训练后统一收口",           "scripts/post_training_finalize_outputs.py"),
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
