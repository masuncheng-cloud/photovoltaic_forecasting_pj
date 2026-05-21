"""
features/solar_physics.py
=========================
太阳物理特征：太阳高度角、方位角、晴空辐照度、clear-sky index、分时段标识。
所有训练/验证/测试集必须使用本模块统一计算，不得各自独立实现。

Dependencies
------------
- pvlib (optional, preferred if installed)
- utils.solar_elevation_deg  (project internal, always available)
- utils.clear_sky_ghi_haurwitz  (project internal, fallback)
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


# ── 低太阳高度角分箱阈值 ───────────────────────────────────────────────────────

LOW_SUN_BINS: list[tuple[Literal["night"] | Literal["very_low"] | Literal["low"] | Literal["mid"] | Literal["high"], float, float]] = [
    ("night",    -999.0,   0.0),
    ("very_low",  0.0,      6.0),
    ("low",       6.0,     12.0),
    ("mid",      12.0,     25.0),
    ("high",     25.0,    999.0),
]


def _solar_azimuth_deg(
    times: pd.Series,
    lat_deg: pd.Series,
    lon_deg: pd.Series,
) -> np.ndarray:
    """计算太阳方位角（从正北顺时针，正东=90°）。

    Uses the same astronomical formula as utils.solar_elevation_deg
    so both functions are consistent.
    """
    dt = pd.to_datetime(times)
    lat = np.radians(lat_deg.astype(float).to_numpy())
    lon = lon_deg.astype(float).to_numpy()
    n = dt.dt.dayofyear.to_numpy()
    hour = dt.dt.hour.to_numpy() + dt.dt.minute.to_numpy() / 60.0

    gamma = 2.0 * np.pi / 365.0 * (n - 1 + (hour - 12.0) / 24.0)
    decl = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2.0 * gamma)
        + 0.000907 * np.sin(2.0 * gamma)
        - 0.002697 * np.cos(3.0 * gamma)
        + 0.00148 * np.sin(3.0 * gamma)
    )
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2.0 * gamma)
        - 0.040849 * np.sin(2.0 * gamma)
    )
    timezone = 8.0
    time_offset = eqtime + 4.0 * (lon - timezone * 15.0)
    tst = hour * 60.0 + time_offset
    ha = np.radians((tst / 4.0) - 180.0)

    # Solar elevation (for consistency check)
    sin_elev = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)
    sin_elev = np.clip(sin_elev, -1.0, 1.0)
    elev = np.degrees(np.arcsin(sin_elev))

    # Solar azimuth: γ_s = arctan2(sin(HA), cos(HA)*sin(lat) - tan(dec)*cos(lat))
    az = np.degrees(
        np.arctan2(
            np.sin(ha),
            np.cos(ha) * np.sin(lat) - np.tan(decl) * np.cos(lat)
        )
    )
    # Convert from [-180,180] to [0,360] with 0=North
    az = (az + 180.0) % 360.0
    az = np.where(elev <= 0, np.nan, az)
    return az


def _clear_sky_ghi_pvlib(times, lat, lon) -> np.ndarray:
    """Use pvlib if available for more accurate clear-sky irradiance."""
    try:
        import pvlib
    except ImportError:
        return np.full(len(times), np.nan)

    site = pvlib.location.Location(lat, lon, tz="Asia/Shanghai")
    cs = site.get_clearsky(times)
    return cs["ghi"].to_numpy()


def add_solar_physics_features(
    df: pd.DataFrame,
    time_col: str = "time",
    lat_col: str = "lat",
    lon_col: str = "lon",
    irradiance_col: str = "g_blend_pred",
) -> pd.DataFrame:
    """生成太阳物理特征列。

    新增列
    ------
    solar_elevation_deg : float
        太阳高度角（°），-90~90。
    solar_azimuth_deg : float
        太阳方位角（°），0=正北，90=正东。
    clear_sky_ghi : float
        晴空水平面总辐照度（W/m²），Haurwitz 近似。
    clear_sky_index : float
        clear_sky_index = g_blend_pred / clear_sky_ghi，clip 到 [0, 1.5]。
    low_sun_bin : str
        {'night', 'very_low', 'low', 'mid', 'high'}，基于 solar_elevation_deg。
    is_low_sun : int
        1 if low_sun_bin in {'night', 'very_low'} else 0。
    is_dawn : int
        1 if solar_elevation_deg in (0, 12] else 0（晨光）。
    is_dusk : int
        1 if solar_elevation_deg in (0, 12] and hour in [16,19] else 0（日落）。
    """
    from ..core.utils import solar_elevation_deg, clear_sky_ghi_haurwitz

    out = df.copy()

    lat_s = pd.to_numeric(out.get(lat_col, pd.Series(34.8, index=out.index)), errors="coerce")
    lon_s = pd.to_numeric(out.get(lon_col, pd.Series(119.4, index=out.index)), errors="coerce")

    # Solar elevation
    if "solar_elevation_deg" not in out.columns:
        out["solar_elevation_deg"] = solar_elevation_deg(out[time_col], lat_s, lon_s)
    else:
        out["solar_elevation_deg"] = pd.to_numeric(out["solar_elevation_deg"], errors="coerce")

    # Solar azimuth
    out["solar_azimuth_deg"] = _solar_azimuth_deg(out[time_col], lat_s, lon_s)

    # Clear-sky GHI
    if "clear_sky_ghi" not in out.columns:
        out["clear_sky_ghi"] = clear_sky_ghi_haurwitz(out["solar_elevation_deg"])

    # Clear-sky index
    if irradiance_col in out.columns:
        irr = pd.to_numeric(out[irradiance_col], errors="coerce")
        cs = out["clear_sky_ghi"].replace(0, np.nan)
        out["clear_sky_index"] = (irr / cs).replace([np.inf, -np.inf], np.nan).clip(0.0, 1.5)
    else:
        out["clear_sky_index"] = np.nan

    # Low-sun bin
    elev = out["solar_elevation_deg"].fillna(-999.0)
    bins = []
    for label, lo, hi in LOW_SUN_BINS:
        bins.append((label, (elev > lo) & (elev <= hi)))
    # night: elev <= 0
    night_mask = elev <= 0
    out["low_sun_bin"] = np.select(
        [night_mask,
         (elev > 0) & (elev <= 6),
         (elev > 6) & (elev <= 12),
         (elev > 12) & (elev <= 25),
         elev > 25],
        ["night", "very_low", "low", "mid", "high"],
        default="night",
    ).astype(str)

    out["is_low_sun"] = (out["low_sun_bin"].isin(["night", "very_low"])).astype(int)

    # Dawn/dusk flags
    hour_s = pd.to_numeric(out.get("hour", pd.to_datetime(out[time_col]).dt.hour), errors="coerce").fillna(12)
    out["is_dawn"] = ((out["solar_elevation_deg"] > 0) & (out["solar_elevation_deg"] <= 12)).astype(int)
    out["is_dusk"] = ((out["solar_elevation_deg"] > 0) & (out["solar_elevation_deg"] <= 12) & (hour_s >= 16)).astype(int)

    return out
