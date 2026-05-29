#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包B: 早晚 ramp floor 修正
================================
只在验证集上学习保守的 floor，然后只对最极端低估的时段做最小干预。

边界时段: hour in [6, 7, 17, 18, 19]
学习维度: hour × month_group × solar_elevation_bin
修正因子: floor_factor = quantile(power_mw / max(p_base, eps), 0.20)
应用: power_pred = max(power_pred, p_base * floor_factor)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES_DIR = OUTPUT_ROOT / "tables"
METRICS_DIR = OUTPUT_ROOT / "metrics"

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

# 参数约束
FLOOR_MIN = 0.05
FLOOR_MAX = 0.80
QUANTILE_LEVEL = 0.20
DAWN_DUSK_HOURS = [6, 7, 17, 18, 19]


def _compute_floor_factor(y, p_base, quantile_level=0.20, floor_min=0.05, floor_max=0.80):
    """计算 floor_factor: 实际功率 / p_base 的分位数"""
    mask = (y > 0) & np.isfinite(y) & np.isfinite(p_base) & (p_base > 1e-6)
    if not mask.any():
        return np.nan
    
    ratio = y[mask] / p_base[mask]
    ratio = ratio[np.isfinite(ratio)]
    if len(ratio) == 0:
        return np.nan
    
    factor = np.quantile(ratio, quantile_level)
    return float(np.clip(factor, floor_min, floor_max))


def fit_dawn_dusk_floor(df_valid):
    """
    在验证集上学习 dawn/dusk floor 修正因子
    
    Parameters
    ----------
    df_valid: pd.DataFrame
        验证集数据，包含 power_mw, p_base, hour, month, solar_elevation_deg 等字段
    
    Returns
    -------
    dict: { (hour, month_group, elev_bin): floor_factor }
    """
    df = df_valid.copy()
    df['time'] = pd.to_datetime(df['time'])
    df['hour'] = df['time'].dt.hour
    df['month'] = df['time'].dt.month
    df['month_group'] = pd.cut(df['month'], bins=[0, 4, 7, 10, 13], labels=['Q1', 'Q2', 'Q3', 'Q4'])
    
    elev = pd.to_numeric(df.get('solar_elevation_deg', pd.Series(0, index=df.index)), errors='coerce').fillna(0)
    df['elev_bin'] = pd.cut(elev, bins=[-90, 6, 18, 35, 90], labels=['low', 'mid', 'high', 'very_high'])
    
    p_base = pd.to_numeric(df['p_base'], errors='coerce').fillna(0).to_numpy()
    y = pd.to_numeric(df['power_mw'], errors='coerce').fillna(0).to_numpy()
    hours = df['hour'].values
    month_groups = df['month_group'].values
    elev_bins = df['elev_bin'].values
    
    # 只对边界时段学习
    dawn_dusk_mask = np.isin(hours, DAWN_DUSK_HOURS)
    
    floor_table = {}
    summary_rows = []
    
    # 按 hour × month_group × elev_bin 学习
    for h in DAWN_DUSK_HOURS:
        for mg in ['Q1', 'Q2', 'Q3', 'Q4']:
            for eb in ['low', 'mid', 'high', 'very_high']:
                mask = dawn_dusk_mask & (hours == h) & (month_groups == mg) & (elev_bins == eb)
                if mask.sum() < 30:
                    # 样本不足，回退到 hour 级别
                    mask_h = dawn_dusk_mask & (hours == h)
                    if mask_h.sum() >= 50:
                        factor = _compute_floor_factor(y[mask_h], p_base[mask_h], QUANTILE_LEVEL, FLOOR_MIN, FLOOR_MAX)
                        key = (h, mg, eb)
                        floor_table[key] = factor
                        summary_rows.append({
                            'hour': h, 'month_group': mg, 'elev_bin': eb,
                            'n_samples': int(mask_h.sum()),
                            'floor_factor': factor,
                            'fallback': 'hour_only'
                        })
                    else:
                        summary_rows.append({
                            'hour': h, 'month_group': mg, 'elev_bin': eb,
                            'n_samples': int(mask.sum()),
                            'floor_factor': np.nan,
                            'fallback': 'insufficient_samples'
                        })
                    continue
                
                factor = _compute_floor_factor(y[mask], p_base[mask], QUANTILE_LEVEL, FLOOR_MIN, FLOOR_MAX)
                key = (h, mg, eb)
                floor_table[key] = factor
                summary_rows.append({
                    'hour': h, 'month_group': mg, 'elev_bin': eb,
                    'n_samples': int(mask.sum()),
                    'floor_factor': factor,
                    'fallback': 'full'
                })
    
    # 也保存 hour 级别的 fallback
    hour_floor = {}
    for h in DAWN_DUSK_HOURS:
        mask_h = dawn_dusk_mask & (hours == h)
        if mask_h.sum() >= 50:
            factor = _compute_floor_factor(y[mask_h], p_base[mask_h], QUANTILE_LEVEL, FLOOR_MIN, FLOOR_MAX)
            hour_floor[h] = factor
        else:
            hour_floor[h] = np.nan
    
    summary_df = pd.DataFrame(summary_rows)
    
    return floor_table, hour_floor, summary_df


def apply_dawn_dusk_floor(df, floor_table, hour_floor):
    """
    应用 dawn/dusk floor 修正
    
    Parameters
    ----------
    df: pd.DataFrame
        包含 power_pred, p_base, hour, month, solar_elevation_deg 等字段
    floor_table: dict
        { (hour, month_group, elev_bin): floor_factor }
    hour_floor: dict
        { hour: floor_factor } 作为 fallback
    """
    df = df.copy()
    df['time'] = pd.to_datetime(df['time'])
    df['hour'] = df['time'].dt.hour
    df['month'] = df['time'].dt.month
    df['month_group'] = pd.cut(df['month'], bins=[0, 4, 7, 10, 13], labels=['Q1', 'Q2', 'Q3', 'Q4'])
    
    elev = pd.to_numeric(df.get('solar_elevation_deg', pd.Series(0, index=df.index)), errors='coerce').fillna(0)
    df['elev_bin'] = pd.cut(elev, bins=[-90, 6, 18, 35, 90], labels=['low', 'mid', 'high', 'very_high'])
    
    # 保存原始预测
    df['power_pred_before_dawn_dusk'] = df['power_pred'].copy()
    
    p_base = pd.to_numeric(df['p_base'], errors='coerce').fillna(0).to_numpy()
    power_pred = pd.to_numeric(df['power_pred'], errors='coerce').fillna(0).to_numpy()
    cap = pd.to_numeric(df.get('capacity_mw', pd.Series(1e6, index=df.index)), errors='coerce').fillna(1e6).to_numpy()
    hours = df['hour'].values
    month_groups = df['month_group'].values
    elev_bins = df['elev_bin'].values
    
    # 只对边界时段应用
    dawn_dusk_mask = np.isin(hours, DAWN_DUSK_HOURS)
    
    new_pred = power_pred.copy()
    
    for i in np.where(dawn_dusk_mask)[0]:
        h = hours[i]
        mg = month_groups[i]
        eb = elev_bins[i]
        
        # 查找 floor_factor
        key = (h, mg, eb)
        if key in floor_table and not np.isnan(floor_table[key]):
            factor = floor_table[key]
        elif h in hour_floor and not np.isnan(hour_floor[h]):
            factor = hour_floor[h]
        else:
            continue
        
        # 应用 floor
        floor_value = p_base[i] * factor
        if new_pred[i] < floor_value:
            new_pred[i] = min(floor_value, cap[i])
    
    df['power_pred'] = new_pred
    
    return df


def evaluate_before_after(df_before, df_after):
    """评估修复前后对比"""
    y_true = pd.to_numeric(df_before['power_mw'], errors='coerce').fillna(0).to_numpy()
    y_before = pd.to_numeric(df_before['power_pred'], errors='coerce').fillna(0).to_numpy()
    y_after = pd.to_numeric(df_after['power_pred'], errors='coerce').fillna(0).to_numpy()
    
    hours = pd.to_datetime(df_before['time']).dt.hour.values
    
    rows = []
    for h in DAWN_DUSK_HOURS:
        mask = hours == h
        if not mask.any():
            continue
        
        actual = y_true[mask]
        before = y_before[mask]
        after = y_after[mask]
        
        city_actual = actual.sum()
        rel_err_before = abs(before.sum() - city_actual) / city_actual * 100 if city_actual > 0 else np.nan
        rel_err_after = abs(after.sum() - city_actual) / city_actual * 100 if city_actual > 0 else np.nan
        
        rows.append({
            'hour': h,
            'city_actual': city_actual,
            'city_pred_before': before.sum(),
            'city_pred_after': after.sum(),
            'rel_err_before': rel_err_before,
            'rel_err_after': rel_err_after,
            'improvement': rel_err_before - rel_err_after,
            'n_samples': mask.sum(),
        })
    
    return pd.DataFrame(rows)


def main():
    print("=" * 60)
    print("修复包B: 早晚 ramp floor 修正")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 加载训练表
    train_path = TABLES_DIR / "distributed_train_table.pkl"
    if not train_path.exists():
        train_path = TABLES_DIR / "distributed_train_table_v159.pkl"
    
    print(f"加载训练数据: {train_path}")
    df = pd.read_pickle(train_path)
    df['time'] = pd.to_datetime(df['time'])
    df['year'] = df['time'].dt.year
    df['month'] = df['time'].dt.month
    
    # 排除异常站点
    df = df[~df['site_id'].isin(BAD_SITES)]
    
    # 分割验证集和测试集
    valid_mask = (df['year'] >= 2025) & (df['month'].between(4, 6))
    test_mask = (df['year'] >= 2025) & (df['month'] >= 7)
    
    df_valid = df[valid_mask].copy()
    df_test = df[test_mask].copy()
    
    # 加载预测结果
    pred_path = TABLES_DIR / "distributed_predictions_v159.pkl"
    print(f"加载预测结果: {pred_path}")
    pred_df = pd.read_pickle(pred_path)
    pred_df['time'] = pd.to_datetime(pred_df['time'])
    pred_df['year'] = pred_df['time'].dt.year
    pred_df['month'] = pred_df['time'].dt.month
    pred_df = pred_df[~pred_df['site_id'].isin(BAD_SITES)]
    pred_df = pred_df[(pred_df['year'] >= 2025) & (pred_df['month'] >= 7)]
    
    # 只保留有功率数据的样本
    df_valid = df_valid[df_valid['power_mw'].notna() & (df_valid['power_mw'] > 0)]
    
    print(f"验证集样本: {len(df_valid):,}")
    print(f"测试集样本: {len(pred_df):,}")
    
    # 学习 floor 参数
    print("\n学习 dawn/dusk floor 参数...")
    floor_table, hour_floor, summary_df = fit_dawn_dusk_floor(df_valid)
    
    # 保存 floor table
    summary_df.to_csv(METRICS_DIR / "dawn_dusk_floor_table.csv", index=False, encoding='utf-8-sig')
    print(f"已保存: {METRICS_DIR / 'dawn_dusk_floor_table.csv'}")
    
    # 打印 hour 级别 floor
    print("\nHour 级别 floor_factor:")
    for h in DAWN_DUSK_HOURS:
        factor = hour_floor.get(h, np.nan)
        print(f"  h={h:02d}: floor_factor={factor:.3f}" if not np.isnan(factor) else f"  h={h:02d}: N/A")
    
    # 应用 floor 修正
    print("\n应用 dawn/dusk floor 修正...")
    pred_before = pred_df[['time', 'site_id', 'power_mw', 'power_pred', 'p_base', 'solar_elevation_deg', 'capacity_mw']].copy()
    pred_after = apply_dawn_dusk_floor(pred_before, floor_table, hour_floor)
    
    # 评估修复前后
    print("\n修复前后对比:")
    df_comparison = evaluate_before_after(pred_before, pred_after)
    print(df_comparison.to_string(index=False))
    
    # 保存对比结果
    df_comparison.to_csv(METRICS_DIR / "dawn_dusk_before_after.csv", index=False, encoding='utf-8-sig')
    print(f"\n已保存: {METRICS_DIR / 'dawn_dusk_before_after.csv'}")
    
    # 保存应用后的预测
    pred_after.to_pickle(TABLES_DIR / "distributed_predictions_v159_floor_fixed.pkl")
    print(f"已保存: {TABLES_DIR / 'distributed_predictions_v159_floor_fixed.pkl'}")
    
    print("\n" + "=" * 60)
    print("修复包B完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
