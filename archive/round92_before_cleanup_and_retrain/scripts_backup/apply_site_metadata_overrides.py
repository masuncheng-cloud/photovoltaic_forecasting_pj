#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round6 脚本三：人工 metadata overrides 应用
============================================
只应用 config/site_metadata_overrides.csv 中人工确认的修正。
容量修改必须通过该文件确认，不自动猜测。
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR.mkdir(parents=True, exist_ok=True)

OVERRIDE_PATH = CONFIG_DIR / "site_metadata_overrides.csv"
IN_PATH = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
OUT_PATH = TABLES_DIR / "distributed_predictions_metadata_overridden_full.pkl"
OUT_LOG = METRICS_DIR / "round6_site_metadata_overrides_applied.csv"


def main():
    if not OVERRIDE_PATH.exists():
        OVERRIDE_PATH.write_text("site_id,override_capacity_mw,override_site_name,reason,enabled\n", encoding="utf-8")
        print(f"已创建空 overrides 文件: {OVERRIDE_PATH}")

    if not IN_PATH.exists():
        raise FileNotFoundError(IN_PATH)

    df = safe_pickle_load(IN_PATH)
    overrides = pd.read_csv(OVERRIDE_PATH)
    if overrides.empty:
        write_prediction_pickle_atomic(
            df,
            OUT_PATH,
            required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        )
        pd.DataFrame(columns=["site_id", "field", "old_value", "new_value", "reason"]).to_csv(
            OUT_LOG, index=False, encoding="utf-8-sig"
        )
        print("overrides 为空，不做修改，仅透传输出。")
        return

    enabled = overrides["enabled"].astype(str).isin(["1", "True", "true", "YES", "yes"])
    overrides = overrides[enabled].copy()
    log_rows = []

    out = df.copy()
    for _, row in overrides.iterrows():
        sid = str(row["site_id"])
        mask = out["site_id"].astype(str) == sid
        if not mask.any():
            continue

        reason = str(row.get("reason", ""))

        if pd.notna(row.get("override_capacity_mw")):
            new_cap = float(row["override_capacity_mw"])
            if new_cap <= 0:
                raise ValueError(f"{sid} override_capacity_mw 必须 > 0")
            old = out.loc[mask, "capacity_mw"].dropna().median()
            out.loc[mask, "capacity_mw"] = new_cap
            out_pred = pd.to_numeric(out.loc[mask, "power_pred"], errors="coerce")
            out.loc[mask, "power_pred"] = out_pred.clip(lower=0, upper=new_cap)
            log_rows.append({
                "site_id": sid,
                "field": "capacity_mw",
                "old_value": old,
                "new_value": new_cap,
                "reason": reason,
            })

        if "override_site_name" in row and pd.notna(row.get("override_site_name")):
            new_name = str(row["override_site_name"]).strip()
            if new_name:
                if "site_name" in out.columns:
                    old_name = ""
                    if out.loc[mask, "site_name"].notna().any():
                        old_name = str(out.loc[mask, "site_name"].dropna().iloc[0])
                    out.loc[mask, "site_name"] = new_name
                    log_rows.append({
                        "site_id": sid,
                        "field": "site_name",
                        "old_value": old_name,
                        "new_value": new_name,
                        "reason": reason,
                    })

    write_prediction_pickle_atomic(
        out,
        OUT_PATH,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    pd.DataFrame(log_rows).to_csv(OUT_LOG, index=False, encoding="utf-8-sig")
    print(f"保存: {OUT_PATH}")
    print(f"应用记录: {OUT_LOG}")


if __name__ == "__main__":
    main()
