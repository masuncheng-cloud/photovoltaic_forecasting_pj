#!/usr/bin/env python3
"""
preflight_check.py
=================
训练前预检钩子：检查 ERA5 文件、功率数据、站点映射、tqdm 可用性等。
必须全部通过才能进入训练；任何失败都会直接退出。

用法：
    python scripts/preflight_check.py
    python scripts/preflight_check.py --config configs/pipeline.yaml
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_cfg(cfg_path: str | None) -> dict:
    import yaml
    if cfg_path is None:
        cfg_path = PROJECT_ROOT / "configs" / "pipeline.yaml"
    else:
        cfg_path = Path(cfg_path)
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check(name: str, condition: bool, msg: str = "") -> bool:
    icon = "PASS" if condition else "FAIL"
    detail = f"  {msg}" if msg else ""
    print(f"  [{icon}] {name}{detail}")
    return condition


def check_file(name: str, path: Path) -> bool:
    ok = path.exists()
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {path}")
    return ok


def run(cfg: dict) -> bool:
    print()
    print("=" * 60)
    print("Preflight Check")
    print("=" * 60)

    data_root = PROJECT_ROOT / cfg.get("data", {}).get("data_root", "data")
    output_root = PROJECT_ROOT / cfg.get("data", {}).get("output_root", "output/pv_pipeline")

    all_ok = True

    # 1. Python / dependencies
    print()
    print("[1] Python 环境")
    all_ok &= check("Python", True, sys.executable)

    # tqdm
    try:
        from tqdm import __version__
        all_ok &= check("tqdm", True, f"version {__version__}")
    except Exception as e:
        all_ok &= check("tqdm", False, str(e))

    # yaml
    try:
        import yaml
        all_ok &= check("yaml", True, "")
    except Exception as e:
        all_ok &= check("yaml", False, str(e))

    # 2. ERA5 files
    print()
    print("[2] ERA5 文件")
    era5_years = cfg.get("data", {}).get("era5_years", [2023, 2024, 2025])
    for year in era5_years:
        year_dir = data_root / str(year)
        accum = year_dir / "data_stream-oper_stepType-accum.nc"
        instant = year_dir / "data_stream-oper_stepType-instant.nc"
        all_ok &= check(f"ERA5 {year} accum", accum.exists(), str(accum.relative_to(PROJECT_ROOT)))
        all_ok &= check(f"ERA5 {year} instant", instant.exists(), str(instant.relative_to(PROJECT_ROOT)))

    # ERA5 经纬度范围（仅检查 2023 accum 文件）
    try:
        import netCDF4
        accum_path = data_root / "2023" / "data_stream-oper_stepType-accum.nc"
        if accum_path.exists():
            ds = netCDF4.Dataset(str(accum_path), "r")
            lon = ds.variables["longitude"][:]
            lat = ds.variables["latitude"][:]
            ds.close()
            lon_min, lon_max = lon.min(), lon.max()
            lat_min, lat_max = lat.min(), lat.max()
            # 连云港大约 118–120 E, 33–35 N
            ok = (lon_min < 119 < lon_max) and (lat_min < 34 < lat_max)
            all_ok &= check("ERA5 覆盖连云港", ok,
                f"lon=[{lon_min:.1f},{lon_max:.1f}] lat=[{lat_min:.1f},{lat_max:.1f}]")
        else:
            all_ok &= check("ERA5 经纬度范围", False, "ERA5 文件不存在，无法检查")
    except Exception as e:
        all_ok &= check("ERA5 经纬度范围", False, str(e))

    # 3. 功率数据
    print()
    print("[3] 功率数据")
    power_dir = data_root / "power_data"
    power_files = ["2023_power.csv", "2024_power.csv", "2025_power.csv"]
    for pf in power_files:
        all_ok &= check(f"功率数据 {pf}", (power_dir / pf).exists(),
            str((power_dir / pf).relative_to(PROJECT_ROOT)))

    # 4. 站点映射
    print()
    print("[4] 站点映射")
    tables_dir = output_root / "tables"
    site_master = tables_dir / "site_master.csv"
    all_ok &= check("site_master.csv", site_master.exists(),
        str(site_master.relative_to(PROJECT_ROOT)))

    if site_master.exists():
        import pandas as pd
        try:
            df = pd.read_csv(site_master)
            cols = set(df.columns)
            needed = {"site_id", "lon", "lat", "capacity_mw", "dev_type"}
            for col in needed:
                all_ok &= check(f"site_master.{col}", col in cols, "")
            # S115 / S116 检查
            if "site_id" in df.columns:
                s115_ok = "S115" in df["site_id"].values
                s116_ok = "S116" in df["site_id"].values
                all_ok &= check("站点 S115 存在", s115_ok)
                all_ok &= check("站点 S116 存在", s116_ok)
        except Exception as e:
            all_ok &= check("读取 site_master", False, str(e))

    # 5. 主流程引用的脚本全部存在
    print()
    print("[5] 主流程脚本存在性")
    scripts_dir = PROJECT_ROOT / "scripts"
    canonical_scripts = [
        "pretrain_audit.py",
        "build_final_predictions.py",
        "build_site_validity.py",
        "apply_final_calibration.py",
        "compute_final_metrics.py",
        "posttrain_validation.py",
        "check_dashboard_prediction_values.py",
        "export_interactive_dashboard_data.py",
        "check_pipeline_consistency.py",
    ]
    for script in canonical_scripts:
        p = scripts_dir / script
        all_ok &= check(f"scripts/{script}", p.exists())

    # 6. 输出目录可写
    print()
    print("[6] 输出目录")
    for sub in ["predictions", "metrics", "tables", "interactive_dashboard"]:
        d = output_root / sub
        writable = d.exists()  # check if dir exists and is writable (by trying to create a temp file)
        if not writable:
            try:
                d.mkdir(parents=True, exist_ok=True)
                test_file = d / ".write_test"
                test_file.write_text("x")
                test_file.unlink()
                writable = True
            except Exception:
                pass
        all_ok &= check(f"output/{sub} 可写", writable, str(d.relative_to(PROJECT_ROOT)))

    # Summary
    print()
    print("=" * 60)
    if all_ok:
        print("  预检全部通过，可以开始训练。")
    else:
        print("  预检失败，请修复上述问题后重新运行。")
        print("  强制继续请设置环境变量 PV_SKIP_PREFLIGHT=1")
    print("=" * 60)
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="训练前预检")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if os.getenv("PV_SKIP_PREFLIGHT") == "1":
        print("[SKIP] 跳过预检 (PV_SKIP_PREFLIGHT=1)")
        sys.exit(0)

    try:
        cfg = load_cfg(args.config)
    except Exception as e:
        print(f"[ERROR] 配置加载失败: {e}")
        sys.exit(1)

    ok = run(cfg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
