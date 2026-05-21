
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from ..core.data_io import load_ledger_files, read_excel_first_sheet
from ..core.utils import calc_capacity_bucket, infer_install_group, is_coastal, normalize_site_name


LEDGER_COL_MAP = {
    "调度全称": "site_full_name",
    "调度简称": "site_short_name",
    "开发方式": "dev_type",
    "调度机构性质": "scheduler_type",
    "实际并网容量（MW）": "capacity_mw",
    "设计总容量（核准）（MW）": "design_capacity_mw",
    "设计（核准）总容量（MW）": "design_capacity_mw",
    "地理坐标经度": "lon",
    "地理坐标纬度": "lat",
    "所在县区": "county",
    "安装位置": "install_type_raw",
    "投运时间": "commission_date",
    "电站状态": "station_status",
    "所属发电集团": "group_name",
    "所属发电集团公司": "group_name",
    "太阳能阵列跟踪类型": "tracking_type",
    "太阳能电池类型": "cell_type",
    "上网模式": "grid_mode",
}


def _std_ledger(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    out = pd.DataFrame()
    for k, v in LEDGER_COL_MAP.items():
        if k in df.columns:
            out[v] = df[k]
    out["source_name"] = source_name
    if "site_full_name" not in out:
        out["site_full_name"] = np.nan
    if "site_short_name" not in out:
        out["site_short_name"] = out["site_full_name"]
    out["site_name_norm"] = out["site_short_name"].apply(normalize_site_name)
    out["county"] = out.get("county", pd.Series(index=out.index, dtype=object)).fillna("unknown")
    out["install_group"] = out.get("install_type_raw", pd.Series(index=out.index, dtype=object)).apply(infer_install_group)
    out["coastal_flag"] = out["county"].apply(is_coastal)
    out["capacity_bucket"] = out.get("capacity_mw", pd.Series(index=out.index, dtype=float)).apply(calc_capacity_bucket)
    return out


def build_site_master(power_root: Path) -> pd.DataFrame:
    f = load_ledger_files(power_root)
    dist_ledger = _std_ledger(read_excel_first_sheet(f["dist_ledger"]), "dist_ledger")
    dist_change = read_excel_first_sheet(f["dist_change"])
    central_local = _std_ledger(read_excel_first_sheet(f["central_ledger_local"]), "central_local")
    central_prov = _std_ledger(read_excel_first_sheet(f["central_ledger_prov"]), "central_prov")

    # ── 合并 dist_ledger 和 dist_alias，优先取 dist_ledger 的坐标 ─────────────
    # 先标准化 dist_alias 加上 lon/lat 字段（待回填）
    dist_alias_std = pd.DataFrame({
        "site_full_name": dist_change.get("调度命名(全称)", pd.Series(dtype=object)),
        "site_short_name": dist_change.get("调度名称(简称)", pd.Series(dtype=object)),
        "scheduler_type": dist_change.get("调度管辖", pd.Series(dtype=object)),
        "capacity_mw": dist_change.get("并网容量MW", pd.Series(dtype=float)),
        "county": dist_change.get("所属行政地区", pd.Series(dtype=object)),
    })
    dist_alias_std["dev_type"] = "分布式"
    dist_alias_std["source_name"] = "dist_change"
    dist_alias_std["site_name_norm"] = dist_alias_std["site_short_name"].apply(normalize_site_name)
    dist_alias_std["install_group"] = "unknown"
    dist_alias_std["coastal_flag"] = dist_alias_std["county"].apply(is_coastal)
    dist_alias_std["capacity_bucket"] = dist_alias_std["capacity_mw"].apply(calc_capacity_bucket)
    dist_alias_std["lon"] = np.nan
    dist_alias_std["lat"] = np.nan

    # 用 dist_ledger 的经纬度回填 dist_alias
    dist_geo = dist_ledger[dist_ledger["lon"].notna() | dist_ledger["lat"].notna()][
        ["site_name_norm", "lon", "lat"]
    ].drop_duplicates("site_name_norm")
    for _, geo_row in dist_geo.iterrows():
        mask = (dist_alias_std["site_name_norm"] == geo_row["site_name_norm"])
        dist_alias_std.loc[mask, "lon"] = geo_row["lon"]
        dist_alias_std.loc[mask, "lat"] = geo_row["lat"]

    # 合并：dist_ledger（优先） + 坐标已回填的 dist_alias + 集中式站点
    all_sites = pd.concat([dist_ledger, dist_alias_std, central_local, central_prov], ignore_index=True, sort=False)
    # 同名站点去重，优先保留 dist_ledger（靠 source_name 区分）
    all_sites["src_priority"] = all_sites["source_name"].map(
        {"dist_ledger": 0, "central_local": 0, "central_prov": 0, "dist_change": 1}
    )
    all_sites = (
        all_sites.sort_values("src_priority")
        .drop_duplicates(subset=["site_name_norm", "dev_type"], keep="first")
    )

    all_sites = all_sites.reset_index(drop=True)
    all_sites["site_id"] = [f"S{i+1:03d}" for i in range(len(all_sites))]
    all_sites["has_geo"] = all_sites[["lon", "lat"]].notna().all(axis=1).astype(int)
    all_sites["capacity_mw"] = pd.to_numeric(all_sites["capacity_mw"], errors="coerce")
    all_sites["lon"] = pd.to_numeric(all_sites["lon"], errors="coerce")
    all_sites["lat"] = pd.to_numeric(all_sites["lat"], errors="coerce")
    all_sites["commission_date"] = pd.to_datetime(all_sites["commission_date"], errors="coerce")
    return all_sites
