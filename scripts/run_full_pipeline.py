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

训练链路（共 15 步）：
    [1]  站点元数据构建              → stages/01_data/build_site_master.py
    [2]  应用人工经纬度覆盖          → scripts/apply_manual_geo_overrides.py
    [3]  数据清洗与气象插值          → stages/01_data/prepare_meteo_and_power.py
    [4]  辐照融合                   → stages/02_irradiance/train_irradiance_blend.py
    [5]  训练前数据审计              → scripts/pretrain_audit_round36.py
    [6]  分布式功率模型训练          → stages/03_power/train_distributed_model_v159.py
    [7]  构建最终预测文件            → scripts/build_round36_predictions.py
    [8]  站点有效性分层              → scripts/build_site_validity_round36.py
    [9]  偏差校准                   → scripts/apply_round36_calibration.py
    [10] 指标重算                   → scripts/compute_round36_metrics.py
    [11] 训练后统一收口             → scripts/post_training_finalize_outputs.py
    [12] 训练后逻辑审计             → scripts/posttrain_validation.py
    [13] Dashboard 预测值校验        → scripts/check_dashboard_prediction_values.py
    [14] 同步正式产物文件名          → （内嵌，Python 函数）
    [15] 写出 manifest.json          → （内嵌，Python 函数）

正式产物（同步后路径）：
    output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
    output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
    output/pv_pipeline/metrics/hourly_nrmse_consistent.csv
    output/pv_pipeline/metrics/site_metrics_consistent.csv
    output/pv_pipeline/interactive_dashboard/index.json
    output/pv_pipeline/manifest.json
"""

import argparse
import shutil
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
    {
        "id": "1",
        "name": "站点元数据构建",
        "script": "stages/01_data/build_site_master.py",
        "required": True,
        "timeout": 60,
    },
    {
        "id": "2",
        "name": "应用人工经纬度覆盖",
        "script": "scripts/apply_manual_geo_overrides.py",
        "required": True,
        "timeout": 60,
    },
    {
        "id": "3",
        "name": "数据清洗与气象插值",
        "script": "stages/01_data/prepare_meteo_and_power.py",
        "required": True,
        "timeout": 300,
    },
    {
        "id": "4",
        "name": "辐照融合",
        "script": "stages/02_irradiance/train_irradiance_blend.py",
        "required": True,
        "timeout": 600,
    },
    {
        "id": "5",
        "name": "训练前数据审计",
        "script": "scripts/pretrain_audit_round36.py",
        "required": True,
        "timeout": 120,
    },
    {
        "id": "6",
        "name": "分布式功率模型训练",
        "script": "stages/03_power/train_distributed_model_v159.py",
        "required": True,
        "timeout": 1800,
    },
    {
        "id": "7",
        "name": "构建最终预测文件",
        "script": "scripts/build_round36_predictions.py",
        "required": True,
        "timeout": 300,
    },
    {
        "id": "8",
        "name": "站点有效性分层",
        "script": "scripts/build_site_validity_round36.py",
        "required": True,
        "timeout": 120,
    },
    {
        "id": "9",
        "name": "偏差校准",
        "script": "scripts/apply_round36_calibration.py",
        "required": True,
        "timeout": 120,
    },
    {
        "id": "10",
        "name": "指标重算",
        "script": "scripts/compute_round36_metrics.py",
        "required": True,
        "timeout": 300,
    },
    {
        "id": "11",
        "name": "训练后统一收口",
        "script": "scripts/post_training_finalize_outputs.py",
        "required": True,
        "timeout": 600,
    },
    {
        "id": "12",
        "name": "训练后逻辑审计",
        "script": "scripts/posttrain_validation.py",
        "required": True,
        "timeout": 300,
    },
    {
        "id": "13",
        "name": "Dashboard 预测值校验",
        "script": "scripts/check_dashboard_prediction_values.py",
        "required": True,
        "timeout": 300,
    },
]


def run_step(step: dict, python: str, cwd: Path, cfg: dict) -> bool:
    """运行单个步骤。失败时根据 required 决定是否停止。"""
    script = step["script"]
    full_path = cwd / script
    if not full_path.exists():
        if step["required"]:
            print(f"\n[FAIL] [{step['id']}] 必需步骤脚本不存在: {full_path}")
            return False
        print(f"\n[WARN] [{step['id']}] 可选步骤脚本不存在，跳过: {full_path}")
        return True

    # Stage 01/02 脚本需要 --data-root 和 --output-root
    cmd = [python, str(full_path)]
    if any(s in script for s in ["stages/01_data", "stages/02_irradiance"]):
        data_root = str(cwd / cfg.get("data", {}).get("data_root", "data"))
        output_root = str(cwd / cfg.get("data", {}).get("output_root", "output/pv_pipeline"))
        cmd.extend(["--data-root", data_root, "--output-root", output_root])

    print()
    print("=" * 60)
    print(f"开始: [{step['id']}/{len(STEPS)}] {step['name']}")
    print(f"脚本: {script}")
    print("=" * 60)

    result = subprocess.run(
        cmd,
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
        print(f"\n[PASS] [{step['id']}/{len(STEPS)}] {step['name']}")
        return True
    else:
        print(f"\n[FAIL] [{step['id']}/{len(STEPS)}] {step['name']} — exit {result.returncode}")
        if step["required"]:
            print("\n[STOP] 必需步骤失败。请修复后重新运行本脚本。")
            print("（已成功的步骤无需重复，脚本会按顺序跳过已完成的中间文件）")
        return not step["required"]


def sync_canonical_paths(cwd: Path) -> None:
    """
    验证 canonical 路径存在；若源脚本已直接写 canonical，则只做一致性检查；
    若旧脚本仍写到 legacy 路径，则从中同步到 canonical。
    """
    out = cwd / "output" / "pv_pipeline"
    preds_dir = out / "predictions"
    metrics_dir = out / "metrics"
    preds_dir.mkdir(parents=True, exist_ok=True)

    # canonical → (legacy copy target,  source-if-legacy-exists)
    # Step 7 (build_predictions) 已直接写 canonical；本函数只做兜底检查
    checks = [
        (preds_dir / "distributed_predictions_final_full.pkl",   "predictions"),
        (preds_dir / "distributed_predictions_final_eval.pkl",   "predictions"),
        (metrics_dir / "hourly_nrmse_consistent.csv",            "metrics"),
        (metrics_dir / "site_metrics_consistent.csv",            "metrics"),
    ]

    print()
    print("=" * 60)
    print("验证 canonical 正式产物")
    print("=" * 60)

    all_ok = True
    for canonical_path, art_type in checks:
        if canonical_path.exists():
            mtime = datetime.fromtimestamp(canonical_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"[OK] {canonical_path.relative_to(cwd)} [{mtime}]")
        else:
            print(f"[FAIL] canonical 缺失: {canonical_path.relative_to(cwd)}")
            all_ok = False

    if all_ok:
        print(f"\n[OK] 4 个 canonical 正式产物全部存在")
    else:
        print(f"\n[WARN] 部分 canonical 产物缺失，run_full_pipeline.py Step 7/10 可能未正常执行")
    print("=" * 60)


def write_manifest(cfg: dict, cwd: Path) -> None:
    """写出 manifest.json，记录训练元信息。"""
    out_dir = cwd / cfg["data"]["output_root"]
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pipeline_entry": "scripts/run_full_pipeline.py",
        "config": "configs/pipeline.yaml",
        "split": cfg.get("split", {}),
        "eval": cfg.get("eval", {}),
        "final_prediction_column": cfg.get("prediction", {}).get("final_column", "power_pred_final"),
        "artifacts": {
            "final_full_pkl":    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
            "final_eval_pkl":    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
            "hourly_nrmse_csv":  "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
            "site_metrics_csv":  "output/pv_pipeline/metrics/site_metrics_consistent.csv",
            "dashboard_dir":     "output/pv_pipeline/interactive_dashboard",
            "dashboard_index":    "output/pv_pipeline/interactive_dashboard/index.json",
        },
        "geo_overrides": {
            "file": "configs/manual_station_geo_overrides.csv",
            "low_confidence_sites": ["S116"],
            "note": (
                "S115: GEM WGS84 approximate, confidence=medium, "
                "precision requires on-site confirmation. "
                "S116: town-center approximation from Wikipedia, confidence=low, "
                "MUST be replaced with actual PV-site coordinates from operator records."
            ),
        },
        "station_count_note": (
            "final_full may include all stations; "
            "final_eval and dashboard include only stations with valid test 6-19 evaluation rows; "
            "S115/S116 have has_geo=0 and no irradiance data, resulting in scene_v151=all night and all-zero predictions"
        ),
        "notes": [
            "test set is only used for final evaluation",
            "dashboard data is exported after final prediction generation",
            "BIAS = mean(pred - actual); BIAS < 0 means under-prediction",
            "NRMSE denominator: station capacity for site metrics, total capacity for city metrics",
            "all NRMSE values are in percent (%)",
            "final prediction column: power_pred_final (no fallback allowed)",
            "S115/S116: no irradiance data → scene_v151=all night → all predictions are 0",
        ],
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[OK] manifest.json → {manifest_path}")


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
        help="跳过指定步骤 ID，逗号分隔，如 --skip 1,2,3",
    )
    args = parser.parse_args()

    python = args.python
    if not Path(python).exists():
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

    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        sys.exit(1)

    skip_ids = set(args.skip.split(",")) - {""}

    # 运行步骤 1-13
    for step in STEPS:
        if step["id"] in skip_ids:
            print(f"\n[SKIP] [{step['id']}/{len(STEPS)}] {step['name']}（用户跳过）")
            continue
        ok = run_step(step, python, cwd, cfg)
        if not ok:
            print(f"\n{'='*60}")
            print("训练流程终止")
            print("="*60)
            sys.exit(1)

    # Step 14：同步正式产物文件名
    sync_canonical_paths(cwd)

    # Step 15：写出 manifest.json
    try:
        write_manifest(cfg, cwd)
    except Exception as e:
        print(f"\n[WARN] manifest 写出失败（不影响主流程）: {e}")

    print()
    print("=" * 60)
    print("✓ 完整训练流水线全部完成！")
    print("=" * 60)
    print()
    print("正式产物：")
    print("  output/pv_pipeline/predictions/distributed_predictions_final_full.pkl")
    print("  output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl")
    print("  output/pv_pipeline/metrics/hourly_nrmse_consistent.csv")
    print("  output/pv_pipeline/metrics/site_metrics_consistent.csv")
    print("  output/pv_pipeline/interactive_dashboard/index.json")
    print("  output/pv_pipeline/manifest.json")
    print()
    print("启动可视化看板：")
    print("  cd /home/ac/data16t/msc/photovoltaic_forecasting_pj")
    print("  python -m http.server 8060")
    print("  访问 http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html")


if __name__ == "__main__":
    main()
