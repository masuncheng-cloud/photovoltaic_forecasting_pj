#!/usr/bin/env python3
"""
check_candidate_prediction_diff.py
==================================
检查候选预测列是否真实不同于 baseline，防止 Round69 中 residual_lgb 等
等于 baseline 却被当作候选的问题。

用法：
    python scripts/check_candidate_prediction_diff.py \
        --candidate-pkl output/pv_pipeline/round70/round70_candidates.pkl \
        --baseline-col power_pred_final

输出：
    output/pv_pipeline/round70/round70_candidate_diff_check.csv
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(cfg_path: str | None) -> dict:
    if cfg_path is None:
        cfg_path = project_root() / "configs" / "round70_state_expert_model.yaml"
    else:
        cfg_path = Path(cfg_path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_candidate_diff(df: pd.DataFrame, baseline_col: str,
                         candidate_col: str) -> dict:
    """对单个候选列与 baseline 比较，输出差异统计。"""
    bl = df[baseline_col].to_numpy(dtype=float)
    cand = df[candidate_col].to_numpy(dtype=float)

    mask = np.isfinite(bl) & np.isfinite(cand)
    bl_f = bl[mask]
    cand_f = cand[mask]

    diff = cand_f - bl_f
    abs_diff = np.abs(diff)

    changed = abs_diff > 1e-8
    n_changed = int(changed.sum())
    changed_ratio = n_changed / max(len(diff), 1)

    max_abs_diff = float(np.max(abs_diff)) if len(abs_diff) > 0 else 0.0
    mean_abs_diff = float(np.mean(abs_diff)) if len(abs_diff) > 0 else 0.0
    median_abs_diff = float(np.median(abs_diff)) if len(abs_diff) > 0 else 0.0
    mean_diff = float(np.mean(diff)) if len(diff) > 0 else 0.0

    # 唯一站点数（用过滤后的数组找索引）
    changed_mask = mask.copy()
    changed_mask[~changed_mask] = False  # only keep True where both finite
    changed_mask[changed_mask] = changed  # only True where abs_diff > 1e-8
    idx_changed = np.where(changed_mask)[0]
    site_ids_changed = df.iloc[idx_changed]["site_id"].nunique() if len(idx_changed) > 0 and "site_id" in df.columns else 0

    # 检验是否完全相同
    is_identical = bool(np.allclose(cand_f, bl_f, atol=1e-8, equal_nan=True))
    is_invalid = is_identical or (n_changed == 0)

    status = "INVALID_IDENTICAL_TO_BASELINE" if is_identical else ("INVALID_ZERO_CHANGES" if n_changed == 0 else "VALID")

    return {
        "candidate_col": candidate_col,
        "status": status,
        "is_identical": is_identical,
        "n_total": int(len(diff)),
        "n_changed": n_changed,
        "changed_ratio": round(changed_ratio, 6),
        "max_abs_diff_mw": round(max_abs_diff, 6),
        "mean_abs_diff_mw": round(mean_abs_diff, 6),
        "median_abs_diff_mw": round(median_abs_diff, 6),
        "mean_diff_mw": round(mean_diff, 6),
        "changed_sites": site_ids_changed,
        "require_diff_min": 1e-6,
        "pass": not is_invalid,
    }


def main():
    parser = argparse.ArgumentParser(description="候选列与 baseline 差异检查")
    parser.add_argument("--candidate-pkl", type=str, required=True,
                        help="包含候选列的预测 pickle 文件路径")
    parser.add_argument("--baseline-col", type=str, default="power_pred_final",
                        help="baseline 列名")
    parser.add_argument("--output-csv", type=str, default=None,
                        help="输出 CSV 路径（默认自动生成）")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    root = project_root()

    # 自动生成输出路径
    if args.output_csv is None:
        out_dir = root / cfg["paths"]["output_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        args.output_csv = str(out_dir / "round70_candidate_diff_check.csv")

    print(f"[INFO] 读取候选文件: {args.candidate_pkl}")
    df = pd.read_pickle(args.candidate_pkl)
    print(f"  总行数: {len(df):,}")

    # 识别所有候选列（排除已知非候选列）
    exclude_prefixes = [
        "time", "site_id", "split", "hour", "month", "dayofyear", "datetime",
        "power_mw", "capacity_mw", "latitude", "longitude", "y_norm",
        "state_label", "time_block", "active_threshold_mw",
        "baseline_norm", "residual_norm", "g_blend_pred", "clear_sky_ghi",
        "clear_sky_index", "scene_v151", "scene", "t2m_c", "tcc", "strd_wm2",
        "ssrd_wm2", "solar_elevation", "quality_score", "pr_median",
        "site_zero_ratio", "site_positive_count", "site_power_median",
        "site_power_p90", "n_sites", "alpha_pred", "idw_pred", "era5_pred",
        "g_base", "g_pred", "power_recon", "city_hourly_power_mw",
        "city_hourly_pred_mw", "eval_mask", "index",
    ]
    exclude_cols = set()
    for prefix in exclude_prefixes:
        for col in df.columns:
            if col == prefix or col.startswith(prefix):
                exclude_cols.add(col)

    # 只识别 Round70/71 候选列
    candidate_cols = [c for c in df.columns
                     if c.startswith("power_pred_round7") and not c.startswith("power_pred_round70_safe")]
    candidate_cols = sorted(set(candidate_cols))

    print(f"\n[INFO] 发现候选列: {candidate_cols}")

    rows = []
    for col in candidate_cols:
        result = check_candidate_diff(df, args.baseline_col, col)
        rows.append(result)
        status_icon = "✓" if result["pass"] else "✗"
        print(f"  {status_icon} {col}: {result['status']}  "
              f"max_abs_diff={result['max_abs_diff_mw']:.6f}  "
              f"mean_abs_diff={result['mean_abs_diff_mw']:.6f}  "
              f"changed_ratio={result['changed_ratio']:.4%}")

    result_df = pd.DataFrame(rows)
    result_df.to_csv(args.output_csv, index=False, encoding="utf-8-sig")
    print(f"\n[OK] 差异检查写出: {args.output_csv}")

    n_invalid = int((~result_df["pass"]).sum())
    print(f"\n总结: {len(rows)} 个候选列，{len(rows) - n_invalid} 有效，{n_invalid} 无效")
    if n_invalid > 0:
        print("  无效候选:")
        for _, r in result_df[~result_df["pass"]].iterrows():
            print(f"    - {r['candidate_col']}: {r['status']}")

    sys.exit(0 if n_invalid == 0 else 1)


if __name__ == "__main__":
    main()
