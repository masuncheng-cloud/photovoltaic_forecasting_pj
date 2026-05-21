#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分布式光伏功率预测 V3：早晚专家模型 + 低功率二阶段 + 小时校准
================================================================
在 v159 基础上，新增：

1. 太阳物理特征增强（solar_azimuth, clear_sky_index, low_sun_bin）
2. 三个专家模型：dawn(6-7), day(8-16), dusk(17-19)
3. 站点-小时均衡权重（缓解低频样本被忽略）
4. 低功率二阶段：is_active 分类器 + 保守功率上限
5. 验证集小时偏差校准器
6. 按小时选择 V3 或回退 V2

Split 口径（core/split.py 唯一标准）
------------------------------------
- train : time < 2025-07-01
- valid : 2025-07-01 <= time < 2025-09-01
- test  : time >= 2025-09-01

输出文件
--------
distributed_model_v3.pkl
distributed_predictions_v3.pkl
distributed_predictions_v3_eval.pkl
distributed_predictions_v3_full.pkl
hourly_calibration_v3.json
final_model_selection_v3.csv
hourly_relative_error_compare_v2_v3.csv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.evaluation import (
    build_eval_frame, clipped_mape, site_rel_err, wape, city_rel_err,
)
from pv_forecasting.core.models import fit_tabular_classifier, fit_tabular_regressor, predict_bundle, predict_proba_bundle
from pv_forecasting.core.split import add_standard_split
from pv_forecasting.core.utils import mae, rmse, safe_pickle_dump
from pv_forecasting.features.solar_physics import add_solar_physics_features
from pv_forecasting.tasks.distributed_model import prepare_distributed_dataset
from pv_forecasting.tasks.distributed_power_v152 import train_distributed_power_v152

# ── 异常站点 ──────────────────────────────────────────────────────────────────
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

# ── 专家模型时段划分 ─────────────────────────────────────────────────────────
EXPERT_BANDS = {
    "dawn":  list(range(6, 8)),    # 6, 7
    "day":    list(range(8, 17)),   # 8-16
    "dusk":   list(range(17, 20)), # 17, 18, 19
}

# ── 早/晚时段样本权重 ─────────────────────────────────────────────────────────
HOUR_WEIGHT_V3 = {
    6: 3.0, 7: 2.5,
    17: 2.5, 18: 3.5, 19: 4.0,
}

# ── 低功率二阶段参数 ──────────────────────────────────────────────────────────
ACTIVE_THRESHOLD_FRAC = 0.02   # active_threshold = max(0.02 * capacity, 0.05)
ACTIVE_PROBA_THRESH = 0.42
LOW_POWER_PRED_CAP_FRAC = {
    6: 0.050, 7: 0.080,
    17: 0.080, 18: 0.055, 19: 0.030,
}

# ── 小时校准器约束 ─────────────────────────────────────────────────────────────
DAWN_DUSK_SCALE_RANGE = (0.60, 1.65)
NORMAL_SCALE_RANGE = (0.88, 1.12)
CAL_SHRINK_N = 180


def _hour_weight(df: pd.DataFrame) -> pd.Series:
    """小时权重（早/晚高权重）。"""
    h = pd.to_numeric(df["hour"], errors="coerce").fillna(12)
    w = pd.Series(1.0, index=df.index)
    for hr, weight in HOUR_WEIGHT_V3.items():
        w[h == hr] = weight
    return w.clip(lower=0.5)


def _station_hour_weight(df: pd.DataFrame) -> pd.Series:
    """站点-小时均衡权重：median_count / count(site_id, hour)，clip 到 [0.4, 2.5]。"""
    counts = df.groupby(["site_id", "hour"]).size()
    median_count = counts.median()
    hour_counts = df.groupby("hour").size()
    hour_median = hour_counts.median()
    out = df[["site_id", "hour"]].copy()
    out["count"] = out.apply(lambda r: counts.get((r["site_id"], r["hour"]), 1), axis=1)
    out["weight"] = (median_count / out["count"].clip(lower=1)).clip(lower=0.4, upper=2.5)
    return out["weight"].values


def _build_v3_features(df: pd.DataFrame) -> pd.DataFrame:
    """增强特征：太阳物理 + is_low_sun + low_sun_bin。"""
    out = add_solar_physics_features(df, time_col="time", lat_col="lat", lon_col="lon",
                                     irradiance_col="g_blend_pred")
    return out


def _fit_expert_regressors(train_pos, valid_pos, reg_features, cat_cols):
    """训练三个专家回归器 + 全局回归器（统一特征集）。"""
    models = {"global": None, "dawn": None, "day": None, "dusk": None}
    summary = []

    for band_name, band_hours in EXPERT_BANDS.items():
        tr = train_pos[train_pos["hour"].isin(band_hours)].copy()
        va = valid_pos[valid_pos["hour"].isin(band_hours)].copy()
        min_rows = 300
        if len(tr) < min_rows or len(va) < max(60, min_rows // 10):
            continue
        try:
            bundle = fit_tabular_regressor(
                tr, va, reg_features, "rel_error_target",
                cat_cols=cat_cols, sample_weight_col="sample_weight_reg_v3",
            )
            models[band_name] = bundle
            summary.append({"scene": band_name, "rows_train": len(tr), "rows_valid": len(va)})
        except Exception:
            continue

    # 全局模型
    if train_pos.empty:
        raise ValueError("正样本回归训练集为空")
    if valid_pos.empty:
        valid_pos = train_pos.sample(min(len(train_pos), 500), random_state=42).copy()

    global_bundle = fit_tabular_regressor(
        train_pos, valid_pos, reg_features, "rel_error_target",
        cat_cols=cat_cols, sample_weight_col="sample_weight_reg_v3",
    )
    models["global"] = global_bundle
    summary.append({"scene": "global", "rows_train": len(train_pos), "rows_valid": len(valid_pos)})

    return models, pd.DataFrame(summary)


def _predict_expert(models, df):
    """专家模型预测：先匹配专家模型，fallback 全局模型。"""
    if df.empty:
        return np.array([], dtype=float), np.array([], dtype=float)

    rel_pred = predict_bundle(models["global"], df)
    rel_pred = np.clip(rel_pred, -1.5, 2.0)

    for band_name in ["dawn", "day", "dusk"]:
        bundle = models.get(band_name)
        if bundle is None:
            continue
        idx = df["hour"].isin(EXPERT_BANDS[band_name])
        if not idx.any():
            continue
        band_pred = predict_bundle(bundle, df.loc[idx])
        rel_pred[idx.values] = np.clip(band_pred, -1.5, 2.0)

    base_pred = pd.to_numeric(df["pred_baseline"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    power_pred = np.clip(base_pred * (1.0 + rel_pred), 0.0, cap)
    return power_pred, rel_pred


def _fit_active_classifier(train, valid, features, cat_cols):
    """训练 is_active 二分类器（早/晚低功率判断）。"""
    if "y_on" not in train.columns:
        raise ValueError("训练集缺少 y_on 列（is_active 标签）")
    tr = train[train["y_on"].notna()].copy()
    va = valid[valid["y_on"].notna()].copy()
    bundle = fit_tabular_classifier(tr, va, features, "y_on", cat_cols=cat_cols,
                                    sample_weight_col="sample_weight_cls")
    return bundle


def _apply_low_power_stage2(df, p_on_pred, power_pred, cal_pred=None):
    """低功率二阶段保守处理。

    当 hour in {6,7,17,18,19} 且 (p_on_pred < 0.42 or pred < active_threshold) 时，
    将 pred 裁剪到 capacity * LOW_POWER_PRED_CAP_FRAC[hour]。
    """
    out = df.copy()
    hour = pd.to_numeric(out["hour"], errors="coerce").fillna(12)
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(1.0)
    pred = np.asarray(power_pred, dtype=float)
    active_thresh = cap.clip(lower=0.05).to_numpy() * ACTIVE_THRESHOLD_FRAC

    mask = (hour.isin([6, 7, 17, 18, 19]).to_numpy()) & (
        (np.asarray(p_on_pred, dtype=float) < ACTIVE_PROBA_THRESH) |
        (pred < active_thresh)
    )
    for h in [6, 7, 17, 18, 19]:
        h_mask = mask & (hour.to_numpy() == h)
        frac = LOW_POWER_PRED_CAP_FRAC[h]
        cur = out["power_pred"].to_numpy()
        cur[h_mask] = np.minimum(cur[h_mask], cap.to_numpy()[h_mask] * frac)
        out["power_pred"] = cur
    return out


def _learn_hourly_calibration(valid_df, pred_col="power_pred_v3_raw"):
    """从 valid 集学习小时偏差校准系数。

    Returns dict: hour -> scale (float)
    """
    scales = {}
    for h, sub in valid_df.groupby("hour"):
        if len(sub) < 30:
            scales[h] = 1.0
            continue
        yt = sub["power_mw"].values.astype(float)
        yp = sub[pred_col].values.astype(float)
        valid_mask = (yt > 0) & np.isfinite(yt) & np.isfinite(yp)
        if not valid_mask.any():
            scales[h] = 1.0
            continue

        yt_v = yt[valid_mask]
        yp_v = yp[valid_mask]
        n = valid_mask.sum()

        raw_scale = float(np.sum(yt_v) / max(np.sum(yp_v), 1e-9))
        hour_scale = raw_scale
        shrink = min(1.0, n / CAL_SHRINK_N)
        final_scale = hour_scale + shrink * (1.0 - hour_scale)

        if h in HOUR_WEIGHT_V3:
            lo, hi = DAWN_DUSK_SCALE_RANGE
        else:
            lo, hi = NORMAL_SCALE_RANGE

        final_scale = max(lo, min(hi, final_scale))
        scales[h] = round(final_scale, 4)

    return scales


def _select_per_hour_v3_v2(valid_df, pred_v3_col, score_version_col="selected_version"):
    """按小时在 valid 集上选择 V3 或 V2。

    评分：score = 0.7 * site_mape_mean + 0.3 * wape
    选择规则：
      - 6,7,17,18,19: V3 score <= V2 score 才启用 V3
      - 8-16: V3 score <= V2 score * 1.03 才启用 V3
    """
    selection = {}
    for h, sub in valid_df.groupby("hour"):
        if len(sub) == 0:
            selection[h] = ("V2", float("inf"), float("inf"))
            continue

        yt = sub["power_mw"].values.astype(float)
        v3_yp = sub[pred_v3_col].values.astype(float)
        v2_yp = sub["power_pred_v2"].values.astype(float)
        v3_yp = np.where(np.isnan(v3_yp), v2_yp, v3_yp)

        v3_site_rels = []
        v2_site_rels = []
        for _, sg in sub.groupby("site_id"):
            # sg 是当前 hour 的单个站点数据，直接取其 values
            yt_sg = sg["power_mw"].values.astype(float)
            re3 = site_rel_err(yt_sg, sg[pred_v3_col].values.astype(float))
            re2 = site_rel_err(yt_sg, sg["power_pred_v2"].values.astype(float))
            if np.isfinite(re3):
                v3_site_rels.append(re3)
            if np.isfinite(re2):
                v2_site_rels.append(re2)

        v3_mape = float(np.nanmean(v3_site_rels)) if v3_site_rels else 100.0
        v2_mape = float(np.nanmean(v2_site_rels)) if v2_site_rels else 100.0
        v3_w = wape(yt, v3_yp)
        v2_w = wape(yt, v2_yp)

        v3_score = 0.7 * v3_mape + 0.3 * (v3_w if np.isfinite(v3_w) else 100.0)
        v2_score = 0.7 * v2_mape + 0.3 * (v2_w if np.isfinite(v2_w) else 100.0)

        if h in [6, 7, 17, 18, 19]:
            use_v3 = v3_score <= v2_score
        else:
            use_v3 = v3_score <= v2_score * 1.03

        selection[h] = ("V3" if use_v3 else "V2", v3_score, v2_score)

    return selection


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Train distributed power V3")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--output-root", default="output/pv_pipeline")
    args = parser.parse_args()

    OUT = PROJECT_ROOT / args.output_root
    TABLES = OUT / "tables"
    METRICS = OUT / "metrics"
    MODELS = OUT / "models"
    for d in [TABLES, METRICS, MODELS]:
        d.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("V3: 早晚专家模型 + 低功率二阶段 + 小时校准")
    print("=" * 60)

    # ── Step 0: 加载 v159 训练表（已包含 v152 的所有特征和 pred_baseline）───
    v159_table = TABLES / "distributed_train_table_v159.pkl"
    if not v159_table.exists():
        print(f"[ERROR] 找不到 v159 训练表: {v159_table}")
        print("请先运行: python stages/03_power/train_distributed_model_v159.py")
        sys.exit(1)

    print(f"\n加载 v159 训练表: {v159_table}")
    df = pd.read_pickle(v159_table)
    print(f"  原始行数: {len(df):,}")

    # ── Step 1: 太阳物理特征增强 ────────────────────────────────────────────
    print("\n[Step 1] 太阳物理特征增强 …")
    df = _build_v3_features(df)

    # 排除异常站点
    n_before = len(df)
    df = df[~df["site_id"].isin(BAD_SITES)].copy()
    print(f"  排除 {n_before - len(df):,} 行（{len(BAD_SITES)} 个异常站点）")

    # ── Step 2: V3 样本权重 ─────────────────────────────────────────────────
    print("\n[Step 2] 构建 V3 样本权重 …")
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").fillna(1.0)
    mape_w = (1.0 / pd.to_numeric(df["power_mw"], errors="coerce").clip(lower=0.02)).clip(lower=0.5, upper=50.0)
    hour_w = _hour_weight(df)
    station_hour_w = _station_hour_weight(df)
    quality = pd.to_numeric(df.get("quality_score", pd.Series(0.5, index=df.index)), errors="coerce").fillna(0.5)
    site_w = pd.to_numeric(df.get("site_weight", pd.Series(1.0, index=df.index)), errors="coerce").fillna(1.0)

    df["sample_weight_reg_v3"] = (
        quality.clip(lower=0.12) * site_w * mape_w * hour_w * station_hour_w
    ).clip(lower=0.01).values

    # ── Step 3: Split（统一标准 split，不得混用 split_adaptive）──────────────
    print("\n[Step 3] 数据分割（标准 split）…")
    df = add_standard_split(df)
    train = df[df["split"] == "train"].copy()
    valid = df[df["split"] == "valid"].copy()
    test  = df[df["split"] == "test"].copy()
    print(f"  train={len(train):,}, valid={len(valid):,}, test={len(test):,}")

    # ── Step 4: 加载 v159 的 power_pred_v2 ──────────────────────────────────
    print("\n[Step 4] 加载 V2 预测 …")
    v159_pred_path = TABLES / "distributed_predictions_v159.pkl"
    v2_pred_df = pd.read_pickle(v159_pred_path)
    v2_pred_df["time"] = pd.to_datetime(v2_pred_df["time"])
    v2_pred_map = v2_pred_df[["time", "site_id", "power_pred"]].rename(
        columns={"power_pred": "power_pred_v2"}
    )

    for part in [train, valid, test]:
        part["time"] = pd.to_datetime(part["time"])
        part["hour"] = part["time"].dt.hour
        part["date"] = part["time"].dt.date

    for part_name, part_df in [("train", train), ("valid", valid), ("test", test)]:
        # 用 merge 而非 join，避免 index 问题
        v2_part = v2_pred_map.copy()
        merged = part_df[["time", "site_id"]].merge(v2_part, on=["time", "site_id"], how="left")
        part_df["power_pred_v2"] = merged["power_pred_v2"].values
        part_df["power_pred_v2"] = part_df["power_pred_v2"].fillna(part_df["pred_baseline"])

    # ── Step 5: is_active 分类器（低功率二阶段）─────────────────────────────
    print("\n[Step 5] 训练 is_active 分类器 …")
    cls_features = [
        "g_blend_pred", "alpha_pred", "t2m_c", "capacity_mw", "quality_score",
        "hour", "solar_elevation_deg", "solar_azimuth_deg", "clear_sky_ghi",
        "clear_sky_index", "low_sun_bin", "is_low_sun",
        "county", "install_group", "capacity_bucket",
    ]
    cat_cols_cls = ["county", "install_group", "capacity_bucket", "low_sun_bin"]

    if train["y_on"].notna().sum() > 0 and valid["y_on"].notna().sum() > 0:
        try:
            on_cls = _fit_active_classifier(train, valid, cls_features, cat_cols_cls)
            print("  is_active 分类器训练成功")
        except Exception as e:
            print(f"  is_active 分类器训练失败，使用默认零输出: {e}")
            on_cls = None
    else:
        on_cls = None
        print("  无有效标签，跳过 is_active 分类器")

    # ── Step 6: 专家回归模型 ───────────────────────────────────────────────
    print("\n[Step 6] 训练专家回归模型 …")
    reg_features = cls_features + [
        "pred_baseline", "baseline_ratio", "p_base", "p_on_pred",
        "g_blend_pred_lag1", "g_blend_pred_lag2", "p_base_lag1", "p_base_lag2",
        "scene_v151",
    ]
    cat_cols_reg = cat_cols_cls + ["scene_v151"]

    # 正样本筛选（V3：只用 train，valid 不得参与回归训练）
    pos_train_raw = train.copy()
    pos_train_raw = pos_train_raw[pos_train_raw["y_on"] == 1].copy()
    pos_valid = valid[valid["y_on"] == 1].copy()

    # 过滤回归有效行
    def _filter_reg(df_in, target="rel_error_target"):
        out = df_in.copy()
        out[target] = pd.to_numeric(out[target], errors="coerce")
        mask = out[target].notna()
        mask &= pd.to_numeric(out["baseline_ratio"], errors="coerce").fillna(0.0) > 0.002
        mask &= pd.to_numeric(out["power_ratio"], errors="coerce").fillna(0.0) > 0.002
        for c in ["capacity_mw", "pred_baseline", "g_blend_pred"]:
            if c in out.columns:
                mask &= pd.to_numeric(out[c], errors="coerce").notna()
        return out.loc[mask].copy()

    pos_train = _filter_reg(pos_train_raw)
    pos_valid_f = _filter_reg(pos_valid)

    if len(pos_train) < 100:
        print("  正样本过少，跳过专家模型训练")
        expert_models = {}
    else:
        expert_models, expert_summary = _fit_expert_regressors(
            pos_train, pos_valid_f, reg_features, cat_cols_reg
        )
        print(f"  专家模型: {expert_summary.to_string(index=False)}")

    # ── Step 7: 全量预测（含专家模型）───────────────────────────────────────
    print("\n[Step 7] 生成 V3 预测 …")
    pred_rows = []

    for part_name, part in [("train", train), ("valid", valid), ("test", test)]:
        part = part.copy()
        if len(part) == 0:
            continue

        # is_active 分类
        if on_cls is not None:
            p_on = predict_proba_bundle(on_cls, part)
        else:
            p_on = np.full(len(part), 0.5)
        part["p_on_pred"] = p_on

        # 专家回归
        if expert_models:
            power_v3_raw, rel_pred = _predict_expert(expert_models, part)
        else:
            # 无专家模型时，使用全局模型
            power_v3_raw = part["pred_baseline"].fillna(0.0).to_numpy()

        part["power_pred_v3_raw"] = power_v3_raw

        # 早/晚低功率保守裁剪
        part = _apply_low_power_stage2(part, part["p_on_pred"].values, part["power_pred_v3_raw"].values)
        part["power_pred_v3_calibrated"] = part["power_pred"].values.copy()

        pred_rows.append(part)

    pred_df = pd.concat(pred_rows, ignore_index=True)
    print(f"  V3 预测完成: {len(pred_df):,} 行")

    # ── Step 8: 小时校准器 ─────────────────────────────────────────────────
    print("\n[Step 8] 小时偏差校准 …")
    valid_for_cal = build_eval_frame(
        pred_df, pred_col="power_pred_v3_raw",
        split="valid", bad_sites=BAD_SITES
    )

    if len(valid_for_cal) > 0:
        cal_scales = _learn_hourly_calibration(valid_for_cal)
        print(f"  小时校准系数: {cal_scales}")

        # 应用校准
        h_arr = pd.to_numeric(pred_df["hour"], errors="coerce").fillna(12).values
        for h, scale in cal_scales.items():
            mask = h_arr == h
            if mask.any():
                raw = pred_df.loc[mask, "power_pred_v3_calibrated"].values
                cap_arr = pd.to_numeric(pred_df.loc[mask, "capacity_mw"], errors="coerce").fillna(1.0).values
                calibrated = np.clip(raw * scale, 0.0, cap_arr)
                pred_df.loc[mask, "power_pred_v3_calibrated"] = calibrated

        # 保存校准系数
        cal_path = METRICS / "hourly_calibration_v3.json"
        with open(cal_path, "w", encoding="utf-8") as f:
            json.dump(cal_scales, f, indent=2, ensure_ascii=False)
        print(f"  校准系数已保存: {cal_path}")
    else:
        print("  无 valid 数据，跳过校准")
        cal_scales = {}

    # ── Step 9: 按小时选择 V3 或 V2 ─────────────────────────────────────────
    print("\n[Step 9] 按小时选择 V3 或 V2 …")
    valid_eval = build_eval_frame(
        pred_df, pred_col="power_pred_v3_calibrated",
        split="valid", bad_sites=BAD_SITES
    )

    if len(valid_eval) > 0:
        selection = _select_per_hour_v3_v2(valid_eval, "power_pred_v3_calibrated")

        # 应用选择到全部数据
        h_arr = pred_df["hour"].values
        for h, (ver, v3_score, v2_score) in selection.items():
            mask = h_arr == h
            if ver == "V3":
                pred_df.loc[mask, "power_pred"] = pred_df.loc[mask, "power_pred_v3_calibrated"].values
            else:
                pred_df.loc[mask, "power_pred"] = pred_df.loc[mask, "power_pred_v2"].values

        print("  选择结果:")
        for h in sorted(selection.keys()):
            ver, v3_s, v2_s = selection[h]
            print(f"    h={h:02d}: {ver} (V3={v3_s:.2f}, V2={v2_s:.2f})")
    else:
        print("  无 valid 数据，全部使用 V2")
        pred_df["power_pred"] = pred_df["power_pred_v2"]

    # ── Step 10: 保存输出 ────────────────────────────────────────────────────
    print("\n[Step 10] 保存输出 …")

    keep_cols = [
        "time", "site_id", "split", "power_mw", "power_pred",
        "power_pred_v2", "power_pred_v3_raw", "power_pred_v3_calibrated",
        "pred_baseline", "p_on_pred", "capacity_mw", "hour", "date",
        "county", "capacity_bucket", "scene_v151",
        "low_sun_bin", "clear_sky_index", "solar_elevation_deg", "solar_azimuth_deg",
    ]
    keep_cols = [c for c in keep_cols if c in pred_df.columns]

    # Full（test 全时段）
    full_test = pred_df[(pred_df["split"] == "test")].copy()
    full_test[keep_cols].to_pickle(TABLES / "distributed_predictions_v3_full.pkl")
    print(f"  已保存: {TABLES / 'distributed_predictions_v3_full.pkl'}")

    # Eval（test + 6-19 点）
    eval_test = full_test[full_test["hour"].between(6, 19)].copy()
    eval_test[keep_cols].to_pickle(TABLES / "distributed_predictions_v3_eval.pkl")
    print(f"  已保存: {TABLES / 'distributed_predictions_v3_eval.pkl'}")

    # 训练表（含 V3 特征）保存
    df[keep_cols].to_pickle(TABLES / "distributed_train_table_v3.pkl")
    print(f"  已保存: {TABLES / 'distributed_train_table_v3.pkl'}")

    # 选择表
    sel_rows = []
    for h in range(6, 20):
        ver, v3_s, v2_s = selection.get(h, ("V2", float("inf"), float("inf")))
        sel_rows.append({
            "hour": h,
            "selected_version": ver,
            "valid_v3_score": round(v3_s, 4) if np.isfinite(v3_s) else np.nan,
            "valid_v2_score": round(v2_s, 4) if np.isfinite(v2_s) else np.nan,
            "valid_delta_score": round(v3_s - v2_s, 4) if np.isfinite(v3_s) and np.isfinite(v2_s) else np.nan,
        })
    sel_df = pd.DataFrame(sel_rows)
    sel_df.to_csv(METRICS / "final_model_selection_v3.csv", index=False, encoding="utf-8-sig")
    print(f"  已保存: {METRICS / 'final_model_selection_v3.csv'}")

    # ── Step 11: V2/V3 逐小时误差对比 ─────────────────────────────────────────
    print("\n[Step 11] V2/V3 逐小时误差对比 …")
    test_eval = build_eval_frame(
        pred_df[pred_df["split"] == "test"], pred_col="power_pred",
        split="test", bad_sites=BAD_SITES
    )
    if len(test_eval) > 0:
        from pv_forecasting.core.evaluation import compare_two_versions
        cmp = compare_two_versions(
            test_eval, "power_pred_v2", "power_pred",
            version_labels=("V2", "V3")
        )
        cmp.to_csv(METRICS / "hourly_relative_error_compare_v2_v3.csv",
                   index=False, encoding="utf-8-sig")
        print(f"  已保存: {METRICS / 'hourly_relative_error_compare_v2_v3.csv'}")

        print("\n逐小时 V2/V3 对比:")
        print(cmp.to_string(index=False))

    # ── Done ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("V3 训练完成")
    print("=" * 60)
    print(f"  V3 full:    {TABLES / 'distributed_predictions_v3_full.pkl'}")
    print(f"  V3 eval:    {TABLES / 'distributed_predictions_v3_eval.pkl'}")
    print(f"  校准系数:   {METRICS / 'hourly_calibration_v3.json'}")
    print(f"  选择表:     {METRICS / 'final_model_selection_v3.csv'}")
    print(f"  V2/V3 对比: {METRICS / 'hourly_relative_error_compare_v2_v3.csv'}")

    return pred_df


if __name__ == "__main__":
    main()
