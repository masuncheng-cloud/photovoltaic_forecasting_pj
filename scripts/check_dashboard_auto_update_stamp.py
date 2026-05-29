"""
check_dashboard_auto_update_stamp.py
====================================
Round44 新增：读取 dashboard_update_stamp.json，验证以下内容：

1. dashboard_update_stamp.json 存在
2. refresh_detected == True
3. city_series_consistency.status == PASS
4. site_series_consistency.overall_status == PASS
5. generated_at 距今不超过 48 小时（可选告警）

此脚本在 update_dashboard_after_training.py 之后执行，
也用于独立验证 dashboard 刷新状态。
"""

import json
import sys
from datetime import datetime, timedelta

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DASH_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
METRIC_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"


def main():
    stamp_path = DASH_DIR / "dashboard_update_stamp.json"

    print("=" * 60)
    print("Round44: check_dashboard_auto_update_stamp")
    print("=" * 60)

    # 1. 存在性检查
    if not stamp_path.exists():
        print(f"[FAIL] {stamp_path} 不存在")
        print("提示：请先运行 scripts/update_dashboard_after_training.py")
        sys.exit(1)
    print(f"[OK] {stamp_path} exists")

    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))

    checks = []

    # 2. refresh_detected
    refreshed = stamp.get("refresh_detected", False)
    checks.append({
        "check": "refresh_detected",
        "value": refreshed,
        "status": "PASS" if refreshed else "FAIL",
    })
    print(f"  refresh_detected={refreshed}")

    # 3. city_series_consistency
    city = stamp.get("city_series_consistency", {})
    city_ok = city.get("status") == "PASS"
    checks.append({
        "check": "city_series_consistency",
        "value": city.get("status"),
        "detail": city,
        "status": "PASS" if city_ok else "FAIL",
    })
    print(f"  city_series_consistency={city.get('status')} (mismatched={city.get('mismatched_rows', -1)})")

    # 4. site_series_consistency
    site = stamp.get("site_series_consistency", {})
    site_ok = site.get("overall_status") == "PASS"
    checks.append({
        "check": "site_series_consistency",
        "value": site.get("overall_status"),
        "detail": site,
        "status": "PASS" if site_ok else "FAIL",
    })
    print(f"  site_series_consistency={site.get('overall_status')}")

    # 5. 时间新鲜度（警告，不失败）
    generated = stamp.get("generated_at", "")
    if generated:
        try:
            gen_time = pd.to_datetime(generated)
            age_hours = (pd.Timestamp.now() - gen_time).total_seconds() / 3600
            stale = age_hours > 48
            checks.append({
                "check": "stamp_freshness",
                "value": f"{age_hours:.1f}h ago",
                "status": "WARN" if stale else "PASS",
                "detail": f"age_hours={round(age_hours, 1)}, threshold=48h",
            })
            print(f"  stamp age={age_hours:.1f}h {'[WARN >48h]' if stale else '[OK]'}")
        except Exception as e:
            checks.append({
                "check": "stamp_freshness",
                "value": f"parse_error: {e}",
                "status": "WARN",
            })
            print(f"  stamp_freshness: WARN (parse error: {e})")

    # 6. key files
    key_files = stamp.get("key_files_refreshed", {})
    for fname, event in key_files.items():
        ok = event != "SAME" and event != "NOT_FOUND"
        checks.append({
            "check": f"key_file_refreshed_{fname}",
            "value": event,
            "status": "PASS" if ok else "FAIL",
        })
        print(f"  {fname}: {event} {'[PASS]' if ok else '[FAIL]'}")

    # 汇总
    df = pd.DataFrame(checks)
    out_csv = METRIC_DIR / "round44_dashboard_update_stamp_check.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[OK] wrote {out_csv}")

    fails = df[df["status"] == "FAIL"]
    warns = df[df["status"] == "WARN"]

    print(f"\n结果汇总：PASS={len(df[df['status']=='PASS'])}, FAIL={len(fails)}, WARN={len(warns)}")
    print(df[["check", "value", "status"]].to_string(index=False)))

    if len(fails) > 0:
        print(f"\n[FAIL] {len(fails)} 项检查失败")
        sys.exit(1)

    if len(warns) > 0:
        print(f"\n[PASS with WARN] {len(warns)} 项告警（不影响通过）")

    print(f"\n[PASS] dashboard auto-update stamp 检查全部通过")


if __name__ == "__main__":
    main()
