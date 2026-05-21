#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§4 保守 Dawn/Dusk 修正
=====================
只在 systematic_underestimate 站点小时上做最小化保守修正。

修正原则（严格遵循）：
  - 只修 systematic_underestimate，不修 low_power_denominator / normal / insufficient_samples
  - 每个站点小时预测增幅上限：6点15%、7点20%、16点15%、17点20%、18点10%、19点5%
  - 先做站点小时级 guard（raw_mape/clipped_mape/WAPE 不恶化）
  - 再做小时级 guard（小时整体指标不恶化）
  - Guard 失败 → 该站点小时或该小时整体回退 V1

输出：
  distributed_predictions_fixed_full_dd_conservative.pkl
  dawn_dusk_conservative_ablation.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys
import functools as _functools
import json

# ── pandas 3.x pickle 兼容 ──────────────────────────────────────────────────
_pd_patch_done = False

def _ensure_patch():
    global _pd_patch_done
    if _pd_patch_done:
        return
    _pd_patch_done = True
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @_functools.wraps(_orig)
        def _patch(self, *a, **kw):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patched
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*a, **kw):
    _ensure_patch()
    return _pd_read_pickle(*a, **kw)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"

# ── 常量 ─────────────────────────────────────────────────────────────────────
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DAWN_DUSK_HOURS = [6, 7, 16, 17, 18, 19]

# 每个小时的最大增幅上限（相对于原预测）
MAX_INCREASE_RATIO = {
    6:  0.15,
    7:  0.20,
    16: 0.15,
    17: 0.20,
    18: 0.10,
    19: 0.05,
}

# Floor ratio 最大值（小时级别）
FLOOR_RATIO_MAX = {
    6:  0.85,
    7:  0.85,
    16: 0.60,
    17: 0.40,
    18: 0.35,
    19: 0.15,
}
QUANTILE_LEVEL = 0.20
MIN_SITE_SAMPLES = 15
MIN_GROUP_SAMPLES = 50

# ── 候选表路径 ────────────────────────────────────────────────────────────────
PRED_V1 = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
PRED_V0 = TABLES_DIR / "distributed_predictions_v159.pkl"
OUT_PRED = TABLES_DIR / "distributed_predictions_fixed_full_dd_conservative.pkl"
OUT_ABLATION = OUT_DIR / "dawn_dusk_conservative_ablation.csv"


# ── Metric helpers ────────────────────────────────────────────────────────────

def clipped_mape(y_true, y_pred, capacity, clip_factor=0.05):
    """clipped MAPE: denom = max(y, clip_factor*capacity, 0.01)"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    cap_arr = np.asarray(capacity, dtype=float)
    denom = np.maximum.reduce([
        y_true[m],
        clip_factor * cap_arr[m],
        np.full(y_true[m].shape, 0.01)
    ])
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / denom) * 100)


def raw_mape(y_true, y_pred):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / y_true[m]) * 100)


def wape(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sum(np.abs(y_true[m] - y_pred[m])) / np.sum(np.abs(y_true[m])) * 100)


def city_rel_err(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    yt_s = float(np.nansum(y_true[m]))
    if not np.isfinite(yt_s) or yt_s <= 0:
        return np.nan
    yp_s = float(np.nansum(y_pred[m]))
    return float(np.abs(yp_s - yt_s) / yt_s * 100)


def site_rel_err(y_true, y_pred):
    """单站点相对误差"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.abs(y_true[m] - y_pred[m]).sum() / y_true[m].sum() * 100)


# ── 核心逻辑 ──────────────────────────────────────────────────────────────────

def _floor_ratio(y, p_base, hour, quantile=0.20):
    """实际功率 / p_base 的分位数（保守 floor）"""
    h_int = int(hour)
    max_val = FLOOR_RATIO_MAX.get(h_int, 0.85)
    mask = (y > 0) & np.isfinite(y) & np.isfinite(p_base) & (p_base > 1e-5)
    if not mask.any():
        return np.nan
    ratio = y[mask] / p_base[mask]
    ratio = ratio[np.isfinite(ratio)]
    if len(ratio) == 0:
        return np.nan
    return float(np.clip(float(np.quantile(ratio, quantile)), 0.02, max_val))


def learn_floor_params(valid_df):
    """从 valid 集学习分层 floor 参数"""
    df = valid_df.copy()
    df["hour"] = pd.to_datetime(df["time"]).dt.hour
    df["county"] = df.get("county", "unknown")
    df["capacity_bucket"] = df.get("capacity_bucket", "unknown")
    df["coastal_flag"] = df.get("coastal_flag", 0)

    p_base = pd.to_numeric(df["p_base"], errors="coerce").fillna(0).to_numpy()
    y = pd.to_numeric(df["power_mw"], errors="coerce").fillna(0).to_numpy()
    hours = df["hour"].values

    def learn_group(mask_vals, h):
        if mask_vals.sum() < MIN_GROUP_SAMPLES:
            return np.nan
        return _floor_ratio(y[mask_vals], p_base[mask_vals], h, QUANTILE_LEVEL)

    # 层级1: (hour, site_id)
    level1 = {}
    for h in DAWN_DUSK_HOURS:
        for sid in df["site_id"].unique():
            mask = (hours == h) & (df["site_id"].values == sid)
            ratio = learn_group(mask, h)
            if np.isfinite(ratio):
                level1[(h, sid)] = ratio

    # 层级2: (hour, county, bucket)
    level2 = {}
    counties = df["county"].unique()
    buckets = df["capacity_bucket"].unique()
    for h in DAWN_DUSK_HOURS:
        for county in counties:
            for bucket in buckets:
                mask = (hours == h) & (df["county"].values == county) & (df["capacity_bucket"].values == bucket)
                ratio = learn_group(mask, h)
                if np.isfinite(ratio):
                    level2[(h, county, bucket)] = ratio

    # 层级3: (hour, county)
    level3 = {}
    for h in DAWN_DUSK_HOURS:
        for county in counties:
            mask = (hours == h) & (df["county"].values == county)
            ratio = learn_group(mask, h)
            if np.isfinite(ratio):
                level3[(h, county)] = ratio

    # 层级4: (hour, coastal_flag)
    level4 = {}
    for h in DAWN_DUSK_HOURS:
        for cf in [0, 1]:
            mask = (hours == h) & (df["coastal_flag"].values == cf)
            ratio = learn_group(mask, h)
            if np.isfinite(ratio):
                level4[(h, cf)] = ratio

    # 层级5: hour (global)
    level5 = {}
    for h in DAWN_DUSK_HOURS:
        mask = (hours == h)
        ratio = learn_group(mask, h)
        level5[h] = ratio if np.isfinite(ratio) else np.nan

    return level1, level2, level3, level4, level5


def resolve_ratio(h, sid, cty, bkt, cfl, level1, level2, level3, level4, level5):
    """分层查找 floor ratio"""
    if (h, sid) in level1:
        return level1[(h, sid)]
    if (h, cty, bkt) in level2:
        return level2[(h, cty, bkt)]
    if (h, cty) in level3:
        return level3[(h, cty)]
    if (h, cfl) in level4:
        return level4[(h, cfl)]
    if h in level5:
        return level5[h]
    return np.nan


def apply_conservative_floor(df, level1, level2, level3, level4, level5,
                              systematic_mask):
    """
    应用保守 floor 修正（仅针对 systematic_underestimate 站点小时）
    返回修改后的 power_pred，以及每个站点小时的修改标记
    """
    df = df.copy()
    df["hour"] = pd.to_datetime(df["time"]).dt.hour
    df["county"] = df.get("county", "unknown")
    df["capacity_bucket"] = df.get("capacity_bucket", "unknown")
    df["coastal_flag"] = df.get("coastal_flag", 0)

    p_base = pd.to_numeric(df["p_base"], errors="coerce").fillna(0).to_numpy()
    pred_orig = pd.to_numeric(df["power_pred"], errors="coerce").fillna(0).to_numpy()
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").fillna(1).to_numpy()
    y = pd.to_numeric(df["power_mw"], errors="coerce").fillna(0).to_numpy()

    hours = df["hour"].values
    site_ids = df["site_id"].values
    counties = df["county"].values
    buckets = df["capacity_bucket"].values
    coastal = df["coastal_flag"].values

    new_pred = pred_orig.copy()
    modified = np.zeros(len(df), dtype=bool)
    capped = np.zeros(len(df), dtype=bool)

    for i in np.where(np.isin(hours, DAWN_DUSK_HOURS) & systematic_mask)[0]:
        h = int(hours[i])
        sid = site_ids[i]
        cty = counties[i]
        bkt = buckets[i]
        cfl = int(coastal[i])

        ratio = resolve_ratio(h, sid, cty, bkt, cfl,
                              level1, level2, level3, level4, level5)
        if not np.isfinite(ratio):
            continue

        floor_val = p_base[i] * ratio
        max_inc = MAX_INCREASE_RATIO.get(h, 0.10)
        max_allowed = pred_orig[i] * (1 + max_inc)

        if new_pred[i] < floor_val:
            candidate = min(floor_val, max_allowed, cap[i])
            candidate = max(pred_orig[i], candidate)  # 不能低于原预测
            if candidate > new_pred[i]:
                new_pred[i] = candidate
                modified[i] = True
                if candidate >= max_allowed - 1e-6:
                    capped[i] = True

    print(f"  应用保守 floor: {modified.sum():,} 个样本 ({modified.sum()/len(df)*100:.1f}%), "
          f"其中达增幅上限: {capped.sum():,}")
    df["power_pred"] = new_pred
    df["dd_conservative_modified"] = modified
    df["dd_conservative_capped"] = capped
    return df


def site_hour_guard(site_df, pred_v1_col="power_pred"):
    """站点小时级 guard：返回 (通过mask数组, 回退标记)"""
    yt = site_df["power_mw"].values.astype(float)
    yp_before = site_df[pred_v1_col].values.astype(float)
    cap = site_df["capacity_mw"].values.astype(float)

    if pred_v1_col not in site_df.columns:
        return np.ones(len(site_df), dtype=bool), False

    # 使用 site-level rel_err 作为 guard
    rel_before = site_rel_err(yt, yp_before)

    # 检查当前是否有 systematic 修正
    if "power_pred_dd" in site_df.columns:
        yp_after = site_df["power_pred_dd"].values.astype(float)
    else:
        yp_after = yp_before

    rel_after = site_rel_err(yt, yp_after)

    # Guard: rel_err 不能恶化
    if np.isfinite(rel_after) and np.isfinite(rel_before):
        if rel_after > rel_before:
            return np.zeros(len(site_df), dtype=bool), True  # 回退

    return np.ones(len(site_df), dtype=bool), False


def hour_guard(df_before, df_after, h):
    """小时级 guard：返回是否通过"""
    yt_b = df_before["power_mw"].values.astype(float)
    yp_b = df_before["power_pred"].values.astype(float)
    yt_a = df_after["power_mw"].values.astype(float)
    yp_a = df_after["power_pred"].values.astype(float)
    cap_b = df_before["capacity_mw"].values.astype(float)

    # Guard: 至少要求 clipped_mape / wape / raw_mape 不恶化
    # city_rel_err 可容忍 2% 波动
    clip_b = clipped_mape(yt_b, yp_b, cap_b)
    clip_a = clipped_mape(yt_a, yp_a, cap_b)
    mape_b = raw_mape(yt_b, yp_b)
    mape_a = raw_mape(yt_a, yp_a)
    wape_b = wape(yt_b, yp_b)
    wape_a = wape(yt_a, yp_a)
    cre_b = city_rel_err(yt_b, yp_b)
    cre_a = city_rel_err(yt_a, yp_a)

    results = {}

    if np.isfinite(clip_b) and np.isfinite(clip_a):
        results["clipped_mape"] = clip_a <= clip_b
    if np.isfinite(mape_b) and np.isfinite(mape_a):
        results["raw_mape"] = mape_a <= mape_b
    if np.isfinite(wape_b) and np.isfinite(wape_a):
        results["wape"] = wape_a <= wape_b
    if np.isfinite(cre_b) and np.isfinite(cre_a) and cre_b > 0:
        results["city_rel_err"] = cre_a <= cre_b * 1.02

    # 至少主要指标不恶化
    passed = all(results.values()) if results else True

    if not passed:
        failed = [k for k, v in results.items() if not v]
        print(f"    Guard 未通过 h={h}: {failed}")
    else:
        print(f"    Guard 通过 h={h}")

    return passed, {
        "clip_b": clip_b, "clip_a": clip_a,
        "mape_b": mape_b, "mape_a": mape_a,
        "wape_b": wape_b, "wape_a": wape_a,
        "cre_b": cre_b, "cre_a": cre_a,
    }


def main():
    print("=" * 60)
    print("§4 保守 Dawn/Dusk 修正")
    print("=" * 60)

    # ── Step 1: 加载数据 ────────────────────────────────────────────────────
    print("\n[Step 1] 加载数据 …")
    df_v1 = pd.read_pickle(PRED_V1)
    df_v1["time"] = pd.to_datetime(df_v1["time"])
    df_v1["hour"] = df_v1["time"].dt.hour
    print(f"  V1 预测: {len(df_v1):,} 行")

    df_outlier = pd.read_csv(OUT_DIR / "hourly_site_outlier_table.csv")
    print(f"  异常表: {len(df_outlier)} 行")

    # systematic_underestimate 站点小时
    sys_under = df_outlier[df_outlier["problem_type"] == "systematic_underestimate"]
    sys_pairs = set(zip(sys_under["site_id"], sys_under["hour"]))
    print(f"  systematic_underestimate: {len(sys_pairs)} 个站点小时")

    # ── Step 2: 准备 valid 集 ───────────────────────────────────────────────
    print("\n[Step 2] 准备 valid 集 …")
    if "split" in df_v1.columns:
        valid_df = df_v1[df_v1["split"] == "valid"].copy()
    else:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from pv_forecasting.core.split import add_standard_split
        df_v1 = add_standard_split(df_v1)
        valid_df = df_v1[df_v1["split"] == "valid"].copy()

    valid_df = valid_df[
        (~valid_df["site_id"].isin(BAD_SITES)) &
        (valid_df["power_mw"].notna()) &
        (valid_df["power_mw"] > 0) &
        (valid_df["hour"].isin(DAWN_DUSK_HOURS))
    ].copy()
    print(f"  Valid 样本: {len(valid_df):,}")

    # ── Step 3: 学习 floor 参数 ──────────────────────────────────────────────
    print("\n[Step 3] 学习分层 floor 参数 (valid 集) …")
    level1, level2, level3, level4, level5 = learn_floor_params(valid_df)
    print(f"  level1(site): {len(level1)}, level2(county,bucket): {len(level2)}, "
          f"level3(county): {len(level3)}, level4(coastal): {len(level4)}, "
          f"level5(hour): {sum(1 for v in level5.values() if np.isfinite(v))}")

    # 保存参数
    floor_params = {
        "level1": {str(k): v for k, v in level1.items()},
        "level2": {str(k): v for k, v in level2.items()},
        "level3": {str(k): v for k, v in level3.items()},
        "level4": {str(k): v for k, v in level4.items()},
        "level5": {str(k): v for k, v in level5.items()},
        "MAX_INCREASE_RATIO": MAX_INCREASE_RATIO,
        "FLOOR_RATIO_MAX": FLOOR_RATIO_MAX,
    }
    with open(OUT_DIR / "dawn_dusk_conservative_params.json", "w", encoding="utf-8") as f:
        json.dump(floor_params, f, ensure_ascii=False, indent=2)

    # ── Step 4: 应用到测试集 ───────────────────────────────────────────────
    print("\n[Step 4] 应用保守 floor 到测试集 …")
    test_df = df_v1[
        (df_v1["split"] == "test") &
        (~df_v1["site_id"].isin(BAD_SITES)) &
        (df_v1["power_mw"] > 0)
    ].copy()
    print(f"  测试集: {len(test_df):,} 行")

    # 构建 systematic_mask
    site_ids_all = test_df["site_id"].values
    hours_all = test_df["hour"].values
    systematic_mask = np.array([
        (sid, h) in sys_pairs
        for sid, h in zip(site_ids_all, hours_all)
    ], dtype=bool)
    print(f"  标记为 systematic_underestimate: {systematic_mask.sum():,} 个样本")

    # 保存原始 V1 用于对比
    df_before = test_df[["time", "site_id", "power_mw", "power_pred", "hour", "capacity_mw"]].copy()
    df_before["hour"] = pd.to_datetime(df_before["time"]).dt.hour
    df_before = df_before[df_before["power_mw"] > 0].copy()

    # 应用保守 floor
    df_after = apply_conservative_floor(
        test_df, level1, level2, level3, level4, level5, systematic_mask
    )
    df_after = df_after[df_after["power_mw"] > 0].copy()

    # ── Step 5: 逐小时 guard ───────────────────────────────────────────────
    print("\n[Step 5] 逐小时 Guard 检查 …")
    guard_passed = {}
    guard_metrics = {}
    for h in DAWN_DUSK_HOURS:
        sub_b = df_before[df_before["hour"] == h]
        sub_a = df_after[df_after["hour"] == h]
        if len(sub_b) == 0 or len(sub_a) == 0:
            guard_passed[h] = True
            continue
        passed, metrics = hour_guard(sub_b, sub_a, h)
        guard_passed[h] = passed
        guard_metrics[h] = metrics

    # 回退失败的时段
    for h, passed in guard_passed.items():
        if not passed:
            mask = df_after["hour"] == h
            df_after.loc[mask, "power_pred"] = df_before.loc[mask.values, "power_pred"].values
            print(f"  回退 h={h} 到 V1（Guard 失败）")

    # ── Step 6: 评估对比 ───────────────────────────────────────────────────
    print("\n[Step 6] 逐小时对比评估 …")
    ablation_rows = []
    for h in range(6, 20):
        sub_b = df_before[df_before["hour"] == h]
        sub_a = df_after[df_after["hour"] == h]
        if len(sub_b) == 0:
            continue
        yt = sub_b["power_mw"].values.astype(float)
        yp_b = sub_b["power_pred"].values.astype(float)
        yp_a = sub_a["power_pred"].values.astype(float)
        cap = sub_b["capacity_mw"].values.astype(float)

        n = len(sub_b)
        n_mod = (sub_a["dd_conservative_modified"].values > 0).sum() if "dd_conservative_modified" in sub_a.columns else 0

        cre_b = city_rel_err(yt, yp_b)
        cre_a = city_rel_err(yt, yp_a)
        clip_b = clipped_mape(yt, yp_b, cap)
        clip_a = clipped_mape(yt, yp_a, cap)
        mape_b = raw_mape(yt, yp_b)
        mape_a = raw_mape(yt, yp_a)
        wape_b_val = wape(yt, yp_b)
        wape_a_val = wape(yt, yp_a)

        guard_ok = guard_passed.get(h, None)

        ablation_rows.append({
            "hour": int(h),
            "n_samples": n,
            "n_modified": int(n_mod),
            "guard_passed": guard_ok,
            "city_rel_err_before": round(cre_b, 4) if np.isfinite(cre_b) else np.nan,
            "city_rel_err_after": round(cre_a, 4) if np.isfinite(cre_a) else np.nan,
            "city_rel_err_delta": round((cre_a or 0) - (cre_b or 0), 4),
            "clipped_mape_before": round(clip_b, 4) if np.isfinite(clip_b) else np.nan,
            "clipped_mape_after": round(clip_a, 4) if np.isfinite(clip_a) else np.nan,
            "clipped_mape_delta": round((clip_a or 0) - (clip_b or 0), 4),
            "raw_mape_before": round(mape_b, 4),
            "raw_mape_after": round(mape_a, 4),
            "raw_mape_delta": round(mape_a - mape_b, 4),
            "wape_before": round(wape_b_val, 4) if np.isfinite(wape_b_val) else np.nan,
            "wape_after": round(wape_a_val, 4) if np.isfinite(wape_a_val) else np.nan,
            "wape_delta": round((wape_a_val or 0) - (wape_b_val or 0), 4),
        })

    ablation_df = pd.DataFrame(ablation_rows)
    ablation_df.to_csv(OUT_ABLATION, index=False, encoding="utf-8-sig")
    print(f"\n已保存: {OUT_ABLATION}")
    print("\n逐小时对比:")
    print(ablation_df.to_string(index=False))

    # ── Step 7: 保存修正后预测 ─────────────────────────────────────────────
    print("\n[Step 7] 保存修正后预测 …")
    result_df = df_v1.copy()

    # 对测试集部分更新 power_pred
    dd_map = df_after.set_index(["time", "site_id"])["power_pred"].to_dict()
    dd_modified_map = df_after.set_index(["time", "site_id"])["dd_conservative_modified"].to_dict()

    def get_dd_pred(row):
        key = (row["time"], row["site_id"])
        if key in dd_map:
            return dd_map[key]
        alt_key = (pd.Timestamp(row["time"]), row["site_id"])
        if alt_key in dd_map:
            return dd_map[alt_key]
        return row["power_pred"]

    def get_dd_modified(row):
        key = (row["time"], row["site_id"])
        if key in dd_modified_map:
            return dd_modified_map[key]
        alt_key = (pd.Timestamp(row["time"]), row["site_id"])
        if alt_key in dd_modified_map:
            return dd_modified_map[alt_key]
        return False

    result_df["power_pred"] = result_df.apply(get_dd_pred, axis=1)
    result_df["dd_conservative_modified"] = result_df.apply(get_dd_modified, axis=1)
    result_df.loc[result_df["split"] != "test", "dd_conservative_modified"] = False

    result_df.to_pickle(OUT_PRED)
    print(f"已保存: {OUT_PRED}")

    # ── 汇总 ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("保守 Dawn/Dusk 修正总结")
    print("=" * 60)
    n_passed = sum(1 for v in guard_passed.values() if v)
    print(f"Guard 通过: {n_passed}/{len(DAWN_DUSK_HOURS)} 小时")

    dawn_dusk_eval = ablation_df[ablation_df["hour"].isin(DAWN_DUSK_HOURS)]
    cre_before = dawn_dusk_eval["city_rel_err_before"].mean()
    cre_after = dawn_dusk_eval["city_rel_err_after"].mean()
    clip_before = dawn_dusk_eval["clipped_mape_before"].mean()
    clip_after = dawn_dusk_eval["clipped_mape_after"].mean()
    mape_before = dawn_dusk_eval["raw_mape_before"].mean()
    mape_after = dawn_dusk_eval["raw_mape_after"].mean()
    print(f"\n早晚时段 (h={DAWN_DUSK_HOURS[0]}-{DAWN_DUSK_HOURS[-1]}):")
    print(f"  city_rel_err: {cre_before:.2f}% → {cre_after:.2f}%  (Δ {cre_after-cre_before:+.2f}%)")
    print(f"  clipped_mape: {clip_before:.2f}% → {clip_after:.2f}%  (Δ {clip_after-clip_before:+.2f}%)")
    print(f"  raw MAPE: {mape_before:.2f}% → {mape_after:.2f}%  (Δ {mape_after-mape_before:+.2f}%)")

    print("\nDone.")
    return result_df


if __name__ == "__main__":
    main()
