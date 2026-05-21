"""
统一数据划分工具
=================
提供 train/valid/test 统一划分函数，确保全项目口径一致。

划分规则:
    train: time < 2025-07-01
    valid: 2025-07-01 <= time < 2025-09-01
    test:  time >= 2025-09-01

说明:
    train 用于模型训练
    valid 用于策略选择、参数搜索、guard 判断（不使用测试集数据）
    test 用于最终留出评估（与 valid 完全不重叠，无数据泄漏）
"""
from __future__ import annotations

import pandas as pd

# 统一划分日期常量
TRAIN_END = pd.Timestamp("2025-07-01")
VALID_END = pd.Timestamp("2025-09-01")


def add_standard_split(df: "pd.DataFrame", time_col: str = "time") -> "pd.DataFrame":
    """添加标准数据划分字段

    Args:
        df: 输入 DataFrame
        time_col: 时间列名，默认 "time"

    Returns:
        包含 "split" 列的 DataFrame
    """
    out = df.copy()
    out[time_col] = pd.to_datetime(out[time_col])
    out["split"] = "test"
    out.loc[out[time_col] < TRAIN_END, "split"] = "train"
    out.loc[(out[time_col] >= TRAIN_END) & (out[time_col] < VALID_END), "split"] = "valid"
    out.loc[out[time_col] >= VALID_END, "split"] = "test"
    return out


def filter_eval_test(df: "pd.DataFrame", time_col: str = "time") -> "pd.DataFrame":
    """筛选测试集数据"""
    out = add_standard_split(df, time_col)
    return out[out["split"] == "test"].copy()


def filter_eval_train(df: "pd.DataFrame", time_col: str = "time") -> "pd.DataFrame":
    """筛选训练集数据"""
    out = add_standard_split(df, time_col)
    return out[out["split"] == "train"].copy()


def filter_eval_valid(df: "pd.DataFrame", time_col: str = "time") -> "pd.DataFrame":
    """筛选验证集数据"""
    out = add_standard_split(df, time_col)
    return out[out["split"] == "valid"].copy()


def assign_hour_scene(df: "pd.DataFrame", time_col: str = "time") -> "pd.DataFrame":
    """基于 hour 划分场景（评估用）

    Args:
        df: 输入 DataFrame
        time_col: 时间列名

    Returns:
        包含 "scene_label_eval" 列的 DataFrame
    """
    out = df.copy()
    if time_col not in out.columns:
        out[time_col] = pd.to_datetime(out[time_col])
    out["hour"] = pd.to_datetime(out[time_col]).dt.hour

    def scene(hour: int) -> str:
        if hour in (6, 7):
            return "dawn"
        if hour in (8, 9):
            return "morning"
        if hour in (10, 11, 12, 13, 14):
            return "midday"
        if hour in (15, 16):
            return "afternoon"
        if hour in (17, 18, 19):
            return "dusk"
        return "night"

    out["scene_label_eval"] = out["hour"].map(scene)
    return out
