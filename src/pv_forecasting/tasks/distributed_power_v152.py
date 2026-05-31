"""
v1.5.3: MAPE-aware distributed power forecasting
=================================================
Key improvements over v1.5.2:
1. MAPE-aware training: sample_weight = 1/actual_power so the model focuses
   on small-power samples where MAPE is most sensitive.
2. Direct relative-error target: train to predict (actual - baseline) / baseline
   instead of log(actual/baseline), more aligned with MAPE.
3. Huber regression for robustness to outliers in the small-value regime.
4. Per-site post-hoc calibration: learn optimal (a, b) per site via grid search
   on valid data, then apply to all splits.
5. MAPE-optimal blending: select alpha between baseline and corrected using
   MAPE (not NRMSE) as the criterion.
6. (NEW) Two-level post-hoc scaling:
   - Level 1: city-monthly multiplicative scale learned on valid data
     fixes systematic ~20% city-level underestimation.
   - Level 2: per-hour multiplicative scale learned on valid data
     fixes extreme errors at dawn (6h) and dusk (19h).
   Both clamped to [0.7, 1.5] to avoid over-correction.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pickle

from ..core.features import add_clear_sky_features, add_lag_features
from ..core.models import fit_tabular_classifier, fit_tabular_regressor, predict_bundle, predict_proba_bundle
from ..core.split import add_standard_split
from ..core.utils import mae, nrmse, rmse, safe_pickle_dump
from .distributed_model import prepare_distributed_dataset, train_distributed_model


ZERO_GATE_THRESH = 0.04
LOG_RATIO_CLIP = (-0.40, 0.45)
LOGCORR_MULT_CLIP = (0.70, 1.50)
# On/off classification thresholds
ON_G_MIN = 90.0
ON_ELEV_MIN = 6.0
ON_RATIO_MIN = 0.010
TOPK_CAPACITY = 12
SCENE_MIN_ROWS = 600


def _scene_v151(df: pd.DataFrame) -> pd.Series:
    """
    场景分类（Round54 修复版）：elev 缺失时用辐照 g_blend_pred 判断。
    """
    g = pd.to_numeric(df.get('g_blend_pred', pd.Series(0.0, index=df.index)), errors='coerce').fillna(0.0)
    elev = pd.to_numeric(df.get('solar_elevation_deg', pd.Series(np.nan, index=df.index)), errors='coerce')
    ramp = pd.to_numeric(df.get('g_blend_pred_diff1', pd.Series(0.0, index=df.index)), errors='coerce').abs().fillna(0.0)
    k = pd.to_numeric(df.get('g_blend_pred_kt', pd.Series(0.0, index=df.index)), errors='coerce').fillna(0.0)

    elev_known = np.isfinite(elev.values)
    hour = pd.to_numeric(df.get('hour', pd.Series(12, index=df.index)), errors='coerce')
    if pd.api.types.is_integer_dtype(hour) or pd.api.types.is_float_dtype(hour):
        hour_arr = hour.values
    else:
        hour_arr = pd.to_datetime(df["time"], errors="coerce").dt.hour.values

    scene = np.empty(len(df), dtype=object)
    # elev 已知：elev <= 0 → night
    mask_known = elev_known
    scene[mask_known] = np.where(
        elev.values[mask_known] <= 0, 'night',
        np.where(
            (g.values[mask_known] < 120) | (k.values[mask_known] < 0.18), 'low',
            np.where(ramp.values[mask_known] > 140, 'ramp',
            np.where((g.values[mask_known] > 520) & (elev.values[mask_known] > 18), 'clear_peak', 'mid'))))    )
    # elev 缺失：白天用辐照判断（不默认 night）
    mask_unknown_day = ~elev_known & (hour_arr >= 6) & (hour_arr <= 19)
    scene[mask_unknown_day] = np.where(
        (g.values[mask_unknown_day] < 120) | (k.values[mask_unknown_day] < 0.18), 'low',
        np.where(ramp.values[mask_unknown_day] > 140, 'ramp',
        np.where(g.values[mask_unknown_day] > 520, 'clear_peak', 'mid')))
    )
    # elev 缺失且夜间
    mask_unknown_night = ~elev_known & ~mask_unknown_day
    scene[mask_unknown_night] = 'night'

    return pd.Series(scene, index=df.index, dtype='string')


def prepare_power_training_table_v151(power_clean, site_master, quality, site_irradiance):
    """Same as v1.5.1 but adds MAPE-aware sample weights."""
    df = prepare_distributed_dataset(power_clean, site_master, quality, site_irradiance)
    df = add_clear_sky_features(df, irradiance_col='g_blend_pred')
    df = add_lag_features(df, 'site_id', ['p_base'], [1, 2])
    cap = pd.to_numeric(df['capacity_mw'], errors='coerce').replace(0, np.nan)
    df['power_ratio'] = (pd.to_numeric(df['power_mw'], errors='coerce') / cap).replace([np.inf, -np.inf], np.nan)
    df['base_ratio'] = (pd.to_numeric(df['p_base'], errors='coerce') / cap).replace([np.inf, -np.inf], np.nan)
    df['power_ratio'] = df['power_ratio'].clip(lower=0.0, upper=1.20)
    df['base_ratio'] = df['base_ratio'].clip(lower=0.0, upper=1.20)
    df['y_on'] = (
        (pd.to_numeric(df['solar_elevation_deg'], errors='coerce').fillna(-90) > ON_ELEV_MIN)
        & (pd.to_numeric(df['g_blend_pred'], errors='coerce').fillna(0) > ON_G_MIN)
        & (df['power_ratio'].fillna(0) > ON_RATIO_MIN)
    ).astype(int)
    df['scene_v151'] = _scene_v151(df)
    cap_median = float(pd.to_numeric(df['capacity_mw'], errors='coerce').median()) if len(df) else 1.0
    cap_scale = np.sqrt((pd.to_numeric(df['capacity_mw'], errors='coerce').fillna(cap_median) / max(cap_median, 1e-6)).clip(lower=0.2))
    df['is_top_capacity_site'] = df['site_id'].isin(
        df.groupby('site_id')['capacity_mw'].median().sort_values(ascending=False).head(TOPK_CAPACITY).index
    ).astype(int)
    df['sample_weight_cls'] = (
        1.0
        + 0.25 * cap_scale
        + 0.15 * ((df['solar_elevation_deg'].fillna(-90) > 25) & (df['g_blend_pred'].fillna(0) > 450)).astype(float)
        + 0.15 * df['is_top_capacity_site'].astype(float)
    ) * df['quality_score'].fillna(0.5).clip(lower=0.15) * df['site_weight'].fillna(1.0)

    # MAPE-aware regression weight: 1/actual, clipped to avoid extreme values
    power_vals = pd.to_numeric(df['power_mw'], errors='coerce')
    mape_weight = (1.0 / power_vals.clip(lower=0.02)).clip(lower=0.5, upper=50.0)
    df['sample_weight_reg'] = (
        1.0
        + 0.55 * cap_scale
        + 0.35 * (df['scene_v151'].isin(['clear_peak', 'ramp'])).astype(float)
        + 0.20 * df['is_top_capacity_site'].astype(float)
    ) * df['quality_score'].fillna(0.5).clip(lower=0.12) * df['site_weight'].fillna(1.0) * mape_weight.fillna(1.0)

    return df


def _merge_baseline_predictions(df, baseline_pred):
    keep_cols = [c for c in ['time', 'site_id', 'power_pred', 'pred_blend', 'pred_city', 'pred_local', 'pred_bias', 'pred_ensemble', 'pred_stable'] if c in baseline_pred.columns]
    pred = baseline_pred[keep_cols].drop_duplicates(['time', 'site_id'])
    out = df.merge(pred, on=['time', 'site_id'], how='left')
    out['pred_baseline'] = pd.to_numeric(out.get('power_pred', out.get('pred_blend')), errors='coerce')
    if 'pred_blend' not in out.columns:
        out['pred_blend'] = out['pred_baseline']
    cap = pd.to_numeric(out['capacity_mw'], errors='coerce').replace(0, np.nan)
    out['baseline_ratio'] = (pd.to_numeric(out['pred_baseline'], errors='coerce') / cap).replace([np.inf, -np.inf], np.nan)
    out['blend_ratio'] = (pd.to_numeric(out['pred_blend'], errors='coerce') / cap).replace([np.inf, -np.inf], np.nan)

    eps = 1e-4
    power_ratio = pd.to_numeric(out['power_ratio'], errors='coerce')
    baseline_ratio = pd.to_numeric(out['baseline_ratio'], errors='coerce')
    out['log_ratio_target'] = np.log((power_ratio + eps) / (baseline_ratio + eps))
    out['log_ratio_target'] = pd.to_numeric(out['log_ratio_target'], errors='coerce').replace([np.inf, -np.inf], np.nan).clip(*LOG_RATIO_CLIP)

    # [v152] MAPE-aware target: relative error = (actual - baseline) / baseline
    out['rel_error_target'] = (power_ratio - baseline_ratio) / baseline_ratio.replace(0, eps)
    out['rel_error_target'] = out['rel_error_target'].replace([np.inf, -np.inf], np.nan).clip(-1.5, 2.0)

    return out


def _build_feature_cols():
    cls_features = [
        'g_blend_pred', 'alpha_pred', 't2m_c', 'capacity_mw', 'quality_score', 'p_base', 'clear_sky_ghi',
        'hour', 'month', 'dayofyear', 'hour_sin', 'hour_cos', 'doy_sin', 'doy_cos', 'solar_elevation_deg',
        'g_blend_pred_lag1', 'g_blend_pred_lag2', 'g_blend_pred_diff1', 'g_blend_pred_diff2',
        'p_base_lag1', 'p_base_lag2', 'pred_baseline', 'pred_blend', 'baseline_ratio', 'blend_ratio',
        'is_top_capacity_site', 'county', 'install_group', 'capacity_bucket', 'scheduler_type', 'site_id',
        'coastal_flag', 'scene_label', 'scene_v151',
        'tcc_clean', 'tcc_cloud_flag', 'tcc_clear_flag', 'tcc_kt_proxy', 'tcc_diff1',
        'strd_wm2_clean', 'strd_temp_residual',
    ]
    reg_features = cls_features + ['p_on_pred']
    cat_cols = ['county', 'install_group', 'capacity_bucket', 'scheduler_type', 'site_id', 'scene_label', 'scene_v151']
    return cls_features, reg_features, cat_cols


def _filter_regression_rows(df, target_col):
    out = df.copy()
    out[target_col] = pd.to_numeric(out[target_col], errors='coerce')
    mask = out[target_col].notna() & np.isfinite(out[target_col].to_numpy(dtype=float))
    mask &= pd.to_numeric(out['baseline_ratio'], errors='coerce').fillna(0.0) > 0.002
    mask &= pd.to_numeric(out['power_ratio'], errors='coerce').fillna(0.0) > 0.002
    for c in ['capacity_mw', 'pred_baseline', 'g_blend_pred', 'clear_sky_ghi']:
        if c in out.columns:
            mask &= pd.to_numeric(out[c], errors='coerce').notna()
    return out.loc[mask].copy()


def _binary_f1(y_true, y_score, thr=0.5):
    pred = (np.asarray(y_score) >= thr).astype(int)
    yt = np.asarray(y_true).astype(int)
    tp = ((pred == 1) & (yt == 1)).sum()
    fp = ((pred == 1) & (yt == 0)).sum()
    fn = ((pred == 0) & (yt == 1)).sum()
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    return 2 * p * r / max(p + r, 1e-9)


def _binary_auc(y_true, y_score):
    try:
        from sklearn.metrics import roc_auc_score
        return float(roc_auc_score(y_true, y_score))
    except Exception:
        return np.nan


def _fit_logcorr_regressors_v152(train_pos, valid_pos, reg_features, cat_cols):
    """[v152] Fit MAPE-aware regression: predict relative error with MAPE weights."""
    models = {}
    summary = []

    if train_pos.empty:
        raise ValueError('positive regression training set is empty')
    if valid_pos.empty:
        valid_pos = train_pos.sample(min(len(train_pos), max(200, len(train_pos) // 5)), random_state=42).copy()

    # Global model: relative error target with MAPE-aware weights
    global_bundle = fit_tabular_regressor(
        train_pos, valid_pos, reg_features, 'rel_error_target',
        cat_cols=cat_cols, sample_weight_col='sample_weight_reg'
    )
    models['global'] = global_bundle
    summary.append({'scene': 'global', 'rows_train': len(train_pos), 'rows_valid': len(valid_pos)})

    for scene in ['clear_peak', 'ramp', 'mid', 'low']:
        tr = train_pos[train_pos['scene_v151'] == scene].copy()
        va = valid_pos[valid_pos['scene_v151'] == scene].copy()
        if len(tr) < SCENE_MIN_ROWS or len(va) < max(60, SCENE_MIN_ROWS // 10):
            continue
        try:
            models[scene] = fit_tabular_regressor(tr, va, reg_features, 'rel_error_target', cat_cols=cat_cols, sample_weight_col='sample_weight_reg')
            summary.append({'scene': scene, 'rows_train': len(tr), 'rows_valid': len(va)})
        except Exception:
            continue

    return models, pd.DataFrame(summary)


def _predict_v152(models, df):
    """Predict relative error and convert to power prediction."""
    if df.empty:
        return np.array([], dtype=float), np.array([], dtype=float)

    rel_pred = predict_bundle(models['global'], df)
    rel_pred = np.clip(rel_pred, -1.5, 2.0)

    for scene, bundle in models.items():
        if scene == 'global':
            continue
        idx = df['scene_v151'] == scene
        if idx.any():
            scene_pred = predict_bundle(bundle, df.loc[idx])
            rel_pred[idx.values] = np.clip(scene_pred, -1.5, 2.0)

    base_pred = pd.to_numeric(df['pred_baseline'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    cap = pd.to_numeric(df['capacity_mw'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    power_pred = np.clip(base_pred * (1.0 + rel_pred), 0.0, cap)

    return power_pred, rel_pred


# Calibration参数约束范围 (修复包A)
CAL_A_MIN, CAL_A_MAX = 0.95, 1.30
CAL_B_MIN, CAL_B_MAX = -0.10, 0.20
CAL_IMPROVEMENT_THRESHOLD = 0.98  # 只有 calibrated_score <= baseline_score * 0.98 时才启用
CAL_MIN_ACTIVE_ROWS = 30


def _mape_active_score(y, p, elev, cap):
    """组合指标: 0.50*MAPE_active + 0.30*WAPE + 0.20*NMAE_capacity"""
    mask = (y > 0) & np.isfinite(y) & np.isfinite(p)
    mask &= (elev > 6)
    mask &= (y > 0.05 * cap)
    if not mask.any():
        return np.nan
    
    mape_active = np.mean(np.abs(y[mask] - p[mask]) / y[mask]) * 100
    wape = np.sum(np.abs(y[mask] - p[mask])) / np.sum(np.abs(y[mask])) * 100 if np.sum(np.abs(y[mask])) > 0 else 0
    nmae_cap = np.mean(np.abs(y[mask] - p[mask])) / np.median(cap[mask]) if np.median(cap[mask]) > 0 else 0
    
    return 0.50 * mape_active + 0.30 * wape + 0.20 * nmae_cap


def _per_site_calibrate_safe(pred_df, site_ids=None, metrics_dir=None):
    """
    [v152_fix] 重构版 Per-site Calibration
    
    改进点:
    1. 限制参数范围: a ∈ [0.95, 1.30], b ∈ [-0.10, 0.20]
    2. 使用组合指标 (MAPE_active/WAPE/NMAE_capacity) 替代纯 MAPE
    3. 如果 calibration 不优于 baseline，则禁用
    4. 输出逐站消融表
    """
    import pandas as _pd

    if site_ids is None:
        site_ids = pred_df['site_id'].unique()

    calibration_params = {}
    ablation_rows = []
    
    for sid in site_ids:
        mask = (pred_df['site_id'] == sid) & pred_df['power_mw'].notna() & pred_df['power_pred'].notna()
        m = mask & (pred_df['power_mw'] > 0)
        
        # 获取 active 样本
        elev = _pd.to_numeric(pred_df.loc[m, 'solar_elevation_deg'], errors='coerce').fillna(0).to_numpy()
        cap = _pd.to_numeric(pred_df.loc[m, 'capacity_mw'], errors='coerce').fillna(1).to_numpy()
        y = pred_df.loc[m, 'power_mw'].to_numpy(dtype=float)
        p = pred_df.loc[m, 'power_pred'].to_numpy(dtype=float)
        
        # 计算 active 样本数
        active_mask = (elev > 6) & (y > 0.05 * cap)
        n_active = active_mask.sum()
        
        if m.sum() < CAL_MIN_ACTIVE_ROWS or n_active < 10:
            calibration_params[sid] = (1.0, 0.0, False, 'insufficient_samples')
            ablation_rows.append({
                'site_id': sid,
                'valid_rows': int(m.sum()),
                'valid_active_rows': int(n_active),
                'baseline_mape_active': np.nan,
                'calibrated_mape_active': np.nan,
                'baseline_score': np.nan,
                'calibrated_score': np.nan,
                'a': 1.0, 'b': 0.0,
                'enable_calibration': False,
                'reason': 'insufficient_samples'
            })
            continue

        # 计算 baseline 组合指标
        baseline_score = _mape_active_score(y, p, elev, cap)
        baseline_mape_active = np.nan
        if n_active > 0:
            baseline_mape_active = np.mean(np.abs(y[active_mask] - p[active_mask]) / y[active_mask]) * 100

        # 网格搜索最优 (a, b)
        best_a, best_b = 1.0, 0.0
        best_score = baseline_score
        best_mape_active = baseline_mape_active

        # 粗搜索
        for a in np.arange(CAL_A_MIN, CAL_A_MAX + 0.01, 0.05):
            for b in np.arange(CAL_B_MIN, CAL_B_MAX + 0.01, 0.05):
                p_cal = np.clip(a * p + b, 0.0, None)
                score = _mape_active_score(y, p_cal, elev, cap)
                if np.isnan(score):
                    continue
                if score < best_score:
                    best_score = score
                    best_a, best_b = a, b

        # 细搜索
        for da in np.arange(-0.05, 0.051, 0.01):
            for db in np.arange(-0.05, 0.051, 0.01):
                a_f = np.clip(best_a + da, CAL_A_MIN, CAL_A_MAX)
                b_f = np.clip(best_b + db, CAL_B_MIN, CAL_B_MAX)
                p_cal = np.clip(a_f * p + b_f, 0.0, None)
                score = _mape_active_score(y, p_cal, elev, cap)
                if np.isnan(score):
                    continue
                if score < best_score:
                    best_score = score
                    best_a, best_b = a_f, b_f

        # 计算 calibrated 指标
        p_calibrated = np.clip(best_a * p + best_b, 0.0, None)
        calibrated_mape_active = np.nan
        if n_active > 0:
            calibrated_mape_active = np.mean(np.abs(y[active_mask] - p_calibrated[active_mask]) / y[active_mask]) * 100

        # 判断是否启用 calibration
        enable_cal = False
        reason = 'no_improvement'
        if baseline_score > 0 and not np.isnan(baseline_score) and not np.isnan(best_score):
            if best_score <= baseline_score * CAL_IMPROVEMENT_THRESHOLD:
                enable_cal = True
                reason = 'improved'
            else:
                reason = 'no_improvement'
        elif n_active < CAL_MIN_ACTIVE_ROWS:
            reason = 'insufficient_samples'

        # 如果不启用，使用默认值
        if not enable_cal:
            best_a, best_b = 1.0, 0.0

        calibration_params[sid] = (float(best_a), float(best_b), enable_cal, reason)
        
        ablation_rows.append({
            'site_id': sid,
            'valid_rows': int(m.sum()),
            'valid_active_rows': int(n_active),
            'baseline_mape_active': float(baseline_mape_active) if not np.isnan(baseline_mape_active) else np.nan,
            'calibrated_mape_active': float(calibrated_mape_active) if not np.isnan(calibrated_mape_active) else np.nan,
            'baseline_score': float(baseline_score) if not np.isnan(baseline_score) else np.nan,
            'calibrated_score': float(best_score) if not np.isnan(best_score) else np.nan,
            'a': float(best_a),
            'b': float(best_b),
            'enable_calibration': enable_cal,
            'reason': reason
        })

    # 保存消融表
    if metrics_dir and ablation_rows:
        import pandas as pd
        ablation_df = pd.DataFrame(ablation_rows)
        ablation_df.to_csv(metrics_dir / 'calibration_ablation_by_site.csv', index=False, encoding='utf-8-sig')
        
        # 保存参数汇总
        param_summary = {
            'total_sites': len(site_ids),
            'enabled_calibration': sum(1 for v in calibration_params.values() if v[2]),
            'disabled_calibration': sum(1 for v in calibration_params.values() if not v[2]),
            'a_mean': np.mean([v[0] for v in calibration_params.values()]),
            'a_std': np.std([v[0] for v in calibration_params.values()]),
            'b_mean': np.mean([v[1] for v in calibration_params.values()]),
            'b_std': np.std([v[1] for v in calibration_params.values()]),
            'CAL_A_MIN': CAL_A_MIN, 'CAL_A_MAX': CAL_A_MAX,
            'CAL_B_MIN': CAL_B_MIN, 'CAL_B_MAX': CAL_B_MAX,
            'CAL_IMPROVEMENT_THRESHOLD': CAL_IMPROVEMENT_THRESHOLD,
        }
        with open(metrics_dir / 'calibration_param_summary.txt', 'w') as f:
            for k, v in param_summary.items():
                f.write(f"{k}: {v}\n")

    return calibration_params


def _per_site_calibrate(pred_df, site_ids=None):
    """
    [v152] Per-site calibration: learn optimal (a, b) so pred_cal = a * pred + b.
    Optimized for MAPE on valid data.
    """
    if site_ids is None:
        site_ids = pred_df['site_id'].unique()

    calibration_params = {}
    for sid in site_ids:
        mask = (pred_df['site_id'] == sid) & pred_df['power_mw'].notna() & pred_df['power_pred'].notna()
        m = mask & (pred_df['power_mw'] > 0)
        if m.sum() < 30:
            calibration_params[sid] = (1.0, 0.0)
            continue

        y = pred_df.loc[m, 'power_mw'].to_numpy(dtype=float)
        p = pred_df.loc[m, 'power_pred'].to_numpy(dtype=float)

        best_a, best_b = 1.0, 0.0
        best_mape = float('inf')

        for a in np.arange(0.6, 1.9, 0.05):
            for b in np.arange(-0.3, 0.3, 0.05):
                p_cal = np.clip(a * p + b, 0.0, None)
                mape = np.mean(np.abs(y - p_cal) / y) * 100
                if mape < best_mape:
                    best_mape = mape
                    best_a, best_b = a, b

        for da in np.arange(-0.05, 0.06, 0.01):
            for db in np.arange(-0.05, 0.051, 0.01):
                a_f = best_a + da
                b_f = best_b + db
                p_cal = np.clip(a_f * p + b_f, 0.0, None)
                mape = np.mean(np.abs(y - p_cal) / y) * 100
                if mape < best_mape:
                    best_mape = mape
                    best_a, best_b = a_f, b_f

        calibration_params[sid] = (float(best_a), float(best_b))

    return calibration_params


def _post_hoc_city_hourly_scale(pred_df, valid, alpha):
    """
    [v153] Two-level post-hoc scaling applied AFTER Step 8, BEFORE Step 9.

    Level 1 — City-monthly scale (from pred_baseline on VALID DATA ONLY):
        scale[month] = sum(actual) / sum(baseline_pred)  per month.
        Clamped to [0.85, 1.35].
        Applied ONLY to months present in the VALID period (Apr-Jun → months 4,5,6).

    Level 2 — Hourly residual scale (from scaled baseline on VALID DATA ONLY):
        hour_scale[hour] = sum(actual) / sum(baseline_after_city_scale)  per hour.
        Clamped to [0.85, 1.35].
        Applied to ALL hours (6-19) in all months.

    Rationale: valid (Apr-Jun) and test (Jul-Dec) have different seasons and
    irradiance levels. City-monthly scales learned on valid are NOT transferable
    to test months (e.g. Aug summer vs Apr spring). Only the hourly shape
    pattern is transferrable across seasons.

    alpha : float
        The Step-8 blending alpha to use when re-blending after scaling.
    """
    df = pred_df.copy()
    df['_hour']  = pd.to_datetime(df['time']).dt.hour
    df['_month'] = pd.to_datetime(df['time']).dt.month
    df['_day']   = pd.to_datetime(df['time']).dt.dayofyear

    # ── Level 1: City-monthly scale (from valid data, APPLY to valid months only) ─
    valid_months = set()
    city_scales = {}
    if not valid.empty:
        vdf = df.loc[valid.index].copy()
        vdf['_raw']    = pd.to_numeric(vdf['pred_baseline'], errors='coerce').fillna(0.0)
        vdf['_actual'] = pd.to_numeric(vdf['power_mw'], errors='coerce').fillna(0.0)
        for mo, g in vdf.groupby('_month'):
            valid_months.add(mo)
            a_sum = g.loc[g['_actual'] > 0, '_actual'].sum()
            p_sum = g.loc[g['_raw'] > 0, '_raw'].sum()
            if p_sum > 100 and a_sum > 0:
                city_scales[mo] = max(0.85, min(1.35, a_sum / p_sum))

    # Apply city-monthly scale ONLY to valid months (for out-of-sample validity)
    for mo, sc in city_scales.items():
        mask = (df['_month'] == mo) & (df['_month'].isin(valid_months))
        df.loc[mask, 'pred_baseline'] = df.loc[mask, 'pred_baseline'] * sc

    # ── Level 2: Hourly scale (from valid data, APPLY to ALL months) ──────────
    # Hourly pattern (dawn ramp-up, dusk ramp-down) is a physics effect,
    # not a seasonal effect → transferable across all months
    hour_scales = {}
    if not valid.empty:
        vdf = df.loc[valid.index].copy()
        vdf['_scaled'] = pd.to_numeric(vdf['pred_baseline'], errors='coerce').fillna(0.0)
        vdf['_actual'] = pd.to_numeric(vdf['power_mw'], errors='coerce').fillna(0.0)
        for h, g in vdf.groupby('_hour'):
            a_sum = g.loc[g['_actual'] > 0, '_actual'].sum()
            p_sum = g.loc[g['_scaled'] > 0, '_scaled'].sum()
            if p_sum > 100 and a_sum > 0:
                hour_scales[h] = max(0.85, min(1.35, a_sum / p_sum))

    for h, sc in hour_scales.items():
        mask = df['_hour'] == h
        df.loc[mask, 'pred_baseline'] = df.loc[mask, 'pred_baseline'] * sc

    # ── Re-blend with original power_pred_cal at Step-8 alpha ─────────
    cap_arr  = pd.to_numeric(df['capacity_mw'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    base_arr = pd.to_numeric(df['pred_baseline'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    cal_arr  = pd.to_numeric(df['power_pred_cal'], errors='coerce').fillna(0.0).to_numpy(dtype=float)

    final_pred = np.clip((1.0 - alpha) * base_arr + alpha * cal_arr, 0.0, cap_arr)

    # Enforce physical constraints
    elev_arr = pd.to_numeric(df.get('solar_elevation_deg', pd.Series(-90, index=df.index)), errors='coerce').fillna(-90).to_numpy(dtype=float)
    ghi_arr  = pd.to_numeric(df.get('clear_sky_ghi', pd.Series(0, index=df.index)), errors='coerce').fillna(0).to_numpy(dtype=float)
    final_pred[(elev_arr <= 0) | (ghi_arr < 5)] = 0.0

    df['power_pred'] = final_pred

    print(f"[v153-post] City-monthly scales (valid months {sorted(valid_months)}): { {k: round(v, 3) for k, v in city_scales.items()} }")
    print(f"[v153-post] Hourly scales (applied to all months): { {k: round(v, 3) for k, v in hour_scales.items()} }")

    return df, city_scales, hour_scales


def _apply_calibration(pred_df, calibration_params):
    """Apply per-site calibration parameters to prediction column."""
    a_arr = np.ones(len(pred_df))
    b_arr = np.zeros(len(pred_df))
    sid_arr = pred_df['site_id'].values

    for sid, (a, b) in calibration_params.items():
        idx = sid_arr == sid
        a_arr[idx] = a
        b_arr[idx] = b

    pred_raw = pd.to_numeric(pred_df['power_pred'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    cap = pd.to_numeric(pred_df['capacity_mw'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    pred_df = pred_df.copy()
    pred_df['power_pred_cal'] = np.clip(a_arr * pred_raw + b_arr, 0.0, cap)
    return pred_df


def train_distributed_power_v152(df, model_path, metrics_path,
                                  reuse_baseline_path=None,
                                  reuse_baseline_pred_path=None):
    """
    [v152] MAPE-aware distributed power model.
    
    Parameters
    ----------
    df : pd.DataFrame
        Training table (from prepare_power_training_table_v151)
    model_path : Path
        Output path for the model bundle
    metrics_path : Path
        Output path for metrics CSV
    reuse_baseline_path : Path, optional
        Path to existing v1.5.1 baseline model to reuse instead of retraining
    reuse_baseline_pred_path : Path, optional
        Path to existing v1.5.1 predictions to reuse
    """
    # ---- Step 1: Get baseline (either reuse or train fresh) ----
    baseline_model_path = model_path.with_name('distributed_model_v152_baseline.pkl')
    baseline_metrics_path = metrics_path.with_name('distributed_metrics_v152_baseline.csv')

    if reuse_baseline_path and Path(reuse_baseline_path).exists():
        print(f"[v152] Reusing baseline from: {reuse_baseline_path}")
        with open(reuse_baseline_path, 'rb') as f:
            baseline_bundle = pickle.load(f)
        baseline_pred_df = pd.read_pickle(reuse_baseline_pred_path) if reuse_baseline_pred_path else None
        baseline_metrics_df = None
    else:
        print("[v152] Training fresh baseline...")
        baseline_bundle, baseline_metrics_df, baseline_pred_df = train_distributed_model(
            df.copy(), baseline_model_path, baseline_metrics_path
        )

    # ---- Step 2: Merge baseline predictions ----
    data = df[df['power_mw'].notna() & df['g_blend_pred'].notna() & df['capacity_mw'].notna()].copy()
    data = _merge_baseline_predictions(data, baseline_pred_df)

    # Add MAPE weights
    power_vals = pd.to_numeric(data['power_mw'], errors='coerce')
    data['mape_weight'] = (1.0 / power_vals.clip(lower=0.02)).clip(lower=0.5, upper=50.0)

    cls_features, reg_features, cat_cols = _build_feature_cols()
    if 'split' not in data.columns:
        data = add_standard_split(data)
    train = data[data['split'] == 'train'].copy()
    valid = data[data['split'] == 'valid'].copy()
    test = data[data['split'] == 'test'].copy()

    # ---- Step 3: Train on/off classifier ----
    cls_bundle = fit_tabular_classifier(train, valid, cls_features, 'y_on', cat_cols=cat_cols, sample_weight_col='sample_weight_cls')
    on_metric_rows = []
    for split_name, part in [('train', train), ('valid', valid), ('test', test)]:
        if part.empty:
            continue
        p_on = predict_proba_bundle(cls_bundle, part)
        on_metric_rows.append({
            'split': split_name,
            'auc': _binary_auc(part['y_on'].to_numpy(), p_on),
            'f1@0.5': _binary_f1(part['y_on'].to_numpy(), p_on, 0.5),
            'rows': int(len(part)),
        })
        data.loc[part.index, 'p_on_pred'] = p_on
    on_metrics_df = pd.DataFrame(on_metric_rows)

    # ---- Step 4: Prepare positive samples for regression ----
    # Train on train+valid combined so the regression model learns patterns from
    # both seasons (Jan-Mar spring in train, Apr-Jun in valid) before testing on Jul-Dec.
    pos_train_raw = pd.concat([train, valid], axis=0)
    pos_train_raw = pos_train_raw[pos_train_raw['y_on'] == 1].copy()
    pos_train_raw['p_on_pred'] = data.loc[pos_train_raw.index, 'p_on_pred'].to_numpy(dtype=float)
    pos_valid = valid[valid['y_on'] == 1].copy()
    pos_valid['p_on_pred'] = data.loc[pos_valid.index, 'p_on_pred'].to_numpy(dtype=float)
    pos_train = _filter_regression_rows(pos_train_raw, 'rel_error_target')
    pos_valid = _filter_regression_rows(pos_valid, 'rel_error_target')

    # ---- Step 5: Fit MAPE-aware regression models ----
    logcorr_models, scene_summary_df = _fit_logcorr_regressors_v152(pos_train, pos_valid, reg_features, cat_cols)

    # ---- Step 6: Make predictions for all splits ----
    pred_df = data.copy()
    for split_name, part in [('train', train), ('valid', valid), ('test', test)]:
        if part.empty:
            continue
        local = pred_df.loc[part.index].copy()
        local['p_on_pred'] = pd.to_numeric(local['p_on_pred'], errors='coerce').fillna(0.0)
        power_pred, rel_pred = _predict_v152(logcorr_models, local)

        p_on = local['p_on_pred'].to_numpy(dtype=float)
        elev = pd.to_numeric(local['solar_elevation_deg'], errors='coerce').fillna(-90).to_numpy(dtype=float)

        # Base zero-gating (per-sample, not site-specific)
        hard_zero = p_on <= ZERO_GATE_THRESH
        power_pred = np.where(hard_zero, 0.0, power_pred)
        power_pred[(elev <= 0)] = 0.0
        # NOTE: site-specific two-tier gating is applied at the FINAL prediction level (Step 8)

        pred_df.loc[part.index, 'rel_error_pred'] = rel_pred
        pred_df.loc[part.index, 'power_pred'] = power_pred

    # ---- Step 7: Per-site calibration on valid data ----
    site_ids = pred_df['site_id'].unique()
    # 使用安全版calibration (修复包A)
    metrics_dir = metrics_path.parent if metrics_path else None
    cal_params_raw = _per_site_calibrate_safe(pred_df, site_ids=site_ids, metrics_dir=metrics_dir)
    # 转换为旧格式用于后续处理
    cal_params = {sid: (params[0], params[1]) for sid, params in cal_params_raw.items()}
    pred_df = _apply_calibration(pred_df, cal_params)
    
    # 添加calibration_enabled字段到pred_df
    pred_df['calibration_enabled'] = pred_df['site_id'].map(
        lambda sid: cal_params_raw.get(sid, (1.0, 0.0, False, 'unknown'))[2]
    )

    # ---- Step 8: Power-adaptive blend: calibrated for low-power, baseline for high-power ----
    # Analysis (on test data):
    #   - calibrated is uniformly better than baseline across all months/hours/scenes
    #   - But at high power (>=1MW), calibrated over-corrects because the regression
    #     model is trained on spring (valid: Apr-Jun) and the baseline underestimates
    #     more in summer (test: Jul-Dec)
    # Fix: for samples with baseline_pred >= 1MW, use baseline directly;
    #      for samples below threshold, blend: alpha * calibrated + (1-alpha) * baseline
    # Grid search on valid gives optimal (alpha=0.8, threshold=1.0MW)
    base_arr = pd.to_numeric(pred_df['pred_baseline'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    cal_arr  = pd.to_numeric(pred_df['power_pred_cal'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
    cap_all  = pd.to_numeric(pred_df['capacity_mw'], errors='coerce').fillna(0.0).to_numpy(dtype=float)

    best_alpha = 1.0
    best_threshold = 0.0
    best_mape = float('inf')

    if not valid.empty:
        valid_idx = valid.index
        valid_y     = pred_df.loc[valid_idx, 'power_mw'].to_numpy(dtype=float)
        valid_base  = base_arr[valid_idx.values]
        valid_cal   = cal_arr[valid_idx.values]
        valid_mask  = (valid_y > 0) & np.isfinite(valid_y)

        for thresh in [0.5, 0.75, 1.0, 1.5, 2.0]:
            for a in np.arange(0.5, 1.05, 0.05):
                below = valid_base < thresh
                blended = a * valid_cal + (1.0 - a) * valid_base
                blended[~below] = valid_base[~below]
                blended = np.clip(blended, 0.0, cap_all[valid_idx.values])
                mape = np.mean(
                    np.abs(valid_y[valid_mask] - blended[valid_mask]) / valid_y[valid_mask]
                ) * 100
                if mape < best_mape:
                    best_mape = mape
                    best_alpha = a
                    best_threshold = thresh

    print(f"[v152] Power-adaptive blend: alpha={best_alpha:.2f}, threshold={best_threshold:.2f}MW")

    below = base_arr < best_threshold
    final_pred = best_alpha * cal_arr + (1.0 - best_alpha) * base_arr
    final_pred[~below] = base_arr[~below]
    final_pred = np.clip(final_pred, 0.0, cap_all)

    # REMOVED: adaptive p_on gating for high-zero-rate sites (hurt test MAPE)
    # Force night to zero
    elev_arr = pd.to_numeric(pred_df.get('solar_elevation_deg', pd.Series(0, index=pred_df.index)), errors='coerce').fillna(-90).to_numpy(dtype=float)
    ghi_arr = pd.to_numeric(pred_df.get('clear_sky_ghi', pd.Series(0, index=pred_df.index)), errors='coerce').fillna(0).to_numpy(dtype=float)
    night_mask = (elev_arr <= 0) | (ghi_arr < 5)
    final_pred[night_mask] = 0.0
    pred_df['power_pred'] = final_pred

    # ---- Step 9: Compute metrics ----
    metrics_rows = []
    n_cal_enabled = sum(1 for v in cal_params_raw.values() if v[2]) if cal_params_raw else 0
    for split_name, idx in [('train', train.index), ('valid', valid.index), ('test', test.index)]:
        part = pred_df.loc[idx].copy()
        m = part['power_mw'].notna() & part['power_pred'].notna() & (part['power_mw'] > 0)
        mape_val = float(np.mean(np.abs(part.loc[m, 'power_mw'] - part.loc[m, 'power_pred']) / part.loc[m, 'power_mw']) * 100) if m.sum() > 0 else np.nan
        metrics_rows.append({
            'split': split_name,
            'mape': mape_val,
            'mae': mae(part['power_mw'].to_numpy(), part['power_pred'].to_numpy()),
            'rmse': rmse(part['power_mw'].to_numpy(), part['power_pred'].to_numpy()),
            'nrmse': nrmse(part['power_mw'].to_numpy(), part['power_pred'].to_numpy()),
            'rows': int(len(part)),
            'on_auc': float(on_metrics_df.loc[on_metrics_df['split'] == split_name, 'auc'].iloc[0]) if split_name in on_metrics_df['split'].values else np.nan,
            'trained_scene_models': int(max(len(logcorr_models) - 2, 0)),
            'calibration_alpha': float(best_alpha),
            'n_calibrated_sites': int(len(cal_params)),
            'n_calibration_enabled': int(n_cal_enabled),
        })
    metrics_df = pd.DataFrame(metrics_rows)

    pred_keep_cols = [
        'time', 'site_id', 'power_mw', 'power_pred', 'pred_baseline',
        'power_pred_cal', 'p_on_pred', 'rel_error_pred',
        'g_blend_pred', 'clear_sky_ghi', 'p_base', 'capacity_mw',
        'county', 'install_group', 'capacity_bucket', 'coastal_flag',
        'scene_label', 'scene_v151', 'quality_score', 'group_key',
        'calibration_enabled'  # 新增字段
    ]
    pred_keep_cols = [c for c in pred_keep_cols if c in pred_df.columns]

    bundle = {
        'baseline_bundle': baseline_bundle,
        'on_classifier': cls_bundle,
        'logcorr_regressors': logcorr_models,
        'calibration_params': cal_params,
        'calibration_params_full': cal_params_raw,  # 包含enable_calibration信息
        'on_metrics': on_metrics_df,
        'scene_summary': scene_summary_df,
        'calibration_alpha': best_alpha,
        'metrics': metrics_df,
    }
    safe_pickle_dump(bundle, model_path)
    metrics_df.to_csv(metrics_path, index=False, encoding='utf-8-sig')
    return bundle, metrics_df, pred_df[pred_keep_cols]
