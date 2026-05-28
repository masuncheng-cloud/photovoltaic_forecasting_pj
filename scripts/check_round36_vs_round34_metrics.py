"""
check_round36_vs_round34_metrics.py
==================================
从真实 CSV 文件核对 Round34 vs Round36 全市 10-14 时 NRMSE 数值，
避免手写导致的不一致。

输出：
  output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv
"""
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
ARCHIVE  = PROJECT_ROOT / "output" / "pv_pipeline" / "archive_before_round36"


def find_city_file(base_name: str) -> Path:
    """优先从 metrics/ 找，找不到则从 archive/ 找。"""
    candidates = [
        METRICS / base_name,
        ARCHIVE  / base_name,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"找不到 {base_name}（搜索了 {candidates}）")


def calc_10_14_nrmse(path: Path) -> float:
    """计算 10-14 时的全市 NRMSE 均值。"""
    df = pd.read_csv(path)
    sub = df[df["hour"].between(10, 14)].copy()
    # 兼容 nrmse_city_pct / nrmse_pct 两种列名
    if "nrmse_city_pct" in sub.columns:
        col = "nrmse_city_pct"
    elif "nrmse_pct" in sub.columns:
        col = "nrmse_pct"
    else:
        raise KeyError(f"{path} 中没有 nrmse_city_pct 或 nrmse_pct 列，"
                        f"实际列：{list(sub.columns)}")
    return float(sub[col].mean())


def main():
    print("=" * 60)
    print("Round36 vs Round34 指标核对")
    print("=" * 60)

    # ── 全市 10-14 时 NRMSE ───────────────────────────────
    r34_path = find_city_file("round34_city_hourly_nrmse.csv")
    r36_path = METRICS / "round36_city_hourly_nrmse.csv"

    r34_val = calc_10_14_nrmse(r34_path)
    r36_val = calc_10_14_nrmse(r36_path)
    delta = r36_val - r34_val

    print(f"\nRound34 全市 10-14 时 NRMSE: {r34_val:.4f}%")
    print(f"Round36 全市 10-14 时 NRMSE: {r36_val:.4f}%")
    print(f"变化: {delta:+.4f}pp ({'改善' if delta < 0 else '变差'})")

    # ── 写 CSV ─────────────────────────────────────────
    OUT = METRICS / "round36_vs_round34_metric_check.csv"
    df_out = pd.DataFrame([{
        "metric":            "city_10_14_nrmse_pct",
        "round34_value_pct": round(r34_val, 4),
        "round36_value_pct": round(r36_val, 4),
        "delta_pp":           round(delta, 4),
        "source_round34":    str(r34_path),
        "source_round36":    str(r36_path),
        "status":            "PASS",
    }])
    df_out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n已保存: {OUT}")
    print(df_out.to_string(index=False))


if __name__ == "__main__":
    main()
