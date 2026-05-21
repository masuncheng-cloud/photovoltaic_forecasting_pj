
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple
import warnings

import numpy as np
import pandas as pd
import xarray as xr



def _find_first(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern))
    if matches:
        return matches[0]
    # fallback: recursive search to tolerate extracted folder names / nested dirs
    matches = sorted(path.rglob(pattern))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No file matched {pattern} under {path}")


def find_era5_files(year_dir: Path) -> Tuple[Path, Path]:
    instant = _find_first(year_dir, "*instant*.nc")
    accum = _find_first(year_dir, "*accum*.nc")
    return instant, accum


def load_era5_year(year_dir: Path) -> xr.Dataset:
    instant_path, accum_path = find_era5_files(year_dir)
    ds_i = xr.open_dataset(instant_path)
    ds_a = xr.open_dataset(accum_path)
    ds = xr.merge([ds_i[["t2m"]], ds_a[["ssrd"]]], compat="override")
    if "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    ds = ds[["t2m", "ssrd"]]
    ds["t2m_c"] = ds["t2m"] - 273.15
    ds["ssrd_wm2"] = ds["ssrd"] / 3600.0
    keep = ["t2m_c", "ssrd_wm2"]
    return ds[keep]


def load_tcc_strd_year(year_dir: Path) -> xr.Dataset:
    """Load TCC (total cloud cover) and STRD (surface thermal radiation downward)
    from the tcc_strd NetCDF files. Both variables are on a finer grid than ERA5.
    """
    tcc_path = _find_first(year_dir, "*instant*.nc")
    strd_path = _find_first(year_dir, "*accum*.nc")
    ds_i = xr.open_dataset(tcc_path)
    ds_a = xr.open_dataset(strd_path)
    ds = xr.merge([ds_i[["tcc"]], ds_a[["strd"]]], compat="override")
    if "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    ds["strd_wm2"] = ds["strd"] / 3600.0
    keep = ["tcc", "strd_wm2"]
    return ds[keep]


def interpolate_tcc_strd_to_sites(ds: xr.Dataset, sites: pd.DataFrame) -> pd.DataFrame:
    """Interpolate TCC/STRD to site locations. Uses the same bilinear interpolation
    as ERA5 meteo data.
    """
    ds_interp = ds.interp(
        latitude=xr.DataArray(sites["lat"].astype(float).to_numpy(), dims="site"),
        longitude=xr.DataArray(sites["lon"].astype(float).to_numpy(), dims="site"),
        method="linear",
    )
    times = pd.to_datetime(ds_interp["time"].to_numpy())
    site_ids = sites["site_id"].tolist()
    n_time = len(times)
    n_site = len(site_ids)
    base = pd.DataFrame({
        "time": np.repeat(times, n_site),
        "site_id": np.tile(site_ids, n_time),
    })
    for var in ["tcc", "strd_wm2"]:
        arr = ds_interp[var].to_numpy()
        base[var] = arr.reshape(-1)
    return base


def interpolate_era5_to_sites(ds: xr.Dataset, sites: pd.DataFrame) -> pd.DataFrame:
    ds_interp = ds.interp(
        latitude=xr.DataArray(sites["lat"].astype(float).to_numpy(), dims="site"),
        longitude=xr.DataArray(sites["lon"].astype(float).to_numpy(), dims="site"),
        method="linear",
    )
    times = pd.to_datetime(ds_interp["time"].to_numpy())
    site_ids = sites["site_id"].tolist()
    n_time = len(times)
    n_site = len(site_ids)
    base = pd.DataFrame({
        "time": np.repeat(times, n_site),
        "site_id": np.tile(site_ids, n_time),
    })
    for var in ["t2m_c", "ssrd_wm2"]:
        arr = ds_interp[var].to_numpy()
        base[var] = arr.reshape(-1)
    return base


def load_ledger_files(power_root: Path) -> Dict[str, Path]:
    # Search recursively from power_root so folder naming differences won't break the pipeline
    files = {
        "dist_ledger": _find_first(power_root, "*地调分布式光伏台账*.xlsx"),
        "dist_change": _find_first(power_root, "*分布式台账变更*.xlsx"),
        "dist_power_a": _find_first(power_root, "*分布式光伏2023-2026年出力值（前38座）*.xlsx"),
        "dist_power_b": _find_first(power_root, "*分布式光伏2023-2026年出力值（后40座）*.xlsx"),
        "central_ledger_local": _find_first(power_root, "*地调集中式光伏台账*.xlsx"),
        "central_ledger_prov": _find_first(power_root, "*统调集中式光伏台账*.xlsx"),
        "central_power": _find_first(power_root, "*集中式光伏2023-2026年出力值（25座）*.xlsx"),
    }
    return files


def read_excel_first_sheet(path: Path) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style, apply openpyxl's default",
            category=UserWarning,
        )
        return pd.read_excel(path, sheet_name=0, engine="openpyxl")
