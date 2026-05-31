#!/usr/bin/env python3
"""
scripts/apply_manual_geo_overrides.py

从 configs/manual_station_geo_overrides.csv 读取人工指定的站点经纬度，
覆盖到 output/pv_pipeline/tables/site_master.csv 中，并写出修正后的版本。

用法（两种模式）：
  1. 作为独立脚本：python scripts/apply_manual_geo_overrides.py
  2. 作为模块：
       from scripts.apply_manual_geo_overrides import apply_manual_geo_overrides
       df = apply_manual_geo_overrides(site_master_df, overrides_path)

本脚本会在 stdout 打印覆盖日志，并在出错时 raise 而非 silent fail。
"""

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERRIDES = PROJECT_ROOT / "configs" / "manual_station_geo_overrides.csv"
DEFAULT_SITE_MASTER = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv"


def in_lianyungang(lat: float, lon: float) -> bool:
    """校验坐标是否在连云港合理范围内（WGS84）。"""
    return 33.9 <= lat <= 35.2 and 118.4 <= lon <= 119.9


def apply_manual_geo_overrides(
    site_master: pd.DataFrame,
    overrides_path: Path,
) -> pd.DataFrame:
    """
    对 site_master 中的指定站点应用人工经纬度覆盖。

    Parameters
    ----------
    site_master : pd.DataFrame
        站点主数据表，必须包含 station_id / site_id 列，以及 lat/lon 列。
    overrides_path : Path
        manual_station_geo_overrides.csv 路径。

    Returns
    -------
    pd.DataFrame
        应用覆盖后的站点表（副本，不修改原始 DataFrame）。
    """
    if not overrides_path.exists():
        print(f"[SKIP] 覆盖文件不存在，跳过: {overrides_path}")
        return site_master.copy()

    overrides = pd.read_csv(overrides_path)
    required = ["station_id", "latitude", "longitude", "confidence"]
    missing = [c for c in required if c not in overrides.columns]
    if missing:
        raise KeyError(
            f"manual geo overrides missing required columns: {missing}"
        )

    valid = overrides.dropna(subset=["station_id", "latitude", "longitude"])
    if len(valid) == 0:
        print("[SKIP] 覆盖文件中无有效数据")
        return site_master.copy()

    # 确定 site_id 列名（兼容 station_id / site_id）
    id_col = "site_id" if "site_id" in site_master.columns else "station_id"
    out = site_master.copy()

    overridden = []
    for _, row in valid.iterrows():
        sid = str(row["station_id"]).strip()
        # 兼容 station_id / site_id 列名
        if "station_id" in out.columns:
            mask = out["station_id"].astype(str).str.strip().eq(sid)
        else:
            mask = out["site_id"].astype(str).str.strip().eq(sid)

        if not mask.any():
            raise ValueError(
                f"manual geo override station_id='{sid}' not found in site_master"
            )

        lat = float(row["latitude"])
        lon = float(row["longitude"])
        src = str(row.get("geo_source", "manual")).strip()
        conf = str(row.get("confidence", "")).strip()
        note = str(row.get("note", "")).strip()

        # 连云港范围校验
        if not in_lianyungang(lat, lon):
            raise ValueError(
                f"站点 {sid} 坐标 ({lat}, {lon}) 不在连云港合理范围 "
                f"[33.9-35.2N, 118.4-119.9E]"
            )

        out.loc[mask, "lat"] = lat
        out.loc[mask, "lon"] = lon
        out.loc[mask, "geo_source"] = src
        out.loc[mask, "geo_confidence"] = conf
        out.loc[mask, "geo_note"] = note

        overridden.append({
            "station_id": sid,
            "lat": lat,
            "lon": lon,
            "confidence": conf,
        })
        print(
            f"[GEO] {sid}: lat={lat}, lon={lon}, source={src}, "
            f"confidence={conf}"
        )

    print(f"\n[OK] 共覆盖 {len(overridden)} 个站点")
    return out


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="应用人工经纬度覆盖到站点主数据表"
    )
    parser.add_argument(
        "--overrides",
        type=str,
        default=str(DEFAULT_OVERRIDES),
        help=f"覆盖 CSV 路径 (default: {DEFAULT_OVERRIDES})",
    )
    parser.add_argument(
        "--site-master",
        type=str,
        default=str(DEFAULT_SITE_MASTER),
        help=f"原始站点表路径 (default: {DEFAULT_SITE_MASTER})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help=f"输出路径 (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印覆盖结果，不写入文件",
    )
    args = parser.parse_args()

    overrides_path = Path(args.overrides)
    site_master_path = Path(args.site_master)
    output_path = Path(args.output)

    if not site_master_path.exists():
        raise FileNotFoundError(f"site_master 不存在: {site_master_path}")

    print("=" * 60)
    print("应用人工经纬度覆盖")
    print("=" * 60)
    print(f"  覆盖文件: {overrides_path}")
    print(f"  站点表:   {site_master_path}")

    sm = pd.read_csv(site_master_path)
    out = apply_manual_geo_overrides(sm, overrides_path)

    if args.dry_run:
        print("\n[DRY RUN] 未写入文件")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n[OK] 已保存: {output_path}")

    print("=" * 60)


if __name__ == "__main__":
    main()
