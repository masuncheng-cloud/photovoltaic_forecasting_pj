#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建分布式预测结果表
====================
输出两类表（分离完整预测与评估子集）：
  - distributed_predictions_fixed_full.pkl：完整预测结果，不过滤小时/功率
  - distributed_predictions_fixed_eval.pkl：评估专用子集，过滤6-19点/有功率/排除BAD
  - distributed_predictions_fixed.pkl：兼容旧脚本，等同于 eval 表
同时生成 prediction_table_summary.json 记录统计信息。

数据划分（统一引用 split.py）：
  - train:  time < 2025-07-01
  - valid:  2025-07-01 <= time < 2025-09-01
  - test:   time >= 2025-09-01
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

# pandas 3.x pickle 兼容 patch
_patch_done = False

def _apply_pd_patch():
    global _patch_done
    if _patch_done:
        return
    _patch_done = True
    try:
        import functools
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _p(self, *a, **kw):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _p
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*a, **kw):
    _apply_pd_patch()
    return _pd_read_pickle(*a, **kw)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def add_scene_label(df):
    """添加场景标签"""
    df = df.copy()
    elev_valid = (
        "solar_elevation_deg" in df.columns
        and df["solar_elevation_deg"].std() > 0
    )

    def get_scene(row):
        hour = row.get("hour", 12)
        elev = row.get("solar_elevation_deg", None)
        if elev_valid and elev is not None and elev > 0:
            if hour in (6, 7): return "dawn"
            if hour in (18, 19): return "dusk"
            if hour in (8, 9): return "morning"
            if hour in (15, 16): return "afternoon"
            if hour in (10, 11, 12, 13, 14): return "midday"
            return "normal"
        if hour in (6, 7): return "dawn"
        if hour in (18, 19): return "dusk"
        if hour in (8, 9): return "morning"
        if hour in (15, 16): return "afternoon"
        if hour in (10, 11, 12, 13, 14): return "midday"
        return "night"

    df["scene_label"] = df.apply(get_scene, axis=1)
    return df


def build_eval_summary(full_df, eval_df):
    """构建预测表摘要 JSON"""
    def vc(series):
        return {str(k): int(v) for k, v in series.value_counts().items()}

    return {
        "full_rows": int(len(full_df)),
        "eval_rows": int(len(eval_df)),
        "full_hour_min": int(full_df["hour"].min()),
        "full_hour_max": int(full_df["hour"].max()),
        "eval_hour_min": int(eval_df["hour"].min()),
        "eval_hour_max": int(eval_df["hour"].max()),
        "full_site_count": int(full_df["site_id"].nunique()),
        "eval_site_count": int(eval_df["site_id"].nunique()),
        "full_time_min": str(full_df["time"].min()),
        "full_time_max": str(full_df["time"].max()),
        "eval_time_min": str(eval_df["time"].min()),
        "eval_time_max": str(eval_df["time"].max()),
        "split_counts_full": vc(full_df["split"]),
        "split_counts_eval": vc(eval_df["split"]),
        "eval_conditions": {
            "hour_range": [6, 19],
            "power_mw_positive": True,
            "exclude_bad_sites": list(sorted(BAD_SITES)),
            "note": "此表为评估子集，不是完整预测表"
        },
    }


def main():
    print("=" * 70)
    print("重建分布式预测结果表（full / eval 分离）")
    print("=" * 70)

    # ─── 1. 加载原始预测 ───────────────────────────────────────────────────
    input_path = OUT_DIR / "distributed_predictions.pkl"
    if not input_path.exists():
        input_path = OUT_DIR / "distributed_predictions_v159.pkl"
    print(f"\n读取: {input_path}")
    df = pd.read_pickle(input_path)
    print(f"原始数据: {len(df):,} 行, {len(df.columns)} 字段")

    # ─── 2. 添加时间字段 + 统一划分 ───────────────────────────────────────
    print("\n添加必需字段...")
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["year"] = df["time"].dt.year
    df["month"] = df["time"].dt.month
    df["date"] = df["time"].dt.date

    from pv_forecasting.core.split import add_standard_split
    df = add_standard_split(df)
    df = add_scene_label(df)

    # 补充缺失字段
    if "power_pred_cal" not in df.columns:
        df["power_pred_cal"] = df.get("power_pred", 0.0)
    if "calibration_enabled" not in df.columns:
        df["calibration_enabled"] = False
    if "power_pred_original" not in df.columns:
        df["power_pred_original"] = df["power_pred"].copy()
    if "power_pred_site_fixed" not in df.columns:
        df["power_pred_site_fixed"] = df["power_pred"].copy()

    # ─── 3. 字段完整性检查 ────────────────────────────────────────────────
    required = [
        "time", "site_id", "county", "capacity_mw",
        "power_mw", "power_pred_original", "power_pred_site_fixed",
        "g_blend_pred", "clear_sky_ghi",
        "scene_label", "split", "hour",
    ]
    missing = [f for f in required if f not in df.columns]
    if missing:
        print(f"\n[WARN] 缺少字段: {missing}")
    else:
        print(f"\n[OK] 所有必需字段已包含")

    # ─── 4. 完整预测表（不过滤） ──────────────────────────────────────────
    df_full = df.copy()
    print(f"\n完整预测表:")
    print(f"  总行数: {len(df_full):,}")
    print(f"  小时范围: {df_full['hour'].min()} ~ {df_full['hour'].max()}")
    print(f"  时间范围: {df_full['time'].min()} ~ {df_full['time'].max()}")
    print(f"  站点数: {df_full['site_id'].nunique()}")
    print(f"  划分分布:")
    for s, cnt in df_full["split"].value_counts().sort_index().items():
        print(f"    {s}: {cnt:,}")

    # ─── 5. 评估子集表（过滤） ───────────────────────────────────────────
    eval_mask = (
        (df["hour"].between(6, 19))
        & df["power_mw"].notna()
        & (df["power_mw"] > 0)
        & (~df["site_id"].isin(BAD_SITES))
        & df["power_pred"].notna()
    )
    df_eval = df[eval_mask].copy()
    print(f"\n评估子集表:")
    print(f"  总行数: {len(df_eval):,}")
    print(f"  小时范围: {df_eval['hour'].min()} ~ {df_eval['hour'].max()}")
    print(f"  时间范围: {df_eval['time'].min()} ~ {df_eval['time'].max()}")
    print(f"  站点数: {df_eval['site_id'].nunique()}")
    print(f"  划分分布:")
    for s, cnt in df_eval["split"].value_counts().sort_index().items():
        print(f"    {s}: {cnt:,}")

    # ─── 6. 保存 ─────────────────────────────────────────────────────────
    full_path = OUT_DIR / "distributed_predictions_fixed_full.pkl"
    eval_path = OUT_DIR / "distributed_predictions_fixed_eval.pkl"
    compat_path = OUT_DIR / "distributed_predictions_fixed.pkl"

    df_full.to_pickle(full_path)
    print(f"\n[保存] 完整表: {full_path}  ({len(df_full):,} 行)")

    df_eval.to_pickle(eval_path)
    print(f"[保存] 评估子集: {eval_path}  ({len(df_eval):,} 行)")

    # 兼容旧脚本入口
    df_eval.to_pickle(compat_path)
    print(f"[保存] 兼容别名: {compat_path}  ({len(df_eval):,} 行)")
    print(f"  ⚠️ 注意：distributed_predictions_fixed.pkl 是评估子集，不是完整预测表")

    # ─── 7. 生成摘要 JSON ─────────────────────────────────────────────────
    summary = build_eval_summary(df_full, df_eval)
    json_path = METRICS_DIR / "prediction_table_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[保存] 预测表摘要: {json_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n" + "=" * 70)
    print("完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()
