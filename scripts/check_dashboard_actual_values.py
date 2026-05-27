#!/usr/bin/env python3
"""快速核对 site_series JSON 中的 actual_mw 与原始数据源是否一致。"""
from pathlib import Path
import argparse
import json
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="output/pv_pipeline")
    parser.add_argument("--site-id", default="S012")
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end", default="2025-12-31")
    args = parser.parse_args()

    root = Path(args.output_root)
    site_json = root / "interactive_dashboard" / "site_series" / f"{args.site_id}.json"
    final_full = root / "tables" / "distributed_predictions_final_full.pkl"
    power_clean = root / "tables" / "power_clean.pkl"

    js = pd.DataFrame(json.loads(site_json.read_text(encoding="utf-8")))
    js["time"] = pd.to_datetime(js["time"])
    js = js[(js["time"] >= args.start) & (js["time"] <= pd.Timestamp(args.end) + pd.Timedelta(days=1))]

    ff = pd.read_pickle(final_full)
    ff["time"] = pd.to_datetime(ff["time"])
    ff = ff[
        ff["site_id"].astype(str).eq(args.site_id)
        & (ff["time"] >= args.start)
        & (ff["time"] <= pd.Timestamp(args.end) + pd.Timedelta(days=1))
        & ff["hour"].between(6, 19)
    ]

    pc = pd.read_pickle(power_clean)
    pc["time"] = pd.to_datetime(pc["time"])
    pc["hour"] = pc["time"].dt.hour
    pc = pc[
        pc["site_id"].astype(str).eq(args.site_id)
        & (pc["time"] >= args.start)
        & (pc["time"] <= pd.Timestamp(args.end) + pd.Timedelta(days=1))
        & pc["hour"].between(6, 19)
    ]

    m1 = js[["time", "actual_mw"]].merge(ff[["time", "power_mw"]], on="time", how="outer", indicator=True)
    m1["diff"] = (m1["actual_mw"] - m1["power_mw"]).abs()

    m2 = js[["time", "actual_mw"]].merge(pc[["time", "power_mw"]], on="time", how="outer", indicator=True)
    m2["diff"] = (m2["actual_mw"] - m2["power_mw"]).abs()

    print(f"site={args.site_id}, range={args.start}~{args.end}")
    print("json rows:", len(js), "sum:", round(js["actual_mw"].sum(), 4), "zero:", int((js["actual_mw"] == 0).sum()))
    print("final_full rows:", len(ff), "sum:", round(ff["power_mw"].sum(), 4), "zero:", int((ff["power_mw"] == 0).sum()))
    print("power_clean rows:", len(pc), "sum:", round(pc["power_mw"].sum(), 4), "zero:", int((pc["power_mw"] == 0).sum()))
    print("json vs final_full max diff:", m1["diff"].max())
    print("json vs power_clean max diff:", m2["diff"].max())

    assert m1["_merge"].eq("both").all(), "Not all json rows matched in final_full"
    assert m2["_merge"].eq("both").all(), "Not all json rows matched in power_clean"
    assert m1["diff"].fillna(0).max() <= 1e-9, f"final_full diff too large: {m1['diff'].max()}"
    assert m2["diff"].fillna(0).max() <= 1e-9, f"power_clean diff too large: {m2['diff'].max()}"
    print("[OK] dashboard actual values match source tables")


if __name__ == "__main__":
    main()
