from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

from ..core.data_io import load_ledger_files, read_excel_first_sheet
from ..core.utils import normalize_site_name, solar_elevation_deg, top_n_strings_by_similarity


DAY_SSRD_WM2 = 20.0
DAY_SOLAR_ELEV = 3.0
ZERO_POWER_EPS = 1e-3
ZERO_RUN_MIN = 14
ZERO_RUN_SOFT_MIN = 5
SEVERE_DAY_SSRD_WM2 = 200.0
SEVERE_OVERCAP_MULT = 1.20
SOFT_OVERCAP_MULT = 1.02


def _melt_power_file(path: Path, file_dev_type: str) -> pd.DataFrame:
    df = read_excel_first_sheet(path)
    df = df.rename(columns={df.columns[0]: "time"})
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    value_cols = [c for c in df.columns if c != "time"]
    out = df.melt(id_vars=["time"], value_vars=value_cols, var_name="power_alias", value_name="power_mw_raw")
    out["file_dev_type"] = file_dev_type
    out["is_reactive"] = out["power_alias"].astype(str).str.contains("无功", na=False)
    out = out[~out["is_reactive"]].copy()
    out["power_name_norm"] = out["power_alias"].apply(normalize_site_name)
    return out



def load_all_power_long(power_root: Path) -> pd.DataFrame:
    f = load_ledger_files(power_root)
    frames = [
        _melt_power_file(f["central_power"], "集中式"),
        _melt_power_file(f["dist_power_a"], "分布式"),
    ]
    # [v2] dist_b contains 欧翔宋庄光伏电站总出力值 which is the centralized 欧翔宋庄 data
    # duplicated in the wrong file — skip it to avoid unmapped rows
    dist_b_raw = _melt_power_file(f["dist_power_b"], "分布式")
    dist_b_raw = dist_b_raw[dist_b_raw["power_alias"] != "欧翔宋庄光伏电站总出力值"].copy()
    frames.append(dist_b_raw)

    out = pd.concat(frames, ignore_index=True)
    out["power_mw_raw"] = pd.to_numeric(out["power_mw_raw"], errors="coerce")
    return out



def build_power_mapping(power_long: pd.DataFrame, site_master: pd.DataFrame, similarity_threshold: float = 0.75) -> pd.DataFrame:
    # [v2] manual overrides for unmapped aliases; central sites need lower threshold
    _MANUAL_OVERRIDES = {
        # power_name_norm: (site_id, dev_type)
        "恒邦智纺": ("S001", "分布式"),   # 恒邦智纺总出力值 → 智邦纺织(S001, 分布式)
        # Central overrides (low fuzzy score ~0.75 → exact prefix match needed)
        "二龙山": ("S080", "集中式"),
        "银山湖": ("S095", "集中式"),
        "福惠泉南岗": ("S088", "集中式"),
        "福惠泉南岗二期": ("S078", "集中式"),
        "易事特": ("S087", "集中式"),
        "大唐利华": ("S094", "集中式"),
        "华电赣榆": ("S082", "集中式"),
        "华电灌南": ("S093", "集中式"),
        "飞展百禄": ("S104", "集中式"),
        "宏耀新安": ("S083", "集中式"),
        "浦利板桥": ("S086", "集中式"),
        "云港板桥": ("S084", "集中式"),
        "中电青口": ("S091", "集中式"),
        "协鑫曲阳光伏": ("S096", "集中式"),
        "信城宁海": ("S089", "集中式"),
    }

    rows = []
    uniq = power_long[["power_alias", "power_name_norm", "file_dev_type"]].drop_duplicates()
    for dev_type, grp in uniq.groupby("file_dev_type"):
        candidates = site_master[site_master["dev_type"] == dev_type].copy()
        candidate_norms = candidates["site_name_norm"].tolist()
        candidate_index = {r["site_name_norm"]: r for _, r in candidates.iterrows()}
        for _, row in grp.iterrows():
            q = row["power_name_norm"]
            match_method = "unmatched"
            best_site_id = None
            best_score = np.nan

            # Manual override first (cross-dev_type check)
            if q in _MANUAL_OVERRIDES:
                override_sid, override_dtype = _MANUAL_OVERRIDES[q]
                if override_dtype == dev_type:
                    best_site_id = override_sid
                    match_method = "manual_override"
                    best_score = 1.0
            # Exact norm match
            elif q in candidate_index:
                best_site_id = candidate_index[q]["site_id"]
                match_method = "exact_norm"
                best_score = 1.0
            # Fuzzy match (use lower threshold for central sites)
            else:
                threshold = 0.72 if dev_type == "集中式" else similarity_threshold
                scored = top_n_strings_by_similarity(q, candidate_norms, n=1)
                if scored and scored[0][1] >= threshold:
                    best_norm, best_score = scored[0]
                    best_site_id = candidate_index[best_norm]["site_id"]
                    match_method = "fuzzy"
            rows.append({
                "power_alias": row["power_alias"],
                "power_name_norm": q,
                "file_dev_type": dev_type,
                "dev_type": dev_type,
                "site_id": best_site_id,
                "match_method": match_method,
                "match_score": best_score,
            })
    return pd.DataFrame(rows)



def _flag_long_day_zero_runs(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values(["site_id", "time"]).copy()
    is_zero = (out["daytime_flag"] == 1) & out["power_mw"].fillna(0).abs().le(ZERO_POWER_EPS)
    severe_day = out["ssrd_wm2"].fillna(0).ge(SEVERE_DAY_SSRD_WM2)
    run_key = (is_zero != is_zero.groupby(out["site_id"]).shift(fill_value=False)).cumsum()
    run_len = is_zero.groupby([out["site_id"], run_key]).transform("sum")
    out["day_zero_run_len"] = np.where(is_zero, run_len, 0)
    out["flag_day_zero_run_soft"] = is_zero & severe_day & (run_len >= ZERO_RUN_SOFT_MIN)
    out["flag_day_zero_run"] = is_zero & severe_day & (run_len >= ZERO_RUN_MIN)
    # 只对严重且持续时间较长的白天零值段做硬剔除；较短零值段保留但在训练中降权
    out.loc[out["flag_day_zero_run"], "power_mw"] = np.nan
    return out



def clean_power(power_long: pd.DataFrame, mapping: pd.DataFrame, site_master: pd.DataFrame, site_meteo: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    meta_cols = [
        "site_id", "capacity_mw", "county", "commission_date", "site_short_name",
        "has_geo", "lon", "lat", "coastal_flag", "install_group", "capacity_bucket",
    ]
    meta_cols = [c for c in meta_cols if c in site_master.columns]

    df = power_long.merge(mapping, on=["power_alias", "power_name_norm", "file_dev_type"], how="left")
    # mapping's dev_type correctly distinguishes 集中式/分布式;
    # second merge adds site_master's dev_type as dev_type_y — drop it
    if "dev_type_y" in df.columns:
        df = df.drop(columns=["dev_type_y"])
    if "dev_type_x" in df.columns:
        df = df.rename(columns={"dev_type_x": "dev_type"})
    df = df.merge(site_master[meta_cols], on="site_id", how="left")
    df = df.merge(site_meteo[["time", "site_id", "ssrd_wm2", "t2m_c", "tcc", "strd_wm2"]], on=["time", "site_id"], how="left")

    df["power_mw"] = pd.to_numeric(df["power_mw_raw"], errors="coerce")

    # 负值处理
    df["flag_negative_small"] = df["power_mw"].lt(0) & df["power_mw"].ge(-0.05)
    df.loc[df["flag_negative_small"], "power_mw"] = 0.0
    df["flag_negative_large"] = df["power_mw"] < -0.05
    df.loc[df["flag_negative_large"], "power_mw"] = np.nan

    # 容量边界：轻微超出裁剪，严重超出剔除
    cap = df["capacity_mw"].astype(float)
    soft_cap = cap * SOFT_OVERCAP_MULT
    severe_cap = cap * SEVERE_OVERCAP_MULT
    df["flag_over_capacity_soft"] = np.isfinite(df["power_mw"]) & np.isfinite(cap) & (df["power_mw"] > soft_cap) & (df["power_mw"] <= severe_cap)
    df["flag_over_capacity"] = np.isfinite(df["power_mw"]) & np.isfinite(cap) & (df["power_mw"] > severe_cap)
    df.loc[df["flag_over_capacity_soft"], "power_mw"] = cap[df["flag_over_capacity_soft"]]
    df.loc[df["flag_over_capacity"], "power_mw"] = np.nan

    # 投运前剔除
    df["flag_pre_commission"] = df["power_mw"].notna() & df["commission_date"].notna() & (df["time"] < df["commission_date"])
    df.loc[df["flag_pre_commission"], "power_mw"] = np.nan

    # 日间判定：ERA5 辐照 + 太阳高度角联合
    if {"lon", "lat"}.issubset(df.columns):
        valid_geo = df["lon"].notna() & df["lat"].notna()
        df["solar_elevation_deg"] = np.nan
        if valid_geo.any():
            df.loc[valid_geo, "solar_elevation_deg"] = solar_elevation_deg(df.loc[valid_geo, "time"], df.loc[valid_geo, "lat"], df.loc[valid_geo, "lon"])
    else:
        df["solar_elevation_deg"] = np.nan
    # 日间判定：ERA5 辐照 + 太阳高度角联合 AND 逻辑
    # [FIX] 原来用 OR：ERA5 ssrd 夜间经常非零导致 71% 夜间记录被误判为白天
    # 改用 AND：太阳高度角 > 阈值 AND ERA5 辐照 > 阈值，两者同时满足才判定为白天
    df["daytime_flag"] = (
        (df["solar_elevation_deg"].fillna(-90) > DAY_SOLAR_ELEV)
        & (df["ssrd_wm2"].fillna(0) > DAY_SSRD_WM2)
    ).astype(int)

    # 白天长零值段：更像缺测而不是真实发电
    df = _flag_long_day_zero_runs(df)

    # [v7] 站点级 day_zero 降权：不是剔除站点，而是根据 day_zero_rate 降低其样本权重
    daytime_mask = df["daytime_flag"] == 1
    site_dayzero_rows = {}
    site_daytime_rows = {}
    for site_id, g in df[daytime_mask].groupby("site_id", dropna=False):
        if pd.isna(site_id):
            continue
        n_daytime = len(g)
        n_zero = int(g["power_mw"].fillna(0).abs().le(ZERO_POWER_EPS).sum())
        site_daytime_rows[site_id] = n_daytime
        site_dayzero_rows[site_id] = n_zero

    SITE_WEIGHT_HIGH_THRESH = 0.60   # day_zero_rate > 60% → 最低权重
    SITE_WEIGHT_LOW_THRESH = 0.20    # day_zero_rate < 20% → 满权重
    site_dayzero_rate = {sid: site_dayzero_rows.get(sid, 0) / max(site_daytime_rows.get(sid, 1), 1)
                         for sid in site_daytime_rows}
    site_weight_map = {}
    for sid, rate in site_dayzero_rate.items():
        if rate >= SITE_WEIGHT_HIGH_THRESH:
            w = 0.25
        elif rate <= SITE_WEIGHT_LOW_THRESH:
            w = 1.0
        else:
            t = (rate - SITE_WEIGHT_LOW_THRESH) / (SITE_WEIGHT_HIGH_THRESH - SITE_WEIGHT_LOW_THRESH)
            w = 1.0 - 0.75 * t
        site_weight_map[sid] = w
    df["site_weight"] = df["site_id"].map(site_weight_map).fillna(1.0)

    df["flag_day_zero"] = (df["daytime_flag"] == 1) & df["power_mw"].fillna(0).abs().le(ZERO_POWER_EPS)

    summary = []
    for site_id, g in df.groupby("site_id", dropna=False):
        if pd.isna(site_id):
            continue
        total = len(g)
        daytime = g["daytime_flag"] == 1
        summary.append({
            "site_id": site_id,
            "rows": total,
            "valid_rate": float(g["power_mw"].notna().mean()) if total else np.nan,
            "negative_large_rate": float(g["flag_negative_large"].mean()) if total else np.nan,
            "over_capacity_rate": float((g["flag_over_capacity"] | g["flag_over_capacity_soft"]).mean()) if total else np.nan,
            "day_zero_rate": float(g.loc[daytime, "flag_day_zero"].mean()) if daytime.sum() else np.nan,
            "day_zero_run_rate": float(g.loc[daytime, "flag_day_zero_run"].mean()) if daytime.sum() else np.nan,
            "has_geo": int(g["has_geo"].dropna().max()) if "has_geo" in g.columns and g["has_geo"].notna().any() else 0,
            "coastal_flag": int(g["coastal_flag"].dropna().max()) if "coastal_flag" in g.columns and g["coastal_flag"].notna().any() else 0,
        })
    quality = pd.DataFrame(summary)
    quality["quality_score"] = (
        0.35 * quality["valid_rate"].fillna(0)
        + 0.25 * (1 - quality["day_zero_rate"].fillna(1))
        + 0.20 * (1 - quality["over_capacity_rate"].fillna(1))
        + 0.10 * (1 - quality["negative_large_rate"].fillna(1))
        + 0.10 * (1 - quality["day_zero_run_rate"].fillna(1))
    ).clip(0, 1)
    return df, quality
