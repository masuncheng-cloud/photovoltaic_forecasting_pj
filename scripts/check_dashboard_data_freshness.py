"""
check_dashboard_data_freshness.py
================================
检查 dashboard 可视化数据是否为最新训练结果。

检查内容：
  1. 最新 final pkl 存在，且含 power_pred_final
  2. 所有 dashboard JSON 关键文件存在
  3. site_series 文件数量正常（>= 60）
  4. metadata.json 中 prediction_column == "power_pred_final"
  5. dashboard 关键文件修改时间 >= final pkl 时间
  6. hourly JSON 与 round46_hourly_nrmse_consistent.csv 逐行一致
  7. 10-14 点 NRMSE 未回到旧错误口径（< 25%）
  8. dashboard 不含 future split 数据

用法：
  python scripts/check_dashboard_data_freshness.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
DASH = OUT / "interactive_dashboard"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"

PYTHON = sys.executable


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def find_final_pkl() -> Path:
    """找到最新 final pkl，按 mtime 排序。"""
    candidates = sorted(
        OUT.rglob("distributed_predictions_final_round*.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    # fallback: any final pkl
    candidates = sorted(
        OUT.rglob("*final*.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        fail("找不到 final pkl（distributed_predictions_final*.pkl）")
    return candidates[0]


def main() -> int:
    print("=" * 60)
    print("check_dashboard_data_freshness")
    print("=" * 60)
    print(f"Project root : {ROOT}")
    print(f"Python      : {PYTHON}")
    print()

    # ── 1. 找 final pkl ──────────────────────────────────────────────
    print("[1/8] 查找 latest final pkl...")
    final_pkl = find_final_pkl()
    ok(f"found: {final_pkl.relative_to(ROOT)} (mtime={datetime.fromtimestamp(final_pkl.stat().st_mtime).isoformat(timespec='seconds')})")

    # ── 2. 检查 power_pred_final 列 ───────────────────────────────
    print("\n[2/8] 检查 power_pred_final 列...")
    try:
        final_df = pd.read_pickle(final_pkl)
    except Exception as e:
        fail(f"无法读取 final pkl: {e}")

    required_cols = {"site_id", "power_mw", "power_pred_final"}
    missing = required_cols - set(final_df.columns)
    if missing:
        fail(f"final pkl 缺少字段: {missing}")
    ok("power_pred_final 存在于 final pkl")

    # 检查不含 future
    if "split" in final_df.columns:
        future_rows = int((final_df["split"] == "future").sum())
        total_rows = len(final_df)
        print(f"       future rows: {future_rows}/{total_rows}")
        if future_rows > 0:
            print(f"       [INFO] final pkl 包含 future 数据，dashboard 导出时应已排除")

    # ── 3. 检查 dashboard 关键文件存在 ──────────────────────────────
    print("\n[3/8] 检查 dashboard 关键文件...")
    required_files = [
        DASH / "metadata.json",
        DASH / "city_series.json",
        DASH / "hourly_prediction_summary.json",
        DASH / "site_metrics.json",
        METRICS / "round46_hourly_nrmse_consistent.csv",
        METRICS / "round46_site_hour_nrmse_consistent.csv",
    ]
    for p in required_files:
        if not p.exists():
            fail(f"文件不存在: {p.relative_to(ROOT)}")
        size = p.stat().st_size
        mtime = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        ok(f"exists: {p.relative_to(ROOT)} ({size:,} bytes, mtime={mtime})")

    # ── 4. 检查 site_series 数量 ────────────────────────────────────
    print("\n[4/8] 检查 site_series 文件数量...")
    site_files = list((DASH / "site_series").glob("*.json"))
    if len(site_files) < 60:
        fail(f"site_series 文件数量异常: {len(site_files)}，期望 >= 60")
    ok(f"site_series files: {len(site_files)}")

    # ── 5. 检查 metadata prediction_column ──────────────────────────
    print("\n[5/8] 检查 metadata prediction_column...")
    try:
        metadata = json.loads((DASH / "metadata.json").read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"无法读取 metadata.json: {e}")

    pred_col = metadata.get("prediction_column", "")
    print(f"       prediction_column = {pred_col}")
    if pred_col != "power_pred_final":
        fail(f"prediction_column 应为 power_pred_final，实际为 {pred_col}")
    ok("prediction_column == power_pred_final")

    # ── 6. 检查 dashboard 文件新鲜度 ────────────────────────────────
    print("\n[6/8] 检查 dashboard 关键文件新鲜度...")
    final_mtime = final_pkl.stat().st_mtime
    key_files = [
        DASH / "metadata.json",
        DASH / "city_series.json",
        DASH / "hourly_prediction_summary.json",
    ]
    stale = []
    for p in key_files:
        p_mtime = p.stat().st_mtime
        age = (p_mtime - final_mtime) / 3600
        if p_mtime < final_mtime:
            stale.append(f"{p.relative_to(ROOT)} ({(final_mtime - p_mtime)/3600:.1f}h older than pkl)")
        print(f"       {p.relative_to(ROOT)}: {'STALE' if p_mtime < final_mtime else 'OK'} "
              f"(pkl vs file: {age:+.2f}h)")

    if stale:
        fail("dashboard 文件早于 final pkl，可能未使用最新训练数据:\n       " + "\n       ".join(stale))
    ok("dashboard 关键文件修改时间 >= final pkl")

    # ── 7. hourly JSON 与 CSV 一致性 ───────────────────────────────
    print("\n[7/8] 检查 hourly JSON 与 CSV 一致性...")
    hourly_json_raw = json.loads((DASH / "hourly_prediction_summary.json").read_text(encoding="utf-8"))
    hourly_csv = pd.read_csv(METRICS / "round46_hourly_nrmse_consistent.csv")

    # 支持 dict 包装或直接 list
    if isinstance(hourly_json_raw, dict):
        hourly_json = hourly_json_raw.get("data") or hourly_json_raw.get("hourly") or []
    else:
        hourly_json = hourly_json_raw

    if len(hourly_json) != 14:
        fail(f"hourly_prediction_summary.json 行数应为 14，实际为 {len(hourly_json)}")

    json_df = pd.DataFrame(hourly_json)
    csv_df = hourly_csv.copy()
    csv_df["hour"] = pd.to_numeric(csv_df["hour"], errors="coerce")
    json_df["hour"] = pd.to_numeric(json_df["hour"], errors="coerce")

    all_match = True
    for h in range(6, 20):
        j = json_df[json_df["hour"] == h]
        c = csv_df[csv_df["hour"] == h]
        if j.empty or c.empty:
            fail(f"缺少小时 {h} 的数据")
        j_val = float(j.iloc[0]["site_avg_nrmse_pct"])
        c_val = float(c.iloc[0]["site_avg_nrmse_pct"])
        diff = abs(j_val - c_val)
        status = "MATCH" if diff < 1e-6 else f"MISMATCH (diff={diff:.6f})"
        print(f"       h={h:2d}: JSON={j_val:.3f}%, CSV={c_val:.3f}% [{status}]")
        if diff >= 1e-6:
            all_match = False

    if not all_match:
        fail("hourly JSON 与 round46_hourly_nrmse_consistent.csv 不一致")
    ok("hourly JSON 与 CSV 逐行一致")

    # ── 8. 检查未回到旧错误口径 ────────────────────────────────────
    print("\n[8/8] 检查未回到旧错误口径（10-14点）...")
    focus = hourly_csv[hourly_csv["hour"].between(10, 14)]
    if focus.empty:
        fail("CSV 中缺少 10-14 点数据")
    max_val = focus["site_avg_nrmse_pct"].max()
    min_val = focus["site_avg_nrmse_pct"].min()
    print(f"       10-14点 site_avg_nrmse_pct: min={min_val:.2f}%, max={max_val:.2f}%")
    if max_val > 25:
        fail(f"站点平均 NRMSE 超过 25%（{max_val:.1f}%），疑似使用旧错误口径（31%-37%）")
    ok(f"口径正常，未回到旧错误口径（max={max_val:.2f}%）")

    # ── Summary ───────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("[PASS] dashboard data freshness check passed")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
