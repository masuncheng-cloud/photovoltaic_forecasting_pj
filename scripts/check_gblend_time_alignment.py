#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包C: g_blend 时间对齐排查与修复
===================================
诊断各字段的峰值小时偏移，检查 UTC/CST 偏移问题

检查字段：
- actual power_mw
- g_blend_pred
- p_base
- pred_baseline
- power_pred
"""
from __future__ import annotations

import functools
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

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
OUTPUT_ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES_DIR = OUTPUT_ROOT / "tables"
METRICS_DIR = OUTPUT_ROOT / "metrics"
FIGURES_DIR = OUTPUT_ROOT / "figures"

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def compute_peak_hour(df, col, group_cols=['date']):
    """计算每个日期的峰值小时"""
    df = df.copy()
    df['time'] = pd.to_datetime(df['time'])
    df['hour'] = df['time'].dt.hour
    
    # 按group_cols和hour聚合
    agg_df = df.groupby(group_cols + ['hour'])[col].sum().reset_index()
    
    # 找每个group的峰值小时
    peak_hours = agg_df.loc[agg_df.groupby(group_cols)[col].idxmax(), group_cols + ['hour']].copy()
    peak_hours.columns = group_cols + [f'peak_hour_{col}']
    
    return peak_hours


def diagnose_time_alignment():
    """诊断时间对齐问题"""
    print("=" * 60)
    print("g_blend 时间对齐诊断")
    print("=" * 60)
    
    # 加载数据
    pred_path = TABLES_DIR / "distributed_predictions.pkl"
    if not pred_path.exists():
        pred_path = TABLES_DIR / "distributed_predictions_v159.pkl"
    
    print(f"加载预测数据: {pred_path}")
    df = pd.read_pickle(pred_path)
    df['time'] = pd.to_datetime(df['time'])
    df['year'] = df['time'].dt.year
    df['month'] = df['time'].dt.month
    df['date'] = df['time'].dt.date
    
    # 筛选测试集
    df = df[(df['year'] >= 2025) & (df['month'] >= 7)]
    df = df[~df['site_id'].isin(BAD_SITES)]
    df = df[df['power_mw'].notna() & (df['power_mw'] > 0)]
    
    print(f"测试集样本数: {len(df):,}")
    
    # ===== 城市级聚合诊断 =====
    print("\n" + "=" * 60)
    print("城市级聚合诊断")
    print("=" * 60)
    
    # 按日期-小时聚合城市总量
    city_df = df.groupby(['date', 'hour']).agg({
        'power_mw': 'sum',
        'g_blend_pred': lambda x: np.average(x, weights=df.loc[x.index, 'capacity_mw'].fillna(1)),
        'p_base': lambda x: np.average(x, weights=df.loc[x.index, 'capacity_mw'].fillna(1)),
    }).reset_index()
    city_df.columns = ['date', 'hour', 'city_power', 'city_gblend', 'city_pbase']
    
    # 计算城市级峰值小时
    city_peaks = {}
    for col in ['city_power', 'city_gblend', 'city_pbase']:
        peak_df = city_df.loc[city_df.groupby('date')[col].idxmax(), ['date', 'hour']].copy()
        peak_df.columns = ['date', f'peak_hour_{col}']
        city_peaks[col] = peak_df
    
    # 合并峰值小时
    city_peak = city_peaks['city_power']
    for col in ['city_gblend', 'city_pbase']:
        city_peak = city_peak.merge(city_peaks[col], on='date', how='outer')
    
    # 计算偏移
    city_peak['delta_gblend'] = city_peak['peak_hour_city_gblend'] - city_peak['peak_hour_city_power']
    city_peak['delta_pbase'] = city_peak['peak_hour_city_pbase'] - city_peak['peak_hour_city_power']
    
    # 统计偏移分布
    print("\n城市级峰值偏移统计:")
    for col in ['delta_gblend', 'delta_pbase']:
        vals = city_peak[col].dropna()
        print(f"  {col}:")
        print(f"    均值: {vals.mean():+.2f} 小时")
        print(f"    中位数: {vals.median():+.2f} 小时")
        print(f"    标准差: {vals.std():.2f} 小时")
        print(f"    delta=0 占比: {(vals == 0).mean()*100:.1f}%")
        print(f"    delta=+1 占比: {(vals == 1).mean()*100:.1f}%")
        print(f"    delta=-1 占比: {(vals == -1).mean()*100:.1f}%")
    
    # 保存城市级峰值诊断
    city_peak.to_csv(METRICS_DIR / "time_alignment_city_peak_v2.csv", index=False, encoding='utf-8-sig')
    
    # ===== 站点级诊断 =====
    print("\n" + "=" * 60)
    print("站点级峰值诊断")
    print("=" * 60)
    
    site_rows = []
    for sid in sorted(df['site_id'].unique()):
        site_df = df[df['site_id'] == sid]
        if len(site_df) < 100:
            continue
        
        # 按日期-小时聚合
        site_agg = site_df.groupby(['date', 'hour']).agg({
            'power_mw': 'sum',
            'g_blend_pred': 'mean',
            'p_base': 'mean',
            'pred_baseline': 'mean' if 'pred_baseline' in site_df.columns else 'power_mw',
        }).reset_index()
        
        # 计算峰值小时
        for col in ['power_mw', 'g_blend_pred', 'p_base']:
            if col in site_agg.columns:
                peak_df = site_agg.loc[site_agg.groupby('date')[col].idxmax(), ['date', 'hour']]
                peak_df.columns = ['date', f'peak_{col}']
                site_agg = site_agg.merge(peak_df, on='date', how='left', suffixes=('', '_peak'))
        
        # 统计偏移
        power_col = 'peak_power_mw'
        for col in ['peak_g_blend_pred', 'peak_p_base']:
            if col in site_agg.columns:
                delta = site_agg[col] - site_agg[power_col]
                site_rows.append({
                    'site_id': sid,
                    'n_dates': len(site_agg['date'].unique()),
                    f'{col}_mean_delta': delta.mean(),
                    f'{col}_median_delta': delta.median(),
                    f'{col}_delta_zero_pct': (delta == 0).mean() * 100,
                })
    
    site_peak_df = pd.DataFrame(site_rows)
    site_peak_df.to_csv(METRICS_DIR / "time_alignment_site_peak_v2.csv", index=False, encoding='utf-8-sig')
    
    # 打印站点级统计
    print("\n站点级 g_blend 偏移统计:")
    gblend_cols = [c for c in site_peak_df.columns if 'g_blend_pred' in c]
    for col in gblend_cols:
        vals = site_peak_df[col].dropna()
        print(f"  {col}: 均值={vals.mean():+.2f}, 中位数={vals.median():+.2f}")
    
    # ===== 检查是否需要修复 =====
    print("\n" + "=" * 60)
    print("诊断结论")
    print("=" * 60)
    
    gblend_mean_delta = city_peak['delta_gblend'].mean()
    pbase_mean_delta = city_peak['delta_pbase'].mean()
    
    if abs(gblend_mean_delta) > 0.3:
        print(f"⚠️ g_blend 存在系统性偏移: {gblend_mean_delta:+.2f} 小时")
        if gblend_mean_delta > 0:
            print("   建议: g_blend 峰值比实际功率晚，需要检查辐照数据是否滞后")
        else:
            print("   建议: g_blend 峰值比实际功率早，需要检查辐照数据是否超前")
    else:
        print(f"✅ g_blend 峰值对齐良好: {gblend_mean_delta:+.2f} 小时")
    
    if abs(pbase_mean_delta) > 0.3:
        print(f"⚠️ p_base 存在系统性偏移: {pbase_mean_delta:+.2f} 小时")
    else:
        print(f"✅ p_base 峰值对齐良好: {pbase_mean_delta:+.2f} 小时")
    
    # 保存诊断报告
    report = {
        'city_peak_hour_mean_delta_gblend': gblend_mean_delta,
        'city_peak_hour_mean_delta_pbase': pbase_mean_delta,
        'city_peak_hour_median_delta_gblend': city_peak['delta_gblend'].median(),
        'city_peak_hour_median_delta_pbase': city_peak['delta_pbase'].median(),
        'city_peak_hour_zero_pct_gblend': (city_peak['delta_gblend'] == 0).mean() * 100,
        'city_peak_hour_zero_pct_pbase': (city_peak['delta_pbase'] == 0).mean() * 100,
        'n_dates_analyzed': len(city_peak),
    }
    
    with open(METRICS_DIR / "time_alignment_stage2_stage3_diagnosis.txt", 'w') as f:
        for k, v in report.items():
            f.write(f"{k}: {v}\n")
    
    print(f"\n诊断文件已保存到: {METRICS_DIR}")
    
    return report


def main():
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report = diagnose_time_alignment()
    print("\n诊断完成")


if __name__ == '__main__':
    main()
