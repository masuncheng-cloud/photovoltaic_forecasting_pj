#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

WATCH = {"S012", "S055", "S050", "S032", "S019", "S053", "S116"}


def main():
    mapping_path = TABLES / "power_mapping.csv"
    site_path = TABLES / "site_master.csv"
    raw_path = TABLES / "power_long_raw.pkl"
    clean_path = TABLES / "power_clean.pkl"

    outputs = {}

    if mapping_path.exists():
        mapping = pd.read_csv(mapping_path)
        outputs["mapping_columns"] = list(mapping.columns)
        print(f"[INFO] mapping columns: {list(mapping.columns)}")

        # Watch site mapping rows
        watch_rows = []
        for idx, row in mapping.iterrows():
            row_str = str(row.to_dict())
            for sid in WATCH:
                if sid in row_str:
                    watch_rows.append(row.to_dict())
                    break
        if watch_rows:
            watch_mapping = pd.DataFrame(watch_rows)
            watch_mapping.to_csv(METRICS / "round9_watch_site_power_mapping_rows.csv", index=False, encoding="utf-8-sig")
            print(f"[INFO] watch site mapping rows: {len(watch_mapping)}")

        # Check duplicate mappings
        dup_rows = []
        for col in mapping.columns:
            vc = mapping[col].astype(str).value_counts()
            dup = vc[vc > 1]
            for val, cnt in dup.items():
                if val and val != "nan":
                    dup_rows.append({"column": col, "value": val, "count": int(cnt)})
        pd.DataFrame(dup_rows).to_csv(METRICS / "round9_power_mapping_duplicate_values.csv", index=False, encoding="utf-8-sig")
        if dup_rows:
            print(f"[WARN] duplicate mapping values: {len(dup_rows)}")

    if site_path.exists():
        site = pd.read_csv(site_path)
        print(f"[INFO] site_master columns: {list(site.columns)}")
        watch_site = []
        for idx, row in site.iterrows():
            row_str = str(row.to_dict())
            for sid in WATCH:
                if sid in row_str:
                    watch_site.append(row.to_dict())
                    break
        if watch_site:
            pd.DataFrame(watch_site).to_csv(METRICS / "round9_watch_site_master_rows.csv", index=False, encoding="utf-8-sig")

    if raw_path.exists():
        raw = safe_pickle_load(raw_path)
        raw_cols = list(raw.columns)
        pd.DataFrame({"raw_columns": raw_cols}).to_csv(METRICS / "round9_power_long_raw_columns.csv", index=False, encoding="utf-8-sig")
        print(f"[INFO] raw columns ({len(raw_cols)}): {raw_cols[:10]}...")

        # Find watch site rows in raw
        possible_id_cols = [c for c in raw.columns if c.lower() in {"site_id", "site_name", "alias", "name", "power_col"}]
        if possible_id_cols:
            mask = raw[possible_id_cols].astype(str).apply(lambda col: col.str.contains("|".join(WATCH), na=False)).any(axis=1)
            n = mask.sum()
            print(f"[INFO] watch site rows in raw: {n}")
            if n > 0:
                raw[mask].head(2000).to_csv(METRICS / "round9_watch_site_raw_power_rows_sample.csv", index=False, encoding="utf-8-sig")

    if clean_path.exists():
        clean = safe_pickle_load(clean_path)
        pd.DataFrame({"clean_columns": list(clean.columns)}).to_csv(METRICS / "round9_power_clean_columns.csv", index=False, encoding="utf-8-sig")
        print(f"[INFO] clean columns: {list(clean.columns)}")

        if "site_id" in clean.columns:
            watch_clean = clean[clean["site_id"].isin(WATCH)].copy()
            if "time" in watch_clean.columns:
                watch_clean["time"] = pd.to_datetime(watch_clean["time"], errors="coerce")
                watch_clean["hour"] = watch_clean["time"].dt.hour
            summary = []
            for sid, g in watch_clean.groupby("site_id"):
                power_col = "power_mw" if "power_mw" in g.columns else None
                if power_col:
                    p = pd.to_numeric(g[power_col], errors="coerce")
                    summary.append({
                        "site_id": sid,
                        "rows": len(g),
                        "positive_rows": int((p > 0).sum()),
                        "zero_rows": int((p == 0).sum()),
                        "p95": round(float(p[p > 0].quantile(0.95)), 4) if (p > 0).any() else np.nan,
                        "p99": round(float(p[p > 0].quantile(0.99)), 4) if (p > 0).any() else np.nan,
                        "max": round(float(p[p > 0].max()), 4) if (p > 0).any() else np.nan,
                        "mean": round(float(p[p > 0].mean()), 4) if (p > 0).any() else np.nan,
                    })
            if summary:
                pd.DataFrame(summary).to_csv(METRICS / "round9_watch_site_clean_power_summary.csv", index=False, encoding="utf-8-sig")
                print("[INFO] watch site clean power summary:")
                print(pd.DataFrame(summary).to_string(index=False))

    print()
    print("[OK] Diagnosis complete. Output files:")
    for f in sorted(METRICS.glob("round9_*.csv")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
