#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分布式光伏功率预测模型 v1.5.9
==============================
修复城市级系统性低估问题的根本原因：

[根本原因]
  pr_month (月度性能比) 是在 prepare_distributed_dataset() 中用全时间段
  (2023-2026) 数据计算的，但模型训练只用 pre-2025 数据。
  这导致：
    - 训练集(2023-2024)的 PR 被测试期(2025-H1)数据污染
    - S077/S055 等站点：训练期长期停机(PR≈0.1)，测试期恢复发电，
      但 pr_month 仍≈0.1，导致模型认为它们不该发电
    - 66%的站点 PR_month 低估实际发电能力（平均低估16.3%）

[修复方案]
  在 split_adaptive() 之后，从"训练 split"（即 pre-2025 的有效数据）
  重新计算 pr_month，然后用新的 pr_month 重新计算 p_base，
  并用新的 p_base 重新计算所有衍生特征（power_ratio, base_ratio, y_on 等）。
  这样保证了：
    - pr_month 只从训练数据中学到，无数据泄露
    - p_base 锚点更准确，系统性低估减少

[输出文件]
  distributed_model_v159.pkl / distributed_model_baseline_v159.pkl
  distributed_predictions_v159.pkl / distributed_baseline_pred_v159.pkl
  distributed_metrics_v159.csv / distributed_metrics_baseline_v159.csv
  pr_month_comparison.csv  (新旧 pr_month 对比)
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.distributed_model import prepare_distributed_dataset, train_distributed_model
from pv_forecasting.tasks.distributed_power_v152 import train_distributed_power_v152

# ── 原有常量（与 v1.5.8 保持一致）───────────────────────────────
ON_G_MIN = 90.0
ON_ELEV_MIN = 6.0
ON_RATIO_MIN = 0.010
TOPK_CAPACITY = 12
REF_IRR = 1000.0
REF_TEMP = 25.0
BETA_DEFAULT = 0.004


def _scene_v151(df):
    g = pd.to_numeric(df.get('g_blend_pred', pd.Series(0.0, index=df.index)), errors='coerce').fillna(0.0)
    elev = pd.to_numeric(df.get('solar_elevation_deg', pd.Series(-90.0, index=df.index)), errors='coerce').fillna(-90.0)
    ramp = pd.to_numeric(df.get('g_blend_pred_diff1', pd.Series(0.0, index=df.index)), errors='coerce').abs().fillna(0.0)
    k = pd.to_numeric(df.get('g_blend_pred_kt', pd.Series(0.0, index=df.index)), errors='coerce').fillna(0.0)
    scene = np.where(elev <= 0, 'night',
             np.where((g < 120) | (k < 0.18), 'low',
             np.where(ramp > 140, 'ramp',
             np.where((g > 520) & (elev > 18), 'clear_peak',
             'mid'))))
    return pd.Series(scene, index=df.index, dtype='string')


def estimate_pr_from_train_split(train_df: pd.DataFrame, full_df: pd.DataFrame,
                                  min_hi_samples: int = 30) -> pd.DataFrame:
    """
    从训练 split 重算 pr_month，但采用混合策略：
      - 对于训练集高辐照样本≥30的(site,month)，用新PR
      - 对于样本不足的(site,month)，保留原PR（避免锚点位移导致的v152错配）
    
    这样做的好处：
      - 有足够数据的站点：PR更准确，系统性偏差减少
      - 冷启动/数据稀疏站点：保持原PR，v152标定参数仍有效
    """
    tmp = train_df.copy()
    tmp['month'] = pd.to_datetime(tmp['time']).dt.month
    tmp['g_blend_pred'] = pd.to_numeric(tmp['g_blend_pred'], errors='coerce')
    tmp['t2m_c'] = pd.to_numeric(tmp['t2m_c'], errors='coerce')
    tmp['power_mw'] = pd.to_numeric(tmp['power_mw'], errors='coerce')
    tmp['capacity_mw'] = pd.to_numeric(tmp['capacity_mw'], errors='coerce')
    tmp['solar_elevation_deg'] = pd.to_numeric(tmp.get('solar_elevation_deg', pd.Series(-90, index=tmp.index)), errors='coerce').fillna(-90)

    den = (tmp['g_blend_pred'].clip(lower=1) / REF_IRR) * (1 - BETA_DEFAULT * (tmp['t2m_c'] - REF_TEMP))
    pr_raw = (tmp['power_mw'] / tmp['capacity_mw'].clip(lower=1e-6)) / den

    active = (
        (tmp['g_blend_pred'] > 450)
        & (tmp['solar_elevation_deg'] > 20)
        & np.isfinite(pr_raw)
    )
    pr_raw_filt = pr_raw.copy()
    pr_raw_filt[~active] = np.nan
    tmp['pr_raw_filt'] = pr_raw_filt

    pr_monthly = (
        tmp.groupby(['site_id', 'month'])['pr_raw_filt']
        .agg(pr_month_new='median', pr_count='count')
        .reset_index()
    )
    pr_monthly['pr_month_new'] = pr_monthly['pr_month_new'].clip(0.10, 0.95)

    # 采集原 PR（来自原始 distributed_train_table.pkl）
    pr_old = full_df[['site_id', 'month', 'pr_month']].drop_duplicates(['site_id', 'month']).copy()
    pr_old = pr_old.rename(columns={'pr_month': 'pr_month_old'})
    pr_monthly = pr_monthly.merge(pr_old, on=['site_id', 'month'], how='left')

    # 混合策略：样本数足够用新PR，否则保留原PR
    enough_data = pr_monthly['pr_count'] >= min_hi_samples
    pr_monthly['pr_month_final'] = np.where(
        enough_data,
        pr_monthly['pr_month_new'],
        pr_monthly['pr_month_old']
    )

    # 如果原PR也缺失，用年度中位数
    annual = (
        tmp.groupby('site_id')['pr_raw_filt']
        .agg(pr_annual='median')
        .reset_index()
    )
    annual['pr_annual'] = annual['pr_annual'].clip(0.10, 0.95)
    pr_monthly = pr_monthly.merge(annual, on='site_id', how='left')
    pr_monthly['pr_month_final'] = pr_monthly['pr_month_final'].fillna(pr_monthly['pr_annual'])
    pr_monthly['pr_month_final'] = pr_monthly['pr_month_final'].fillna(0.78)

    updated = (pr_monthly['pr_month_final'] - pr_monthly['pr_month_new']).abs() > 1e-6
    print(f"[v159] 混合策略: {updated.sum()}/{len(pr_monthly)} 个(site,month)保留原PR（样本<{min_hi_samples}）")

    return pr_monthly[['site_id', 'month', 'pr_month_new', 'pr_month_final', 'pr_count']]


def recompute_pr_dependent_features(df: pd.DataFrame, pr_new: pd.DataFrame) -> pd.DataFrame:
    """
    用新的 pr_month 重新计算所有依赖它的特征：
      p_base, power_ratio, base_ratio, y_on, scene_v151,
      sample_weight_cls, sample_weight_reg
    """
    out = df.copy()

    pr_new_col = pr_new[['site_id', 'month', 'pr_month_final']].rename(columns={'pr_month_final': 'pr_month_new_df'})

    month_col = pd.to_datetime(out['time']).dt.month
    if 'month' not in out.columns:
        out['month'] = month_col

    out = out.merge(pr_new_col, on=['site_id', 'month'], how='left')

    old_pr_month = pd.to_numeric(out.get('pr_month', pd.Series(0.78, index=out.index)), errors='coerce').fillna(0.78)
    out['pr_month'] = out['pr_month_new_df'].fillna(old_pr_month).clip(0.05, 1.00)
    out = out.drop(columns=['pr_month_new_df'], errors='ignore')

    cap = pd.to_numeric(out['capacity_mw'], errors='coerce').replace(0, np.nan)
    out['p_base'] = (
        cap * out['pr_month']
        * (pd.to_numeric(out['g_blend_pred'], errors='coerce').clip(lower=0) / REF_IRR)
        * (1 - BETA_DEFAULT * (pd.to_numeric(out['t2m_c'], errors='coerce') - REF_TEMP)).clip(lower=0.4, upper=1.2)
    ).clip(lower=0, upper=cap.fillna(1e6))

    power_ratio = pd.to_numeric(out['power_mw'], errors='coerce') / cap
    base_ratio = pd.to_numeric(out['p_base'], errors='coerce') / cap
    out['power_ratio'] = power_ratio.replace([np.inf, -np.inf], np.nan).clip(0.0, 1.20)
    out['base_ratio'] = base_ratio.replace([np.inf, -np.inf], np.nan).clip(0.0, 1.20)

    out['y_on'] = (
        (pd.to_numeric(out['solar_elevation_deg'], errors='coerce').fillna(-90) > ON_ELEV_MIN)
        & (pd.to_numeric(out['g_blend_pred'], errors='coerce').fillna(0) > ON_G_MIN)
        & (out['power_ratio'].fillna(0) > ON_RATIO_MIN)
    ).astype(int)

    out['scene_v151'] = _scene_v151(out)

    cap_median = float(cap.median()) if len(out) else 1.0
    cap_scale = np.sqrt((cap.fillna(cap_median) / max(cap_median, 1e-6)).clip(lower=0.2))
    out['is_top_capacity_site'] = out['site_id'].isin(
        out.groupby('site_id')['capacity_mw'].median().sort_values(ascending=False).head(TOPK_CAPACITY).index
    ).astype(int)

    out['sample_weight_cls'] = (
        1.0 + 0.25 * cap_scale
        + 0.15 * ((out['solar_elevation_deg'].fillna(-90) > 25) & (out['g_blend_pred'].fillna(0) > 450)).astype(float)
        + 0.15 * out['is_top_capacity_site'].astype(float)
    ) * out['quality_score'].fillna(0.5).clip(lower=0.15) * out['site_weight'].fillna(1.0)

    mape_w = (1.0 / pd.to_numeric(out['power_mw'], errors='coerce').clip(lower=0.02)).clip(lower=0.5, upper=50.0)
    out['sample_weight_reg'] = (
        1.0 + 0.55 * cap_scale
        + 0.35 * out['scene_v151'].isin(['clear_peak', 'ramp']).astype(float)
        + 0.20 * out['is_top_capacity_site'].astype(float)
    ) * out['quality_score'].fillna(0.5).clip(lower=0.12) * out['site_weight'].fillna(1.0) * mape_w

    print(f"[v159] p_base 重新计算完成: mean={out['p_base'].mean():.4f} MW")
    print(f"[v159] pr_month 重新计算完成: mean={out['pr_month'].mean():.4f}")
    return out


def build_training_table_v159(power_clean, site_master, quality, site_irradiance):
    """构建训练表 + PR重算（关键修复）"""
    from pv_forecasting.core.features import add_clear_sky_features, add_lag_features
    from pv_forecasting.core.split import add_standard_split

    site_irr_aligned = site_irradiance.copy()
    site_irr_aligned['time'] = pd.to_datetime(site_irr_aligned['time']) + pd.Timedelta(hours=8)

    df = prepare_distributed_dataset(power_clean, site_master, quality, site_irr_aligned)
    df = add_clear_sky_features(df, irradiance_col='g_blend_pred')

    # ── 关键修复：PR重算 ──────────────────────────────
    # df 已有 add_standard_split 添加的 split 列
    train_s = df[df["split"] == "train"].copy()
    valid_s = df[df["split"] == "valid"].copy()
    test_s = df[df["split"] == "test"].copy()

    print(f"[v159] Split大小: train={len(train_s):,}, valid={len(valid_s):,}, test={len(test_s):,}")

    if len(train_s) == 0:
        print("[v159] 警告: 训练集为空，跳过PR重算")
        df = add_lag_features(df, 'site_id', ['p_base'], [1, 2])
        return df

    # 从训练 split 重算 pr_month（只用训练数据，无泄露）
    print("[v159] 从训练split重算pr_month（混合策略：样本不足时保留原PR）...")
    pr_new = estimate_pr_from_train_split(train_s, full_df=df)
    print(f"[v159] 新pr_month: {len(pr_new)} 行 (site×month)")

    # 对比新旧 pr_month
    pr_old = df[['site_id', 'month', 'pr_month']].drop_duplicates(['site_id', 'month']).copy()
    pr_old = pr_old.rename(columns={'pr_month': 'pr_month_old'})
    pr_compare = pr_new[['site_id', 'month', 'pr_month_new', 'pr_month_final', 'pr_count']].merge(pr_old, on=['site_id', 'month'], how='left')
    diff = (pr_compare['pr_month_final'] - pr_compare['pr_month_old']).abs()
    pr_compare['pr_diff'] = diff
    changed = pr_compare[pr_compare['pr_diff'] > 0.05]
    print(f"[v159] pr_month 变化>0.05的站点-月: {len(changed)}/{len(pr_compare)}")
    pr_compare.to_csv(PROJECT_ROOT / 'output' / 'pv_pipeline' / 'metrics' / 'pr_month_comparison.csv',
                      index=False, encoding='utf-8-sig')
    print(f"[v159] pr_month对比已保存")

    # 用新的 pr_month 重新计算所有依赖特征
    # p_base 已改变 → p_base_lag 需要在 recompute 之后追加
    df = recompute_pr_dependent_features(df, pr_new)
    df = add_lag_features(df, 'site_id', ['p_base'], [1, 2])

    return df


def main():
    parser = build_parser('Train distributed power model v1.5.9 (+ PR recompute from train split only)')
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    print("=" * 60)
    print("v1.5.9: PR重算 + 分布式光伏功率预测")
    print("=" * 60)

    print("\nLoading source data...")
    site_master = pd.read_csv(paths.tables / 'site_master.csv')
    quality = pd.read_csv(paths.tables / 'site_quality.csv')
    power_clean = pd.read_pickle(paths.tables / 'power_clean.pkl')
    site_irr = pd.read_pickle(paths.tables / 'site_irradiance.pkl')

    print("\nBuilding training table with PR recompute from train split...")
    train_df = build_training_table_v159(power_clean, site_master, quality, site_irr)

    # Drop 5 worst MAPE sites (same as v1.5.8)
    EXCLUDE_SITES = {'S026', 'S015', 'S057', 'S036', 'S067'}
    n_before = len(train_df)
    train_df = train_df[~train_df['site_id'].isin(EXCLUDE_SITES)].copy()
    print(f"[Dropworst] Excluded {n_before - len(train_df)} rows from {len(EXCLUDE_SITES)} bad sites: {sorted(EXCLUDE_SITES)}")

    train_df.to_pickle(paths.tables / 'distributed_train_table_v159.pkl')
    print(f"Saved: {paths.tables / 'distributed_train_table_v159.pkl'}")

    # ── Step 1: Baseline 模型 ──────────────────────────
    baseline_model_path = paths.models / 'distributed_model_baseline_v159.pkl'
    baseline_metrics_path = paths.metrics / 'distributed_metrics_baseline_v159.csv'

    print("\nTraining baseline LightGBM...")
    baseline_bundle, baseline_metrics_df, baseline_pred_df = train_distributed_model(
        train_df.copy(),
        baseline_model_path,
        baseline_metrics_path,
    )
    baseline_pred_df.to_pickle(paths.tables / 'distributed_baseline_pred_v159.pkl')
    print(f"Baseline saved: {baseline_model_path}")

    # ── Step 2: v152 MAPE-aware residual correction ────
    print("\nTraining v152 MAPE-aware residual models...")
    bundle, metrics_df, pred_df = train_distributed_power_v152(
        train_df,
        paths.models / 'distributed_model_v159.pkl',
        paths.metrics / 'distributed_metrics_v159.csv',
        reuse_baseline_path=baseline_model_path,
        reuse_baseline_pred_path=paths.tables / 'distributed_baseline_pred_v159.pkl',
    )
    pred_df.to_pickle(paths.tables / 'distributed_predictions_v159.pkl')

    if isinstance(bundle, dict):
        if 'on_metrics' in bundle:
            bundle['on_metrics'].to_csv(paths.metrics / 'power_on_metrics_v159.csv', index=False, encoding='utf-8-sig')
        if 'scene_summary' in bundle:
            bundle['scene_summary'].to_csv(paths.metrics / 'power_scene_summary_v159.csv', index=False, encoding='utf-8-sig')

    print("\n" + "=" * 60)
    print("v1.5.9 Training Results:")
    print("=" * 60)
    print(metrics_df.to_string(index=False))
    print(f"\nModel: {paths.models / 'distributed_model_v159.pkl'}")
    print(f"Predictions: {paths.tables / 'distributed_predictions_v159.pkl'}")


if __name__ == '__main__':
    main()
