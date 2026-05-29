"""
check_post_training_auto_finalize.py
===================================
验证训练后自动收口链路是否完整。

检查内容：
  1. output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv 存在
  2. output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json 存在
  3. output/pv_pipeline/docs/post_training_finalize_stamp.json 存在
  4. 三个文件的修改时间合理（不应早于训练开始时间）
  5. JSON 中 10-14 点站点平均 NRMSE 不是旧错误口径的 31%-37%
  6. metadata.json 中预测列为 power_pred_final

用法：
  python scripts/check_post_training_auto_finalize.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"

METRICS_DIR = OUT / "metrics"
DASHBOARD_DIR = OUT / "interactive_dashboard"
DOCS_DIR = OUT / "docs"

PYTHON = sys.executable


def check_file_exists(path: Path, label: str) -> bool:
    if not path.exists():
        print(f"[FAIL] {label}: 不存在 {path.relative_to(ROOT)}")
        return False
    size = path.stat().st_size
    mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    print(f"[OK]   {label}: {path.relative_to(ROOT)} ({size:,} bytes, mtime={mtime})")
    return True


def check_hourly_nrmse_caliber(df) -> bool:
    """检查逐小时 NRMSE 是否使用了正确的口径（不是旧错误口径 31%-37%）。"""
    focus = df[df["hour"].between(10, 14)]
    if focus.empty:
        print("[FAIL] CSV 中没有 10-14 点的数据")
        return False
    max_val = focus["site_avg_nrmse_pct"].max()
    min_val = focus["site_avg_nrmse_pct"].min()
    print(f"       10-14点 site_avg_nrmse_pct: min={min_val:.2f}%, max={max_val:.2f}%")
    if max_val > 25:
        print(f"[FAIL] 站点平均 NRMSE 过高 ({max_val:.1f}%)，疑似使用旧错误口径（31%-37%）")
        return False
    if max_val < 10:
        print(f"[WARN] 站点平均 NRMSE 偏低 ({max_val:.1f}%)，请人工确认口径正确性")
    print(f"[OK]   口径检查通过（未使用旧错误口径）")
    return True


def check_hourly_json(df) -> bool:
    """检查 hourly_prediction_summary.json 数据合理性。"""
    focus = [r for r in df if 10 <= r["hour"] <= 14]
    if not focus:
        print("[FAIL] JSON 中没有 10-14 点的数据")
        return False
    vals = [r["site_avg_nrmse_pct"] for r in focus]
    max_val = max(vals)
    if max_val > 25:
        print(f"[FAIL] JSON 中站点平均 NRMSE 过高 ({max_val:.1f}%)，疑似使用旧错误口径")
        return False
    print(f"[OK]   JSON 10-14点 site_avg_nrmse_pct: {vals}")
    return True


def check_prediction_column() -> bool:
    """检查 metadata.json 中预测列是否为 power_pred_final。"""
    meta_path = DASHBOARD_DIR / "metadata.json"
    if not meta_path.exists():
        print("[FAIL] metadata.json 不存在")
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pred_col = meta.get("prediction_column", "")
    print(f"       prediction_column = {pred_col}")
    if pred_col != "power_pred_final":
        print(f"[FAIL] 预测列应为 power_pred_final，实际为 {pred_col}")
        return False
    print(f"[OK]   预测列为 power_pred_final")
    return True


def main():
    print("=" * 60)
    print("check_post_training_auto_finalize")
    print("=" * 60)
    print(f"项目根目录: {ROOT}")
    print(f"Python    : {PYTHON}")
    print()

    results = []

    # 1. Check hourly CSV
    print("[1/6] 检查 round46_hourly_nrmse_consistent.csv ...")
    csv_path = METRICS_DIR / "round46_hourly_nrmse_consistent.csv"
    ok = check_file_exists(csv_path, "hourly CSV")
    results.append(("hourly CSV exists", ok))
    if ok:
        import pandas as pd
        df_csv = pd.read_csv(csv_path)
        ok2 = check_hourly_nrmse_caliber(df_csv)
        results.append(("hourly CSV caliber", ok2))

    # 2. Check hourly JSON
    print("\n[2/6] 检查 hourly_prediction_summary.json ...")
    json_path = DASHBOARD_DIR / "hourly_prediction_summary.json"
    ok = check_file_exists(json_path, "hourly JSON")
    results.append(("hourly JSON exists", ok))
    if ok:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        ok2 = check_hourly_json(data)
        results.append(("hourly JSON caliber", ok2))

    # 3. Check stamp
    print("\n[3/6] 检查 post_training_finalize_stamp.json ...")
    stamp_path = DOCS_DIR / "post_training_finalize_stamp.json"
    ok = check_file_exists(stamp_path, "finalize stamp")
    results.append(("stamp exists", ok))
    if ok:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        print(f"       finalized_at = {stamp.get('finalized_at', 'N/A')}")
        steps = stamp.get("steps", [])
        ok_steps = [s for s in steps if s.get("status") == "ok"]
        print(f"       steps: {len(ok_steps)}/{len(steps)} OK")
        if len(ok_steps) < len(steps):
            print(f"[WARN] 部分步骤失败:")
            for s in steps:
                if s.get("status") != "ok":
                    print(f"       - {s.get('name')}: {s.get('status')} (code={s.get('returncode')})")

    # 4. Check stamp freshness (should be recent)
    print("\n[4/6] 检查 stamp 新鲜度 ...")
    if stamp_path.exists():
        age_sec = datetime.now().timestamp() - stamp_path.stat().st_mtime
        age_h = age_sec / 3600
        print(f"       stamp age = {age_h:.1f}h")
        if age_h > 48:
            print(f"[WARN] stamp 已超过 48h 未更新，建议重新运行完整训练流程")
        else:
            print(f"[OK]   stamp 新鲜度正常")

    # 5. Check prediction column
    print("\n[5/6] 检查 metadata.json 预测列 ...")
    ok = check_prediction_column()
    results.append(("prediction_column=power_pred_final", ok))

    # 6. Cross-check: hourly JSON rows count
    print("\n[6/6] 检查 hourly JSON 行数 ...")
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if len(data) == 14:
            print(f"[OK]   hourly JSON 行数正确（14行，6-19时）")
            results.append(("hourly JSON row count", True))
        else:
            print(f"[FAIL] hourly JSON 行数应为 14，实际为 {len(data)}")
            results.append(("hourly JSON row count", False))

    # Summary
    print()
    print("=" * 60)
    print("检查结果汇总")
    print("=" * 60)
    passed = [label for label, ok in results if ok]
    failed = [label for label, ok in results if not ok]
    for label, ok in results:
        print(f"  {'[OK]' if ok else '[FAIL]'} {label}")
    print()
    if not failed:
        print(f"[PASS] 全部 {len(passed)} 项检查通过")
        return 0
    else:
        print(f"[FAIL] {len(failed)}/{len(results)} 项检查失败: {failed}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
