"""
core/eval_frame.py
==================
统一数据筛选口径：所有评估、可视化、报告必须调用本模块。

口径约定
--------
  split == "test"  : 2025-09-01 ~ 2025-12-31
  hour 6-19        : 白天有效发电时段
  future           : 2026-01-01 之后，不参与任何评估和默认可视化

用法示例
--------
  df = build_eval_frame(df_full, split="test", hour_start=6, hour_end=19)
  df = build_eval_frame(df_full, mode="train")
  df = build_eval_frame(df_full, mode="visualize_all")
"""
from __future__ import annotations

from typing import Literal, Optional
import numpy as np
import pandas as pd

# ── 口径常量 ─────────────────────────────────────────────────────────────────

SPLIT_TRAIN_END = pd.Timestamp("2025-07-01")
SPLIT_VALID_END = pd.Timestamp("2025-09-01")
SPLIT_TEST_END  = pd.Timestamp("2026-01-01")

DEFAULT_HOUR_START = 6
DEFAULT_HOUR_END   = 20   # exclusive, i.e. hour in [6, 19]

MODE_SPLITS: dict[str, list[str]] = {
    "train":               ["train"],
    "valid":              ["valid"],
    "test":               ["test"],
    "test_eval":           ["test"],
    "train_valid":         ["train", "valid"],
    "train_valid_test":    ["train", "valid", "test"],
    "visualize_all":       ["train", "valid", "test"],
    "full_no_future":      ["train", "valid", "test"],
}

DEFAULT_MODE = "test_eval"


def _parse_time(df: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
    """确保 time 列存在且为 datetime 类型，新增 hour 列。"""
    df = df.copy()
    if time_col not in df.columns:
        raise KeyError(f"Column '{time_col}' not found. Available: {list(df.columns)}")
    df[time_col] = pd.to_datetime(df[time_col])
    if "hour" not in df.columns:
        df["hour"] = df[time_col].dt.hour
    return df


def _add_split(df: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
    """确保 split 列存在，基于 split.py 规则。"""
    df = df.copy()
    if "split" not in df.columns:
        df[time_col] = pd.to_datetime(df[time_col])
        df["split"] = "future"
        df.loc[df[time_col] < SPLIT_TRAIN_END, "split"] = "train"
        df.loc[
            (df[time_col] >= SPLIT_TRAIN_END) & (df[time_col] < SPLIT_VALID_END), "split"
        ] = "valid"
        df.loc[
            (df[time_col] >= SPLIT_VALID_END) & (df[time_col] < SPLIT_TEST_END), "split"
        ] = "test"
    return df


def build_eval_frame(
    df: pd.DataFrame,
    mode: Literal[
        "train", "valid", "test", "test_eval", "train_valid",
        "train_valid_test", "visualize_all", "full_no_future"
    ] | list[str] | None = None,
    split: str | list[str] | None = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    hour_start: int = DEFAULT_HOUR_START,
    hour_end: int = DEFAULT_HOUR_END,
    require_non_future: bool = True,
    exclude_invalid_site: bool = False,
    invalid_site_ids: Optional[set[str]] = None,
    time_col: str = "time",
    power_col: str = "power_mw",
    pred_col: str = "power_pred",
    capacity_col: str = "capacity_mw",
    raise_on_duplicate: bool = False,
) -> pd.DataFrame:
    """统一数据筛选口径。

    Parameters
    ----------
    df : DataFrame
        输入数据，必须包含 time, site_id, split (或可推导 split)。
    mode : str or list or None
        预定义口径模式：
          - "train"             仅训练集
          - "valid"             仅验证集
          - "test" / "test_eval" 仅测试集（默认，用于最终评价）
          - "train_valid"       训练+验证集
          - "train_valid_test"  除 future 外的全部
          - "visualize_all"     同 train_valid_test
          - "full_no_future"    同 train_valid_test
        设为 None 时使用 split 参数。
    split : str or list or None
        手动指定 split 筛选，如 "test" 或 ["train", "valid"]。
        mode 和 split 不能同时为 None。
    start, end : str or None
        时间范围（闭区间），格式 "YYYY-MM-DD"。
    hour_start, hour_end : int
        小时范围，hour_end 为 exclusive（默认 6~19）。
    require_non_future : bool
        默认 True，排除 split == "future"。
    exclude_invalid_site : bool
        是否排除指定异常站点。
    invalid_site_ids : set or None
        异常站点 ID 集合（与 exclude_invalid_site 配合使用）。
    time_col, power_col, pred_col, capacity_col : str
        列名。
    raise_on_duplicate : bool
        若为 True，发现重复 (site_id, time, split) 时抛出异常。

    Returns
    -------
    DataFrame
        筛选后的数据（浅拷贝）。

    Raises
    ------
    KeyError
        必要列缺失时。
    ValueError
        mode 和 split 同时为 None 时。
    """
    # ── 1. 列和类型检查 ──────────────────────────────────────────────────────
    df = _parse_time(df, time_col)
    df = _add_split(df, time_col)

    # ── 2. split / mode 筛选 ─────────────────────────────────────────────────
    if split is not None:
        if isinstance(split, str):
            mask = df["split"] == split
        else:
            mask = df["split"].isin(split)
    elif mode is not None:
        if isinstance(mode, list):
            splits = mode
        elif mode in MODE_SPLITS:
            splits = MODE_SPLITS[mode]
        else:
            raise ValueError(f"Unknown mode: {mode!r}")
        mask = df["split"].isin(splits)
    else:
        raise ValueError("Both 'mode' and 'split' are None; at least one must be set.")

    df = df.loc[mask].copy()

    # ── 3. future 排除 ───────────────────────────────────────────────────────
    if require_non_future:
        before_count = len(df)
        df = df[df["split"] != "future"].copy()
        # 不打印，避免大量输出

    # ── 4. 时间范围筛选 ──────────────────────────────────────────────────────
    if start is not None:
        df = df[df[time_col] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df[time_col] < pd.Timestamp(end)]

    # ── 5. 小时筛选 ──────────────────────────────────────────────────────────
    df = df[(df["hour"] >= hour_start) & (df["hour"] < hour_end)]

    # ── 6. 异常站点排除 ──────────────────────────────────────────────────────
    if exclude_invalid_site and invalid_site_ids:
        df = df[~df["site_id"].isin(invalid_site_ids)]

    # ── 7. 重复检查 ──────────────────────────────────────────────────────────
    if raise_on_duplicate and len(df) > 0:
        key_cols = [c for c in ["site_id", time_col, "split"] if c in df.columns]
        if len(key_cols) == 3:
            dup_count = df.duplicated(subset=key_cols, keep=False).sum()
            if dup_count > 0:
                dup_rows = df[df.duplicated(subset=key_cols, keep=False)]
                raise ValueError(
                    f"Found {dup_count} duplicate rows with (site_id, time, split). "
                    f"Duplicate sample:\n{dup_rows.head(5).to_string()}"
                )

    # ── 8. 完整性断言（调试用）───────────────────────────────────────────────
    _assert_eval_frame_sanity(df, time_col, power_col, pred_col, capacity_col)

    return df


def _assert_eval_frame_sanity(
    df: pd.DataFrame,
    time_col: str,
    power_col: str,
    pred_col: str,
    capacity_col: str,
) -> None:
    """开发期断言，生产环境可注释掉。"""
    required = [time_col, "site_id", capacity_col, power_col, pred_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")
    if df[time_col].isna().any():
        raise ValueError(f"Null values found in '{time_col}' column.")
    if df["site_id"].isna().any():
        raise ValueError("Null values found in 'site_id' column.")
    if (df[capacity_col] <= 0).any():
        neg_cap = df[df[capacity_col] <= 0]["site_id"].unique()
        raise ValueError(f"Found non-positive capacity_mw for sites: {neg_cap}")


def build_eval_summary(df: pd.DataFrame) -> dict:
    """返回当前 eval_frame 的简要统计摘要。"""
    total = len(df)
    splits = df["split"].value_counts().to_dict()
    sites = df["site_id"].nunique()
    hours = sorted(df["hour"].unique()) if "hour" in df.columns else []
    t0 = df["time"].min() if total else None
    t1 = df["time"].max() if total else None
    pos = (df["power_mw"] > 0).sum() if "power_mw" in df.columns else None
    zero = (df["power_mw"] == 0).sum() if "power_mw" in df.columns else None
    return {
        "total_rows": total,
        "splits": splits,
        "n_sites": sites,
        "hours": hours,
        "time_range": [str(t0), str(t1)],
        "positive_power_rows": int(pos) if pos is not None else None,
        "zero_power_rows": int(zero) if zero is not None else None,
    }


# ── 预测列解析 ──────────────────────────────────────────────────────────────

def resolve_prediction_column(df: pd.DataFrame) -> str:
    """从 DataFrame 中解析出当前可用的预测功率列。

    优先级：power_pred_final > pred_calibrated > power_pred_cal > power_pred
    所有评估脚本必须调用此函数，禁止直接写死列名。

    Parameters
    ----------
    df : DataFrame
        预测结果 DataFrame。

    Returns
    -------
    str
        当前可用的预测功率列名。

    Raises
    ------
    KeyError
        没有任何预测列时。
    """
    candidates = ["power_pred_final", "pred_calibrated", "power_pred_cal", "power_pred"]
    for col in candidates:
        if col in df.columns:
            return col
    raise KeyError(
        f"未找到预测功率列，尝试的优先级顺序：{candidates}"
    )


def get_pred_col_safe(df: pd.DataFrame, default: str = "power_pred") -> str:
    """安全版本：若找不到任何预测列，返回 default 而非抛出异常。"""
    candidates = ["power_pred_final", "pred_calibrated", "power_pred_cal", "power_pred"]
    for col in candidates:
        if col in df.columns:
            return col
    return default
