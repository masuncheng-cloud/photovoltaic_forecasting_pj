
from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import add_time_features, solar_elevation_deg, clear_sky_ghi_haurwitz


def add_common_features(df: pd.DataFrame) -> pd.DataFrame:
    out = add_time_features(df, "time")
    if {"lat", "lon"}.issubset(out.columns):
        out["solar_elevation_deg"] = solar_elevation_deg(out["time"], out["lat"], out["lon"])
    else:
        out["solar_elevation_deg"] = np.nan
    out["daylight_model_flag"] = (out["solar_elevation_deg"].fillna(-90) > 0).astype(int)
    return out


def add_lag_features(df: pd.DataFrame, group_col: str, value_cols: list[str], lags: list[int]) -> pd.DataFrame:
    out = df.sort_values([group_col, "time"]).copy()
    for c in value_cols:
        for lag in lags:
            out[f"{c}_lag{lag}"] = out.groupby(group_col)[c].shift(lag)
        out[f"{c}_diff1"] = out[c] - out.groupby(group_col)[c].shift(1)
        out[f"{c}_diff2"] = out[c] - out.groupby(group_col)[c].shift(2)
    return out



def add_clear_sky_features(df: pd.DataFrame, irradiance_col: str | None = None) -> pd.DataFrame:
    out = df.copy()
    if 'solar_elevation_deg' not in out.columns:
        out = add_common_features(out)
    out['clear_sky_ghi'] = clear_sky_ghi_haurwitz(out['solar_elevation_deg'])
    if irradiance_col is not None and irradiance_col in out.columns:
        denom = out['clear_sky_ghi'].replace(0, np.nan)
        out[f'{irradiance_col}_kt'] = (pd.to_numeric(out[irradiance_col], errors='coerce') / denom).replace([np.inf, -np.inf], np.nan).clip(lower=0, upper=1.5)
    return out


def add_tcc_strd_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive physics-informed features from TCC (total cloud cover) and STRD (surface
    thermal radiation downward). These are appended as new columns on df.

    TCC captures sky clarity and cloud-induced irradiance variability that is NOT fully
    explained by the ERA5 ssrd alone (corr ~ -0.06 only). STRD provides a direct
    measure of downward thermal radiation that complements the t2m_c temperature field.

    Derived features
    ----------------
    tcc_clean       : TCC clipped to [0, 1]
    tcc_cloud_flag  : 1 if TCC > 0.7 (heavily overcast)
    tcc_clear_flag  : 1 if TCC < 0.2 (mostly clear sky)
    tcc_kt_proxy    : cloud index proxy = TCC * (1 - alpha_pred) — high when sky
                       is cloudy AND irradiance is suppressed (synergy of both signals)
    tcc_lag1        : lagged TCC (1-hour lag) — captures persistence
    tcc_diff1       : TCC change over 1 hour — captures cloud dynamics
    tcc_cloud_rate   : absolute rate of change of TCC — fast-moving clouds → more
                       variability in solar generation

    strd_wm2_clean  : STRD clipped to physically plausible range [50, 600] W/m²
    strd_eff_temp_K : effective temperature from STRD via Stefan-Boltzmann law
                       T = (STRD / 5.67e-8)^0.25  (emissivity = 1)
    strd_temp_residual : STRD-derived temperature minus ERA5 air temperature
                          (captures surface heating/cooling not in t2m)
    strd_t_ratio    : STRD thermal ratio = strd_wm2 / (sigma * (t2m_c+273.15)^4)
                       > 1 means surface receives more downward thermal radiation
                       than what a bare surface at t2m would emit
    strd_daytime_mean : rolling mean of STRD over past 3 daytime hours (smooths
                         hourly noise, captures atmospheric column state)
    """
    out = df.copy()

    if "tcc" not in out.columns:
        out["tcc"] = 0.5
    if "strd_wm2" not in out.columns:
        out["strd_wm2"] = 300.0

    out["tcc_clean"] = pd.to_numeric(out["tcc"], errors="coerce").clip(lower=0.0, upper=1.0)
    out["tcc_cloud_flag"] = (out["tcc_clean"] > 0.7).astype(int)
    out["tcc_clear_flag"] = (out["tcc_clean"] < 0.2).astype(int)

    alpha = pd.to_numeric(out.get("alpha_pred", pd.Series(0.5, index=out.index)), errors="coerce").fillna(0.5)
    out["tcc_kt_proxy"] = (out["tcc_clean"] * (1.0 - alpha.clip(0, 1))).clip(lower=0, upper=1)

    if "site_id" in out.columns:
        tcc_lagged = out.sort_values(["site_id", "time"]).copy()
        tcc_lagged["tcc_lag1"] = tcc_lagged.groupby("site_id")["tcc_clean"].shift(1)
        tcc_lagged["tcc_diff1"] = tcc_lagged["tcc_clean"] - tcc_lagged.groupby("site_id")["tcc_clean"].shift(1)
        tcc_lagged["tcc_cloud_rate"] = tcc_lagged["tcc_diff1"].abs()
        out["tcc_lag1"] = tcc_lagged["tcc_lag1"]
        out["tcc_diff1"] = tcc_lagged["tcc_diff1"]
        out["tcc_cloud_rate"] = tcc_lagged["tcc_cloud_rate"]
    else:
        out["tcc_lag1"] = out["tcc_clean"].shift(1)
        out["tcc_diff1"] = out["tcc_clean"] - out["tcc_clean"].shift(1)
        out["tcc_cloud_rate"] = out["tcc_diff1"].abs()

    out["strd_wm2_clean"] = pd.to_numeric(out["strd_wm2"], errors="coerce").clip(lower=50.0, upper=600.0)

    sigma = 5.67e-8
    strd_w = pd.to_numeric(out["strd_wm2_clean"], errors="coerce").fillna(300.0)
    t2m_k = pd.to_numeric(out["t2m_c"], errors="coerce").fillna(15.0) + 273.15
    out["strd_eff_temp_K"] = (strd_w / sigma).clip(lower=1.0) ** 0.25
    out["strd_temp_residual"] = out["strd_eff_temp_K"] - t2m_k

    t_ref = t2m_k.clip(lower=200.0)
    out["strd_t_ratio"] = (strd_w / (sigma * t_ref ** 4)).replace([np.inf, -np.inf], np.nan).clip(lower=0.5, upper=2.0)

    return out
