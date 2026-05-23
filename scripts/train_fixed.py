#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复版训练流水线 (train_fixed.py)
=================================
完整修复流程，确保无测试集泄漏、可复现、可解释。

执行顺序：
  Stage 1-4: 原始训练/预测流程
  Stage 5: 重建固定预测表
  Stage 6: 时间对齐诊断
  Stage 7: 验证集小时偏差学习
  Stage 8: P0/P1 分层修正
  Stage 9: 修复后完整评估
  Stage 10: 生成模型能力报告

使用方法:
    python scripts/train_fixed.py --data-root data --output-root output/pv_pipeline
    python scripts/train_fixed.py --smoke-test  # 仅检查脚本可执行性
    python scripts/train_fixed.py --skip-training  # 仅运行修复后处理
"""
import argparse, subprocess, sys, os
from pathlib import Path
from datetime import datetime

# 优先使用项目环境的 Python，避免系统 Python 缺少依赖
_PROJECT_PYTHON = "/home/ac/anaconda3/bin/python3"
PYTHON_BIN = _PROJECT_PYTHON if os.path.exists(_PROJECT_PYTHON) else sys.executable

ROOT = Path(__file__).resolve().parents[1]

# 原始训练流水线（支持 --data-root / --output-root）
STAGES = [
    ROOT / 'stages' / '01_data' / 'build_site_master.py',
    ROOT / 'stages' / '01_data' / 'prepare_meteo_and_power.py',
    ROOT / 'stages' / '02_irradiance' / 'train_inverse_model.py',
    ROOT / 'stages' / '02_irradiance' / 'train_irradiance_blend.py',
    ROOT / 'stages' / '03_power' / 'train_distributed_model_v159.py',
    ROOT / 'stages' / '04_evaluation' / 'evaluate_layers.py',
    ROOT / 'stages' / '04_evaluation' / 'evaluate_pipeline.py',
]

# 修复后处理脚本（需要 argparse 检测）
FIX_SCRIPTS = [
    ROOT / 'scripts' / 'rebuild_fixed_predictions.py',
    ROOT / 'scripts' / 'check_gblend_time_alignment.py',
    ROOT / 'scripts' / 'fix_hourly_bias.py',
    ROOT / 'scripts' / 'apply_p0_p1_fix_v2.py',
    ROOT / 'scripts' / 'evaluate_fixed_predictions.py',
    ROOT / 'scripts' / 'apply_midday_site_nrmse_calibration.py',
    ROOT / 'scripts' / 'select_final_prediction_by_guard.py',
    ROOT / 'scripts' / 'regenerate_chinese_metrics.py',
    ROOT / 'scripts' / 'compare_with_week2_reference.py',
    ROOT / 'scripts' / 'update_project_md_metrics.py',
    ROOT / 'scripts' / 'check_pipeline_consistency.py',
]

# 关键脚本：失败必须中止
CRITICAL_SCRIPTS = {
    'rebuild_fixed_predictions.py',
    'fix_hourly_bias.py',
    'apply_p0_p1_fix_v2.py',
    'evaluate_fixed_predictions.py',
    'apply_midday_site_nrmse_calibration.py',
    'select_final_prediction_by_guard.py',
    'regenerate_chinese_metrics.py',
    'compare_with_week2_reference.py',
    'check_pipeline_consistency.py',
}

# 关键输出文件：必须存在且非空
KEY_OUTPUT_FILES = [
    'tables/distributed_predictions_fixed.pkl',
    'tables/distributed_predictions_fixed_eval.pkl',
    'tables/distributed_predictions_fixed_full.pkl',
    'tables/distributed_predictions_final_eval.pkl',
    'tables/distributed_predictions_final_full.pkl',
    'metrics/distributed_metrics_fixed.csv',
    'metrics/distributed_metrics_by_scene_fixed.csv',
    'metrics/distributed_metrics_by_hour_fixed.csv',
    'metrics/分布式光伏预测_逐小时平均NRMSE.csv',
    'metrics/分布式光伏预测_周报_整体统计.csv',
    'metrics/当前结果_vs_周二基准_整体对比.csv',
]


def supported_args(script_path):
    """检测脚本支持的参数，避免传递不支持的 --data-root"""
    content = script_path.read_text(encoding="utf-8", errors="ignore")
    return {
        "data_root": "--data-root" in content,
        "output_root": "--output-root" in content,
    }


def run_script(script_path, args, capture=True, critical=False):
    """运行单个脚本

    Args:
        script_path: 脚本路径
        args: 命令行参数
        capture: 是否捕获输出（True=捕获并打印，False=实时输出）
        critical: 是否为关键脚本，失败时中止
    """
    if not script_path.exists():
        msg = f'[SKIP] 脚本不存在: {script_path}'
        print(msg)
        if critical:
            print('[ABORT] 关键脚本不存在')
            sys.exit(1)
        return False

    # 构建命令：只给支持参数的脚本传参
    cmd = [PYTHON_BIN, str(script_path)]
    supp = supported_args(script_path)

    if supp["data_root"]:
        cmd.extend(["--data-root", str(args.data_root)])

    if supp["output_root"]:
        cmd.extend(["--output-root", str(args.output_root)])

    cmd_str = " ".join(cmd)
    print(f"\n[RUN] {cmd_str}")

    # 实时输出，避免子进程日志堆在缓冲区
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        stdout=None,
        stderr=None,
    )
    if result.returncode != 0:
        print(f'[FAIL] 脚本执行失败: {script_path.name}')
        if critical:
            print('[ABORT] 关键脚本失败，流水线中止')
            sys.exit(1)
        return False

    print(f'[OK] {script_path.name}')
    return True


def assert_output_exists(output_root):
    """检查关键输出文件是否存在且非空"""
    output_path = ROOT / output_root
    missing = []
    for rel_path in KEY_OUTPUT_FILES:
        full_path = output_path / rel_path
        if not full_path.exists():
            missing.append(str(rel_path))
        elif full_path.stat().st_size == 0:
            missing.append(f"{rel_path} (空文件)")
    
    if missing:
        print('[ERROR] 关键输出文件缺失或为空:')
        for m in missing:
            print(f'  - {m}')
        return False
    return True


def assert_scene_metrics_valid(metrics_dir):
    """检查场景指标文件是否包含必需场景"""
    import pandas as pd
    scene_path = metrics_dir / 'distributed_metrics_by_scene_fixed.csv'
    if not scene_path.exists():
        print('[ERROR] 场景指标文件不存在')
        return False
    
    df = pd.read_csv(scene_path)
    required_scenes = {'dawn', 'morning', 'midday', 'afternoon', 'dusk'}
    actual_scenes = set(df['scene'].astype(str))
    missing = required_scenes - actual_scenes
    
    if missing:
        print(f'[ERROR] 场景指标缺少场景: {sorted(missing)}')
        return False
    
    print(f'[OK] 场景指标包含所有必需场景: {sorted(required_scenes)}')
    return True


def assert_final_metrics_valid(output_root):
    """检查 final_eval 是否真实可读，并且整体结果接近周二效果。"""
    import pandas as pd
    import numpy as np

    # 确保能导入项目模块
    _src = ROOT / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

    output_path = ROOT / output_root
    final_eval = output_path / "tables" / "distributed_predictions_final_eval.pkl"

    if not final_eval.exists():
        print(f"[ERROR] final_eval 不存在: {final_eval}")
        return False

    try:
        from pv_forecasting.core.utils import safe_pickle_load
        df = safe_pickle_load(final_eval)
    except Exception as e:
        print(f"[ERROR] final_eval 读取失败: {e}")
        return False

    if df.empty:
        print("[ERROR] final_eval 为空")
        return False

    required_cols = {"time", "site_id", "power_mw", "power_pred"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"[ERROR] final_eval 缺少字段: {sorted(missing)}")
        return False

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    rows = len(df)
    n_sites = df["site_id"].nunique()
    h_min = int(df["hour"].min())
    h_max = int(df["hour"].max())
    actual = float(pd.to_numeric(df["power_mw"], errors="coerce").sum())
    pred = float(pd.to_numeric(df["power_pred"], errors="coerce").sum())
    ratio = pred / max(actual, 1e-9)
    bias = (pred - actual) / max(actual, 1e-9) * 100
    mae = float(np.mean(np.abs(df["power_pred"] - df["power_mw"])))
    rmse = float(np.sqrt(np.mean((df["power_pred"] - df["power_mw"]) ** 2)))

    # 检查 power_pred 是否与 pred_baseline 完全一致（BaselineTotal 接管检测）
    if "pred_baseline" in df.columns:
        final_pred = pd.to_numeric(df["power_pred"], errors="coerce")
        baseline = pd.to_numeric(df["pred_baseline"], errors="coerce")
        same_as_baseline = bool(np.nanmax(np.abs(final_pred - baseline)) < 1e-9)
    else:
        same_as_baseline = False

    print("[FINAL CHECK]")
    print(f"  rows={rows:,}")
    print(f"  sites={n_sites}")
    print(f"  hour_range={h_min}-{h_max}")
    print(f"  actual={actual:.2f}")
    print(f"  pred={pred:.2f}")
    print(f"  pred_actual_ratio={ratio:.4f}")
    print(f"  bias_pct={bias:.2f}%")
    print(f"  MAE={mae:.4f}")
    print(f"  RMSE={rmse:.4f}")
    print(f"  same_as_baseline={same_as_baseline}")

    ok = True
    # BaselineTotal 接管检测
    if same_as_baseline:
        print("[ERROR] final power_pred 与 pred_baseline 完全一致，说明 BaselineTotal 接管了最终结果")
        ok = False
    # 行数：TEST_END=2026-01-01 后约 67k 行（允许 60k-75k 范围）
    if not (60000 <= rows <= 75000):
        print(f"[ERROR] final_eval 行数异常: {rows:,}，应为约 67,102（允许 60k-75k）")
        ok = False
    # 站点数：固定 53 个
    if n_sites != 53:
        print(f"[ERROR] final_eval 站点数异常: {n_sites}，应为 53")
        ok = False
    if not (h_min >= 6 and h_max <= 19):
        print("[ERROR] final_eval 小时范围异常，应为 6-19")
        ok = False
    if not (0.90 <= ratio <= 0.98):
        print(f"[ERROR] pred_actual_ratio 异常 ({ratio:.4f})，应在 0.90~0.98，目标接近周二 0.9488")
        ok = False
    if abs(bias) > 10:
        print(f"[ERROR] bias 超过 10% ({bias:.2f}%)，没有恢复周二效果")
        ok = False

    # MAE/RMSE 与周二基准对比（提示性，不中止）
    WEEK2_MAE = 0.4547
    WEEK2_RMSE = 0.9676
    if mae > WEEK2_MAE * 1.20:
        print(f"[WARN] MAE 距周二基准仍偏高: {mae:.4f} > 1.20*{WEEK2_MAE:.4f}")
    if rmse > WEEK2_RMSE * 1.20:
        print(f"[WARN] RMSE 距周二基准仍偏高: {rmse:.4f} > 1.20*{WEEK2_RMSE:.4f}")

    # 早晚重点小时 NRMSE 检查
    try:
        from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

        fixed_path = output_path / "tables" / "distributed_predictions_fixed_eval.pkl"
        if fixed_path.exists():
            fixed_df = safe_pickle_load(fixed_path)
            fixed_eval = build_eval_frame(fixed_df, target_site_count=53)
            final_eval_df = build_eval_frame(df, target_site_count=53)

            fixed_h = hourly_nrmse_metrics(fixed_eval).set_index("hour")
            final_h = hourly_nrmse_metrics(final_eval_df).set_index("hour")

            for h in [6, 17, 18, 19]:
                if h not in fixed_h.index or h not in final_h.index:
                    continue
                f_site = final_h.loc[h, "site_nrmse_mean_pct"]
                b_site = fixed_h.loc[h, "site_nrmse_mean_pct"]
                f_city = final_h.loc[h, "city_nrmse_pct"]
                b_city = fixed_h.loc[h, "city_nrmse_pct"]
                if f_site > b_site * 1.05 or f_city > b_city * 1.10:
                    print(
                        f"[ERROR] h={h} final NRMSE 劣于 fixed: "
                        f"site {f_site:.2f}>{b_site:.2f}, city {f_city:.2f}>{b_city:.2f}"
                    )
                    ok = False
    except Exception as e:
        print(f"[WARN] 早晚小时 NRMSE 验收检查失败: {e}")

    return ok


def clean_stale_outputs(output_root):
    """删除旧的修复结果，防止失败后静默复用假数据"""
    stale_outputs = [
        "tables/distributed_predictions_fixed.pkl",
        "tables/distributed_predictions_fixed_eval.pkl",
        "tables/distributed_predictions_fixed_full.pkl",
        "tables/distributed_predictions_final_eval.pkl",
        "tables/distributed_predictions_final_full.pkl",
        "metrics/final_version_selection_by_hour.csv",
        "metrics/final_guard_reject_reasons.csv",
        "metrics/分布式光伏预测_逐小时平均NRMSE.csv",
        "metrics/分布式光伏预测_周报_整体统计.csv",
    ]
    root = ROOT / output_root
    for rel in stale_outputs:
        p = root / rel
        if p.exists():
            print(f"[CLEAN] remove stale output: {p}")
            p.unlink()


def main():
    parser = argparse.ArgumentParser(
        description='运行修复版光伏预测训练流水线',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/train_fixed.py --data-root data --output-root output/pv_pipeline
  python scripts/train_fixed.py --smoke-test  # 检查脚本可执行性
  python scripts/train_fixed.py --skip-training  # 仅运行修复后处理
        """
    )
    parser.add_argument('--data-root', default='data', help='数据根目录')
    parser.add_argument('--output-root', default='output/pv_pipeline', help='输出根目录')
    parser.add_argument('--skip-training', action='store_true', help='跳过训练，直接运行修复处理')
    parser.add_argument('--smoke-test', action='store_true', help='仅运行 smoke test')

    args = parser.parse_args()

    print("=" * 70)
    print("光伏预测项目 - 修复版训练流水线")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据目录: {args.data_root}")
    print(f"输出目录: {args.output_root}")
    print("=" * 70)

    # Smoke test
    if args.smoke_test:
        print("\n[SMOKE TEST] 检查脚本可执行性...")
        all_scripts = STAGES + FIX_SCRIPTS
        for script in all_scripts:
            status = '[OK]' if script.exists() else '[MISSING]'
            print(f'  {status} {script.name}')
        print("\n[SMOKE TEST] 完成")
        return

    # 清理旧结果，防止失败后静默复用
    output_root = Path(args.output_root)
    clean_stale_outputs(output_root)

    # Stage 1-4: 原始训练
    if not args.skip_training:
        print(f"\n{'='*70}")
        print("Stage 1-4: 运行原始训练流水线")
        print("=" * 70)

        for i, stage in enumerate(STAGES, 1):
            critical = stage.name in CRITICAL_SCRIPTS
            print(f"\n[Stage {i}/{len(STAGES)}] 运行 {stage.name}...")
            if not run_script(stage, args, critical=critical):
                print(f"\n[ABORT] 流水线在 Stage {i} 失败: {stage.name}")
                sys.exit(1)

    # Stage 5: 重建固定预测表（关键脚本）
    print(f"\n{'='*70}")
    print("Stage 5: 重建固定预测表")
    print("=" * 70)
    rebuild_script = ROOT / 'scripts' / 'rebuild_fixed_predictions.py'
    if not run_script(rebuild_script, args, critical=True):
        print("[ABORT] 重建预测表失败")
        sys.exit(1)

    # Stage 6-9: 修复后处理脚本
    print(f"\n{'='*70}")
    print("Stage 6-9: 运行修复后处理")
    print("=" * 70)

    for i, script in enumerate(FIX_SCRIPTS[1:], 6):  # 跳过 rebuild（已在 Stage 5 执行）
        script_name = script.name
        critical = script_name in CRITICAL_SCRIPTS
        print(f"\n[Stage {i}] 运行 {script_name}...")
        if not run_script(script, args, critical=critical):
            if critical:
                print(f"[ABORT] 关键脚本 {script_name} 失败，流水线中止")
                sys.exit(1)
            print(f"  [WARN] {script_name} 执行失败，继续下一阶段")

    # Stage 10: 输出文件检查
    print(f"\n{'='*70}")
    print("Stage 10: 输出文件检查")
    print("=" * 70)
    
    output_root = Path(args.output_root)
    metrics_dir = output_root / 'metrics'
    metrics_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = output_root / 'docs'
    docs_dir.mkdir(parents=True, exist_ok=True)

    # 检查关键文件
    if not assert_output_exists(args.output_root):
        print("[ABORT] 关键输出文件检查失败")
        sys.exit(1)
    print("[OK] 关键输出文件存在")

    # 检查场景指标
    if not assert_scene_metrics_valid(metrics_dir):
        print("[ABORT] 场景指标检查失败")
        sys.exit(1)

    if not assert_final_metrics_valid(args.output_root):
        print("[ABORT] final 预测结果验收失败")
        sys.exit(1)

    # 生成模型能力报告
    print(f"\n{'='*70}")
    print("Stage 11: 生成模型能力评估报告")
    print("=" * 70)
    report_script = ROOT / 'scripts' / 'generate_model_capability_report.py'
    if report_script.exists():
        run_script(report_script, args)
    else:
        print("[INFO] 生成模型能力报告脚本不存在，跳过")

    print(f"\n{'='*70}")
    print("修复版训练流水线完成!")
    print("=" * 70)
    print(f"\n生成的关键文件:")
    print(f"  - {args.output_root}/tables/distributed_predictions_fixed.pkl")
    print(f"  - {args.output_root}/metrics/hourly_strategy_valid_selected.csv")
    print(f"  - {args.output_root}/metrics/distributed_metrics_fixed.csv")
    print(f"  - {args.output_root}/metrics/distributed_metrics_by_scene_fixed.csv")
    print(f"  - {args.output_root}/metrics/distributed_metrics_by_hour_fixed.csv")
    print(f"  - {args.output_root}/docs/model_capability_on_existing_dataset.md")


if __name__ == '__main__':
    main()
