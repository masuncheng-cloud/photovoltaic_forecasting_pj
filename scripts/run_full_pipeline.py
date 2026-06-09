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

训练链路（共 14 步 + 2 内嵌步骤）：
    [1]  站点元数据构建              → stages/01_data/build_site_master.py
    [2]  应用人工经纬度覆盖          → scripts/apply_manual_geo_overrides.py
    [3]  数据清洗与气象插值          → stages/01_data/prepare_meteo_and_power.py
    [3b] 辐照反演                   → stages/02_irradiance/train_inverse_model.py
    [4]  辐照融合                   → stages/02_irradiance/train_irradiance_blend.py
    [5]  训练前数据审计              → scripts/pretrain_audit.py
    [6]  分布式功率模型训练          → stages/03_power/train_distributed_model_v159.py
    [7]  构建最终预测文件            → scripts/build_final_predictions.py
    [8]  站点有效性分层              → scripts/build_site_validity.py
    [9]  偏差校准                   → scripts/apply_final_calibration.py
    [10] 指标重算                   → scripts/compute_final_metrics.py
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
import os
import subprocess
import sys
import time
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


# ─── Progress tracking ─────────────────────────────────────────────────────────

progress_state = {
    "mode": "",
    "total_steps": 0,
    "current_index": 0,
    "current_step": "",
    "current_status": "INIT",
    "started_at": "",
    "updated_at": "",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def update_progress(out_dir: Path, *, mode: str, total_steps: int,
                    current_index: int, current_step: str,
                    current_status: str) -> None:
    """写出实时训练状态 JSON，供 Cursor 或外部工具查看。终端输出已移除外层伪进度条。"""
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    progress_state.update({
        "mode": mode,
        "total_steps": total_steps,
        "current_index": current_index,
        "current_step": current_step,
        "current_status": current_status,
        "updated_at": _now(),
    })
    if not progress_state.get("started_at"):
        progress_state["started_at"] = _now()

    percent = 0 if total_steps <= 0 else round(current_index / total_steps * 100, 1)
    progress_state["percent"] = percent

    bar_len = 28
    filled = int(bar_len * percent / 100)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
    line = (
        f"[{bar}] {percent:5.1f}% "
        f"({current_index}/{total_steps}) "
        f"{current_status}: {current_step}"
    )
    progress_state["bar"] = line

    (logs_dir / "pipeline_progress_latest.json").write_text(
        json.dumps(progress_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (logs_dir / "pipeline_progress_latest.txt").write_text(line + "\n", encoding="utf-8")


def run_subprocess_streaming(cmd: list[str], cwd: Path, log_path: Path | None = None,
                              *, progress_mode: str = "tqdm") -> int:
    """
    Run a subprocess with streaming output.

    When PV_PROGRESS_MODE=tqdm, stdout/stderr are inherited directly so that
    tqdm's single-line refresh works correctly.  Log output is still captured
    to disk when log_path is given.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PV_PROGRESS", "1")
    env.setdefault("PV_PROGRESS_MODE", progress_mode)
    env.setdefault("PV_MODEL_VERBOSE", "0")

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
    else:
        log_file = None

    try:
        print("[CMD] " + " ".join(cmd), flush=True)

        if progress_mode == "tqdm":
            # Inherit stdout/stderr so tqdm can refresh in-place on the terminal.
            # PIPE would break tqdm's \r carriage-return mechanism.
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
            )
            returncode = proc.wait()
            if log_file is not None and returncode == 0:
                log_file.write(f"[CMD] {' '.join(cmd)}  -> exit {returncode}\n")
                log_file.flush()
            return returncode

        # Log mode: capture stdout line by line for display and file logging.
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            if log_file is not None:
                log_file.write(line)
                log_file.flush()
        return proc.wait()
    finally:
        if log_file is not None:
            log_file.close()


# ─── Step definitions ─────────────────────────────────────────────────────────

STEPS = [
    {
        "id": "1",
        "name": "站点元数据构建",
        "script": "stages/01_data/build_site_master.py",
        "required": True,
        "timeout": 60,
        "needs_data_root": True,
        "needs_output_root": True,
    },
    {
        "id": "2",
        "name": "应用人工经纬度覆盖",
        "script": "scripts/apply_manual_geo_overrides.py",
        "required": True,
        "timeout": 60,
        "needs_output_root": True,
    },
    {
        "id": "3",
        "name": "数据清洗与气象插值",
        "script": "stages/01_data/prepare_meteo_and_power.py",
        "required": True,
        "timeout": 300,
        "needs_data_root": True,
        "needs_output_root": True,
    },
    {
        "id": "3b",
        "name": "辐照反演",
        "script": "stages/02_irradiance/train_inverse_model.py",
        "required": True,
        "timeout": 900,
        "needs_data_root": True,
        "needs_output_root": True,
    },
    {
        "id": "4",
        "name": "辐照融合",
        "script": "stages/02_irradiance/train_irradiance_blend.py",
        "required": True,
        "timeout": 600,
        "needs_data_root": True,
        "needs_output_root": True,
    },
    {
        "id": "5",
        "name": "训练前数据审计",
        "script": "scripts/pretrain_audit.py",
        "required": True,
        "timeout": 120,
        "needs_output_root": True,
    },
    {
        "id": "6",
        "name": "分布式功率模型训练",
        "script": "stages/03_power/train_distributed_model_v159.py",
        "required": True,
        "timeout": 1800,
        "needs_data_root": True,
        "needs_output_root": True,
    },
    {
        "id": "7",
        "name": "构建最终预测文件",
        "script": "scripts/build_final_predictions.py",
        "required": True,
        "timeout": 300,
        "needs_output_root": True,
    },
    {
        "id": "8",
        "name": "站点有效性分层",
        "script": "scripts/build_site_validity.py",
        "required": True,
        "timeout": 120,
        "needs_output_root": True,
    },
    {
        "id": "9",
        "name": "偏差校准",
        "script": "scripts/apply_final_calibration.py",
        "required": True,
        "timeout": 120,
        "needs_output_root": True,
    },
    {
        "id": "10",
        "name": "指标重算",
        "script": "scripts/compute_final_metrics.py",
        "required": True,
        "timeout": 300,
        "needs_output_root": True,
    },
    {
        "id": "11",
        "name": "训练后统一收口",
        "desc": "11a 重算指标, 11b 导出看板, 11c stamp, 11d 回归, 11e 完整性检查, 11f 一致性检查",
        "script": "scripts/post_training_finalize_outputs.py",
        "needs_output_root": True,
        "subs": [
            {"id": "11a", "name": "recompute_hourly_nrmse_consistent", "desc": "重算逐小时 NRMSE 指标", "needs_output_root": True},
            {"id": "11b", "name": "export_interactive_dashboard_data", "desc": "导出可视化看板数据", "needs_output_root": True},
            {"id": "11c", "name": "dashboard_stamp_check", "desc": "看板新鲜度stamp检查", "needs_output_root": True},
            {"id": "11d", "name": "dashboard_regression_check", "desc": "看板回归检查", "needs_output_root": True},
            {"id": "11e", "name": "check_dashboard_integrity", "desc": "看板数据完整性检查（禁止占位数据）", "needs_output_root": True},
            {"id": "11f", "name": "check_pipeline_consistency", "desc": "pipeline 一致性检查", "needs_output_root": True},
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
        "needs_config": True,
    },
    {
        "id": "13",
        "name": "Dashboard 预测值校验",
        "script": "scripts/check_dashboard_prediction_values.py",
        "required": True,
        "timeout": 300,
        "needs_config": True,
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
        "steps": ["1", "2", "3", "3b", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"],
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
             cache=None, *, out_dir: Path | None = None,
             mode: str = "", total_steps: int = 0,
             progress_index: int = 0,
             progress_mode: str = "tqdm") -> bool:
    """运行单个步骤（带缓存检查、计时、流式输出和进度追踪）。"""
    script = step["script"]
    full_path = cwd / script
    step_id = step["id"]
    step_name = step["name"]

    if out_dir is not None and total_steps > 0:
        update_progress(out_dir, mode=mode, total_steps=total_steps,
                       current_index=progress_index,
                       current_step=f"[{step_id}] {step_name}",
                       current_status="RUNNING")

    if not full_path.exists():
        if step["required"]:
            print(f"\n[FAIL] [{step_id}] 必需步骤脚本不存在: {full_path}")
            if out_dir is not None and total_steps > 0:
                update_progress(out_dir, mode=mode, total_steps=total_steps,
                               current_index=progress_index,
                               current_step=f"[{step_id}] {step_name}",
                               current_status="FAIL")
            return False
        print(f"\n[WARN] [{step_id}] 可选步骤脚本不存在，跳过: {full_path}")
        if out_dir is not None and total_steps > 0:
            update_progress(out_dir, mode=mode, total_steps=total_steps,
                           current_index=progress_index,
                           current_step=f"[{step_id}] {step_name}",
                           current_status="SKIP")
        return True

    # Step 11 有 4 个独立子步骤，各自计时
        if "subs" in step:
            return run_step_with_subs(step, python, cwd, cfg,
                                      out_dir=out_dir, mode=mode,
                                      total_steps=total_steps,
                                      progress_index=progress_index,
                                      progress_mode=progress_mode)

    # 使用显式 flags 决定传递哪些参数（不再依赖脚本名猜测）
    cmd = [python, str(full_path)]
    data_root = str(cwd / cfg.get("data", {}).get("data_root", "data"))
    output_root = str(cwd / cfg.get("data", {}).get("output_root", "output/pv_pipeline"))
    if step.get("needs_data_root"):
        cmd.extend(["--data-root", data_root])
    if step.get("needs_output_root"):
        cmd.extend(["--output-root", output_root])

    log_path = None
    if out_dir is not None:
        log_path = (out_dir / "logs" / f"step_{step_id}_{step_name.replace(' ', '_')}.log")

    with timed_step(f"[{step_id}] {step_name}", outputs=[str(full_path)]):
        returncode = run_subprocess_streaming(cmd, cwd, log_path, progress_mode=progress_mode)

        if returncode == 0:
            print(f"\n[PASS] [{step_id}] {step_name}")
            if out_dir is not None and total_steps > 0:
                update_progress(out_dir, mode=mode, total_steps=total_steps,
                               current_index=progress_index,
                               current_step=f"[{step_id}] {step_name}",
                               current_status="PASS")
            return True
        else:
            print(f"\n[FAIL] [{step_id}] {step_name} — exit {returncode}")
            if out_dir is not None and total_steps > 0:
                update_progress(out_dir, mode=mode, total_steps=total_steps,
                               current_index=progress_index,
                               current_step=f"[{step_id}] {step_name}",
                               current_status="FAIL")
            if step["required"]:
                print("\n[STOP] 必需步骤失败。请修复后重新运行本脚本。")
            return not step["required"]


def run_step_with_subs(step: dict, python: str, cwd: Path, cfg: dict,
                       *, out_dir: Path | None = None, mode: str = "",
                       total_steps: int = 0, progress_index: int = 0,
                       progress_mode: str = "tqdm") -> bool:
    """Step 11：按子步骤执行，每个子步骤独立计时、流式输出和进度追踪。"""
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

        if out_dir is not None and total_steps > 0:
            update_progress(out_dir, mode=mode, total_steps=total_steps,
                          current_index=progress_index,
                          current_step=f"[{sub_id}] {sub_name}",
                          current_status="RUNNING")

        cmd = [python, str(sub_script)]
        output_root = str(cwd / cfg.get("data", {}).get("output_root", "output/pv_pipeline"))
        if sub.get("needs_output_root"):
            cmd.extend(["--output-root", output_root])
        # Round98_1: check_pipeline_consistency 必须用 --stage posttrain
        if sub_name == "check_pipeline_consistency":
            cmd.extend(["--stage", "posttrain"])

        log_path = None
        if out_dir is not None:
            log_path = (out_dir / "logs" / f"step_{step_id}_{sub_id}_{sub_name.replace(' ', '_')}.log")

        with timed_step(f"[{sub_id}] {sub_name} ({sub_desc})", outputs=[str(sub_script)]):
            returncode = run_subprocess_streaming(cmd, cwd, log_path, progress_mode=progress_mode)

            if returncode == 0:
                print(f"\n[PASS] [{sub_id}] {sub_name}")
                if out_dir is not None and total_steps > 0:
                    update_progress(out_dir, mode=mode, total_steps=total_steps,
                                  current_index=progress_index,
                                  current_step=f"[{sub_id}] {sub_name}",
                                  current_status="PASS")
            else:
                print(f"\n[FAIL] [{sub_id}] {sub_name} — exit {returncode}")
                if out_dir is not None and total_steps > 0:
                    update_progress(out_dir, mode=mode, total_steps=total_steps,
                                  current_index=progress_index,
                                  current_step=f"[{sub_id}] {sub_name}",
                                  current_status="FAIL")
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
            cwd / "scripts" / "recompute_hourly_nrmse_consistent.py",
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
        "check_dashboard_integrity": [
            cwd / "scripts" / "check_dashboard_integrity.py",
        ],
        "check_pipeline_consistency": [
            cwd / "scripts" / "check_pipeline_consistency.py",
        ],
        "dashboard_regression_check": [
            cwd / "scripts" / "dashboard_regression_check.py",
        ],
    }
    for path in candidates.get(sub_name, []):
        if path.exists():
            return path
    return None


def snapshot_default_output(default_output: Path) -> dict[str, tuple[float, int]]:
    """对默认输出目录做快照，返回 {path: (mtime, size)}"""
    watched = {}
    for sub in ["predictions", "metrics", "tables", "interactive_dashboard", "models", "docs"]:
        d = default_output / sub
        if d.exists():
            for p in d.glob("*"):
                if p.is_file():
                    watched[str(p)] = (p.stat().st_mtime, p.stat().st_size)
    # Also watch the top-level canonical files
    for f in ["manifest.json"]:
        p = default_output / f
        if p.exists():
            watched[str(p)] = (p.stat().st_mtime, p.stat().st_size)
    return watched


def assert_default_output_unchanged(before: dict, default_output: Path, step_name: str):
    """如果默认目录被修改，立即报错并显示哪些文件被改。"""
    after = snapshot_default_output(default_output)
    # Check for modified or new files
    changed = []
    for path, (mtime, size) in after.items():
        if path not in before:
            changed.append(f"  +NEW: {Path(path).name}")
        elif before[path] != (mtime, size):
            changed.append(f"  ~MOD: {Path(path).name}")

    if changed:
        raise RuntimeError(
            f"[POLLUTION BLOCKED] Step '{step_name}' wrote to the official "
            f"output/pv_pipeline directory while running with a non-default output root.\n"
            f"Changed files:\n" + "\n".join(changed) + "\n"
            f"Abort to prevent official result contamination."
        )


# ─── Post-steps ───────────────────────────────────────────────────────────────

def sync_canonical_paths(cwd: Path, output_root: Path) -> None:
    """验证 canonical 路径存在；若源脚本已直接写 canonical，则只做一致性检查。"""
    out = output_root
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
    out_rel = Path(cfg["data"]["output_root"])
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pipeline_entry": "scripts/run_full_pipeline.py",
        "config": "configs/pipeline.yaml",
        "split": cfg.get("split", {}),
        "eval": cfg.get("eval", {}),
        "final_prediction_column": cfg.get("prediction", {}).get("final_column", "power_pred_final"),
        "artifacts": {
            "final_full_pkl":    str(out_rel / "predictions" / "distributed_predictions_final_full.pkl"),
            "final_eval_pkl":    str(out_rel / "predictions" / "distributed_predictions_final_eval.pkl"),
            "hourly_nrmse_csv":  str(out_rel / "metrics" / "hourly_nrmse_consistent.csv"),
            "site_metrics_csv":  str(out_rel / "metrics" / "site_metrics_consistent.csv"),
            "dashboard_dir":     str(out_rel / "interactive_dashboard"),
            "dashboard_index":   str(out_rel / "interactive_dashboard" / "index.json"),
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

def warn_if_not_interactive_terminal():
    """提示非交互式终端风险。"""
    if not sys.stdout.isatty():
        print(
            "[WARN] 当前 stdout 不是交互式终端。"
            "如果你使用 nohup、后台任务或重定向运行，可能看不到实时训练进度。",
            flush=True,
        )


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
        "--dry-run",
        action="store_true",
        help="仅打印将要执行的步骤，不执行任何训练脚本",
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

    progress_mode = os.getenv("PV_PROGRESS_MODE", "tqdm").lower().strip()

    python = args.python
    if not Path(python).exists():
        conda_py = sys.executable
        if Path(conda_py).exists():
            python = conda_py
            print(f"[INFO] 使用 conda Python: {python}")

    cwd = project_root()
    mode = args.mode
    mode_info = MODES[mode]

    # 前台执行检查
    warn_if_not_interactive_terminal()

    print("=" * 60)
    print("光伏预测训练流水线")
    print(f"执行模式: {mode} — {mode_info['desc']}")
    print("=" * 60)
    print(f"项目根目录: {cwd}")
    print(f"Python:     {python}")
    print(f"Force:      {args.force}")
    print()

    # ── Dry-run ─────────────────────────────────────────────────────────────────
    if args.dry_run:
        print()
        print("[DRY-RUN] 仅检查步骤配置，不执行任何训练脚本")
        print("=" * 60)
        try:
            cfg = load_config(args.config)
        except Exception as e:
            print(f"[WARN] 配置加载跳过（dry-run）: {e}")
        print()
        print("[DRY-RUN] pretrain checks:")
        print("  - preflight_check.py")
        print("  - check_pipeline_consistency.py --stage pretrain")
        print()
        print("[DRY-RUN] posttrain hooks (after training):")
        print("  - export_interactive_dashboard_data.py")
        print("  - check_dashboard_integrity.py")
        print("  - check_pipeline_consistency.py --stage posttrain")
        print()
        print("[DRY-RUN] steps to execute:")
        steps_to_run = []
        for step in STEPS:
            if args.skip and step["id"] in args.skip.split(","):
                continue
            sid = step["id"].ljust(3)
            name = step["name"]
            script = step["script"]
            script_path = cwd / script
            exists = "YES" if script_path.exists() else "NO"
            status = "SKIP" if args.skip and step["id"] in args.skip.split(",") else ""
            print(f"[DRY-RUN] [{sid}] {name} -> {script}  exists={exists}  {status}")
            steps_to_run.append(step)
        print()
        print(f"[DRY-RUN] total steps: {len(steps_to_run)}")
        print(f"[DRY-RUN] progress_mode={progress_mode}")
        # Check output dirs writable
        test_dirs = ["predictions", "metrics", "tables", "interactive_dashboard"]
        for d in test_dirs:
            out_path = cwd / "output" / "pv_pipeline" / d
            writable = "WRITABLE" if out_path.exists() and os.access(out_path, os.W_OK) else "NOT_WRITABLE_OR_MISSING"
            print(f"[DRY-RUN] output/{d}/: {writable}")
        print()
        print("[DRY-RUN] no subprocess executed — exiting")
        sys.exit(0)

    # ── 训练前预检 ──────────────────────────────────────────────────────────────
    preflight_cmd = [python, str(cwd / "scripts" / "preflight_check.py")]
    if args.config:
        preflight_cmd.extend(["--config", args.config])
    pf_result = subprocess.call(preflight_cmd, cwd=str(cwd))
    if pf_result != 0:
        print()
        print("=" * 60)
        print("[FAIL] 训练前预检失败，请修复上述问题后重新运行。")
        print("=" * 60)
        sys.exit(1)
    print("[PREFLIGHT] 预检通过。")

    # Round98_1: 训练前一致性检查（pretrain 模式，不检查最终 PKL）
    pretrain_check_cmd = [python, str(cwd / "scripts" / "check_pipeline_consistency.py"), "--stage", "pretrain"]
    print()
    print("[PRETRAIN CHECK] 开始训练前一致性检查（--stage pretrain）...")
    pc_result = subprocess.call(pretrain_check_cmd, cwd=str(cwd))
    if pc_result != 0:
        print()
        print("=" * 60)
        print("[FAIL] 训练前一致性检查失败，请修复上述问题后重新运行。")
        print("=" * 60)
        sys.exit(1)
    print("[PRETRAIN CHECK] 训练前一致性检查通过。")

    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        sys.exit(1)

    out_dir = cwd / cfg["data"]["output_root"]

    # ── Path Isolation Protection ──────────────────────────────────────────────
    # 如果本次输出目录不是默认的 output/pv_pipeline，则对默认目录做快照
    # 并在每个 step 后检查是否被污染
    DEFAULT_OUTPUT = (cwd / "output" / "pv_pipeline").resolve()
    RUN_OUTPUT = out_dir.resolve()
    is_non_default_run = (RUN_OUTPUT != DEFAULT_OUTPUT)
    default_snapshot = {}
    if is_non_default_run:
        print()
        print("=" * 60)
        print("[PATH GUARD] 非默认输出目录，启用路径隔离保护")
        print(f"  Default:  {DEFAULT_OUTPUT}")
        print(f"  Running:  {RUN_OUTPUT}")
        print("=" * 60)
        default_snapshot = snapshot_default_output(DEFAULT_OUTPUT)
        print(f"[PATH GUARD] 快照完成，监控 {len(default_snapshot)} 个文件/目录")

    # ── Step Pollution Check Helper ────────────────────────────────────────────
    def check_pollution(step_name: str):
        if is_non_default_run:
            assert_default_output_unchanged(default_snapshot, DEFAULT_OUTPUT, step_name)
            # Refresh snapshot after each step
            default_snapshot.clear()
            default_snapshot.update(snapshot_default_output(DEFAULT_OUTPUT))

    # 初始化缓存
    try:
        from scripts.pipeline_cache import PipelineCache
        cache = PipelineCache(force=args.force)
    except Exception:
        cache = None

    skip_ids = set(args.skip.split(",")) - {""}
    step_ids_to_run = set(mode_info["steps"])

    # 计算总步骤数（用于进度条）
    run_steps_order = [s for s in STEPS if s["id"] in step_ids_to_run and s["id"] not in skip_ids]
    total_steps = len(run_steps_order)
    if mode_info.get("run_step14", True):
        total_steps += 1
    if mode_info.get("run_step15", True):
        total_steps += 1
    progress_index = 0

    print(f"[PROGRESS] total steps: {total_steps}")
    print()

    # ── Phase 1: pre-validation steps ──────────────────────────────────────
    for step in STEPS:
        step_id = step["id"]
        if step_id not in step_ids_to_run:
            print(f"\n[SKIP] [{step_id}] {step['name']}（{mode} 模式跳过）")
            continue
        if step_id in skip_ids:
            print(f"\n[SKIP] [{step_id}] {step['name']}（用户跳过）")
            continue
        # Stop before step 12 (posttrain_validation needs manifest written first)
        if step_id == "12":
            break
        progress_index += 1
        ok = run_step(step, python, cwd, cfg, cache,
                     out_dir=out_dir, mode=mode, total_steps=total_steps,
                     progress_index=progress_index,
                     progress_mode=progress_mode)
        check_pollution(step["name"])
        if not ok:
            print(f"\n{'='*60}")
            print("训练流程终止")
            print("="*60)
            sys.exit(1)

    # ── Phase 2: manifest must be written before step 12 ─────────────────
    # Step 14：同步正式产物文件名
    if mode_info.get("run_step14", True):
        progress_index += 1
        update_progress(out_dir, mode=mode, total_steps=total_steps,
                      current_index=progress_index,
                      current_step="[14] 同步 canonical 产物",
                      current_status="RUNNING")
        with timed_step("[14] 同步 canonical 产物"):
            sync_canonical_paths(cwd, out_dir)
        update_progress(out_dir, mode=mode, total_steps=total_steps,
                      current_index=progress_index,
                      current_step="[14] 同步 canonical 产物",
                      current_status="PASS")

    # Step 15：写出 manifest.json（必须在 step 12 之前，硬失败）
    if mode_info.get("run_step15", True):
        progress_index += 1
        update_progress(out_dir, mode=mode, total_steps=total_steps,
                      current_index=progress_index,
                      current_step="[15] 写出 manifest.json",
                      current_status="RUNNING")
        with timed_step("[15] 写出 manifest.json"):
            try:
                write_manifest(cfg, cwd)
            except Exception as e:
                print(f"\n[FAIL] manifest 写出失败: {e}")
                update_progress(out_dir, mode=mode, total_steps=total_steps,
                              current_index=progress_index,
                              current_step="[15] 写出 manifest.json",
                              current_status="FAIL")
                sys.exit(1)
        update_progress(out_dir, mode=mode, total_steps=total_steps,
                      current_index=progress_index,
                      current_step="[15] 写出 manifest.json",
                      current_status="PASS")

    # ── Phase 3: post-validation steps (12, 13) ───────────────────────────
    for step in STEPS:
        step_id = step["id"]
        if step_id not in step_ids_to_run:
            continue
        if step_id in skip_ids:
            print(f"\n[SKIP] [{step_id}] {step['name']}（用户跳过）")
            continue
        # Only run step 12 and later (already handled 1-11 above)
        if step_id < "12":
            continue
        progress_index += 1
        ok = run_step(step, python, cwd, cfg, cache,
                     out_dir=out_dir, mode=mode, total_steps=total_steps,
                     progress_index=progress_index,
                     progress_mode=progress_mode)
        check_pollution(step["name"])
        if not ok:
            print(f"\n{'='*60}")
            print("训练流程终止")
            print("="*60)
            sys.exit(1)

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
    print(f"  cd {project_root()}")
    print("  python -m http.server 8070")
    print("  访问 http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html")


if __name__ == "__main__":
    main()
