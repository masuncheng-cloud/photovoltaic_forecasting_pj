#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config"
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
CONFIG.mkdir(parents=True, exist_ok=True)
METRICS.mkdir(parents=True, exist_ok=True)

OVERRIDE = CONFIG / "power_alias_overrides_round9.csv"
IN_MAPPING = TABLES / "power_mapping.csv"
OUT_MAPPING = TABLES / "power_mapping_round9_corrected.csv"
LOG = METRICS / "round9_power_alias_overrides_applied.csv"


def main():
    if not OVERRIDE.exists():
        OVERRIDE.write_text("site_id,old_alias,new_alias,reason,enabled\n", encoding="utf-8")
        print(f"[INFO] 已创建空配置: {OVERRIDE}")

    if not IN_MAPPING.exists():
        raise FileNotFoundError(IN_MAPPING)

    mapping = pd.read_csv(IN_MAPPING)
    overrides = pd.read_csv(OVERRIDE)

    if overrides.empty:
        mapping.to_csv(OUT_MAPPING, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=["site_id", "old_alias", "new_alias", "reason", "status"]).to_csv(LOG, index=False, encoding="utf-8-sig")
        print("[INFO] 无 alias override，透传 power_mapping -> power_mapping_round9_corrected.csv")
        return

    enabled = overrides[overrides["enabled"].astype(str).isin(["1", "true", "True", "yes", "YES"])].copy()
    log_rows = []

    out = mapping.copy()
    for _, r in enabled.iterrows():
        sid = str(r["site_id"])
        old_alias = str(r["old_alias"])
        new_alias = str(r["new_alias"])
        reason = str(r.get("reason", ""))

        site_mask = out.astype(str).apply(lambda col: col.str.contains(sid, na=False)).any(axis=1)
        old_mask = out.astype(str).apply(lambda col: col == old_alias).any(axis=1)
        mask = site_mask & old_mask

        if not mask.any():
            log_rows.append({
                "site_id": sid, "old_alias": old_alias, "new_alias": new_alias,
                "reason": reason, "status": "not_found",
            })
            continue

        for col in out.columns:
            out.loc[mask & (out[col].astype(str) == old_alias), col] = new_alias

        log_rows.append({
            "site_id": sid, "old_alias": old_alias, "new_alias": new_alias,
            "reason": reason, "status": "applied",
        })

    out.to_csv(OUT_MAPPING, index=False, encoding="utf-8-sig")
    pd.DataFrame(log_rows).to_csv(LOG, index=False, encoding="utf-8-sig")
    print(f"[OK] 保存: {OUT_MAPPING}")
    print(f"[OK] 日志: {LOG}")


if __name__ == "__main__":
    main()
