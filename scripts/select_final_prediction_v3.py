#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终预测版本选择脚本（V3 — NRMSE 版）
=====================================
修复项（相比旧版）：
1. 主指标改为 NRMSE（替换 WAPE/MAPE）
2. 选择基于 valid 集 NRMSE（不得使用 test 集）
3. 使用统一 BAD_SITES（7 个异常站点）
4. 严格闭环：selected_version == V2 → power_pred == pred_v2
5. 输出 NRMSE 对比 CSV

Split 口径：train < 2025-07-01 < valid < 2025-09-01 <= test
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── pandas 3.x StringDtype pickle 兼容补丁 ──────────────────────────────────
_pd_read_pickle = pd.read_pickle

def _apply_pd_patch():
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _patched(self, *args, **kwargs):
            try:
                _orig(self, *args, **kwargs)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patched
    except Exception:
        pass

def _patched_read_pickle(*a, **kw):
    _apply_pd_patch()
    return _pd_read_pickle(*a, **kw)

pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from pv_forecasting.core.evaluation import (
    DEFAULT_BAD_SITES as BAD_SITES, build_eval_frame,
    site_hour_nrmse, city_hour_nrmse,
    wape,
)
from pv_forecasting.core.split import add_standard_split

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

ALL_HOURS = list(range(6, 20))
DAWN_DUSK = {6, 7, 17, 18, 19}


def _nrmse_score(sub, pred_col) -> float:
    """综合 NRMSE score（越低越好）：0.7*站点 + 0.3*城市。"""
    site_vals, city_vals = [], []
    for _, sg in sub.groupby("site_id"):
        nr = site_hour_nrmse(
            sg["power_mw"].values, sg[pred_col].values, sg["capacity_mw"].values)
        if np.isfinite(nr):
            site_vals.append(nr)
    cn = city_hour_nrmse(sub, pred_col)
    site_mean = float(np.nanmean(site_vals)) if site_vals else 100.0
    city_val = float(cn) if np.isfinite(cn) else 100.0
    return 0.7 * site_mean + 0.3 * city_val


def main():
    print("=" * 60)
    print("最终预测版本选择（V2 vs V3 — NRMSE 版）")
    print("=" * 60)

    # ── 1. 加载 V2 ────────────────────────────────────────────────────────────
    print("\n[1] 加载 V2 预测 …")
    v2 = pd.read_pickle(TABLES_DIR / "distributed_predictions_fixed_full.pkl")
    v2["time"] = pd.to_datetime(v2["time"])
    v2["hour"] = v2["time"].dt.hour
    v2["date"] = v2["time"].dt.date
    if "split" not in v2.columns:
        v2 = add_standard_split(v2)
    v2["pred_v2"] = v2["power_pred"].copy()
    print(f"  V2: {len(v2):,} 行, split={v2['split'].value_counts().to_dict()}")

    # ── 2. 加载 V3 ────────────────────────────────────────────────────────────
    print("\n[2] 加载 V3 预测 …")
    v3_path = TABLES_DIR / "distributed_predictions_v3_full.pkl"
    if not v3_path.exists():
        alt = TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl"
        if alt.exists():
            v3_path = alt
        else:
            print(f"[ERROR] V3 预测不存在: {v3_path} 或 {alt}")
            sys.exit(1)
    v3 = pd.read_pickle(v3_path)
    v3["time"] = pd.to_datetime(v3["time"])
    v3["hour"] = v3["time"].dt.hour
    if "split" not in v3.columns:
        v3 = add_standard_split(v3)
    # V3 预测列：power_pred_v3
    v3["pred_v3"] = v3["power_pred_v3"].copy() if "power_pred_v3" in v3.columns else v3["power_pred"].copy()
    print(f"  V3: {len(v3):,} 行")

    # ── 3. 合并 ────────────────────────────────────────────────────────────────
    print("\n[3] 合并 V2/V3 …")
    base = v2[["time", "site_id", "split", "power_mw",
               "pred_v2", "hour", "date", "capacity_mw"]].copy()
    v3_map = v3[["time", "site_id", "pred_v3"]].copy()
    base = base.merge(v3_map, on=["time", "site_id"], how="left")
    base["pred_v3"] = base["pred_v3"].fillna(base["pred_v2"])
    n_diff = int((base["pred_v2"] - base["pred_v3"]).abs().gt(1e-6).sum())
    print(f"  合并: {len(base):,} 行, V2≠V3 的行: {n_diff:,}")

    # ── 4. Valid 集选择 ──────────────────────────────────────────────────────
    print("\n[4] 按小时选择（valid 集 NRMSE）…")
    v_valid = build_eval_frame(base, pred_col="pred_v2", split="valid",
                                active_only=True, bad_sites=BAD_SITES)
    print(f"  Valid 样本: {len(v_valid):,}, 站点: {v_valid['site_id'].nunique()}")

    selection = {}
    for h in ALL_HOURS:
        sub = v_valid[v_valid["hour"] == h]
        if len(sub) == 0:
            selection[h] = ("V2", float("inf"), float("inf"), {}, {})
            continue
        v2_s = _nrmse_score(sub, "pred_v2")
        v3_s = _nrmse_score(sub, "pred_v3")
        if h in DAWN_DUSK:
            use_v3 = v3_s <= v2_s
        else:
            use_v3 = v3_s <= v2_s * 1.03
        ver = "V3" if use_v3 else "V2"
        selection[h] = (ver, v2_s, v3_s, {}, {})
        flag = "✓" if ver == "V3" else "回退"
        delta = v3_s - v2_s
        print(f"  h={h:02d}: {ver}  V2={v2_s:.2f}  V3={v3_s:.2f}  Δ={delta:+.2f} {flag}")

    # ── 5. 构建最终预测 ───────────────────────────────────────────────────────
    print("\n[5] 构建最终预测（严格闭环）…")
    base["power_pred"] = np.where(
        pd.Series([selection.get(h, ("V2", 0, 0))[0] == "V3" for h in base["hour"]], index=base.index),
        base["pred_v3"], base["pred_v2"]
    )

    # ── 6. 闭环校验 ──────────────────────────────────────────────────────────
    print("\n[6] 闭环校验 …")
    n_v2, n_v3, n_ok = 0, 0, 0
    for h in ALL_HOURS:
        ver = selection[h][0]
        sub = base[(base["split"] == "test") & (base["hour"] == h)]
        if len(sub) == 0:
            continue
        if ver == "V2":
            n_v2 += 1
            diff = float((sub["power_pred"] - sub["pred_v2"]).abs().max())
            ok = diff < 1e-4
            status = "✓" if ok else f"✗ diff={diff:.6f}"
            print(f"  h={h:02d} V2: {status}")
        else:
            n_v3 += 1
            diff = float((sub["power_pred"] - sub["pred_v3"]).abs().max())
            ok = diff < 1e-4
            status = "✓" if ok else f"✗ diff={diff:.6f}"
            print(f"  h={h:02d} V3: {status}")
        if not ok:
            print(f"  [ERROR] h={h} 闭环校验失败！power_pred ≠ pred_{ver.lower()}")
            sys.exit(1)

    # ── 7. 保存 ──────────────────────────────────────────────────────────────
    print("\n[7] 保存 …")
    full_out = TABLES_DIR / "distributed_predictions_final_full.pkl"
    base.to_pickle(full_out)
    print(f"  ✓ {full_out.name}")

    eval_out = TABLES_DIR / "distributed_predictions_final_eval.pkl"
    eval_df = build_eval_frame(base, pred_col="power_pred", split="test",
                                active_only=True, bad_sites=BAD_SITES)
    # build_eval_frame 不过滤 split 之外的列，补上 split 列
    eval_df["split"] = "test"
    eval_df.to_pickle(eval_out)
    print(f"  ✓ {eval_out.name}  ({len(eval_df):,} 行)")

    # ── 8. NRMSE 对比 CSV ────────────────────────────────────────────────────
    # 注：也由 regenerate_chinese_metrics.py 统一生成，这里兼容保留
    print("\n[8] NRMSE 对比 CSV（可由 regenerate_chinese_metrics.py 统一覆盖）…")
    cmp_out = METRICS_DIR / "hourly_nrmse_compare_v2_v3.csv"
    from pv_forecasting.core.evaluation import compare_two_versions

    test_eval = build_eval_frame(
        base,
        pred_col="power_pred",
        split="test",
        active_only=True,
        bad_sites=BAD_SITES,
    )

    cmp = compare_two_versions(
        test_eval,
        "pred_v2",
        "power_pred",
        version_labels=("V2", "Final"),
    )
    cmp.to_csv(cmp_out, index=False, encoding="utf-8-sig")
    print(f"  ✓ {cmp_out.name}")

    # ── 9. 选择表 CSV ───────────────────────────────────────────────────────
    print("\n[9] 保存选择表 …")
    rows = []
    for h in ALL_HOURS:
        ver, v2_s, v3_s, *_ = selection[h]
        rows.append({
            "hour": h,
            "selected_version": ver,
            "valid_v2_nrmse_score": round(v2_s, 4) if np.isfinite(v2_s) else np.nan,
            "valid_v3_nrmse_score": round(v3_s, 4) if np.isfinite(v3_s) else np.nan,
            "valid_delta_nrmse_score": round(v3_s - v2_s, 4) if np.isfinite(v3_s) and np.isfinite(v2_s) else np.nan,
        })
    sel_df = pd.DataFrame(rows)
    sel_out = METRICS_DIR / "final_model_selection_v3.csv"
    sel_df.to_csv(sel_out, index=False, encoding="utf-8-sig")
    print(f"  ✓ {sel_out.name}")

    # ── 汇总 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    n_v3_sel = sum(1 for v in selection.values() if v[0] == "V3")
    n_v2_sel = sum(1 for v in selection.values() if v[0] == "V2")
    print(f"选择结果: V3={n_v3_sel}/14, V2={n_v2_sel}/14")
    print("Done.")


if __name__ == "__main__":
    main()
