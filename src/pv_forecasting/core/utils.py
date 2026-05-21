
import functools
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


# ── pandas StringDtype pickle 兼容补丁 ───────────────────────────────────────

_PANDAS_PATCH_DONE = False


def patch_pandas_string_dtype_pickle() -> None:
    """兼容旧 pandas StringDtype pickle 的额外构造参数。

    pandas 3.x 改变了 StringDtype.__init__ 的签名，旧版 pickle 写出时保存了
    额外的关键字参数，读取时 __init__ 会报 TypeError。
    此补丁在读取前修改 StringDtype.__init__，使其静默忽略未知参数。
    """
    global _PANDAS_PATCH_DONE
    if _PANDAS_PATCH_DONE:
        return
    _PANDAS_PATCH_DONE = True
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _patched_init(self, *args, **kwargs):
            try:
                _orig(self, *args, **kwargs)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patched_init
    except Exception:
        pass


# ── pickle 读写工具 ───────────────────────────────────────────────────────────

def safe_pickle_dump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(obj, path)


def safe_pickle_load(path: Path):
    """安全读取 pickle，自动注入 pandas StringDtype 兼容补丁。"""
    patch_pandas_string_dtype_pickle()
    return pd.read_pickle(path)


def write_pickle_atomic(obj, path: Path, validate: bool = True) -> Path:
    """原子写出 pickle：先写临时文件，读回校验，通过后再 rename。

    Parameters
    ----------
    obj : any
        要序列化的对象。
    path : Path
        目标路径。
    validate : bool
        是否读回校验（默认 True，建议对重要输出保持开启）。

    Returns
    -------
    Path
        最终目标路径（与输入 path 相同）。

    Raises
    ------
    ValueError
        校验失败时抛出。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 写入临时文件
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix='.pkl', prefix='._write_', dir=path.parent)
    os.close(tmp_fd)
    tmp = Path(tmp_path_str)

    try:
        pd.to_pickle(obj, tmp)

        # 读回校验
        if validate:
            patch_pandas_string_dtype_pickle()
            loaded = pd.read_pickle(tmp)
            # 基本完整性检查
            if hasattr(obj, '__len__') and hasattr(loaded, '__len__'):
                if len(loaded) != len(obj):
                    raise ValueError(
                        f"Pickle 校验失败：行数不匹配（期望 {len(obj)}, 实际 {len(loaded)}）"
                    )
            del loaded

        # rename 到最终路径（原子操作）
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise

    return path


def write_prediction_pickle_atomic(
    df: pd.DataFrame,
    path: Path,
    required_cols: Iterable[str] | None = None,
    hour_range: tuple[int, int] | None = None,
) -> Path:
    """原子写出预测表 pickle，带业务层校验。

    Parameters
    ----------
    df : pd.DataFrame
        预测 DataFrame。
    path : Path
        目标路径。
    required_cols : iterable of str, optional
        必须包含的列名列表。
    hour_range : tuple (h_min, h_max), optional
        若提供，校验表中必须存在指定小时范围的样本。

    Returns
    -------
    Path
        最终路径。
    """
    # 业务层校验
    if df.empty:
        raise ValueError("预测表为空，拒绝写出")

    if required_cols:
        missing = set(required_cols) - set(df.columns)
        if missing:
            raise ValueError(f"预测表缺少必需列: {missing}")

    if hour_range:
        h_min, h_max = hour_range
        if 'hour' not in df.columns:
            dt = pd.to_datetime(df['time'])
            hours = dt.dt.hour
        else:
            hours = df['hour']
        in_range = hours.between(h_min, h_max).any()
        if not in_range:
            raise ValueError(
                f"预测表不包含 {h_min}-{h_max} 点数据，拒绝写出"
            )

    return write_pickle_atomic(df, path, validate=True)


def ensure_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def save_json(obj: Dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def normalize_site_name(name: str) -> str:
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return ""
    s = str(name)
    s = s.replace("连云港", "")
    s = s.replace("江苏", "")
    s = re.sub(r"[\s\-—_·•,。．.()（）/\\]", "", s)
    replacements = [
        "总无功出力值", "总出力值", "发电站", "光伏电站", "光伏电厂", "机组", "电站", "电厂",
    ]
    for r in replacements:
        s = s.replace(r, "")
    return s


def is_coastal(county: str) -> int:
    if county is None or (isinstance(county, float) and np.isnan(county)):
        return 0
    s = str(county)
    keys = ["连云", "赣榆", "徐圩"]
    return int(any(k in s for k in keys))


def infer_install_group(val: str) -> str:
    if pd.isna(val):
        return "unknown"
    s = str(val)
    if "屋顶" in s:
        return "rooftop"
    if "地面" in s or "渔光" in s or "农光" in s:
        return "ground"
    return "other"


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() == 0:
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() == 0:
        return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))


def nrmse(y_true: np.ndarray, y_pred: np.ndarray, scale: float | None = None) -> float:
    if scale is None:
        mask = np.isfinite(y_true)
        scale = float(np.nanmax(y_true[mask]) - np.nanmin(y_true[mask])) if mask.sum() else np.nan
    if not np.isfinite(scale) or scale == 0:
        return np.nan
    return rmse(y_true, y_pred) / scale


def nmae(y_true: np.ndarray, y_pred: np.ndarray, scale: float | None = None) -> float:
    if scale is None:
        mask = np.isfinite(y_true)
        scale = float(np.nanmax(y_true[mask]) - np.nanmin(y_true[mask])) if mask.sum() else np.nan
    if not np.isfinite(scale) or scale == 0:
        return np.nan
    return mae(y_true, y_pred) / scale


def corr(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() < 3:
        return np.nan
    yt = y_true[mask].astype(float)
    yp = y_pred[mask].astype(float)
    if np.nanstd(yt) == 0 or np.nanstd(yp) == 0:
        return np.nan
    return float(np.corrcoef(yt, yp)[0, 1])




def relative_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean relative error for finite true values."""
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true != 0)
    if mask.sum() == 0:
        return np.nan
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def relative_error_active(y_true: np.ndarray, y_pred: np.ndarray,
                         capacity: np.ndarray | None = None,
                         daytime_flag: np.ndarray | None = None) -> float:
    """Mean relative error during active (non-zero) daytime hours."""
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true != 0)
    if daytime_flag is not None:
        mask = mask & (daytime_flag == 1)
    if mask.sum() == 0:
        return np.nan
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def calc_capacity_bucket(cap: float) -> str:
    if not np.isfinite(cap):
        return "unknown"
    if cap < 5:
        return "small"
    if cap < 20:
        return "medium"
    return "large"


def add_time_features(df: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
    out = df.copy()
    dt = pd.to_datetime(out[time_col])
    out["hour"] = dt.dt.hour
    out["month"] = dt.dt.month
    out["dayofyear"] = dt.dt.dayofyear
    out["year"] = dt.dt.year
    out["hour_sin"] = np.sin(2 * np.pi * out["hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour"] / 24)
    out["doy_sin"] = np.sin(2 * np.pi * out["dayofyear"] / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * out["dayofyear"] / 365.25)
    return out


def solar_elevation_deg(times: pd.Series, lat_deg: pd.Series, lon_deg: pd.Series) -> np.ndarray:
    dt = pd.to_datetime(times)
    lat = np.radians(lat_deg.astype(float).to_numpy())
    lon = lon_deg.astype(float).to_numpy()
    n = dt.dt.dayofyear.to_numpy()
    hour = dt.dt.hour.to_numpy() + dt.dt.minute.to_numpy() / 60.0

    gamma = 2.0 * np.pi / 365.0 * (n - 1 + (hour - 12) / 24.0)
    decl = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma)
        - 0.040849 * np.sin(2 * gamma)
    )
    timezone = 8.0
    time_offset = eqtime + 4.0 * (lon - timezone * 15.0)
    tst = hour * 60.0 + time_offset
    ha = np.radians((tst / 4.0) - 180.0)

    sin_elev = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)
    sin_elev = np.clip(sin_elev, -1.0, 1.0)
    elev = np.degrees(np.arcsin(sin_elev))
    return elev




def clear_sky_ghi_haurwitz(solar_elevation_deg: pd.Series | np.ndarray) -> np.ndarray:
    """Approximate clear-sky global horizontal irradiance using Haurwitz model."""
    elev = np.asarray(solar_elevation_deg, dtype=float)
    cos_z = np.sin(np.radians(np.clip(elev, -90.0, 90.0)))
    out = np.zeros_like(cos_z, dtype=float)
    mask = cos_z > 0
    if np.any(mask):
        cz = np.clip(cos_z[mask], 1e-4, None)
        out[mask] = 1098.0 * cz * np.exp(-0.059 / cz)
    return np.clip(out, 0.0, 1400.0)

def idw_predict(src_lon: np.ndarray, src_lat: np.ndarray, src_val: np.ndarray,
                tgt_lon: np.ndarray, tgt_lat: np.ndarray, power: float = 2.0,
                min_points: int = 3) -> np.ndarray:
    src_mask = np.isfinite(src_lon) & np.isfinite(src_lat) & np.isfinite(src_val)
    src_lon = src_lon[src_mask]
    src_lat = src_lat[src_mask]
    src_val = src_val[src_mask]
    if src_val.size == 0:
        return np.full_like(tgt_lon, np.nan, dtype=float)
    if src_val.size < min_points:
        return np.full_like(tgt_lon, np.nanmedian(src_val), dtype=float)

    out = np.zeros_like(tgt_lon, dtype=float)
    for i, (x, y) in enumerate(zip(tgt_lon, tgt_lat)):
        d = np.sqrt((src_lon - x) ** 2 + (src_lat - y) ** 2)
        if np.any(d == 0):
            out[i] = src_val[np.argmin(d)]
            continue
        w = 1.0 / np.power(d, power)
        out[i] = float(np.sum(w * src_val) / np.sum(w))
    return out


def top_n_strings_by_similarity(query: str, candidates: Iterable[str], n: int = 5) -> List[Tuple[str, float]]:
    import difflib
    scored = []
    for c in candidates:
        score = difflib.SequenceMatcher(None, query, c).ratio()
        scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n]


def split_adaptive(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """DEPRECATED for V3. Use core.split.add_standard_split instead."""
    raise RuntimeError(
        "split_adaptive is DEPRECATED for V3. "
        "Use 'from pv_forecasting.core.split import add_standard_split' instead. "
        "V3 scripts must use the single canonical split from core/split.py: "
        "train < 2025-07-01 < valid < 2025-09-01 <= test."
    )

    for site_id, group in df.groupby('site_id', observed=True):
        site_data = group.sort_values('time')
        pre_test = site_data[site_data['time'] < '2025-07-01']
        nonnull_pre = pre_test[pre_test['power_mw'].notna()]

        if len(nonnull_pre) == 0:
            train_rows.append(pre_test.head(0))
            valid_rows.append(pre_test.head(0))
            continue

        hist_nonnull = nonnull_pre[nonnull_pre['year'] <= 2024]
        if len(hist_nonnull) >= 500:
            site_train = nonnull_pre[nonnull_pre['time'] < '2025-01-01']
            site_valid = nonnull_pre[nonnull_pre['time'] >= '2025-01-01']
        else:
            site_train = nonnull_pre
            site_valid = nonnull_pre.head(0)

        train_rows.append(site_train)
        valid_rows.append(site_valid)

    train = pd.concat(train_rows, ignore_index=True) if train_rows else df.head(0)
    valid = pd.concat(valid_rows, ignore_index=True) if valid_rows else df.head(0)
    test = df[test_mask].copy()
    return train, valid, test
