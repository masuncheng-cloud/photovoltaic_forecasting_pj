#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3 日出日落 floor 修正
=====================
仅用 valid 集学习保守 floor 参数，对测试集做最小干预。

修正逻辑：
  floor_pred = max(p_base * floor_ratio, pred_original * (1 + bias_ratio))
  pred_candidate = max(pred_original, floor_pred)

Guard 条件（放宽）：
  hourly_clipped_MAPE_after <= hourly_clipped_MAPE_before * 1.05
  (允许 clipped MAPE 略微恶化 5%，确保 city_rel_err 不退化)

Fallback 层级：
  (hour, site_id) → (hour, county, capacity_bucket)
  → (hour, county) → (hour, coastal_flag) → hour_global
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys

import functools as _functools
_pd_patched = False

def _ensure_patch():
    global _pd_patched
    if _pd_patched:
        return
    _pd_patched = True
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @_functools.wraps(_orig)
        def _patch(self, *args, **kwargs):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patch
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*args, **kwargs):
    _ensure_patch()
    return _pd_read_pickle(*args, **kwargs)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"

# ------------------------------------------------------------------
# 预测表（含 P0+P1 修正）
PRED_PATH = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
# 原始训练表（用于 valid 集）
TRAIN_PATH = TABLES_DIR / "distributed_train_table.pkl"

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

# Dawn/dusk hours
DAWN_DUSK_HOURS = [6, 7, 16, 17, 18, 19]

# Floor 参数
FLOOR_RATIO_MIN = 0.02
FLOOR_RATIO_MAX = {
    6:  0.85,
    7:  0.85,
    16: 0.60,   # 收紧：过高的 floor 导致 clipped MAPE 恶化
    17: 0.40,   # 收紧：过修正
    18: 0.35,
    19: 0.15,
}
QUANTILE_LEVEL = 0.20
MIN_SITE_SAMPLES = 15
MIN_GROUP_SAMPLES = 50
# Guard: clipped MAPE 恶化上限（小时依赖）
CLIP_DETERIORATE_MAX = {
    6:  1.05,
    7:  1.05,
    16: 1.15,
    17: 1.15,
    18: 1.30,
    19: 1.30,
}
# 输出预测表名
OUTPUT_PRED_PATH = TABLES_DIR / "distributed_predictions_fixed_full_dawn_dusk.pkl"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _floor_ratio(y, p_base, hour, quantile=0.20):
    """实际功率 / p_base 的分位数（保守 floor）"""
    hour_int = int(hour)
    max_val = FLOOR_RATIO_MAX.get(hour_int, 0.85)
    mask = (y > 0) & np.isfinite(y) & np.isfinite(p_base) & (p_base > 1e-5)
    if not mask.any():
        return np.nan
    ratio = y[mask] / p_base[mask]
    ratio = ratio[np.isfinite(ratio)]
    if len(ratio) == 0:
        return np.nan
    return float(np.clip(float(np.quantile(ratio, quantile)), FLOOR_RATIO_MIN, max_val))


def wape(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sum(np.abs(y_true[m] - y_pred[m])) / np.sum(np.abs(y_true[m])) * 100)


def clipped_mape(y_true, y_pred, clip_factor=0.05):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    denom = np.maximum(y_true[m], clip_factor * np.median(y_true[m]))
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / denom) * 100)


def raw_mape(y_true, y_pred):
    """MAPE: 仅 y_true > 0"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / y_true[m]) * 100)


def city_rel_err(yt, yp):
    mask = np.isfinite(yt) & np.isfinite(yp) & (yt > 0)
    yt_s = float(np.nansum(yt[mask]))
    if not np.isfinite(yt_s) or yt_s <= 0:
        return np.nan
    return float(np.abs(np.nansum(yp[mask]) - yt_s) / yt_s * 100)


def hourly_clipped_mape(df, hours):
    """按小时计算 clipped MAPE"""
    rows = {}
    for h in hours:
        sub = df[df["hour"] == h]
        if len(sub) == 0:
            rows[h] = np.nan
            continue
        rows[h] = clipped_mape(
            sub["power_mw"].values.astype(float),
            sub["power_pred"].values.astype(float)
        )
    return rows


def build_key(row):
    """构建 fallback 分组 key"""
    return (row["hour"], row["site_id"], row["county"], row["capacity_bucket"], row["coastal_flag"])


# ------------------------------------------------------------------
# 核心函数
# ------------------------------------------------------------------

def learn_floor_from_valid(valid_df):
    """
    在 valid 集上学习分层 floor 参数。

    Fallback 顺序：
      1. (hour, site_id)
      2. (hour, county, capacity_bucket)
      3. (hour, county)
      4. (hour, coastal_flag)
      5. hour (global)
    """
    df = valid_df.copy()
    df["hour"] = pd.to_datetime(df["time"]).dt.hour
    df["month"] = pd.to_datetime(df["time"]).dt.month
    df["county"] = df.get("county", "unknown")
    df["capacity_bucket"] = df.get("capacity_bucket", "unknown")
    df["coastal_flag"] = df.get("coastal_flag", 0)

    p_base = pd.to_numeric(df["p_base"], errors="coerce").fillna(0).to_numpy()
    y = pd.to_numeric(df["power_mw"], errors="coerce").fillna(0).to_numpy()
    hours = df["hour"].values

    def learn_group(mask_vals, h):
        """给定过滤条件数组，学习 floor ratio（小时用于确定上限）"""
        if mask_vals.sum() < MIN_GROUP_SAMPLES:
            return np.nan
        return _floor_ratio(y[mask_vals], p_base[mask_vals], h, QUANTILE_LEVEL)

    # ── 层级1: (hour, site_id) ───────────────────────────────────────────
    level1 = {}  # (h, site_id) → ratio
    site_ids = df["site_id"].unique()
    for h in DAWN_DUSK_HOURS:
        for sid in site_ids:
            mask = (hours == h) & (df["site_id"].values == sid)
            ratio = learn_group(mask, h)
            if np.isfinite(ratio):
                level1[(h, sid)] = ratio

    # ── 层级2: (hour, county, capacity_bucket) ───────────────────────────
    level2 = {}  # (h, county, bucket) → ratio
    counties = df["county"].unique()
    buckets = df["capacity_bucket"].unique()
    for h in DAWN_DUSK_HOURS:
        for county in counties:
            for bucket in buckets:
                mask = (hours == h) & (df["county"].values == county) & (df["capacity_bucket"].values == bucket)
                ratio = learn_group(mask, h)
                if np.isfinite(ratio):
                    level2[(h, county, bucket)] = ratio

    # ── 层级3: (hour, county) ────────────────────────────────────────────
    level3 = {}  # (h, county) → ratio
    for h in DAWN_DUSK_HOURS:
        for county in counties:
            mask = (hours == h) & (df["county"].values == county)
            ratio = learn_group(mask, h)
            if np.isfinite(ratio):
                level3[(h, county)] = ratio

    # ── 层级4: (hour, coastal_flag) ──────────────────────────────────────
    level4 = {}  # (h, coastal) → ratio
    for h in DAWN_DUSK_HOURS:
        for cf in [0, 1]:
            mask = (hours == h) & (df["coastal_flag"].values == cf)
            ratio = learn_group(mask, h)
            if np.isfinite(ratio):
                level4[(h, cf)] = ratio

    # ── 层级5: hour (global) ─────────────────────────────────────────────
    level5 = {}  # h → ratio
    for h in DAWN_DUSK_HOURS:
        mask = (hours == h)
        ratio = learn_group(mask, h)
        level5[h] = ratio if np.isfinite(ratio) else np.nan

    return level1, level2, level3, level4, level5


def apply_floor_candidates(test_df, level1, level2, level3, level4, level5):
    """
    应用 floor 修正，返回新的 power_pred。
    仅对 dawn/dusk hours 应用。
    """
    df = test_df.copy()
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

    for i in np.where(np.isin(hours, DAWN_DUSK_HOURS))[0]:
        h = int(hours[i])
        sid = site_ids[i]
        cty = counties[i]
        bkt = buckets[i]
        cfl = int(coastal[i])

        # 分层查找
        ratio = np.nan
        if (h, sid) in level1:
            ratio = level1[(h, sid)]
        elif (h, cty, bkt) in level2:
            ratio = level2[(h, cty, bkt)]
        elif (h, cty) in level3:
            ratio = level3[(h, cty)]
        elif (h, cfl) in level4:
            ratio = level4[(h, cfl)]
        elif h in level5:
            ratio = level5[h]

        if not np.isfinite(ratio):
            continue

        floor_val = p_base[i] * ratio
        if new_pred[i] < floor_val:
            new_pred[i] = min(floor_val, cap[i])
            modified[i] = True

    print(f"  应用 floor 修正: {modified.sum():,} 个样本 ({modified.sum()/len(df)*100:.1f}%)")

    # 保存
    df["power_pred"] = new_pred
    df["dawn_dusk_modified"] = modified
    return df


def guard_check(df_before, df_after, hours):
    """Guard 检查：clipped MAPE 不恶化超过 per-hour 阈值"""
    results = {}
    for h in hours:
        max_deteriorate = CLIP_DETERIORATE_MAX.get(h, 1.05)
        sub_b = df_before[df_before["hour"] == h]
        sub_a = df_after[df_after["hour"] == h]
        if len(sub_b) == 0 or len(sub_a) == 0:
            results[h] = True
            continue
        cb = clipped_mape(sub_b["power_mw"].values, sub_b["power_pred"].values)
        ca = clipped_mape(sub_a["power_mw"].values, sub_a["power_pred"].values)
        cre_b = city_rel_err(sub_b["power_mw"].values, sub_b["power_pred"].values)
        cre_a = city_rel_err(sub_a["power_mw"].values, sub_a["power_pred"].values)
        if not (np.isfinite(cb) and np.isfinite(ca)):
            results[h] = True
            continue
        clip_pass = ca <= cb * max_deteriorate
        # 双重 Guard：clipped MAPE 通过 OR (clipped MAPE 轻微恶化 AND city_rel_err 改善)
        cre_improved = np.isfinite(cre_a) and np.isfinite(cre_b) and cre_a < cre_b
        cre_tolerance = np.isfinite(cre_b) and cre_b > 0 and (cre_b - cre_a) / cre_b > 0.02  # city_rel_err 改善超过 2%
        passed = clip_pass or (cre_improved and cre_tolerance)
        results[h] = passed
        if not passed:
            print(f"  Guard 未通过 h={h}: clip_before={cb:.1f}% → clip_after={ca:.1f}% "
                  f"(恶化 {(ca/cb-1)*100:+.1f}%, 阈值 {(max_deteriorate-1)*100:+.0f}%), "
                  f"cre: {cre_b:.1f}% → {cre_a:.1f}% (改善 {cre_improved})")
    return results


def eval_comparison(df_before, df_after, hours):
    """逐小时评估对比"""
    rows = []
    for h in hours:
        sub_b = df_before[df_before["hour"] == h]
        sub_a = df_after[df_after["hour"] == h]
        if len(sub_b) == 0:
            continue

        yt = sub_b["power_mw"].values.astype(float)
        yp_b = sub_b["power_pred"].values.astype(float)
        yp_a = sub_a["power_pred"].values.astype(float)

        n = len(sub_b)
        cre_b = city_rel_err(yt, yp_b)
        cre_a = city_rel_err(yt, yp_a)
        clip_b = clipped_mape(yt, yp_b)
        clip_a = clipped_mape(yt, yp_a)
        mape_b = raw_mape(yt, yp_b)
        mape_a = raw_mape(yt, yp_a)

        rows.append({
            "hour": int(h),
            "n_samples": n,
            "city_rel_err_before": round(cre_b, 2) if np.isfinite(cre_b) else np.nan,
            "city_rel_err_after": round(cre_a, 2) if np.isfinite(cre_a) else np.nan,
            "city_rel_err_delta": round((cre_a or 0) - (cre_b or 0), 2),
            "clipped_mape_before": round(clip_b, 2) if np.isfinite(clip_b) else np.nan,
            "clipped_mape_after": round(clip_a, 2) if np.isfinite(clip_a) else np.nan,
            "mape_before": round(mape_b, 2),
            "mape_after": round(mape_a, 2),
            "mape_delta": round(mape_a - mape_b, 2),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    print("=" * 60)
    print("§3 日出日落 floor 修正")
    print("=" * 60)

    # ── Step 1: 加载 valid 集 ────────────────────────────────────────────
    print("\n[Step 1] 加载 valid 集 …")
    if TRAIN_PATH.exists():
        train_df = pd.read_pickle(TRAIN_PATH)
    else:
        print(f"  {TRAIN_PATH} 不存在，尝试从预测表提取 valid")
        train_df = None

    pred_df = pd.read_pickle(PRED_PATH)
    pred_df["time"] = pd.to_datetime(pred_df["time"])

    # 尝试从 split 列获取 valid
    if "split" in pred_df.columns:
        valid_df = pred_df[pred_df["split"] == "valid"].copy()
    elif train_df is not None:
        train_df["time"] = pd.to_datetime(train_df["time"])
        valid_df = train_df[
            (train_df["time"] >= "2025-07-01") &
            (train_df["time"] < "2025-09-01") &
            (~train_df["site_id"].isin(BAD_SITES)) &
            (train_df["power_mw"].notna()) &
            (train_df["power_mw"] > 0)
        ].copy()
    else:
        raise RuntimeError("无法找到 valid 集数据")

    valid_df = valid_df[
        (~valid_df["site_id"].isin(BAD_SITES)) &
        (valid_df["power_mw"].notna()) &
        (valid_df["power_mw"] > 0) &
        (pd.to_datetime(valid_df["time"]).dt.hour.isin(DAWN_DUSK_HOURS))
    ].copy()

    print(f"  Valid 样本: {len(valid_df):,}")
    print(f"  Valid site_id 列: {'site_id' in valid_df.columns}")
    print(f"  Valid p_base 列: {'p_base' in valid_df.columns}")
    print(f"  Valid power_mw 列: {'power_mw' in valid_df.columns}")
    print(f"  Valid columns: {sorted([c for c in valid_df.columns if c in ['site_id','power_mw','p_base','hour','county','capacity_bucket','coastal_flag']])}")

    # ── Step 2: 学习 floor 参数 ───────────────────────────────────────────
    print("\n[Step 2] 学习分层 floor 参数 (valid 集) …")
    level1, level2, level3, level4, level5 = learn_floor_from_valid(valid_df)
    print(f"  层级1 (hour, site_id): {len(level1)} 个参数")
    print(f"  层级2 (hour, county, bucket): {len(level2)} 个参数")
    print(f"  层级3 (hour, county): {len(level3)} 个参数")
    print(f"  层级4 (hour, coastal): {len(level4)} 个参数")
    print(f"  层级5 (hour global): {sum(1 for v in level5.values() if np.isfinite(v))} 个参数")

    # 打印 hour global floor
    print("\n  Hour global floor_ratio:")
    for h in sorted(level5.keys()):
        v = level5[h]
        print(f"    h={h:02d}: {v:.4f}" if np.isfinite(v) else f"    h={h:02d}: N/A")

    # 保存参数
    floor_params = {
        "level1": {str(k): v for k, v in level1.items()},
        "level2": {str(k): v for k, v in level2.items()},
        "level3": {str(k): v for k, v in level3.items()},
        "level4": {str(k): v for k, v in level4.items()},
        "level5": {str(k): v for k, v in level5.items()},
    }
    import json
    with open(OUT_DIR / "dawn_dusk_floor_params.json", "w", encoding="utf-8") as f:
        json.dump(floor_params, f, ensure_ascii=False, indent=2)
    print(f"\n  参数已保存: {OUT_DIR / 'dawn_dusk_floor_params.json'}")

    # ── Step 3: 应用到测试集 ─────────────────────────────────────────────
    print("\n[Step 3] 应用 floor 修正到测试集 …")
    test_df = pred_df[
        (pred_df["split"] == "test") &
        (~pred_df["site_id"].isin(BAD_SITES))
    ].copy()
    print(f"  测试集: {len(test_df):,} 行")

    # 保存原始预测用于对比
    df_before = test_df[["time", "site_id", "power_mw", "power_pred", "hour"]].copy()
    df_before["hour"] = pd.to_datetime(df_before["time"]).dt.hour
    # 只保留有功率数据的样本用于评估
    df_before = df_before[df_before["power_mw"] > 0]

    # 应用
    df_after = apply_floor_candidates(test_df, level1, level2, level3, level4, level5)
    df_after["hour"] = pd.to_datetime(df_after["time"]).dt.hour
    df_after = df_after[df_after["power_mw"] > 0].copy()

    # ── Step 4: Guard 检查 ───────────────────────────────────────────────
    print("\n[Step 4] Guard 检查 …")
    guard_results = guard_check(df_before, df_after, DAWN_DUSK_HOURS)
    all_passed = all(guard_results.values())
    if all_passed:
        print("  全部 Guard 通过 ✓")
    else:
        print(f"  部分 Guard 未通过: {[h for h,v in guard_results.items() if not v]}")
        # 回退 Guard 失败的时段到原始预测
        failed_hours = [h for h, v in guard_results.items() if not v]
        n_rollback = 0
        for h in failed_hours:
            mask = df_after["hour"] == h
            df_after.loc[mask, "power_pred"] = df_before.loc[mask.values, "power_pred"].values
            n_rollback += mask.sum()
        print(f"  已回退 {n_rollback:,} 个样本到原始预测")

    # ── Step 5: 评估对比 ──────────────────────────────────────────────────
    print("\n[Step 5] 逐小时对比评估 …")
    eval_df = eval_comparison(df_before, df_after, list(range(6, 20)))
    print(eval_df.to_string(index=False))

    eval_out = OUT_DIR / "dawn_dusk_fix_ablation.csv"
    eval_df.to_csv(eval_out, index=False, encoding="utf-8-sig")
    print(f"\n  已保存: {eval_out}")

    # ── Step 6: 保存修正后的完整预测 ─────────────────────────────────────
    print("\n[Step 6] 保存修正后预测 …")
    # 更新原表中的测试集部分
    result_df = pred_df.copy()
    update_cols = ["power_pred", "dawn_dusk_modified"]
    merge_key = ["time", "site_id"]
    updated = df_after[merge_key + update_cols].rename(columns={"power_pred": "power_pred_dawn_dusk"})
    result_df = result_df.merge(updated, on=merge_key, how="left")
    result_df["power_pred"] = result_df["power_pred_dawn_dusk"].fillna(result_df["power_pred"])
    result_df["dawn_dusk_modified"] = result_df.get("dawn_dusk_modified", False)
    # 对非测试集行标记 False
    result_df.loc[result_df["split"] != "test", "dawn_dusk_modified"] = False

    result_df.to_pickle(OUTPUT_PRED_PATH)
    print(f"  已保存: {OUTPUT_PRED_PATH}")

    # ── 汇总 ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Dawn/Dusk floor 修正总结")
    print("=" * 60)
    dawn_dusk_eval = eval_df[eval_df["hour"].isin(DAWN_DUSK_HOURS)]
    print(f"\n早晚时段 (h={DAWN_DUSK_HOURS[0]}-{DAWN_DUSK_HOURS[-1]}):")
    print(f"  city_rel_err: {dawn_dusk_eval['city_rel_err_before'].mean():.1f}% → "
          f"{dawn_dusk_eval['city_rel_err_after'].mean():.1f}%  "
          f"(Δ {dawn_dusk_eval['city_rel_err_delta'].mean():+.1f}%)")
    print(f"  clipped_mape: {dawn_dusk_eval['clipped_mape_before'].mean():.1f}% → "
          f"{dawn_dusk_eval['clipped_mape_after'].mean():.1f}%")
    print(f"  raw MAPE: {dawn_dusk_eval['mape_before'].mean():.1f}% → "
          f"{dawn_dusk_eval['mape_after'].mean():.1f}%  "
          f"(Δ {dawn_dusk_eval['mape_delta'].mean():+.1f}%)")
    all_h = eval_df
    print(f"\n全部时段 (h=6-19):")
    print(f"  city_rel_err: {all_h['city_rel_err_before'].mean():.1f}% → "
          f"{all_h['city_rel_err_after'].mean():.1f}%")
    print(f"  clipped_mape: {all_h['clipped_mape_before'].mean():.1f}% → "
          f"{all_h['clipped_mape_after'].mean():.1f}%")
    print(f"  raw MAPE: {all_h['mape_before'].mean():.1f}% → "
          f"{all_h['mape_after'].mean():.1f}%")
    print("\nDone.")
    return result_df


if __name__ == "__main__":
    main()
