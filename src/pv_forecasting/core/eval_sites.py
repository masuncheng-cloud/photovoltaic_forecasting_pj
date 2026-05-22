from __future__ import annotations

import pandas as pd


DEFAULT_BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DEFAULT_EVAL_SITE_COUNT = 53


def get_eval_site_ids(
    df: pd.DataFrame,
    target_n: int = DEFAULT_EVAL_SITE_COUNT,
    bad_sites: set[str] | None = None,
) -> list[str]:
    """返回固定、可复现的评估站点集合。

    选择原则：
    - 排除异常站点。
    - 优先保留正功率样本多、有效记录多、覆盖日期多的站点。
    - 若站点数超过 target_n，保留前 target_n 个。
    """
    bad_sites = bad_sites or DEFAULT_BAD_SITES
    if df.empty or "site_id" not in df.columns:
        return []

    x = df.copy()
    x = x[~x["site_id"].isin(bad_sites)].copy()
    if x.empty:
        return []

    if "time" in x.columns:
        x["time"] = pd.to_datetime(x["time"], errors="coerce")
        x["date"] = x["time"].dt.date
    elif "date" not in x.columns:
        x["date"] = 0

    power = pd.to_numeric(x.get("power_mw"), errors="coerce")
    x["_positive"] = power.gt(0).astype(int)
    x["_valid_power"] = power.notna().astype(int)

    g = (
        x.groupby("site_id", dropna=False)
        .agg(
            rows=("site_id", "size"),
            positive_rows=("_positive", "sum"),
            valid_rows=("_valid_power", "sum"),
            n_dates=("date", "nunique"),
        )
        .reset_index()
    )
    g["positive_ratio"] = g["positive_rows"] / g["rows"].clip(lower=1)
    g["valid_ratio"] = g["valid_rows"] / g["rows"].clip(lower=1)

    g = g.sort_values(
        ["positive_rows", "valid_rows", "n_dates", "positive_ratio", "site_id"],
        ascending=[False, False, False, False, True],
    )

    return g["site_id"].astype(str).head(target_n).tolist()
