"""
run_round44_training_logic_fix.py
===================================
Round44 训练逻辑修正脚本（无需重新训练模型）。

此脚本在已有 Round36 模型基础上，应用训练逻辑修正和可视化刷新。
无需重新执行 steps 1-6（pretrain/训练/预测/站点分层/校准/指标），直接基于现有 PKL 文件。

执行流程：
  1. round41_42_unified_daytime_and_site_calibration.py
     — 修正 daytime_source 选择逻辑（只用 valid 集，禁止 test snooping）
     — 站点级校准增加 valid 集守门，变差自动回退
  2. round40_compare_final_prediction_metrics.py
     — 基于修正后的 PKL 重算指标
  3. round41_42_guard.py
     — 守门检查（如果失败自动回退 PKL）
  4. export_interactive_dashboard_data.py
     — 导出可视化数据（基于修正后的 PKL）
  5. update_dashboard_after_training.py
     — 检测 dashboard 是否真的刷新了
  6. check_dashboard_auto_update_stamp.py
     — 验证 stamp 文件有效
  7. round44_dashboard_regression_check.py
     — 可视化全问题回归检查
  8. posttrain_validation_round36.py
     — 全链路最终验证
  9. regenerate_project_report_round36.py
     — 项目报告更新

用法：
  python scripts/run_round44_training_logic_fix.py
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

STEPS = [
    ("[1/9] 训练逻辑修正（daytime_source + 站点校准守门）",
     "scripts/round41_42_unified_daytime_and_site_calibration.py"),
    ("[2/9] 指标重算",
     "scripts/round40_compare_final_prediction_metrics.py"),
    ("[3/9] 守门检查",
     "scripts/round41_42_guard.py"),
    ("[4/9] 可视化数据导出",
     "scripts/export_interactive_dashboard_data.py"),
    ("[5/9] Dashboard 自动刷新检测",
     "scripts/update_dashboard_after_training.py"),
    ("[6/9] Dashboard stamp 验证",
     "scripts/check_dashboard_auto_update_stamp.py"),
    ("[7/9] Dashboard 回归检查",
     "scripts/round44_dashboard_regression_check.py"),
    ("[8/9] 全链路最终验证",
     "scripts/posttrain_validation_round36.py"),
    ("[9/9] 项目报告更新",
     "scripts/regenerate_project_report_round36.py"),
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
    print("Round44 训练逻辑修正流程")
    print("（基于现有 Round36 模型，无需重新训练）")
    print("=" * 60)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"共 {len(STEPS)} 步")
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
    print("Round44 训练逻辑修正流程全部完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
