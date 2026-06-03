from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.core.data_io import load_era5_year, interpolate_era5_to_sites, load_tcc_strd_year, interpolate_tcc_strd_to_sites
from pv_forecasting.tasks.power_processing import build_power_mapping, clean_power, load_all_power_long


def main():
    parser = build_parser("Prepare site meteo and clean power")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    # ── 优先读取 canonical 元数据（含 override 已应用）─────────────────
    canonical = paths.tables / "station_metadata_canonical.csv"
    if canonical.exists():
        site_master = pd.read_csv(canonical)
        print(f"[INFO] loaded canonical station metadata: {len(site_master)} sites, "
              f"has_geo={site_master['has_geo'].sum()}")
    else:
        site_master = pd.read_csv(paths.tables / "site_master.csv")
        print(f"[WARN] canonical not found, using site_master.csv")

    # ── 对所有站点（含 has_geo==0）插值 ERA5 ───────────────────────
    # Round54 修复：不再过滤 has_geo==1，保证 S115/S116 也能获得 ERA5 特征
    site_geo = site_master[["site_id", "lon", "lat"]].copy()
    print(f"[INFO] ERA5 插值站点数: {len(site_geo)} "
          f"(含 has_geo==0: {(site_geo['lon'].isna() | site_geo['lat'].isna()).sum()})")
    meteo_frames = []
    tcc_strd_frames = []
    for year_dir in [paths.year_2023, paths.year_2024, paths.year_2025]:
        print(f"[INFO] interpolate ERA5 -> sites: {year_dir}")
        ds = load_era5_year(year_dir)
        meteo_frames.append(interpolate_era5_to_sites(ds, site_geo))
        tcc_strd_year_dir = paths.tcc_strd_root / str(year_dir.name)
        if tcc_strd_year_dir.exists():
            print(f"[INFO] interpolate TCC/STRD -> sites: {tcc_strd_year_dir}")
            try:
                ds_tcc = load_tcc_strd_year(tcc_strd_year_dir)
                tcc_strd_frames.append(interpolate_tcc_strd_to_sites(ds_tcc, site_geo))
            except FileNotFoundError:
                print(f"[WARN] TCC/STRD files not found in {tcc_strd_year_dir}, skipping")
        else:
            print(f"[WARN] TCC/STRD year dir not found: {tcc_strd_year_dir}, skipping")

    site_meteo = pd.concat(meteo_frames, ignore_index=True)

    if tcc_strd_frames:
        tcc_strd_merged = pd.concat(tcc_strd_frames, ignore_index=True)
        site_meteo = site_meteo.merge(
            tcc_strd_merged[["time", "site_id", "tcc", "strd_wm2"]],
            on=["time", "site_id"],
            how="left",
        )
        print(f"[INFO] TCC/STRD merged: {site_meteo['tcc'].notna().sum()} / {len(site_meteo)} rows have TCC")
    else:
        site_meteo["tcc"] = 0.5
        site_meteo["strd_wm2"] = 300.0

    site_meteo.to_pickle(paths.tables / "site_meteo.pkl")

    print("[INFO] loading power excels ...")
    power_long = load_all_power_long(paths.power_root)
    print(f"[INFO] power_long rows={len(power_long)}")
    power_long.to_pickle(paths.tables / "power_long_raw.pkl")
    mapping = build_power_mapping(power_long, site_master)
    mapping.to_csv(paths.tables / "power_mapping.csv", index=False, encoding="utf-8-sig")

    print("[INFO] cleaning and merging power/meteo ...")
    power_clean, quality = clean_power(power_long, mapping, site_master, site_meteo)
    power_clean.to_pickle(paths.tables / "power_clean.pkl")
    quality.to_csv(paths.tables / "site_quality.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] site_meteo={len(site_meteo)} power_clean={len(power_clean)}")


if __name__ == "__main__":
    main()
