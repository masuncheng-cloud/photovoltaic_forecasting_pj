"""
update_dashboard_after_training.py
===================================
Round44 新增：训练完成后自动刷新可视化 dashboard 数据，并检测刷新确实生效。

执行流程：
1. 记录刷新前的 dashboard 文件 mtime / size / sha256
2. 执行 export_interactive_dashboard_data.py（实际导出）
3. 校验 city_series.json 与 final pkl 的一致性
4. 校验 site_series/*.json 与 final pkl 的一致性
5. 记录刷新后的 dashboard 文件 mtime / size / sha256
6. 写出 dashboard_update_stamp.json
7. 如果本次训练后 dashboard 文件没有刷新（mtime 不变），直接失败

此脚本必须在每次完整训练（Round41/42 融合、指标重算等）之后执行，
作为训练流程的最后一个自动化环节。
"""

import hashlib
import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TABLE_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
DASH_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
METRIC_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRIC_DIR.mkdir(parents=True, exist_ok=True)


def find_final_pkl():
    """找到最新的 distributed_predictions_final_roundXX.pkl"""
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def file_signature(path):
    """返回 (mtime, size, sha256)"""
    stat = path.stat()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return {
        "mtime": stat.st_mtime,
        "mtime_iso": pd.Timestamp(stat.st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
        "size": stat.st_size,
        "sha256_prefix": sha,
    }


def snapshot_dir(dir_path, extensions=None):
    """对目录下所有指定扩展名文件生成签名快照"""
    if extensions is None:
        extensions = [".json"]
    sigs = {}
    if dir_path.exists():
        for p in sorted(dir_path.iterdir()):
            if p.is_file() and p.suffix.lower() in extensions:
                sigs[p.name] = file_signature(p)
            elif p.is_dir() and p.name == "site_series":
                for sp in sorted(p.glob("*.json")):
                    rel = p.name + "/" + sp.name
                    sigs[rel] = file_signature(sp)
    return sigs


def check_city_series_consistency():
    """校验 city_series.json 与 final pkl 的一致性"""
    pkl_path = find_final_pkl()
    df = pd.read_pickle(pkl_path).copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "split" in df.columns:
        df = df[df["split"].isin(["train", "valid", "test"])]
    df = df[df["hour"].between(6, 19)]
    df = df[df["power_mw"].notna() & df["power_pred_final"].notna()]

    city_pkl = (
        df.groupby("time", as_index=False)
        .agg(
            actual_mw=("power_mw", "sum"),
            pred_mw=("power_pred_final", "sum"),
            n_sites=("site_id", "nunique"),
            capacity_sum_mw=("capacity_mw", "sum"),
        )
    )

    city_json = pd.read_json(DASH_DIR / "city_series.json")
    city_json["time"] = pd.to_datetime(city_json["time"])

    cmp = city_pkl.merge(
        city_json[["time", "actual_mw", "pred_mw", "n_sites"]],
        on="time",
        how="outer",
        suffixes=("_pkl", "_json"),
        indicator=True,
    )

    mismatched = cmp[cmp["_merge"] != "both"]
    max_diff_actual = float(
        (cmp["actual_mw_pkl"] - cmp["actual_mw_json"]).abs().max()
    ) if "actual_mw_pkl" in cmp.columns and "actual_mw_json" in cmp.columns else 0.0
    max_diff_pred = float(
        (cmp["pred_mw_pkl"] - cmp["pred_mw_json"]).abs().max()
    ) if "pred_mw_pkl" in cmp.columns and "pred_mw_json" in cmp.columns else 0.0

    return {
        "city_series_rows_pkl": int(len(city_pkl)),
        "city_series_rows_json": int(len(city_json)),
        "mismatched_rows": int(len(mismatched)),
        "max_diff_actual_mw": round(max_diff_actual, 6),
        "max_diff_pred_mw": round(max_diff_pred, 6),
        "status": "PASS" if len(mismatched) == 0 else "FAIL",
    }


def check_site_series_consistency():
    """校验 site_series/*.json 与 final pkl 的一致性（采样检查 3 个站点）"""
    pkl_path = find_final_pkl()
    df = pd.read_pickle(pkl_path).copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "split" in df.columns:
        df = df[df["split"].isin(["train", "valid", "test"])]
    df = df[df["hour"].between(6, 19)]
    df = df[df["power_mw"].notna() & df["power_pred_final"].notna()]

    site_dir = DASH_DIR / "site_series"
    results = []

    for sid in ["S017", "S062", "S019"]:
        p = site_dir / f"{sid}.json"
        if not p.exists():
            results.append({"site_id": sid, "status": "FAIL", "reason": "file_not_found"})
            continue

        js_data = json.loads(p.read_text(encoding="utf-8"))
        if not js_data:
            results.append({"site_id": sid, "status": "FAIL", "reason": "empty_json"})
            continue

        # Build lookup from pkl
        site_df = df[df["site_id"].astype(str).eq(sid)].copy()
        pkl_lookup = site_df.set_index("time")[["power_mw", "power_pred_final"]]

        max_diff_actual = 0.0
        max_diff_pred = 0.0
        bad_rows = 0
        for rec in js_data:
            t = pd.to_datetime(rec["time"])
            if t in pkl_lookup.index:
                diff_a = abs(float(rec["actual_mw"]) - float(pkl_lookup.loc[t, "power_mw"]))
                diff_p = abs(float(rec["pred_mw"]) - float(pkl_lookup.loc[t, "power_pred_final"]))
                max_diff_actual = max(max_diff_actual, diff_a)
                max_diff_pred = max(max_diff_pred, diff_p)
                if diff_a > 1e-9 or diff_p > 1e-9:
                    bad_rows += 1

        status = "PASS" if bad_rows == 0 else "FAIL"
        results.append({
            "site_id": sid,
            "status": status,
            "json_rows": len(js_data),
            "pkl_rows": int(len(site_df)),
            "bad_rows": bad_rows,
            "max_diff_actual_mw": round(max_diff_actual, 6),
            "max_diff_pred_mw": round(max_diff_pred, 6),
        })

    all_pass = all(r["status"] == "PASS" for r in results)
    return {
        "checks": results,
        "overall_status": "PASS" if all_pass else "FAIL",
    }


def main():
    print("=" * 60)
    print("Round44: update_dashboard_after_training")
    print("=" * 60)

    # 1. 刷新前快照
    print("\n[1] 刷新前 dashboard 快照...")
    before = snapshot_dir(DASH_DIR)
    print(f"  监控 {len(before)} 个文件")

    # 2. 执行 export
    print("\n[2] 执行 export_interactive_dashboard_data.py...")
    export_script = SCRIPTS_DIR / "export_interactive_dashboard_data.py"
    cmd = [sys.executable, str(export_script),
           "--output-root", "output/pv_pipeline",
           "--dashboard-root", "output/pv_pipeline/interactive_dashboard"]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(result.stdout.decode("utf-8", errors="replace")[-2000:])
        print(result.stderr.decode("utf-8", errors="replace")[-1000:])
        raise RuntimeError(f"export_interactive_dashboard_data.py 失败，exit={result.returncode}")

    # 3. 刷新后快照
    print("\n[3] 刷新后 dashboard 快照...")
    after = snapshot_dir(DASH_DIR)

    # 4. 一致性校验
    print("\n[4] city_series.json 与 final pkl 一致性校验...")
    city_check = check_city_series_consistency()
    print(f"  city_series: {city_check}")

    print("\n[5] site_series/*.json 与 final pkl 一致性校验（采样 S017/S062/S019）...")
    site_check = check_site_series_consistency()
    for r in site_check["checks"]:
        print(f"  {r['site_id']}: {r['status']} (max_diff_actual={r.get('max_diff_actual_mw')}, max_diff_pred={r.get('max_diff_pred_mw')})")

    # 5. 变化检测
    print("\n[6] Dashboard 文件变化检测...")
    changed = {}
    for name in set(list(before.keys()) + list(after.keys())):
        b = before.get(name)
        a = after.get(name)
        if b is None and a is not None:
            changed[name] = {"event": "CREATED", "after": a}
        elif a is None and b is not None:
            changed[name] = {"event": "DELETED", "before": b}
        elif b and a and (b["mtime"] != a["mtime"] or b["size"] != a["size"]):
            changed[name] = {"event": "CHANGED", "before": b, "after": a}
        else:
            changed[name] = {"event": "SAME", "sig": b}

    changed_files = {k: v for k, v in changed.items() if v["event"] != "SAME"}
    print(f"  变化文件数: {len(changed_files)}")
    for name, info in sorted(changed_files.items()):
        print(f"  {info['event']:8s} {name}")

    # 6. 判断是否真正刷新
    key_files = ["city_series.json", "metadata.json", "typical_sites.json"]
    refreshed = any(
        changed.get(f, {}).get("event") != "SAME"
        for f in key_files
    )

    # 7. 写出 stamp
    stamp = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "final_pkl": str(find_final_pkl()),
        "dashboard_root": str(DASH_DIR),
        "refresh_detected": refreshed,
        "refresh_details": changed,
        "key_files_refreshed": {
            f: changed.get(f, {}).get("event", "NOT_FOUND")
            for f in key_files
        },
        "city_series_consistency": city_check,
        "site_series_consistency": site_check,
        "before_snapshot_file_count": len(before),
        "after_snapshot_file_count": len(after),
    }
    stamp_path = DASH_DIR / "dashboard_update_stamp.json"
    stamp_path.write_text(json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] dashboard_update_stamp.json written")

    # 8. 最终判定
    consistency_ok = city_check["status"] == "PASS" and site_check["overall_status"] == "PASS"

    if not refreshed:
        print("\n[FAIL] Dashboard 文件未刷新（mtime/size 未变）")
        print("  提示：检查 export_interactive_dashboard_data.py 是否真的写入了新文件")
        raise RuntimeError("Dashboard auto-update failed: files not refreshed")

    if not consistency_ok:
        print(f"\n[FAIL] Dashboard 与 final pkl 不一致")
        print(f"  city_check: {city_check['status']}")
        print(f"  site_check: {site_check['overall_status']}")
        raise RuntimeError("Dashboard auto-update failed: consistency check failed")

    print(f"\n[PASS] Dashboard 刷新成功，{len(changed_files)} 个文件已更新")
    print(f"  city_series: {city_check['status']}")
    print(f"  site_series: {site_check['overall_status']}")
    print(f"[OK] stamp: {stamp_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
