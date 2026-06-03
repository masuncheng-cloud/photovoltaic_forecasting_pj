"""
round44_dashboard_regression_check.py
=====================================
Round44 新增：可视化全问题回归检查脚本。

检查内容：
1. 所有必需的 dashboard JSON 文件存在且非空
2. city_series.json 结构和内容正确
3. 典型站点 JSON 格式正确
4. 四季最佳日 JSON 格式正确
5. site_series/*.json 存在且非空（采样）
6. dashboard_update_stamp.json 存在
7. 未来数据未混入 city_series

此脚本在每次训练流程完成后执行，确保可视化数据没有退化。
"""

from pathlib import Path
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
DASH = OUT / "interactive_dashboard"
METRIC = OUT / "metrics"
METRIC.mkdir(parents=True, exist_ok=True)


def load_json(name):
    p = DASH / name
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    checks = []

    print("=" * 60)
    print("Round44: dashboard regression check")
    print("=" * 60)

    # 1. 必需文件存在性
    required = [
        "metadata.json",
        "city_series.json",
        "site_metrics.json",
        "typical_sites.json",
        "season_best_days_city.json",
        "season_best_days_by_site.json",
        "dashboard_update_stamp.json",
    ]

    for name in required:
        p = DASH / name
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        checks.append({
            "check": f"exists_{name}",
            "status": "PASS" if exists and size > 0 else "FAIL",
            "value": size,
        })
        print(f"  {'[OK]' if size > 0 else '[FAIL]'} {name} ({size} bytes)")

    # 2. city_series.json 结构
    city = pd.read_json(DASH / "city_series.json")
    checks.append({
        "check": "city_series_not_empty",
        "status": "PASS" if len(city) > 0 else "FAIL",
        "value": len(city),
    })
    print(f"  {'[OK]' if len(city) > 0 else '[FAIL]'} city_series rows={len(city)}")

    for col in ["time", "actual_mw", "pred_mw", "n_sites"]:
        has_col = col in city.columns
        checks.append({
            "check": f"city_series_has_{col}",
            "status": "PASS" if has_col else "FAIL",
            "value": has_col,
        })
        print(f"  {'[OK]' if has_col else '[FAIL]'} city_series.{col}")

    # 3. city_series 不含 future
    if "split" in city.columns:
        has_future = city["split"].astype(str).eq("future").any()
        checks.append({
            "check": "city_series_no_future",
            "status": "PASS" if not has_future else "FAIL",
            "value": bool(has_future),
        })
        print(f"  {'[OK]' if not has_future else '[FAIL]'} city_series.no_future (future_count={has_future.sum() if has_future.any() else 0})")

    # 4. city_series 小时范围
    if "hour" in city.columns:
        hour_ok = city["hour"].between(6, 19).all()
        checks.append({
            "check": "city_series_hours_6_19",
            "status": "PASS" if hour_ok else "FAIL",
            "value": f"{city['hour'].min()}-{city['hour'].max()}",
        })
        print(f"  {'[OK]' if hour_ok else '[FAIL]'} city_series hours 6-19")

    # 5. 典型站点
    typical = load_json("typical_sites.json")
    typical_text = json.dumps(typical, ensure_ascii=False)
    for key in ["best", "worst"]:
        has_key = key in typical_text or ("最好" in typical_text if key == "best" else "最差" in typical_text)
        checks.append({
            "check": f"typical_has_{key}_or_chinese",
            "status": "PASS" if has_key else "FAIL",
            "value": key,
        })
        print(f"  {'[OK]' if has_key else '[FAIL]'} typical_sites.{key} (or Chinese)")

    # 6. 四季最佳日
    season_city = load_json("season_best_days_city.json")
    season_site = load_json("season_best_days_by_site.json")
    for s in ["spring", "summer", "autumn", "winter"]:
        has_s = s in season_city
        checks.append({
            "check": f"season_city_has_{s}",
            "status": "PASS" if has_s else "FAIL",
            "value": s in season_city,
        })
        print(f"  {'[OK]' if has_s else '[FAIL]'} season_city.{s}")
    checks.append({
        "check": "season_site_not_empty",
        "status": "PASS" if isinstance(season_site, dict) and len(season_site) > 0 else "FAIL",
        "value": len(season_site) if isinstance(season_site, dict) else 0,
    })
    print(f"  {'[OK]' if isinstance(season_site, dict) and len(season_site) > 0 else '[FAIL]'} season_site non-empty")

    # 7. site_series 文件数
    site_dir = DASH / "site_series"
    site_files = sorted(site_dir.glob("S*.json"))
    site_ok = len(site_files) >= 60
    checks.append({
        "check": "site_series_files_exist",
        "status": "PASS" if site_ok else "FAIL",
        "value": len(site_files),
    })
    print(f"  {'[OK]' if site_ok else '[FAIL]'} site_series files={len(site_files)} (>=60 required)")

    # 8. 采样检查特定站点
    for sid in ["S017", "S062", "S019"]:
        p = site_dir / f"{sid}.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            ok = len(data) > 0
            checks.append({
                "check": f"site_series_{sid}_not_empty",
                "status": "PASS" if ok else "FAIL",
                "value": len(data),
            })
            print(f"  {'[OK]' if ok else '[FAIL]'} {sid}.json rows={len(data)}")
        else:
            checks.append({
                "check": f"site_series_{sid}_exists",
                "status": "FAIL",
                "value": 0,
            })
            print(f"  [FAIL] {sid}.json not found")

    # 9. dashboard_update_stamp 有效
    stamp = load_json("dashboard_update_stamp.json")
    stamp_refresh = stamp.get("refresh_detected", False)
    checks.append({
        "check": "dashboard_update_stamp_refreshed",
        "status": "PASS" if stamp_refresh else "FAIL",
        "value": stamp_refresh,
    })
    print(f"  {'[OK]' if stamp_refresh else '[FAIL]'} dashboard_update_stamp.refresh_detected={stamp_refresh}")

    stamp_city = stamp.get("city_series_consistency", {}).get("status") == "PASS"
    checks.append({
        "check": "dashboard_update_stamp_city_consistency",
        "status": "PASS" if stamp_city else "FAIL",
        "value": stamp.get("city_series_consistency", {}).get("status"),
    })
    print(f"  {'[OK]' if stamp_city else '[FAIL]'} stamp.city_consistency={stamp.get('city_series_consistency', {}).get('status')}")

    # 汇总
    df = pd.DataFrame(checks)
    out_csv = METRIC / "round44_dashboard_regression_check.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[OK] wrote {out_csv}")

    fail_df = df[df["status"] == "FAIL"]
    warn_df = df[df["status"] == "WARN"]

    print(f"\n结果：PASS={len(df[df['status']=='PASS'])}, FAIL={len(fail_df)}, WARN={len(warn_df)}")
    print(df[["check", "status", "value"]].to_string(index=False))

    if len(fail_df) > 0:
        print(f"\n[FAIL] {len(fail_df)} 项检查失败")
        print("失败的检查：")
        for _, r in fail_df.iterrows():
            print(f"  - {r['check']}: {r['value']}")
        raise SystemExit(1)

    print(f"\n[PASS] dashboard regression check 全部通过")


if __name__ == "__main__":
    main()
