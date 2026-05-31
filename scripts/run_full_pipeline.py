#!/usr/bin/env python3
"""
run_full_pipeline.py
====================
光伏预测流水线唯一正式训练入口。

本脚本是项目的唯一训练入口，所有正式训练必须通过本脚本执行。
禁止直接调用 roundXX 临时脚本作为主流程。

用法：
    python scripts/run_full_pipeline.py
    python scripts/run_full_pipeline.py --config configs/pipeline.yaml

配置：
    所有训练参数统一在 configs/pipeline.yaml 中管理，
    不允许在脚本中硬编码 split 日期、小时范围或预测列名。

训练链路（按顺序执行）：
    [1/9] 训练前数据审计           → pretrain_audit_round36.py
    [2/9] 分布式功率模型训练       → stages/03_power/train_distributed_model_v159.py
    [3/9] 构建最终预测文件         → build_round36_predictions.py
    [4/9] 站点有效性分层           → build_site_validity_round36.py
    [5/9] 偏差校准                 → apply_round36_calibration.py
    [6/9] 指标重算                 → compute_round36_metrics.py
    [7/9] 训练后统一收口           → post_training_finalize_outputs.py
    [8/9] 训练后逻辑审计           → scripts/posttrain_validation.py
    [9/9] Dashboard 校验           → scripts/check_dashboard_prediction_values.py

最终产物：
    output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
    output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
    output/pv_pipeline/interactive_dashboard/index.json
    output/pv_pipeline/manifest.json
"""

import argparse
import subprocess
import sys
import json
from datetime import datetime
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(cfg_path: str | None = None) -> dict:
    """加载并校验 pipeline.yaml。"""
    import yaml
    if cfg_path is None:
        cfg_path = project_root() / "configs" / "pipeline.yaml"
    else:
        cfg_path = Path(cfg_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    print(f"[CONFIG] loaded: {cfg_path}")
    print(f"  data_root:    {cfg.get('data', {}).get('data_root')}")
    print(f"  output_root:  {cfg.get('data', {}).get('output_root')}")
    print(f"  eval_hours:   {cfg.get('eval', {}).get('start_hour')}-{cfg.get('eval', {}).get('end_hour')}")
    print(f"  final_pred:   {cfg.get('prediction', {}).get('final_column')}")
    return cfg


STEPS = [
    # ── 数据准备（Stage 01）───────────────────────────────
    {
        "id": "1/11",
        "name": "站点元数据构建",
        "script": "stages/01_data/build_site_master.py",
        "required": True,
        "timeout": 60,
    },
    {
        "id": "2/11",
        "name": "数据清洗与气象插值（Stage 01）",
        "script": "stages/01_data/prepare_meteo_and_power.py",
        "required": True,
        "timeout": 300,
    },
    # ── 辐照反演与融合（Stage 02）────────────────────────
    {
        "id": "3/11",
        "name": "辐照融合（Stage 02）",
        "script": "stages/02_irradiance/train_irradiance_blend.py",
        "required": True,
        "timeout": 600,
    },
    # ── 训练前审计（原有 Step 1，现为 Step 4）────────────
    {
        "id": "4/11",
        "name": "训练前数据审计",
        "script": "scripts/pretrain_audit_round36.py",
        "required": True,
        "timeout": 120,
    },
    # ── 分布式功率模型训练（原有 Step 2，现为 Step 5）────
    {
        "id": "5/11",
        "name": "分布式功率模型训练",
        "script": "stages/03_power/train_distributed_model_v159.py",
        "required": True,
        "timeout": 1800,
    },
    # ── 后处理（原有 Step 3-9，现为 Step 6-11）──────────
    {
        "id": "6/11",
        "name": "构建最终预测文件",
        "script": "scripts/build_round36_predictions.py",
        "required": True,
        "timeout": 300,
    },
    {
        "id": "7/11",
        "name": "站点有效性分层",
        "script": "scripts/build_site_validity_round36.py",
        "required": True,
        "timeout": 120,
    },
    {
        "id": "8/11",
        "name": "偏差校准",
        "script": "scripts/apply_round36_calibration.py",
        "required": True,
        "timeout": 120,
    },
    {
        "id": "9/11",
        "name": "指标重算",
        "script": "scripts/compute_round36_metrics.py",
        "required": True,
        "timeout": 300,
    },
    {
        "id": "10/11",
        "name": "训练后统一收口",
        "script": "scripts/post_training_finalize_outputs.py",
        "required": True,
        "timeout": 600,
    },
    {
        "id": "11/11",
        "name": "训练后逻辑审计 + Dashboard 校验",
        "script": "scripts/posttrain_validation.py",
        "required": True,
        "timeout": 300,
    },
]


def run_step(step: dict, python: str, cwd: Path) -> bool:
    """运行单个步骤。失败时根据 required 决定是否停止。"""
    script = step["script"]
    full_path = cwd / script
    if not full_path.exists():
        if step["required"]:
            print(f"\n[FAIL] {step['id']} 必需步骤脚本不存在: {full_path}")
            return False
        print(f"\n[WARN] {step['id']} 可选步骤脚本不存在，跳过: {full_path}")
        return True

    print()
    print("=" * 60)
    print(f"开始: [{step['id']}] {step['name']}")
    print(f"脚本: {script}")
    print("=" * 60)

    result = subprocess.run(
        [python, str(full_path)],
        cwd=str(cwd),
        check=False,
        capture_output=True,
    )

    # 打印最后 2000 字符
    if result.stdout:
        print(result.stdout.decode("utf-8", errors="replace")[-2000:])
    if result.stderr and result.returncode != 0:
        print(result.stderr.decode("utf-8", errors="replace")[-500:])

    if result.returncode == 0:
        print(f"\n[PASS] [{step['id']}] {step['name']}")
        return True
    else:
        print(f"\n[FAIL] [{step['id']}] {step['name']} — exit {result.returncode}")
        if step["required"]:
            print("\n[STOP] 必需步骤失败。请修复后重新运行本脚本。")
            print("（已成功的步骤无需重复，脚本会按顺序跳过已完成的中间文件）")
        return not step["required"]


def write_manifest(cfg: dict, cwd: Path) -> None:
    """写出 manifest.json，记录训练元信息。"""
    import yaml
    from scripts.common_paths import output_root

    out_dir = cwd / cfg["data"]["output_root"]
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "config": str(cwd / "configs" / "pipeline.yaml"),
        "pipeline_version": "v1.0",
        "split": cfg.get("split", {}),
        "eval": cfg.get("eval", {}),
        "prediction": cfg.get("prediction", {}),
        "final_artifacts": {
            "final_predictions_pkl": str(
                out_dir / "tables" / "distributed_predictions_final_round36.pkl"
            ),
            "eval_predictions_pkl": str(
                out_dir / "tables" / "distributed_predictions_final_eval_round36.pkl"
            ),
            "hourly_nrmse_csv": str(
                out_dir / "metrics" / "round46_hourly_nrmse_consistent.csv"
            ),
            "site_metrics_csv": str(
                out_dir / "metrics" / "round36_site_metrics.csv"
            ),
            "dashboard_dir": str(
                out_dir / "interactive_dashboard"
            ),
        },
        "notes": [
            "唯一正式训练入口: python scripts/run_full_pipeline.py",
            "最终预测列: power_pred_final（不允许回退）",
            "评估口径: split=test, hour=6-19",
            "站点NRMSE分母: capacity_mw",
            "城市NRMSE分母: 参与评估站点装机容量之和",
            "所有指标均为百分比（%）",
        ],
    }

    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] manifest.json → {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="光伏预测完整训练流水线")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="pipeline.yaml 路径（默认为 configs/pipeline.yaml）",
    )
    parser.add_argument(
        "--python",
        type=str,
        default=sys.executable,
        help=f"Python 解释器（默认: {sys.executable}）",
    )
    parser.add_argument(
        "--skip",
        type=str,
        default="",
        help="跳过指定步骤 ID，逗号分隔，如 --skip 1/9,2/9",
    )
    args = parser.parse_args()

    python = args.python
    if not Path(python).exists():
        # fallback to conda
        conda_py = "/home/ac/anaconda3/bin/python3"
        if Path(conda_py).exists():
            python = conda_py
            print(f"[INFO] 使用 conda Python: {python}")

    cwd = project_root()
    print("=" * 60)
    print("光伏预测完整训练流水线 — 唯一正式入口")
    print("=" * 60)
    print(f"项目根目录: {cwd}")
    print(f"Python:     {python}")
    print(f"共 {len(STEPS)} 步")
    print()

    # 加载配置
    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        sys.exit(1)

    skip_ids = set(args.skip.split(",")) - {""}

    # 运行步骤
    for step in STEPS:
        if step["id"] in skip_ids:
            print(f"\n[SKIP] [{step['id']}] {step['name']}（用户跳过）")
            continue
        ok = run_step(step, python, cwd)
        if not ok:
            print(f"\n{'='*60}")
            print("训练流程终止")
            print("="*60)
            sys.exit(1)

    # 写出 manifest
    try:
        write_manifest(cfg, cwd)
    except Exception as e:
        print(f"\n[WARN] manifest 写出失败（不影响主流程）: {e}")

    print()
    print("=" * 60)
    print("✓ 完整训练流水线全部完成！")
    print("=" * 60)
    print()
    print("最终产物：")
    print("  - output/pv_pipeline/tables/distributed_predictions_final_round36.pkl")
    print("  - output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv")
    print("  - output/pv_pipeline/interactive_dashboard/index.json")
    print("  - output/pv_pipeline/manifest.json")
    print()
    print("启动可视化看板：")
    print("  cd /home/ac/data16t/msc/photovoltaic_forecasting_pj")
    print("  python -m http.server 8060")
    print("  访问 http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html")


if __name__ == "__main__":
    main()
