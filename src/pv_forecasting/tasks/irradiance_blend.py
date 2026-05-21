from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..core.models import fit_tabular_regressor, predict_bundle
from ..core.utils import idw_predict, nrmse, rmse, safe_pickle_dump


def _coalesce_columns(df: pd.DataFrame, target: str, candidates: list[str], default=np.nan) -> pd.DataFrame:
    if target in df.columns:
        return df
    vals = None
    for c in candidates:
        if c in df.columns:
            vals = df[c] if vals is None else vals.combine_first(df[c])
    df[target] = vals if vals is not None else default
    return df


def prepare_blend_training(inverse_pred: pd.DataFrame, site_master: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ['site_id', 'lon', 'lat', 'county', 'coastal_flag'] if c in site_master.columns]
    central_sites = site_master[(site_master['dev_type'] == '集中式') & (site_master['has_geo'] == 1)][cols].copy()
    data = inverse_pred.merge(central_sites, on='site_id', how='inner', suffixes=('', '_meta'))
    data = _coalesce_columns(data, 'county', ['county', 'county_meta', 'county_x', 'county_y'], default='unknown')
    data['county'] = data['county'].fillna('unknown')
    if 'coastal_flag' not in data.columns:
        data = _coalesce_columns(data, 'coastal_flag', ['coastal_flag_meta', 'coastal_flag_x', 'coastal_flag_y'], default=0)
    rows = []
    for t, g in data.groupby('time'):
        if len(g) < 4:
            continue
        src_lon = g['lon'].to_numpy(dtype=float)
        src_lat = g['lat'].to_numpy(dtype=float)
        src_val = g['g_pred'].to_numpy(dtype=float)
        src_era5 = g['ssrd_wm2'].to_numpy(dtype=float)
        for i in range(len(g)):
            mask = np.ones(len(g), dtype=bool)
            mask[i] = False
            idw_val = idw_predict(src_lon[mask], src_lat[mask], src_val[mask], np.array([src_lon[i]]), np.array([src_lat[i]]))[0]
            era5_val = src_era5[i]
            true_val = src_val[i]
            denom = idw_val - era5_val
            alpha_opt = (true_val - era5_val) / denom if np.isfinite(denom) and abs(denom) > 1e-6 else 0.5
            alpha_opt = float(np.clip(alpha_opt, 0.0, 1.0))
            rows.append({
                'time': t,
                'site_id': g.iloc[i]['site_id'],
                'county': g.iloc[i].get('county', 'unknown'),
                'coastal_flag': g.iloc[i].get('coastal_flag', 0),
                'n_sites': int(mask.sum()),
                'idw_pred': idw_val,
                'era5_pred': era5_val,
                'true_g': true_val,
                'g_spatial_std': float(np.nanstd(src_val[mask])),
                'g_spatial_mean': float(np.nanmean(src_val[mask])),
                'alpha_target': alpha_opt,
            })
    train_df = pd.DataFrame(rows)
    if len(train_df) == 0:
        return train_df
    dt = pd.to_datetime(train_df['time'])
    train_df['hour'] = dt.dt.hour
    train_df['month'] = dt.dt.month
    train_df['year'] = dt.dt.year
    train_df['county'] = train_df['county'].fillna('unknown')
    return train_df


def train_blend_model(train_df: pd.DataFrame, model_path: Path, metrics_path: Path):
    feature_cols = ['idw_pred', 'era5_pred', 'g_spatial_std', 'g_spatial_mean', 'n_sites', 'hour', 'month', 'county', 'coastal_flag', 'site_id']
    cat_cols = ['county', 'site_id']
    train = train_df[train_df['year'] <= 2024].copy()
    valid = train_df[(train_df['year'] == 2025) & (train_df['month'] <= 6)].copy()
    test = train_df[(train_df['year'] == 2025) & (train_df['month'] > 6)].copy()
    bundle = fit_tabular_regressor(train, valid, feature_cols, 'alpha_target', cat_cols=cat_cols)
    metric_rows = []
    pred_frames = []
    for split_name, split_df in [('train', train), ('valid', valid), ('test', test)]:
        if len(split_df) == 0:
            continue
        split_df = split_df.copy()
        split_df['alpha_pred'] = np.clip(predict_bundle(bundle, split_df), 0, 1)
        split_df['g_blend_pred'] = split_df['alpha_pred'] * split_df['idw_pred'] + (1 - split_df['alpha_pred']) * split_df['era5_pred']
        metric_rows.append({
            'split': split_name,
            'rmse_idw': rmse(split_df['true_g'].to_numpy(), split_df['idw_pred'].to_numpy()),
            'rmse_era5': rmse(split_df['true_g'].to_numpy(), split_df['era5_pred'].to_numpy()),
            'rmse_blend': rmse(split_df['true_g'].to_numpy(), split_df['g_blend_pred'].to_numpy()),
            'nrmse_blend': nrmse(split_df['true_g'].to_numpy(), split_df['g_blend_pred'].to_numpy()),
            'rows': int(len(split_df)),
        })
        pred_frames.append(split_df)
    metrics_df = pd.DataFrame(metric_rows)
    safe_pickle_dump(bundle, model_path)
    metrics_df.to_csv(metrics_path, index=False, encoding='utf-8-sig')
    return bundle, metrics_df, pd.concat(pred_frames, ignore_index=True) if pred_frames else pd.DataFrame()


def infer_site_irradiance(inverse_pred: pd.DataFrame, site_master: pd.DataFrame, site_meteo: pd.DataFrame, blend_bundle) -> pd.DataFrame:
    central_cols = [c for c in ['site_id', 'lon', 'lat', 'county'] if c in site_master.columns]
    target_cols = [c for c in ['site_id', 'lon', 'lat', 'county', 'coastal_flag'] if c in site_master.columns]
    central_sites = site_master[(site_master['dev_type'] == '集中式') & (site_master['has_geo'] == 1)][central_cols].copy()
    target_sites = site_master[site_master['has_geo'] == 1][target_cols].copy()
    source = inverse_pred.merge(central_sites, on='site_id', how='inner', suffixes=('', '_meta'))
    source = _coalesce_columns(source, 'county', ['county', 'county_meta', 'county_x', 'county_y'], default='unknown')
    meteo = site_meteo[['time', 'site_id', 'ssrd_wm2']].rename(columns={'ssrd_wm2': 'era5_site_ssrd'})
    out_rows = []
    for t, g in source.groupby('time'):
        if len(g) < 2:
            continue
        target = target_sites.copy()
        if 'county' not in target.columns:
            target['county'] = 'unknown'
        if 'coastal_flag' not in target.columns:
            target['coastal_flag'] = 0
        idw_vals = idw_predict(g['lon'].to_numpy(dtype=float), g['lat'].to_numpy(dtype=float), g['g_pred'].to_numpy(dtype=float), target['lon'].to_numpy(dtype=float), target['lat'].to_numpy(dtype=float))
        era5_t = meteo[meteo['time'] == t][['site_id', 'era5_site_ssrd']]
        target = target.merge(era5_t, on='site_id', how='left')
        target['time'] = t
        target['idw_pred'] = idw_vals
        target['n_sites'] = len(g)
        target['g_spatial_std'] = float(np.nanstd(g['g_pred'].to_numpy(dtype=float)))
        target['g_spatial_mean'] = float(np.nanmean(g['g_pred'].to_numpy(dtype=float)))
        target['hour'] = pd.Timestamp(t).hour
        target['month'] = pd.Timestamp(t).month
        pred_df = target[['idw_pred', 'era5_site_ssrd', 'g_spatial_std', 'g_spatial_mean', 'n_sites', 'hour', 'month', 'county', 'coastal_flag', 'site_id']].rename(columns={'era5_site_ssrd': 'era5_pred'})
        alpha = np.clip(predict_bundle(blend_bundle, pred_df), 0, 1)
        target['alpha_pred'] = alpha
        target['g_blend_pred'] = alpha * target['idw_pred'] + (1 - alpha) * target['era5_site_ssrd']
        out_rows.append(target[['time', 'site_id', 'g_blend_pred', 'alpha_pred', 'idw_pred', 'era5_site_ssrd']])
    return pd.concat(out_rows, ignore_index=True) if out_rows else pd.DataFrame(columns=['time', 'site_id', 'g_blend_pred'])
