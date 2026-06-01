#!/usr/bin/env python3
"""
run_full_pipeline.py
====================
光伏预测流水线唯一正式训练入口。

本脚本是项目的唯一训练入口，所有正式训练必须通过本脚本执行。
禁止直接调用 roundXX 临时脚本作为主流程。

执行模式：
    full          从 Stage 01 到最终 dashboard 全部执行（默认）
    geo-refresh   只改经纬度或地理特征时：重建站点元数据 + 预测 + 评估 + dashboard
    train-only    从训练表开始训练模型，不重跑原始清洗
    eval-only     使用已有预测 pkl 重算指标和报告
    dashboard-only 使用 canonical pkl/csv 重新导出可视化
    audit-only    只跑 posttrain/dashboard/链路审计

用法：
    python scripts/run_full_pipeline.py --mode full
    python scripts/run_full_pipeline.py --mode dashboard-only
    python scripts/run_full_pipeline.py --mode full --force  # 强制重跑（忽略缓存）

训练链路（共 13 步 + 2 内嵌步骤）：
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
    [14] 同步正式产物文件名          → （内嵌）
    [15] 写出 manifest.json          → （内嵌）

正式产物（同步后路径）：
    output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
    output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
    output/pv_pipeline/metrics/hourly_nrmse_consistent.csv
    output/pv_pipeline/metrics/site_metrics_consistent.csv
    output/pv_pipeline/interactive_dashboard/index.json
    output/pv_pipeline/manifest.json
"""

import argparse
import hashlib
import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter


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


# ─── Timing infrastructure ────────────────────────────────────────────────────

timing_rows = []


@contextmanager
def timed_step(name: str, outputs: list[str] | None = None):
    """统一步骤计时器。"""
    start = perf_counter()
    wall_start = datetime.now().isoformat(timespec="seconds")
    print(f"\n[STEP START] {name} @ {wall_start}")
    status = "PASS"
    error = ""
    try:
        yield
    except Exception as exc:
        status = "FAIL"
        error = repr(exc)
        raise
    finally:
        sec = perf_counter() - start
        row = {
            "step": name,
            "status": status,
            "seconds": round(sec, 3),
            "minutes": round(sec / 60, 3),
            "started_at": wall_start,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": error,
            "outputs": outputs or [],
        }
        timing_rows.append(row)
        icon = "✓" if status == "PASS" else "✗"
        print(f"[STEP END] [{icon} {status}] {name}: {sec:.1f}s")


def write_timing_logs(out_dir: Path, mode: str):
    """写出 timing 日志。"""
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    import csv as csvmod
    csv_path = logs_dir / "pipeline_timing_latest.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csvmod.DictWriter(f, fieldnames=["step", "status", "seconds", "minutes", "started_at", "finished_at", "error", "outputs"])
        writer.writeheader()
        writer.writerows(timing_rows)
    print(f"\n[OK] timing CSV → {csv_path}")

    # JSON
    json_path = logs_dir / "pipeline_timing_latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "mode": mode,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_seconds": round(sum(r["seconds"] for r in timing_rows), 3),
            "total_minutes": round(sum(r["seconds"] for r in timing_rows) / 60, 3),
            "steps": timing_rows,
            "top_5_by_seconds": sorted(timing_rows, key=lambda r: r["seconds"], reverse=True)[:5],
        }, f, ensure_ascii=False, indent=2)
    print(f"[OK] timing JSON → {json_path}")

    # Top 5
    top5 = sorted(timing_rows, key=lambda r: r["seconds"], reverse=True)[:5]
    print(f"\n耗时 Top 5 步骤:")
    for i, r in enumerate(top5, 1):
        icon = "✓" if r["status"] == "PASS" else "✗"
        print(f"  {i}. [{icon} {r['step']}] {r['seconds']:.1f}s ({r['minutes']:.2f}min)")


# ─── Step definitions ─────────────────────────────────────────────────────────

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
        "desc": "11a 重算指标, 11b 导出看板, 11c 看板stamp, 11d 看板回归",
        "script": "scripts/post_training_finalize_outputs.py",
        "subs": [
            {"id": "11a", "name": "recompute_hourly_nrmse_consistent", "desc": "重算逐小时 NRMSE 指标"},
            {"id": "11b", "name": "export_interactive_dashboard_data", "desc": "导出可视化看板数据"},
            {"id": "11c", "name": "dashboard_stamp_check", "desc": "看板新鲜度stamp检查"},
            {"id": "11d", "name": "dashboard_regression_check", "desc": "看板回归检查"},
        ],
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


# ─── Mode definitions ──────────────────────────────────────────────────────────

MODES = {
    "full": {
        "desc": "从 Stage 01 到最终 dashboard 全部执行",
        "steps": [s["id"] for s in STEPS],
        "run_step14": True,
        "run_step15": True,
    },
    "geo-refresh": {
        "desc": "只改经纬度或地理特征：重建站点元数据 + 辐照 + 预测 + 评估 + dashboard",
        "steps": ["1", "2", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"],
        "run_step14": True,
        "run_step15": True,
    },
    "train-only": {
        "desc": "从训练表开始训练模型，不重跑原始清洗",
        "steps": ["5", "6", "7", "8", "9", "10", "11", "12", "13"],
        "run_step14": True,
        "run_step15": True,
    },
    "eval-only": {
        "desc": "使用已有预测 pkl 重算指标和报告",
        "steps": ["10", "11", "12", "13"],
        "run_step14": False,
        "run_step15": False,
    },
    "dashboard-only": {
        "desc": "使用 canonical pkl/csv 重新导出可视化",
        "steps": ["11", "12", "13"],
        "run_step14": False,
        "run_step15": False,
    },
    "audit-only": {
        "desc": "只跑 posttrain/dashboard/链路审计",
        "steps": ["12", "13"],
        "run_step14": False,
        "run_step15": False,
    },
    "round64-experiment": {
        "desc": "Round64 安全残差融合实验：基线复核 -> 权重融合 -> test评估 -> 决策 -> 导出候选dashboard",
        "steps": [],
        "run_step14": False,
        "run_step15": False,
    },
    "round70-performance-upgrade": {
        "desc": "Round70 训练样本口径重构与状态专家模型性能提升",
        "steps": [],
        "run_step14": False,
        "run_step15": False,
    },
    "round71-conservative-residual": {
        "desc": "Round71 季节适配与保守残差提升，先诊断后训练",
        "steps": [],
        "run_step14": False,
        "run_step15": False,
    },
    "round72-consistent-base-residual": {
        "desc": "Round72 重建全历史一致基线并重新训练残差模型",
        "steps": [],
        "run_step14": False,
        "run_step15": False,
    },
    "round73-training-framework-reset": {
        "desc": "Round73 回退最优版本并重构训练框架",
        "steps": [],
        "run_step14": False,
        "run_step15": False,
    },
}


def check_upstream_dependencies(mode: str, cwd: Path) -> bool:
    """
    检查当前模式所需的上游文件是否存在。
    如果上游文件不存在，必须报错并提示使用 --mode full。
    """
    out = cwd / "output" / "pv_pipeline"
    preds_dir = out / "predictions"

    missing = []
    canonical_files = [
        preds_dir / "distributed_predictions_final_full.pkl",
        preds_dir / "distributed_predictions_final_eval.pkl",
        out / "metrics" / "hourly_nrmse_consistent.csv",
        out / "metrics" / "site_metrics_consistent.csv",
    ]

    if mode in ("train-only", "eval-only", "dashboard-only", "audit-only"):
        # 需要有 final pkl
        if not (preds_dir / "distributed_predictions_final_full.pkl").exists():
            missing.append("output/pv_pipeline/predictions/distributed_predictions_final_full.pkl")
    if mode in ("eval-only", "dashboard-only", "audit-only"):
        # 需要有指标文件
        for f in canonical_files[2:]:
            if not f.exists():
                missing.append(str(f.relative_to(cwd)))

    if missing:
        print(f"\n[FAIL] {mode} 模式所需上游文件缺失:")
        for p in missing:
            print(f"  - {p}")
        print(f"\n请使用 --mode full 重新生成所有上游文件。")
        return False
    return True


# ─── Step execution ───────────────────────────────────────────────────────────

def run_step(step: dict, python: str, cwd: Path, cfg: dict,
             cache=None) -> bool:
    """运行单个步骤（带缓存检查和计时）。"""
    script = step["script"]
    full_path = cwd / script
    step_id = step["id"]
    step_name = step["name"]

    if not full_path.exists():
        if step["required"]:
            print(f"\n[FAIL] [{step_id}] 必需步骤脚本不存在: {full_path}")
            return False
        print(f"\n[WARN] [{step_id}] 可选步骤脚本不存在，跳过: {full_path}")
        return True

    # Step 11 有 4 个独立子步骤，各自计时
    if "subs" in step:
        return run_step_with_subs(step, python, cwd, cfg)

    # Stage 01/02 脚本需要 --data-root 和 --output-root
    cmd = [python, str(full_path)]
    if any(s in script for s in ["stages/01_data", "stages/02_irradiance"]):
        data_root = str(cwd / cfg.get("data", {}).get("data_root", "data"))
        output_root = str(cwd / cfg.get("data", {}).get("output_root", "output/pv_pipeline"))
        cmd.extend(["--data-root", data_root, "--output-root", output_root])

    with timed_step(f"[{step_id}] {step_name}", outputs=[str(full_path)]):
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            capture_output=True,
        )

        if result.stdout:
            print(result.stdout.decode("utf-8", errors="replace")[-2000:])
        if result.stderr and result.returncode != 0:
            print(result.stderr.decode("utf-8", errors="replace")[-500:])

        if result.returncode == 0:
            print(f"\n[PASS] [{step_id}] {step_name}")
            return True
        else:
            print(f"\n[FAIL] [{step_id}] {step_name} — exit {result.returncode}")
            if step["required"]:
                print("\n[STOP] 必需步骤失败。请修复后重新运行本脚本。")
            return not step["required"]


def run_step_with_subs(step: dict, python: str, cwd: Path, cfg: dict) -> bool:
    """Step 11：按子步骤执行，每个子步骤独立计时。"""
    step_id = step["id"]
    step_name = step["name"]
    subs = step["subs"]

    print(f"\n{'='*60}")
    print(f"[STEP START] {step_id} {step_name}")
    print(f"  子步骤: {[s['id'] for s in subs]}")
    print(f"{'='*60}")

    all_ok = True
    for sub in subs:
        sub_id = sub["id"]
        sub_name = sub["name"]
        sub_desc = sub.get("desc", "")
        sub_script = _find_sub_script(sub_name, cwd)
        if sub_script is None:
            print(f"\n[WARN] [{sub_id}] {sub_name} — 脚本不存在，跳过")
            continue

        cmd = [python, str(sub_script)]
        data_root = str(cwd / cfg.get("data", {}).get("data_root", "data"))
        output_root = str(cwd / cfg.get("data", {}).get("output_root", "output/pv_pipeline"))
        if "stages" in sub_script.name or "irradiance" in str(sub_script):
            cmd.extend(["--data-root", data_root, "--output-root", output_root])

        with timed_step(f"[{sub_id}] {sub_name} ({sub_desc})", outputs=[str(sub_script)]):
            result = subprocess.run(cmd, cwd=str(cwd), check=False, capture_output=True)
            if result.stdout:
                print(result.stdout.decode("utf-8", errors="replace")[-1000:])
            if result.stderr and result.returncode != 0:
                print(result.stderr.decode("utf-8", errors="replace")[-500:])

            if result.returncode == 0:
                print(f"\n[PASS] [{sub_id}] {sub_name}")
            else:
                print(f"\n[FAIL] [{sub_id}] {sub_name} — exit {result.returncode}")
                all_ok = False

    print(f"\n{'='*60}")
    icon = "✓" if all_ok else "✗"
    print(f"[STEP END] [{icon} {'PASS' if all_ok else 'FAIL'}] {step_id} {step_name}")
    print(f"{'='*60}")
    return all_ok


def _find_sub_script(sub_name: str, cwd: Path) -> Path | None:
    """根据子步骤名称找到对应的脚本路径。"""
    candidates = {
        "recompute_hourly_nrmse_consistent": [
            cwd / "scripts" / "compute_hourly_nrmse_consistent.py",
            cwd / "scripts" / "round46_recompute_hourly_nrmse_consistent.py",
        ],
        "export_interactive_dashboard_data": [
            cwd / "scripts" / "export_interactive_dashboard_data.py",
        ],
        "update_dashboard_after_training": [
            cwd / "scripts" / "update_dashboard_after_training.py",
        ],
        "check_dashboard_auto_update_stamp": [
            cwd / "scripts" / "check_dashboard_auto_update_stamp.py",
        ],
        "check_dashboard_data_freshness": [
            cwd / "scripts" / "check_dashboard_data_freshness.py",
        ],
        "dashboard_regression_check": [
            cwd / "scripts" / "round44_dashboard_regression_check.py",
            cwd / "scripts" / "dashboard_regression_check.py",
        ],
    }
    for path in candidates.get(sub_name, []):
        if path.exists():
            return path
    return None


# ─── Post-steps ───────────────────────────────────────────────────────────────

def sync_canonical_paths(cwd: Path) -> None:
    """验证 canonical 路径存在；若源脚本已直接写 canonical，则只做一致性检查。"""
    out = cwd / "output" / "pv_pipeline"
    preds_dir = out / "predictions"
    metrics_dir = out / "metrics"
    preds_dir.mkdir(parents=True, exist_ok=True)

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


def file_sha256(path: Path) -> str:
    """计算文件的 SHA256 哈希。"""
    if not path.exists():
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(cfg: dict, cwd: Path) -> None:
    """写出 manifest.json，记录训练元信息和 artifact hash。"""
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
        "artifact_hashes": {
            "final_full_pkl_sha256":   file_sha256(out_dir / "predictions" / "distributed_predictions_final_full.pkl"),
            "final_eval_pkl_sha256":   file_sha256(out_dir / "predictions" / "distributed_predictions_final_eval.pkl"),
            "hourly_nrmse_csv_sha256": file_sha256(out_dir / "metrics" / "hourly_nrmse_consistent.csv"),
            "site_metrics_csv_sha256": file_sha256(out_dir / "metrics" / "site_metrics_consistent.csv"),
            "dashboard_index_sha256":   file_sha256(out_dir / "interactive_dashboard" / "index.json"),
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
            "S115/S116 have has_geo=0 and no irradiance data; "
            "scene_v151 all-night in 'all' scope is normal (includes nighttime hours); "
            "test 10-14 daytime window should have non-night scenes per GEO5 checks"
        ),
        "notes": [
            "test set is only used for final evaluation",
            "dashboard data is exported after final prediction generation",
            "BIAS = mean(pred - actual); BIAS < 0 means under-prediction",
            "NRMSE denominator: station capacity for site metrics, total capacity for city metrics",
            "all NRMSE values are in percent (%)",
            "final prediction column: power_pred_final (no fallback allowed)",
            "Round56 修正说明：S115/S116 scene_v151=all-night in full scope（含夜间）为正常；"
            "test 10-14 评估窗口以 GEO5 检查为准，链路正常。",
        ],
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[OK] manifest.json → {manifest_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="光伏预测训练流水线 — 唯一正式入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
执行模式：
  full           从 Stage 01 到最终 dashboard 全部执行（默认）
  geo-refresh    只改经纬度或地理特征时
  train-only     从训练表开始训练，不重跑原始清洗
  eval-only      使用已有预测 pkl 重算指标和报告
  dashboard-only 只更新可视化（不重训模型）
  audit-only     只做验证和审计（不重训模型）

示例：
  python scripts/run_full_pipeline.py --mode full --force
  python scripts/run_full_pipeline.py --mode dashboard-only
  python scripts/run_full_pipeline.py --mode eval-only
  python scripts/run_full_pipeline.py --mode audit-only
  python scripts/run_full_pipeline.py --mode geo-refresh
""",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="pipeline.yaml 路径（默认为 configs/pipeline.yaml）",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="full",
        choices=list(MODES.keys()),
        help="执行模式（默认: full）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新执行所有步骤（忽略缓存）",
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
    mode = args.mode
    mode_info = MODES[mode]

    print("=" * 60)
    print("光伏预测训练流水线")
    print(f"执行模式: {mode} — {mode_info['desc']}")
    print("=" * 60)
    print(f"项目根目录: {cwd}")
    print(f"Python:     {python}")
    print(f"Force:      {args.force}")
    print()

    # 检查上游依赖
    if not check_upstream_dependencies(mode, cwd):
        sys.exit(1)

    # Special handling for round64-experiment: runs outside the normal pipeline steps
    if mode == "round64-experiment":
        print()
        print("=" * 60)
        print("Round64 实验模式（独立脚本调用）")
        print("=" * 60)
        round64_scripts = [
            ("基线复核", "scripts/verify_round61_baseline.py"),
            ("安全残差融合构建", "scripts/build_round64_safe_residual_blend.py"),
            ("Test 集评估", "scripts/evaluate_round64_safe_blend.py"),
            ("最终决策", "scripts/select_round64_final_decision.py"),
        ]
        for label, script in round64_scripts:
            print(f"\n>>> [{label}] {script}")
            ret = subprocess.run(
                [python, str(cwd / script)],
                cwd=str(cwd),
            )
            if ret.returncode != 0:
                print(f"\n[FAIL] {label} 失败，退出")
                sys.exit(1)
        print()
        print("=" * 60)
        print("Round64 实验完成！")
        print("=" * 60)
        sys.exit(0)

    # Special handling for round70-performance-upgrade
    if mode == "round70-performance-upgrade":
        print()
        print("=" * 60)
        print("Round70 训练样本口径重构与状态专家模型性能提升")
        print("=" * 60)
        round70_scripts = [
            ("Step 1: 构建训练表", "scripts/build_round70_training_table.py"),
            ("Step 2: 发电状态分类模型", "scripts/train_round70_active_state_model.py"),
            ("Step 3: 10-14点bias约束模型", "scripts/train_round70_noon_bias_constrained_model.py"),
            ("Step 4: 高误差站点专家模型", "scripts/train_round70_high_error_site_expert.py"),
            ("Step 5: 候选有效性检查", "scripts/check_candidate_prediction_diff.py"),
            ("Step 6: 最终候选选择与safe blend", "scripts/select_round70_final_candidate.py"),
            ("Step 7: Test集评估", "scripts/evaluate_round70_candidate_on_test.py"),
        ]
        for label, script in round70_scripts:
            print(f"\n>>> [{label}] {script}")
            ret = subprocess.run(
                [python, str(cwd / script)],
                cwd=str(cwd),
            )
            if ret.returncode != 0:
                print(f"\n[WARN] [{label}] 失败 (exit {ret.returncode})，继续执行后续步骤")
        print()
        print("=" * 60)
        print("Round70 性能提升实验完成！")
        print("=" * 60)
        print("\n主要输出文件：")
        print("  output/pv_pipeline/round70/round70_training_distribution_by_split.csv")
        print("  output/pv_pipeline/round70/round70_candidate_diff_check.csv")
        print("  output/pv_pipeline/round70/round70_active_state_valid_metrics.csv")
        print("  output/pv_pipeline/round70/round70_valid_candidate_compare.csv")
        print("  output/pv_pipeline/round70/round70_candidate_decision.json")
        print("  output/pv_pipeline/round70/round70_test_overall_compare.csv")
        print("  docs/Round70_训练样本口径重构与状态专家模型性能提升报告.md")
        sys.exit(0)

    # Special handling for round71-conservative-residual
    if mode == "round71-conservative-residual":
        print()
        print("=" * 60)
        print("Round71 季节适配与保守残差提升（先诊断后训练）")
        print("=" * 60)
        round71_scripts = [
            ("Step 1: 诊断", "scripts/diagnose_round71_drift_and_error_sources.py"),
            ("Step 2: 构建训练表", "scripts/build_round71_residual_training_table.py"),
            ("Step 3: 训练候选", "scripts/train_round71_conservative_residual_candidates.py"),
            ("Step 4: 候选差异检查", "scripts/check_candidate_prediction_diff.py"),
            ("Step 5: 多窗口选择", "scripts/select_round71_candidate_multi_window.py"),
            ("Step 6: Test评估", "scripts/evaluate_round71_candidate_on_test.py"),
        ]
        for label, script in round71_scripts:
            print(f"\n>>> [{label}] {script}")
            ret = subprocess.run(
                [python, str(cwd / script)],
                cwd=str(cwd),
            )
            if ret.returncode != 0:
                print(f"\n[WARN] [{label}] 失败 (exit {ret.returncode})，继续执行后续步骤")
        print()
        print("=" * 60)
        print("Round71 实验完成！")
        print("=" * 60)
        print("\n主要输出文件：")
        print("  output/pv_pipeline/round71/round71_diagnosis_summary.json")
        print("  output/pv_pipeline/round71/round71_candidate_decision.json")
        print("  output/pv_pipeline/round71/round71_test_overall_compare.csv")
        print("  docs/Round71_季节适配与保守残差提升报告.md")
        sys.exit(0)

    # Special handling for round72-consistent-base-residual
    if mode == "round72-consistent-base-residual":
        print()
        print("=" * 60)
        print("Round72 重建全历史一致基线并重新训练残差模型")
        print("=" * 60)
        round72_scripts = [
            ("Step1: 审计预测列", "scripts/audit_prediction_column_consistency.py"),
            ("Step2: 构建一致基线", "scripts/build_round72_consistent_base_prediction.py"),
            ("Step3: 校验一致基线", "scripts/validate_round72_consistent_base.py"),
            ("Step4: 训练残差候选", "scripts/train_round72_residual_on_consistent_base.py"),
            ("Step5: 多窗口选择", "scripts/select_round72_candidate_multi_window.py"),
            ("Step6: Test评估", "scripts/evaluate_round72_candidate_on_test.py"),
        ]
        for label, script in round72_scripts:
            print(f"\n>>> [{label}] {script}")
            ret = subprocess.run(
                [python, str(cwd / script)],
                cwd=str(cwd),
            )
            if ret.returncode != 0:
                print(f"\n[WARN] [{label}] 失败 (exit {ret.returncode})，继续执行后续步骤")
        print()
        print("=" * 60)
        print("Round72 实验完成！")
        print("=" * 60)
        print("\n主要输出文件：")
        print("  output/pv_pipeline/round72/round72_prediction_column_audit_summary.json")
        print("  output/pv_pipeline/round72/round72_consistent_base_predictions.pkl")
        print("  output/pv_pipeline/round72/round72_consistent_base_validation.json")
        print("  output/pv_pipeline/round72/round72_candidate_decision.json")
        print("  output/pv_pipeline/round72/round72_test_overall_compare.csv")
        print("  docs/Round72_重建全历史一致基线并重新训练残差模型报告.md")
        sys.exit(0)

    # Special handling for round73-training-framework-reset
    if mode == "round73-training-framework-reset":
        print()
        print("=" * 60)
        print("Round73 回退最优版本并重构训练框架")
        print("=" * 60)
        round73_scripts = [
            ("Step1: 校验基线", "scripts/verify_current_best_round68.py"),
            ("Step2: 归档失败实验", "scripts/archive_failed_round_experiments.py"),
            ("Step3: 构建回测数据集", "scripts/build_training_v2_backtest_dataset.py"),
            ("Step4: 训练候选", "scripts/train_round73_backtest_candidates.py"),
            ("Step5: 回测选择", "scripts/select_round73_candidate_by_backtest.py"),
            ("Step6: Test评估", "scripts/evaluate_round73_candidate_on_test.py"),
        ]
        for label, script in round73_scripts:
            print(f"\n>>> [{label}] {script}")
            ret = subprocess.run([python, str(cwd / script)], cwd=str(cwd))
            if ret.returncode != 0:
                print(f"\n[WARN] [{label}] 失败 (exit {ret.returncode})，继续")
        print()
        print("=" * 60)
        print("Round73 完成！")
        print("=" * 60)
        print("\n主要输出文件：")
        print("  output/pv_pipeline/round73/round73_current_best_verify.json")
        print("  output/pv_pipeline/round73/round73_candidate_decision.json")
        print("  output/pv_pipeline/round73/round73_test_overall_compare.csv")
        print("  docs/Round73_回退最优版本并重构训练框架提升报告.md")
        sys.exit(0)

    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        sys.exit(1)

    out_dir = cwd / cfg["data"]["output_root"]

    # 初始化缓存
    try:
        from scripts.pipeline_cache import PipelineCache
        cache = PipelineCache(force=args.force)
    except Exception:
        cache = None

    skip_ids = set(args.skip.split(",")) - {""}
    step_ids_to_run = set(mode_info["steps"])

    # 运行步骤
    for step in STEPS:
        step_id = step["id"]
        if step_id not in step_ids_to_run:
            print(f"\n[SKIP] [{step_id}] {step['name']}（{mode} 模式跳过）")
            continue
        if step_id in skip_ids:
            print(f"\n[SKIP] [{step_id}] {step['name']}（用户跳过）")
            continue

        ok = run_step(step, python, cwd, cfg, cache)
        if not ok:
            print(f"\n{'='*60}")
            print("训练流程终止")
            print("="*60)
            sys.exit(1)

    # Step 14：同步正式产物文件名
    if mode_info.get("run_step14", True):
        with timed_step("[14] 同步 canonical 产物"):
            sync_canonical_paths(cwd)

    # Step 15：写出 manifest.json
    if mode_info.get("run_step15", True):
        with timed_step("[15] 写出 manifest.json"):
            try:
                write_manifest(cfg, cwd)
            except Exception as e:
                print(f"\n[WARN] manifest 写出失败（不影响主流程）: {e}")

    # 写出 timing 日志
    write_timing_logs(out_dir, mode)

    print()
    print("=" * 60)
    print(f"✓ 训练流水线全部完成！模式: {mode}")
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
