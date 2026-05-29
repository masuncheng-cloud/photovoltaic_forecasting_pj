#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包4（修订版v3）：多目标逐小时策略修正
============================================
核心思路：
  1. 策略选择基于验证集（split=="valid"），不在测试集上调参
  2. 多目标评分：50%城市相对误差 + 30%WAPE + 20%相关系数
  3. Guard保护：零恶化原则（WAPE/clipped_MAPE/bias方向均不允许恶化）
  4. 输出候选策略明细表，供审计追溯

数据划分（统一引用 split.py）：
  - train:  time < 2025-07-01
  - valid:  2025-07-01 <= time < 2025-09-01
  - test:   time >= 2025-09-01
"""
from __future__ import annotations

from pathlib import Path
import argparse
import functools
import sys
import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# pandas 3.x pickle 兼容 patch（pickle 由 pandas 2.x 创建）
# 延迟导入：在首次 pd.read_pickle 时自动注入
# ─────────────────────────────────────────────
_pandas_patched = False

def _ensure_pandas_patch():
    global _pandas_patched
    if _pandas_patched:
        return
    _pandas_patched = True
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _patch(self, *args, **kwargs):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patch
    except Exception:
        pass

# 替换 pd.read_pickle 为自动 patch 版本
_pd_read_pickle = pd.read_pickle

def _patched_read_pickle(*args, **kwargs):
    _ensure_pandas_patch()
    return _pd_read_pickle(*args, **kwargs)

pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

CANDIDATE_STRATEGIES = [
    "current", "baseline", "blend_50", "blend_30", "blend_70",
    "floor_base_0.5", "floor_base_0.8", "floor_base_1.0",
    "floor_blend_0.5", "floor_blend_0.7", "floor_blend_0.9",
]


def mape(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)


def clipped_mape(y_true, y_pred, cap, floor_ratio=0.05):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    denom = np.maximum(y_true[mask], floor_ratio * cap[mask])
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom) * 100)


def wape(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    if not mask.any():
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)


def mae(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))


def rmse(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))


def correlation(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.corrcoef(y_true[mask], y_pred[mask])[0, 1])


def bias_pct(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    if not mask.any():
        return np.nan
    return float((np.sum(y_pred[mask]) - np.sum(y_true[mask])) / np.sum(y_true[mask]) * 100)


def city_rel_err(y_true_sum, y_pred_sum):
    if not np.isfinite(y_true_sum) or y_true_sum <= 0:
        return np.nan
    return float(np.abs(y_pred_sum - y_true_sum) / y_true_sum * 100)


def apply_strategy(pred, baseline, p_base, strategy_name):
    if strategy_name == "current":
        return pred
    elif strategy_name == "baseline":
        return baseline
    elif strategy_name == "blend_50":
        return 0.5 * baseline + 0.5 * pred
    elif strategy_name == "blend_30":
        return 0.3 * baseline + 0.7 * pred
    elif strategy_name == "blend_70":
        return 0.7 * baseline + 0.3 * pred
    elif strategy_name == "floor_base_0.5":
        return np.maximum(pred, p_base * 0.5)
    elif strategy_name == "floor_base_0.8":
        return np.maximum(pred, p_base * 0.8)
    elif strategy_name == "floor_base_1.0":
        return np.maximum(pred, p_base * 1.0)
    elif strategy_name == "floor_blend_0.5":
        return np.maximum(pred, baseline * 0.5)
    elif strategy_name == "floor_blend_0.7":
        return np.maximum(pred, baseline * 0.7)
    elif strategy_name == "floor_blend_0.9":
        return np.maximum(pred, baseline * 0.9)
    return pred


def apply_guard(base_metrics, cand_metrics):
    forbid = False
    reasons = []
    base_wape = base_metrics.get("wape", 0) or 0
    cand_wape = cand_metrics.get("wape", 0) or 0
    if cand_wape > base_wape:
        forbid = True
        reasons.append(f"WAPE {base_wape:.2f}→{cand_wape:.2f}")
    base_cm = base_metrics.get("clipped_mape", 0) or 0
    cand_cm = cand_metrics.get("clipped_mape", 0) or 0
    if cand_cm > base_cm:
        forbid = True
        reasons.append(f"clipped_MAPE {base_cm:.2f}→{cand_cm:.2f}")
    base_bias = base_metrics.get("bias_pct", 0) or 0
    cand_bias = cand_metrics.get("bias_pct", 0) or 0
    if base_bias < 0 and cand_bias > 0:
        forbid = True
        reasons.append(f"bias翻转 {base_bias:+.2f}→{cand_bias:+.2f}")
    return forbid, "; ".join(reasons) if reasons else ""


def multi_objective_score(metrics, forbid=False):
    if forbid:
        return float("inf")
    corr_val = max(float(metrics.get("corr", 0) or 0), 0)
    corr_err = (1 - corr_val) * 100
    return (
        0.50 * float(metrics.get("city_rel_err", 0) or 0)
        + 0.30 * float(metrics.get("wape", 0) or 0)
        + 0.20 * corr_err
    )


def evaluate_candidate(sub, yp_candidate):
    yt = sub["power_mw"].to_numpy(dtype=float)
    cap = sub["capacity_mw"].to_numpy(dtype=float)
    return {
        "city_rel_err": city_rel_err(yt.sum(), yp_candidate.sum()),
        "bias_pct": bias_pct(yt, yp_candidate),
        "wape": wape(yt, yp_candidate),
        "mae": mae(yt, yp_candidate),
        "clipped_mape": clipped_mape(yt, yp_candidate, cap),
        "corr": correlation(yt, yp_candidate),
        "mape": mape(yt, yp_candidate),
        "rmse": rmse(yt, yp_candidate),
    }


def fit_hourly_bias_strategy(valid_df):
    rows_selected = []
    rows_candidates = []
    for h in range(6, 20):
        sub = valid_df[valid_df["hour"] == h].copy()
        if len(sub) == 0:
            continue
        yt = sub["power_mw"].values.astype(float)
        yp = sub["power_pred"].values.astype(float)
        yb = pd.to_numeric(sub["pred_baseline"], errors="coerce").fillna(0).values
        pb = pd.to_numeric(sub["p_base"], errors="coerce").fillna(0).values
        cap = sub["capacity_mw"].values.astype(float)

        base_metrics = evaluate_candidate(sub, yp)
        base_score = multi_objective_score(base_metrics)

        best_score = base_score
        best_name = "current"
        best_metrics = base_metrics
        best_forbid, best_reason = False, ""

        for strat_name in CANDIDATE_STRATEGIES:
            yp_new = apply_strategy(yp, yb, pb, strat_name) if strat_name != "current" else yp
            cand_metrics = evaluate_candidate(sub, yp_new)
            forbid, reason = apply_guard(base_metrics, cand_metrics)
            score = multi_objective_score(cand_metrics, forbid=forbid)
            rows_candidates.append({
                "hour": h, "strategy": strat_name, "selection_split": "valid",
                "n_samples": len(sub), "forbidden": forbid, "forbid_reason": reason,
                "city_rel_err": cand_metrics.get("city_rel_err"),
                "bias_pct": cand_metrics.get("bias_pct"),
                "wape": cand_metrics.get("wape"),
                "mae": cand_metrics.get("mae"),
                "clipped_mape": cand_metrics.get("clipped_mape"),
                "corr": cand_metrics.get("corr"),
                "mape": cand_metrics.get("mape"),
                "score": score,
                "base_city_rel_err": base_metrics.get("city_rel_err"),
                "base_wape": base_metrics.get("wape"),
                "base_clipped_mape": base_metrics.get("clipped_mape"),
                "base_corr": base_metrics.get("corr"),
                "base_bias_pct": base_metrics.get("bias_pct"),
            })
            if score < best_score:
                best_score = score
                best_name = strat_name
                best_metrics = cand_metrics
                best_forbid, best_reason = forbid, reason

        rows_selected.append({
            "hour": h, "selected_strategy": best_name, "selection_split": "valid",
            "n_samples": len(sub),
            "selected_score": round(best_score, 4),
            "selected_forbidden": best_forbid, "guard_reason": best_reason,
            "valid_city_rel_err_before": round(base_metrics.get("city_rel_err", np.nan), 4),
            "valid_city_rel_err_after": round(best_metrics.get("city_rel_err", np.nan), 4),
            "valid_WAPE_before": round(base_metrics.get("wape", np.nan), 4),
            "valid_WAPE_after": round(best_metrics.get("wape", np.nan), 4),
            "valid_clipped_MAPE_before": round(base_metrics.get("clipped_mape", np.nan), 4),
            "valid_clipped_MAPE_after": round(best_metrics.get("clipped_mape", np.nan), 4),
            "valid_MAE_before": round(base_metrics.get("mae", np.nan), 4),
            "valid_bias_before": round(base_metrics.get("bias_pct", np.nan), 4),
            "valid_bias_after": round(best_metrics.get("bias_pct", np.nan), 4),
            "valid_corr_before": round(base_metrics.get("corr", np.nan), 4),
        })
    return pd.DataFrame(rows_selected), pd.DataFrame(rows_candidates)


def apply_hourly_bias_strategy(df, strategy_df):
    df = df.copy()
    df["power_pred_fixed"] = df["power_pred"].copy()
    for _, row in strategy_df.iterrows():
        h = int(row["hour"])
        mask = df["hour"] == h
        if not mask.any():
            continue
        sub = df.loc[mask]
        yp = sub["power_pred"].values.astype(float)
        yb = pd.to_numeric(sub["pred_baseline"], errors="coerce").fillna(0).values
        pb = pd.to_numeric(sub["p_base"], errors="coerce").fillna(0).values
        df.loc[mask, "power_pred_fixed"] = apply_strategy(yp, yb, pb, row["selected_strategy"])
    return df


def main():
    parser = argparse.ArgumentParser(description="多目标逐小时偏差修正")
    parser.add_argument("--input", default="distributed_predictions.pkl")
    parser.add_argument("--output", default="distributed_predictions_fixed.pkl")
    parser.add_argument("--valid-only", action="store_true")
    args = parser.parse_args()

    OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
    METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("多目标逐小时偏差修正 (v3)")
    print("=" * 70)

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = OUT_DIR / input_path
    if not input_path.exists():
        input_path = OUT_DIR / "distributed_predictions_v159.pkl"
    print(f"\n读取: {input_path}")
    pred_df = pd.read_pickle(input_path)
    print(f"原始数据: {len(pred_df):,} 行")

    from pv_forecasting.core.split import add_standard_split
    pred_df["time"] = pd.to_datetime(pred_df["time"])
    pred_df["year"] = pred_df["time"].dt.year
    pred_df["month"] = pred_df["time"].dt.month
    pred_df["date"] = pred_df["time"].dt.date
    pred_df["hour"] = pred_df["time"].dt.hour
    pred_df = add_standard_split(pred_df)
    print(f"\n数据划分:\n{pred_df['split'].value_counts()}")

    mask = (
        (pred_df["hour"] >= 6) & (pred_df["hour"] <= 19) &
        (pred_df["power_mw"] > 0) &
        (~pred_df["site_id"].isin(BAD_SITES)) &
        pred_df["power_mw"].notna() &
        pred_df["power_pred"].notna()
    )
    pred_df = pred_df[mask].copy()
    print(f"过滤后: {len(pred_df):,} 行")

    print("\n" + "=" * 70)
    print("Step 1: 多目标策略选择（验证集）")
    print("=" * 70)
    df_valid = pred_df[pred_df["split"] == "valid"].copy()
    print(f"验证集: {len(df_valid):,} 行")
    if len(df_valid) == 0:
        df_train = pred_df[pred_df["split"] == "train"].copy()
        if len(df_train) > 0:
            df_valid = df_train.tail(max(1000, len(df_train) // 5)).copy()
            print(f"备选验证集: {len(df_valid):,} 行")

    if len(df_valid) > 0:
        strategy_df, candidates_df = fit_hourly_bias_strategy(df_valid)
        print(f"\n选中策略:")
        print(strategy_df[["hour", "selected_strategy", "selected_score",
                          "valid_city_rel_err_before", "valid_city_rel_err_after",
                          "valid_WAPE_before", "valid_WAPE_after"]].to_string(index=False))
    else:
        print("[ERROR] 验证集为空")
        return

    candidates_df.to_csv(METRICS_DIR / "hourly_strategy_candidates_valid.csv",
                         index=False, encoding="utf-8-sig")
    print(f"\n保存候选: {METRICS_DIR / 'hourly_strategy_candidates_valid.csv'}")
    strategy_df.to_csv(METRICS_DIR / "hourly_strategy_valid_selected.csv",
                       index=False, encoding="utf-8-sig")
    print(f"保存选中: {METRICS_DIR / 'hourly_strategy_valid_selected.csv'}")

    print("\n" + "=" * 70)
    print("Step 2: 应用策略")
    print("=" * 70)
    pred_df = apply_hourly_bias_strategy(pred_df, strategy_df)

    print("\n" + "=" * 70)
    print("Step 3: 测试集评估")
    print("=" * 70)
    df_test = pred_df[pred_df["split"] == "test"].copy()
    print(f"测试集: {len(df_test):,} 行")
    if len(df_test) > 0:
        rows = []
        for h in range(6, 20):
            sub = df_test[df_test["hour"] == h].copy()
            if len(sub) == 0:
                continue
            yt = sub["power_mw"].values.astype(float)
            yp_orig = sub["power_pred"].values.astype(float)
            yp_fix = sub["power_pred_fixed"].values.astype(float)
            cap = sub["capacity_mw"].values.astype(float)
            curr_rel = city_rel_err(yt.sum(), yp_orig.sum())
            fix_rel = city_rel_err(yt.sum(), yp_fix.sum())
            curr_wape = wape(yt, yp_orig)
            fix_wape = wape(yt, yp_fix)
            curr_cm = clipped_mape(yt, yp_orig, cap)
            fix_cm = clipped_mape(yt, yp_fix, cap)
            curr_bias = bias_pct(yt, yp_orig)
            fix_bias = bias_pct(yt, yp_fix)
            curr_corr = correlation(yt, yp_orig)
            fix_corr = correlation(yt, yp_fix)
            rows.append({
                "hour": h, "n_samples": len(sub),
                "test_rel_err_before": round(curr_rel, 4),
                "test_rel_err_after": round(fix_rel, 4),
                "test_improvement": round(curr_rel - fix_rel, 4),
                "test_WAPE_before": round(curr_wape, 4),
                "test_WAPE_after": round(fix_wape, 4),
                "test_clipped_MAPE_before": round(curr_cm, 4),
                "test_clipped_MAPE_after": round(fix_cm, 4),
                "test_bias_before": round(curr_bias, 4),
                "test_bias_after": round(fix_bias, 4),
                "test_corr_before": round(curr_corr, 4),
                "test_corr_after": round(fix_corr, 4),
            })
        df_test_results = pd.DataFrame(rows)
        print(df_test_results.to_string(index=False))

        periods = [("dawn", 6, 7), ("morning", 8, 9), ("midday", 10, 14),
                   ("afternoon", 15, 16), ("dusk", 17, 19)]
        print("\n按时段汇总:")
        for name, hs, he in periods:
            sub = df_test_results[df_test_results["hour"].between(hs, he)]
            if len(sub) == 0:
                continue
            b_rel = sub["test_rel_err_before"].mean()
            a_rel = sub["test_rel_err_after"].mean()
            b_wape = sub["test_WAPE_before"].mean()
            a_wape = sub["test_WAPE_after"].mean()
            print(f"  {name:>10}: rel {b_rel:.2f}%→{a_rel:.2f}% ({b_rel-a_rel:+.2f}%)  "
                  f"WAPE {b_wape:.2f}%→{a_wape:.2f}% ({b_wape-a_wape:+.2f}%)")
        df_test_results.to_csv(METRICS_DIR / "hourly_bias_test_results.csv",
                               index=False, encoding="utf-8-sig")

    if not args.valid_only:
        print("\n" + "=" * 70)
        print("Step 4: 保存预测")
        print("=" * 70)
        pred_df["power_pred_original"] = pred_df["power_pred"].copy()
        pred_df["power_pred"] = pred_df["power_pred_fixed"].copy()
        pred_df = pred_df.drop(columns=["power_pred_fixed"])
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = OUT_DIR / out_path
        pred_df.to_pickle(out_path)
        print(f"保存: {out_path} ({len(pred_df):,} 行)")

    print("\n" + "=" * 70)
    print("完成！")
    print("=" * 70)
    print("多目标权重: city_rel_err×0.50 + WAPE×0.30 + (1-Corr)×0.20")
    print("Guard规则: 零恶化（WAPE/clipped_MAPE/bias方向均不允许恶化）")


if __name__ == "__main__":
    main()
