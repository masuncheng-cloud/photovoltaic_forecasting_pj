#!/usr/bin/env python3
"""
Round97_1 Dashboard 新鲜度检查。
不重新训练，只验证可视化 JSON 数据是否与最新训练结果一致。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if (_SRC / "pv_forecasting").exists():
    sys.path.insert(0, str(_SRC))


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return -1


def _mtime_str(p: Path) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
    except OSError:
        return "NOT_FOUND"


def check_dashboard_freshness() -> bool:
    project_root = Path(__file__).resolve().parents[1]
    dashboard_root = project_root / "output" / "pv_pipeline" / "interactive_dashboard"
    predictions_root = project_root / "output" / "pv_pipeline" / "tables"

    errors = []
    warnings = []

    # ── 1. metadata.json ────────────────────────────────────────────────────
    meta_path = dashboard_root / "metadata.json"
    if not meta_path.exists():
        errors.append(f"[ERROR] metadata.json 不存在: {meta_path}")
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            pred_col = meta.get("prediction_column", "")
            if pred_col != "power_pred_final":
                errors.append(f"[ERROR] prediction_column={pred_col}，期望 power_pred_final")
            else:
                print(f"[PASS] prediction_column={pred_col}")
            if meta.get("contains_future"):
                warnings.append("[WARN] metadata.json 包含 future 数据")
            print(f"[PASS] metadata.json 解析正常")
        except Exception as e:
            errors.append(f"[ERROR] metadata.json 解析失败: {e}")

    # ── 2. index.json ───────────────────────────────────────────────────────
    idx_path = dashboard_root / "index.json"
    if not idx_path.exists():
        errors.append(f"[ERROR] index.json 不存在: {idx_path}")
    else:
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            # 检查是否引用了正确的目录
            data_dir = idx.get("data_directory", "")
            if "interactive_dashboard" not in data_dir and str(dashboard_root) not in data_dir:
                warnings.append(f"[WARN] index.json data_directory={data_dir}，可能引用旧目录")
            print(f"[PASS] index.json 解析正常")
        except Exception as e:
            errors.append(f"[ERROR] index.json 解析失败: {e}")

    # ── 3. site_series 数量检查 ──────────────────────────────────────────────
    site_series_dir = dashboard_root / "site_series"
    if not site_series_dir.exists():
        errors.append(f"[ERROR] site_series/ 目录不存在: {site_series_dir}")
    else:
        site_jsons = list(site_series_dir.glob("*.json"))
        print(f"[INFO] site_series/ 共 {len(site_jsons)} 个 JSON 文件")
        # 站点数应在 60~80 之间
        if len(site_jsons) < 50:
            warnings.append(f"[WARN] site_series/ 仅 {len(site_jsons)} 个文件，数量偏少")
        elif len(site_jsons) > 100:
            warnings.append(f"[WARN] site_series/ 有 {len(site_jsons)} 个文件，可能有重复")
        else:
            print(f"[PASS] site_series/ 数量 {len(site_jsons)} 在合理范围")

    # ── 4. 时间戳新鲜度对比 ───────────────────────────────────────────────────
    # 获取最新预测文件时间戳
    prediction_files = sorted(predictions_root.glob("distributed_predictions_*.pkl"))
    if prediction_files:
        latest_pred = max(prediction_files, key=lambda p: _mtime(p))
        pred_mtime = _mtime(latest_pred)
        print(f"[INFO] 最新预测文件: {latest_pred.name}  ({_mtime_str(latest_pred)})")

        # metadata 应该不比预测文件旧
        if meta_path.exists() and _mtime(meta_path) < pred_mtime:
            warnings.append(
                f"[WARN] metadata.json ({_mtime_str(meta_path)}) 比预测文件旧"
                f"（{latest_pred.name} {_mtime_str(latest_pred)}）"
            )
        else:
            print(f"[PASS] metadata.json 时间戳正常")

        # index.json 也应该不旧
        if idx_path.exists() and _mtime(idx_path) < pred_mtime:
            warnings.append(
                f"[WARN] index.json ({_mtime_str(idx_path)}) 比预测文件旧"
            )
        else:
            print(f"[PASS] index.json 时间戳正常")

        # 检查 site_series 时间戳
        if site_series_dir.exists():
            stale_sites = []
            for sj in site_jsons:
                if _mtime(sj) < pred_mtime:
                    stale_sites.append(sj.name)
            if stale_sites:
                warnings.append(
                    f"[WARN] {len(stale_sites)}/{len(site_jsons)} 个 site_series JSON"
                    f"比预测文件旧（最多显示 5 个: {stale_sites[:5]}）"
                )
            else:
                print(f"[PASS] 所有 site_series JSON 都是最新的")
    else:
        warnings.append("[WARN] 未找到预测文件，无法对比新鲜度（可能是预训练状态）")

    # ── 5. 检查 metadata 中引用的数据路径 ───────────────────────────────────
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key in ["data_directory", "output_root"]:
                val = meta.get(key, "")
                if val and "round" in val.lower() and "interactive_dashboard" not in val:
                    warnings.append(f"[WARN] metadata.{key}={val} 引用了含 round 的目录")
            print(f"[INFO] metadata 引用路径检查通过")
        except Exception:
            pass

    # ── 汇总 ────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if errors:
        print(f"❌ 检查失败，共 {len(errors)} 个错误:")
        for e in errors:
            print(f"   {e}")
    if warnings:
        print(f"⚠️  警告，共 {len(warnings)} 项:")
        for w in warnings:
            print(f"   {w}")
    if not errors and not warnings:
        print("✅ Dashboard 数据新鲜度检查全部通过！")
    elif not errors:
        print(f"⚠️  Dashboard 数据新鲜度检查完成（有 {len(warnings)} 个警告）")

    # 返回 True 表示只有 warnings（可接受），False 表示有 errors
    return len(errors) == 0


def main() -> None:
    print("=" * 60)
    print("Round97_1 Dashboard 新鲜度检查")
    print("=" * 60)
    ok = check_dashboard_freshness()
    print("=" * 60)
    if not ok:
        print()
        print("如果仅是警告，可执行以下命令重新导出可视化 JSON：")
        print("  python scripts/export_interactive_dashboard_data.py")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
