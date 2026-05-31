#!/usr/bin/env python3
"""
scripts/apply_manual_geo_overrides.py
======================================
重新执行站点元数据构建（调用修复后的 build_site_master），
应用 configs/manual_station_geo_overrides.csv 中的经纬度覆盖，
并输出 canonical 元数据。

本脚本现在直接调用 build_site_master，因此 override 在源头生效，
后续 Stage 01/02/03 都会自动使用覆盖后的经纬度。

用法：
  python scripts/apply_manual_geo_overrides.py

注意：Step 2 在 run_full_pipeline.py 中会自动调用本脚本。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.tasks.site_master import build_site_master
from pv_forecasting.core.runtime import build_parser, make_paths


def main():
    parser = build_parser("Build site master with geo overrides")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    print("=" * 60)
    print("重新构建站点元数据（含人工经纬度覆盖）")
    print("=" * 60)
    print(f"power_root: {paths.power_root}")
    print(f"output:     {paths.tables}")

    site_master = build_site_master(paths.power_root)
    # build_site_master 已输出 station_metadata_canonical.csv/pkl

    # 同时覆盖旧的 site_master.csv（Stage 01/02 读取）
    site_master.to_csv(paths.tables / "site_master.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] site_master.csv → {paths.tables / 'site_master.csv'}")
    print(f"     has_geo=1 count: {int(site_master['has_geo'].sum())} / {len(site_master)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
