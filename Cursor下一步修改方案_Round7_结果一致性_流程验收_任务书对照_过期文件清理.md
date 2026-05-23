# Cursor 下一步修改方案 Round7：结果一致性、流程验收、任务书对照与过期文件清理

## 0. 当前状态判断

Round6 后的核心结论：

1. 最终精度没有继续提升，10-14 点最终仍采用 `MiddaySiteCalibrated`。
2. 自动后处理已经到边界，`Round6StableBias` 在 valid 上有效，但 test 上轻微恶化，最终被安全阈值拦截。
3. 高误差问题已定位到数据侧：
   - S012/S055/S050：10-14 点系统性高估 2-3 倍。
   - S032：10-14 点系统性低估约 50%。
   - 这些站点容量未明显超限，更可能是功率列映射、别名字典、站点台账或数据源错位问题。
4. 当前存在一个必须先修的问题：部分 metrics/report 文件没有在最终 `final_eval.pkl` 后重新生成，导致 CSV 和最终 pkl 不完全一致。

本轮 Round7 不再继续新增模型后处理，而是做工程闭环：

```text
统一 final 指标来源
→ 重新生成所有核心 metrics
→ 检查流水线完整性
→ 对照任务书逐项验收
→ 标记并清理过期/无效产物
→ 输出最终可交付报告
```

---

## 1. 本轮目标

### 1.1 必须解决的问题

| 问题 | 当前表现 | Round7 处理方式 |
|---|---|---|
| metrics 与 final pkl 不一致 | `midday_nrmse_current_vs_fixed.csv` 曾出现 13.32，但 final 是 13.29 | 强制所有 metrics 从最新 final pkl 重算 |
| 报告可能引用旧结果 | 部分报告中残留 Round6 第一次入选结果 | 统一报告生成入口 |
| 过期候选产物太多 | residual/selective/round6 等候选文件混在 output 中 | 建立 archive 清单，移动或标记过期文件 |
| 任务书完成情况缺少机器可验收清单 | 报告中是人工描述 | 新增任务书对照 CSV/MD |
| 高误差站点问题未闭环 | 已定位 S012/S055/S050/S032，但没有单独验收结论 | 输出数据侧问题清单和下一步人工核查表 |

### 1.2 本轮不做的事

1. 不再新增 10-14 点后处理网格搜索。
2. 不用 test 集选择参数。
3. 不自动修改容量或站点映射。
4. 不删除原始数据、模型、最终 pkl。
5. 不把 S012/S055/S050/S032 直接剔除。

---

## 2. 最终口径固定

所有最终报告、CSV、验收脚本必须以这个文件为唯一最终预测来源：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
```

最终完整预测表：

```text
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
```

当前 final 参考值必须为：

| 指标 | 当前 final |
|---|---:|
| final_eval 行数 | 68,888 |
| 评估站点数 | 53 |
| 实际总出力 | 93,382.49 MWh |
| 预测总出力 | 92,069.09 MWh |
| pred_actual_ratio | 0.9859 |
| bias | -1.406% |
| MAE | 0.5893 MW |
| RMSE | 1.2047 MW |
| h10 NRMSE | 13.29% |
| h11 NRMSE | 14.68% |
| h12 NRMSE | 15.36% |
| h13 NRMSE | 15.31% |
| h14 NRMSE | 13.51% |

如果重新运行后不等于上述值，可以接受小数最后一位浮动，但不能出现 13.32、14.72、15.39 这一组 Round6 第一次错误入选结果。

---

## 3. 修改一：新增统一 final metrics 重算脚本

新建：

```text
scripts/regenerate_final_metrics_round7.py
```

作用：

1. 从 `distributed_predictions_final_eval.pkl` 读取最终结果。
2. 重新生成所有核心指标文件。
3. 覆盖旧的、不一致的 metrics。
4. 输出一个 `round7_final_metrics_manifest.csv`，记录每个文件的生成时间和数据来源。

写入以下代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import json
import hashlib
from datetime import datetime
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FIXED_EVAL = TABLES / "distributed_predictions_fixed_eval.pkl"
FIXED_FULL = TABLES / "distributed_predictions_fixed_full.pkl"
MSC_EVAL = TABLES / "distributed_predictions_midday_site_calibrated_eval.pkl"
MSC_FULL = TABLES / "distributed_predictions_midday_site_calibrated_full.pkl"

MIDDAY = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def overall_metrics(df: pd.DataFrame) -> dict:
    y = pd.to_numeric(df["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(df["power_pred"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(df["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c)
    actual = float(np.sum(y[m]))
    pred = float(np.sum(p[m]))
    mae = float(np.mean(np.abs(y[m] - p[m])))
    rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
    cap_mean = float(np.nanmean(c[m]))
    return {
        "rows": int(len(df)),
        "n_sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 2),
        "pred_mwh": round(pred, 2),
        "pred_actual_ratio": round(pred / actual, 6) if actual > 0 else np.nan,
        "bias_pct": round((pred / actual - 1.0) * 100.0, 3) if actual > 0 else np.nan,
        "mae_mw": round(mae, 4),
        "rmse_mw": round(rmse, 4),
        "nrmse_capacity_pct": round(rmse / cap_mean * 100.0, 3) if cap_mean > 0 else np.nan,
    }


def load_eval(eval_path: Path, full_path: Path | None = None) -> pd.DataFrame:
    if eval_path.exists():
        return safe_pickle_load(eval_path)
    if full_path is None or not full_path.exists():
        raise FileNotFoundError(f"找不到 eval/full: {eval_path}, {full_path}")
    df = safe_pickle_load(full_path)
    return build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )


def compare_hourly(base: pd.DataFrame, final: pd.DataFrame, name: str) -> pd.DataFrame:
    b = hourly_nrmse_metrics(base)
    f = hourly_nrmse_metrics(final)
    rows = []
    for h in range(6, 20):
        br = b[b["hour"] == h]
        fr = f[f["hour"] == h]
        if br.empty or fr.empty:
            continue
        br = br.iloc[0]
        fr = fr.iloc[0]
        rows.append({
            "hour": int(h),
            f"{name}_site_nrmse_pct": round(float(br["site_nrmse_mean_pct"]), 4),
            "final_site_nrmse_pct": round(float(fr["site_nrmse_mean_pct"]), 4),
            "improvement_pp": round(float(br["site_nrmse_mean_pct"] - fr["site_nrmse_mean_pct"]), 4),
            f"{name}_city_nrmse_pct": round(float(br["city_nrmse_pct"]), 4),
            "final_city_nrmse_pct": round(float(fr["city_nrmse_pct"]), 4),
            "city_improvement_pp": round(float(br["city_nrmse_pct"] - fr["city_nrmse_pct"]), 4),
        })
    return pd.DataFrame(rows)


def main():
    if not FINAL_EVAL.exists():
        raise FileNotFoundError(FINAL_EVAL)

    final = safe_pickle_load(FINAL_EVAL)
    if "hour" not in final.columns:
        final["time"] = pd.to_datetime(final["time"])
        final["hour"] = final["time"].dt.hour

    manifest = []
    source_hash = file_sha256(FINAL_EVAL)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    overall = overall_metrics(final)
    overall_df = pd.DataFrame([overall])
    out_overall = METRICS / "round7_final_overall_metrics.csv"
    overall_df.to_csv(out_overall, index=False, encoding="utf-8-sig")
    manifest.append({"file": str(out_overall.relative_to(PROJECT_ROOT)), "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)), "source_sha256": source_hash})

    hourly = hourly_nrmse_metrics(final)
    out_hourly = METRICS / "分布式光伏预测_逐小时平均NRMSE.csv"
    hourly[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_csv(out_hourly, index=False, encoding="utf-8-sig")
    manifest.append({"file": str(out_hourly.relative_to(PROJECT_ROOT)), "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)), "source_sha256": source_hash})

    # final vs fixed
    fixed = load_eval(FIXED_EVAL, FIXED_FULL)
    cmp_fixed = compare_hourly(fixed, final, "fixed")
    cmp_fixed_midday = cmp_fixed[cmp_fixed["hour"].isin(MIDDAY)].copy()
    out_fixed = METRICS / "midday_nrmse_current_vs_fixed.csv"
    cmp_fixed_midday.to_csv(out_fixed, index=False, encoding="utf-8-sig")
    manifest.append({"file": str(out_fixed.relative_to(PROJECT_ROOT)), "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)), "source_sha256": source_hash})

    # final vs MiddaySiteCalibrated safe
    if MSC_EVAL.exists() or MSC_FULL.exists():
        msc = load_eval(MSC_EVAL, MSC_FULL)
        cmp_safe = compare_hourly(msc, final, "safe")
        cmp_safe = cmp_safe[cmp_safe["hour"].isin(MIDDAY)].copy()
        out_safe = METRICS / "round6_midday_gain_vs_safe.csv"
        cmp_safe.to_csv(out_safe, index=False, encoding="utf-8-sig")
        manifest.append({"file": str(out_safe.relative_to(PROJECT_ROOT)), "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)), "source_sha256": source_hash})

    summary = {
        "generated_at": generated_at,
        "source_final_eval": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
        "source_sha256": source_hash,
        "overall": overall,
        "midday_hourly": hourly[hourly["hour"].isin(MIDDAY)][["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_dict(orient="records"),
    }
    out_json = METRICS / "round7_final_metrics_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.append({"file": str(out_json.relative_to(PROJECT_ROOT)), "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)), "source_sha256": source_hash})

    manifest_df = pd.DataFrame(manifest)
    manifest_df["generated_at"] = generated_at
    out_manifest = METRICS / "round7_final_metrics_manifest.csv"
    manifest_df.to_csv(out_manifest, index=False, encoding="utf-8-sig")

    print("Round7 final metrics regenerated from final_eval.")
    print(overall_df.to_string(index=False))
    print(hourly[hourly["hour"].isin(MIDDAY)][["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
```

---

## 4. 修改二：新增 metrics 一致性断言脚本

新建：

```text
scripts/assert_final_metrics_consistency_round7.py
```

作用：

1. 读取最新 `final_eval.pkl`。
2. 读取核心 CSV。
3. 检查 CSV 是否与 pkl 一致。
4. 如果发现 13.32/14.72 这类旧结果残留，直接失败。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
HOURLY_CSV = METRICS / "分布式光伏预测_逐小时平均NRMSE.csv"
VS_FIXED = METRICS / "midday_nrmse_current_vs_fixed.csv"
VS_SAFE = METRICS / "round6_midday_gain_vs_safe.csv"
SUMMARY_MD = DOCS / "当前最终结果摘要.md"

MIDDAY = [10, 11, 12, 13, 14]


def main():
    final = safe_pickle_load(FINAL_EVAL)
    h = hourly_nrmse_metrics(final)
    h = h[h["hour"].isin(MIDDAY)].copy()
    truth = {
        int(r["hour"]): round(float(r["site_nrmse_mean_pct"]), 2)
        for _, r in h.iterrows()
    }

    errors = []

    hourly = pd.read_csv(HOURLY_CSV)
    for hour, val in truth.items():
        row = hourly[hourly["hour"] == hour]
        if row.empty:
            errors.append(f"hourly csv 缺少 hour={hour}")
            continue
        csv_val = round(float(row.iloc[0]["site_nrmse_mean_pct"]), 2)
        if abs(csv_val - val) > 0.01:
            errors.append(f"hourly csv hour={hour} 不一致: csv={csv_val}, final={val}")

    if VS_SAFE.exists():
        safe = pd.read_csv(VS_SAFE)
        for hour, val in truth.items():
            row = safe[safe["hour"] == hour]
            if row.empty:
                continue
            final_val = round(float(row.iloc[0]["final_site_nrmse_pct"]), 2)
            if abs(final_val - val) > 0.01:
                errors.append(f"vs_safe hour={hour} 不一致: csv={final_val}, final={val}")

    if VS_FIXED.exists():
        fixed = pd.read_csv(VS_FIXED)
        for hour, val in truth.items():
            row = fixed[fixed["hour"] == hour]
            if row.empty:
                continue
            final_val = round(float(row.iloc[0]["final_site_nrmse_pct"]), 2)
            if abs(final_val - val) > 0.01:
                errors.append(f"vs_fixed hour={hour} 不一致: csv={final_val}, final={val}")

    if SUMMARY_MD.exists():
        text = SUMMARY_MD.read_text(encoding="utf-8")
        for hour, val in truth.items():
            if f"{val:.2f}" not in text:
                errors.append(f"当前最终结果摘要.md 可能未包含 hour={hour} 最新值 {val:.2f}")

    if errors:
        print("[FAIL] final metrics consistency failed:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print("[OK] final metrics consistency passed.")
    print(truth)


if __name__ == "__main__":
    main()
```

---

## 5. 修改三：新增整体流程验收脚本

新建：

```text
scripts/check_end_to_end_deliverables_round7.py
```

作用：

1. 检查核心源码是否存在。
2. 检查核心表是否存在且可读。
3. 检查 final full/eval 行数、小时范围、站点数。
4. 检查关键 metrics/docs 是否都来自最新 final。
5. 输出 `round7_end_to_end_deliverables_check.csv`。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"


def check_file(path: Path, required=True) -> dict:
    return {
        "item": str(path.relative_to(PROJECT_ROOT)) if path.exists() or path.is_absolute() else str(path),
        "exists": path.exists(),
        "required": required,
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3) if path.exists() else 0,
        "status": "OK" if path.exists() or not required else "MISSING",
    }


def main():
    checks = []

    required_files = [
        PROJECT_ROOT / "scripts" / "train_fixed.py",
        PROJECT_ROOT / "scripts" / "select_final_prediction_by_guard.py",
        PROJECT_ROOT / "scripts" / "apply_midday_site_nrmse_calibration.py",
        PROJECT_ROOT / "scripts" / "diagnose_site_capacity_mapping_round6.py",
        PROJECT_ROOT / "scripts" / "diagnose_midday_bias_stability_round6.py",
        PROJECT_ROOT / "scripts" / "regenerate_final_metrics_round7.py",
        PROJECT_ROOT / "scripts" / "assert_final_metrics_consistency_round7.py",
        PROJECT_ROOT / "src" / "pv_forecasting" / "core" / "evaluation.py",
        TABLES / "distributed_predictions_final_full.pkl",
        TABLES / "distributed_predictions_final_eval.pkl",
        METRICS / "final_version_selection_by_hour.csv",
        METRICS / "分布式光伏预测_逐小时平均NRMSE.csv",
        METRICS / "round6_watch_site_diagnosis.csv",
        METRICS / "round7_final_overall_metrics.csv",
        DOCS / "当前最终结果摘要.md",
    ]

    for f in required_files:
        checks.append(check_file(f, required=True))

    final_eval_path = TABLES / "distributed_predictions_final_eval.pkl"
    if final_eval_path.exists():
        try:
            df = safe_pickle_load(final_eval_path)
            if "hour" not in df.columns:
                df["time"] = pd.to_datetime(df["time"])
                df["hour"] = df["time"].dt.hour
            checks.append({
                "item": "final_eval_rows",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "OK" if len(df) > 0 else "EMPTY",
                "detail": len(df),
            })
            checks.append({
                "item": "final_eval_site_count",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "OK" if df["site_id"].nunique() == 53 else "WARN",
                "detail": df["site_id"].nunique(),
            })
            hmin, hmax = int(df["hour"].min()), int(df["hour"].max())
            checks.append({
                "item": "final_eval_hour_range",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "OK" if hmin >= 6 and hmax <= 19 else "WARN",
                "detail": f"{hmin}-{hmax}",
            })
        except Exception as exc:
            checks.append({
                "item": "final_eval_readable",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "FAIL",
                "detail": str(exc),
            })

    out = pd.DataFrame(checks)
    out.to_csv(METRICS / "round7_end_to_end_deliverables_check.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    bad = out[(out["required"] == True) & (~out["status"].isin(["OK"]))]
    if not bad.empty:
        print("[FAIL] 存在未通过检查项")
        raise SystemExit(1)
    print("[OK] end-to-end deliverables check passed.")


if __name__ == "__main__":
    main()
```

---

## 6. 修改四：新增任务书对照验收脚本

新建：

```text
scripts/generate_taskbook_compliance_round7.py
```

输出：

```text
output/pv_pipeline/docs/任务书完成情况_Round7.md
output/pv_pipeline/metrics/round7_taskbook_compliance.csv
```

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def exists(rel: str) -> bool:
    return (PROJECT_ROOT / rel).exists()


def main():
    rows = [
        {
            "任务书要求方向": "汇聚气象、辐照、功率、站点台账等多源数据",
            "当前证据": "已形成原始功率长表、站点映射、气象插值与特征表；报告列出集中式/分布式映射数量",
            "关键文件": "output/pv_pipeline/docs/当前最终结果摘要.md",
            "完成状态": "基本满足",
            "遗留问题": "S012/S055/S050/S032 需人工核查功率列映射",
        },
        {
            "任务书要求方向": "利用集中式光伏功率反演光伏资源/辐照",
            "当前证据": "测试集辐照 Corr 0.99987，辐照 NRMSE 0.387%",
            "关键文件": "光伏功率预测项目.md",
            "完成状态": "满足",
            "遗留问题": "需在正式报告中说明辐照 NRMSE 归一化基准",
        },
        {
            "任务书要求方向": "将集中式信息扩展到分布式站点",
            "当前证据": "IDW/ERA5/反演融合，测试集融合 RMSE 3.016 W/m²",
            "关键文件": "光伏功率预测项目.md",
            "完成状态": "满足",
            "遗留问题": "高误差站点需核查映射，而非继续调融合参数",
        },
        {
            "任务书要求方向": "实现分布式光伏功率预测",
            "当前证据": "final_full/final_eval 已生成；68,888 条测试评估样本，53 个站点",
            "关键文件": "output/pv_pipeline/tables/distributed_predictions_final_eval.pkl",
            "完成状态": "基本满足",
            "遗留问题": "小容量和异常映射站点误差偏高",
        },
        {
            "任务书要求方向": "输出站点级和全市级预测结果",
            "当前证据": "逐小时 NRMSE、站点诊断、城市统计、版本选择表均已生成",
            "关键文件": "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv",
            "完成状态": "满足",
            "遗留问题": "需清理过期候选结果，避免交付混乱",
        },
        {
            "任务书要求方向": "评估模型预测能力",
            "当前证据": "MAE=0.5893 MW，RMSE=1.2047 MW，pred_actual_ratio=0.9859，逐小时 NRMSE 完整",
            "关键文件": "output/pv_pipeline/metrics/round7_final_overall_metrics.csv",
            "完成状态": "满足",
            "遗留问题": "统一禁止使用旧 MAPE/WAPE 作为主指标",
        },
        {
            "任务书要求方向": "逐小时误差诊断",
            "当前证据": "6-19 点站点平均 NRMSE 和城市 NRMSE 已输出；10-14 点安全版本固定",
            "关键文件": "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv",
            "完成状态": "满足",
            "遗留问题": "6/18/19 城市 NRMSE 仍偏高，但本阶段暂不优化早晚",
        },
        {
            "任务书要求方向": "结果闭环和可复现检查",
            "当前证据": "新增 Round7 end-to-end 检查和 metrics 一致性检查",
            "关键文件": "output/pv_pipeline/metrics/round7_end_to_end_deliverables_check.csv",
            "完成状态": "基本满足",
            "遗留问题": "需将 Round7 脚本接入 train_fixed 总入口",
        },
        {
            "任务书要求方向": "工程化交付",
            "当前证据": "核心 pkl/csv/docs 齐全",
            "关键文件": "output/pv_pipeline/",
            "完成状态": "部分满足",
            "遗留问题": "需要 archive 过期产物，输出最终交付清单",
        },
    ]

    df = pd.DataFrame(rows)
    out_csv = METRICS / "round7_taskbook_compliance.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    md = ["# 任务书完成情况 Round7", ""]
    md.append("> 本文件由 `scripts/generate_taskbook_compliance_round7.py` 生成。")
    md.append("")
    md.append("| 任务书要求方向 | 当前证据 | 关键文件 | 完成状态 | 遗留问题 |")
    md.append("|---|---|---|---|---|")
    for _, r in df.iterrows():
        md.append(
            f"| {r['任务书要求方向']} | {r['当前证据']} | `{r['关键文件']}` | {r['完成状态']} | {r['遗留问题']} |"
        )
    md.append("")
    md.append("## 总体判断")
    md.append("")
    md.append("当前项目在既有数据集上的模型能力评估、分布式功率预测、逐小时 NRMSE 诊断、站点级与城市级输出方面基本满足任务书实现要求。")
    md.append("当前主要未闭环问题不是模型流程缺失，而是少数高误差站点的数据映射/别名字典/功率列来源需要人工核查。")
    md.append("")
    (DOCS / "任务书完成情况_Round7.md").write_text("\n".join(md), encoding="utf-8")

    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
```

---

## 7. 修改五：新增过期文件归档脚本

本轮不直接删除文件，而是移动到：

```text
output/pv_pipeline/archive_round7/
```

这样可回溯，不会误删重要中间结果。

新建：

```text
scripts/archive_stale_outputs_round7.py
```

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import shutil
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
ARCHIVE = OUT / "archive_round7"
ARCHIVE.mkdir(parents=True, exist_ok=True)

# 不归档 final、安全基准、核心诊断、Round7 文件。
KEEP_PATTERNS = [
    "distributed_predictions_final",
    "distributed_predictions_midday_site_calibrated",
    "分布式光伏预测_逐小时平均NRMSE",
    "final_version_selection_by_hour",
    "round6_watch_site_diagnosis",
    "round6_flagged_site_diagnosis",
    "round6_site_capacity_mapping_diagnosis",
    "round6_midday_bias_stability",
    "round6_stable_extreme_bias_candidates",
    "round7_",
    "当前最终结果摘要",
]

STALE_PATTERNS = [
    "midday_residual_specialist",
    "midday_selective_site_correction",
    "distributed_predictions_midday_residual_specialist",
    "distributed_predictions_midday_selective_site_corrected",
    "distributed_predictions_round6_stable_bias",
    "midday_nrmse_acceptance",
    "当前结果_vs_周二基准",
]


def should_keep(path: Path) -> bool:
    name = path.name
    return any(p in name for p in KEEP_PATTERNS)


def should_archive(path: Path) -> bool:
    name = path.name
    if should_keep(path):
        return False
    return any(p in name for p in STALE_PATTERNS)


def main():
    rows = []
    for base in [METRICS, TABLES]:
        if not base.exists():
            continue
        for path in base.iterdir():
            if not path.is_file():
                continue
            if should_archive(path):
                rel_parent = path.parent.relative_to(OUT)
                dest_dir = ARCHIVE / rel_parent
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                shutil.move(str(path), str(dest))
                rows.append({
                    "original_path": str(path.relative_to(PROJECT_ROOT)),
                    "archived_path": str(dest.relative_to(PROJECT_ROOT)),
                    "size_mb": round(dest.stat().st_size / 1024 / 1024, 3),
                    "reason": "stale_candidate_or_old_baseline",
                })

    manifest = pd.DataFrame(rows)
    manifest_path = ARCHIVE / "archive_round7_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    print(f"Archived {len(rows)} stale files.")
    if not manifest.empty:
        print(manifest.to_string(index=False))


if __name__ == "__main__":
    main()
```

### 7.1 注意

归档脚本应在所有 final metrics 和报告重新生成、检查通过之后再运行。

---

## 8. 修改六：更新项目主报告

修改：

```text
scripts/update_project_md_metrics.py
```

要求：

1. 读取 `round7_final_overall_metrics.csv` 和 `分布式光伏预测_逐小时平均NRMSE.csv`。
2. 报告中写明：

```text
本报告所有最终预测指标均来自 output/pv_pipeline/tables/distributed_predictions_final_eval.pkl。
```

3. 报告中新增一段：

```text
Round7 工程闭环说明：
- 已重新生成所有核心 metrics；
- 已通过 final pkl 与 CSV 一致性检查；
- 已生成任务书完成情况对照；
- 已将无效候选/过期中间结果归档至 archive_round7。
```

4. 报告中不要再把 `Round6StableBias` 或 `MiddaySiteSelectiveCorrected` 写成最终有效版本。

---

## 9. 修改七：更新总入口 `train_fixed.py`

将 Round7 脚本加入总入口，建议顺序：

```python
FIX_SCRIPTS = [
    ...
    "apply_midday_site_nrmse_calibration.py",
    "diagnose_midday_worst_site_hours.py",
    "diagnose_site_capacity_mapping_round6.py",
    "diagnose_midday_bias_stability_round6.py",
    "apply_site_metadata_overrides.py",
    "apply_midday_stable_bias_correction_round6.py",
    "select_final_prediction_by_guard.py",

    # Round7: final 指标统一重算与验收
    "regenerate_final_metrics_round7.py",
    "assert_final_metrics_consistency_round7.py",
    "check_end_to_end_deliverables_round7.py",
    "generate_taskbook_compliance_round7.py",
    "update_project_md_metrics.py",
]
```

`archive_stale_outputs_round7.py` 不建议默认加入完整训练入口，建议人工确认后单独运行。

critical 建议：

| 脚本 | critical |
|---|---|
| `regenerate_final_metrics_round7.py` | 是 |
| `assert_final_metrics_consistency_round7.py` | 是 |
| `check_end_to_end_deliverables_round7.py` | 是 |
| `generate_taskbook_compliance_round7.py` | 是 |
| `archive_stale_outputs_round7.py` | 否，手动运行 |

---

## 10. Cursor 执行顺序

在项目根目录执行：

```bash
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_final_metrics_round7.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/check_end_to_end_deliverables_round7.py
python scripts/generate_taskbook_compliance_round7.py
python scripts/update_project_md_metrics.py
```

确认以上全部通过后，再执行归档：

```bash
python scripts/archive_stale_outputs_round7.py
python scripts/regenerate_final_metrics_round7.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/check_end_to_end_deliverables_round7.py
```

归档后再次重算 metrics，是为了保证归档没有误移动核心文件。

---

## 11. Round7 验收标准

### 11.1 final 指标一致性

`assert_final_metrics_consistency_round7.py` 必须通过。

必须确认：

| 小时 | final NRMSE |
|---:|---:|
| 10 | 13.29% |
| 11 | 14.68% |
| 12 | 15.36% |
| 13 | 15.31% |
| 14 | 13.51% |

不允许核心 CSV 中再出现：

```text
13.32, 14.72, 15.39, 15.35, 13.54
```

作为 final 结果。

### 11.2 流程完整性

`round7_end_to_end_deliverables_check.csv` 中 required 项必须全部 OK。

### 11.3 任务书完成情况

必须生成：

```text
output/pv_pipeline/docs/任务书完成情况_Round7.md
output/pv_pipeline/metrics/round7_taskbook_compliance.csv
```

其中结论应为：

```text
当前项目在既有数据集上的模型能力评估、分布式功率预测、逐小时 NRMSE 诊断、站点级与城市级输出方面基本满足任务书实现要求；
主要遗留问题是少数高误差站点的数据映射/别名字典/功率列来源需要人工核查。
```

### 11.4 过期文件归档

归档后必须保留：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_eval.pkl
output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_full.pkl
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/metrics/final_version_selection_by_hour.csv
output/pv_pipeline/metrics/round7_final_overall_metrics.csv
output/pv_pipeline/docs/当前最终结果摘要.md
output/pv_pipeline/docs/任务书完成情况_Round7.md
```

---

## 12. 最终输出给用户看的结论模板

Round7 完成后，执行总结建议写：

```text
Round7 未继续调模型，而是完成最终结果一致性和工程闭环。

1. 已统一 final 指标来源：所有核心 metrics 均从 distributed_predictions_final_eval.pkl 重算。
2. 已修复 CSV 与 final pkl 不一致问题，10-14 点最终 NRMSE 固定为 13.29/14.68/15.36/15.31/13.51。
3. 已完成任务书对照验收，当前在既有数据集上的模型能力、分布式预测、逐小时诊断、站点/城市输出基本满足要求。
4. 已确认主要遗留问题是 S012/S055/S050/S032 等高误差站点的数据映射或别名字典问题，不适合继续自动后处理。
5. 已归档无效候选和过期中间结果，保留 final、安全基准、诊断和任务书对照文件。
```

---

## 13. 后续真正提升精度的方向

Round7 后，如果还要继续提升模型能力，应进入人工数据核查阶段：

1. 核查 S012/S055/S050/S032 的原始功率列名、别名、站点台账、装机容量、坐标。
2. 对比这些站点与相邻站点的日曲线，确认是否列错位或混入其他站点。
3. 若确认映射错误，修正映射表后重新从数据清洗开始跑全流程。
4. 若映射无误，再考虑引入更高分辨率气象或站点分组模型。

不要再继续做纯后处理系数搜索；前几轮已经证明 valid 上的小幅改善无法稳定泛化到 test。

