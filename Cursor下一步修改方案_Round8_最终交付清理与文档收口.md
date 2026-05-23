# Cursor 下一步修改方案 Round8：最终交付清理与文档收口

## 0. 当前状态

Round7 已经完成了主要工程闭环：

1. final 指标来源已经统一到 `distributed_predictions_final_eval.pkl`。
2. 10-14 点最终 NRMSE 已稳定为：
   - h10 = 13.29%
   - h11 = 14.68%
   - h12 = 15.36%
   - h13 = 15.31%
   - h14 = 13.51%
3. 18/18 项 end-to-end 检查通过。
4. 任务书对照文件已生成。
5. 大部分无效候选文件已经归档到 `archive_round7/`。

但还剩下几个交付层面的混淆点：

| 问题 | 当前表现 | Round8 处理 |
|---|---|---|
| 残留 Round6 诊断候选文件 | `round6_stable_bias_*` 仍在 metrics 主目录 | 归档到 `archive_round7/metrics` 或 `archive_round8/metrics` |
| 旧周二对比文档残留 | `docs/当前结果_vs_周二基准对比.md` 仍在 docs | 归档，避免交付误读 |
| 最终摘要里仍有 Round5 选择性修正参数 | 容易误以为 Round5 被 final 使用 | 移到历史诊断小节或删除 |
| 任务书对照文案未同步 | “需 archive 过期产物”仍写在遗留问题 | 改成“已完成归档，后续整理交付包” |
| 缺少最终交付清单 | 不知道哪些文件是正式交付，哪些是历史诊断 | 生成 `最终交付文件清单_Round8.md/csv` |

Round8 不再改模型、不再改 final pkl，只做最终交付清理。

---

## 1. 本轮目标

### 1.1 必须完成

1. 归档残留历史诊断文件。
2. 修正 `当前最终结果摘要.md` 中容易误导的历史段落。
3. 修正 `任务书完成情况_Round7.md/csv` 中过期文案。
4. 生成最终交付文件清单。
5. 再次运行 final metrics 一致性检查和 end-to-end 检查。

### 1.2 严禁操作

1. 不要修改 `distributed_predictions_final_eval.pkl`。
2. 不要修改 `distributed_predictions_final_full.pkl`。
3. 不要重新训练模型。
4. 不要删除文件，统一移动到 archive。
5. 不要把 Round5/Round6 历史候选写成最终有效版本。

---

## 2. 修改一：扩展 archive 脚本，归档 Round6 残留文件

打开：

```text
scripts/archive_stale_outputs_round7.py
```

将 `STALE_PATTERNS` 扩展为：

```python
STALE_PATTERNS = [
    "midday_residual_specialist",
    "midday_selective_site_correction",
    "distributed_predictions_midday_residual_specialist",
    "distributed_predictions_midday_selective_site_corrected",
    "distributed_predictions_round6_stable_bias",
    "round6_stable_bias_test_hourly_nrmse",
    "round6_stable_bias_correction_params",
    "round6_stable_bias_valid_ablation",
    "midday_nrmse_acceptance",
    "当前结果_vs_周二基准",
]
```

把 `KEEP_PATTERNS` 保持为：

```python
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
    "任务书完成情况",
    "最终交付文件清单",
]
```

并让脚本同时扫描 docs 目录：

```python
DOCS = OUT / "docs"

for base in [METRICS, TABLES, DOCS]:
    ...
```

如果当前脚本只处理 `METRICS, TABLES`，请改成处理 `METRICS, TABLES, DOCS`。

归档目录继续使用：

```text
output/pv_pipeline/archive_round7/
```

或者新建：

```text
output/pv_pipeline/archive_round8/
```

建议继续使用 `archive_round7/`，减少交付目录层级。

---

## 3. 修改二：新增最终摘要清理脚本

新建：

```text
scripts/clean_final_summary_round8.py
```

作用：

1. 清理 `当前最终结果摘要.md` 中的 Round5 选择性修正参数段落。
2. 保留 Round7 工程闭环段落。
3. 明确最终有效版本：
   - h10-h14：`MiddaySiteCalibrated`
   - h7-h9/h15-h16：`BlendTotal_a10`
   - h6/h17-h19：`V1`
4. 明确 Round5/Round6 是历史诊断，不参与 final。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC = PROJECT_ROOT / "output" / "pv_pipeline" / "docs" / "当前最终结果摘要.md"


def main():
    if not DOC.exists():
        raise FileNotFoundError(DOC)

    text = DOC.read_text(encoding="utf-8")

    # 删除 Round5 选择性修正参数段落，避免误解为 final 生效版本。
    text = re.sub(
        r"\n## 选择性站点修正参数（Round5，共 225 个站点小时对）\n\n"
        r"- k 范围:.*?\n"
        r"- k 均值:.*?\n"
        r"- alpha 分布:.*?\n",
        "\n",
        text,
        flags=re.S,
    )

    history_note = """
## 历史候选说明

Round5 的 `MiddaySiteSelectiveCorrected` 和 Round6 的 `Round6StableBias` 均属于历史诊断候选：

- Round5 选择性站点修正在 valid 上改善，但 test 上变差，未进入 final。
- Round6 稳定偏差修正在 valid 上改善，但 test 上轻微变差，已被安全阈值拦截。
- 当前 final 未采用上述两个历史候选。

最终生效版本以 `metrics/final_version_selection_by_hour.csv` 为准。
"""

    if "## 历史候选说明" not in text:
        if "## Round7 工程闭环" in text:
            text = text.replace("## Round7 工程闭环", history_note + "\n## Round7 工程闭环")
        else:
            text += "\n" + history_note

    # 统一最终来源声明
    source_line = "> **本报告所有最终预测指标均来自 `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl`。**"
    if source_line not in text:
        text += "\n\n" + source_line + "\n"

    DOC.write_text(text, encoding="utf-8")
    print(f"已清理最终摘要: {DOC}")


if __name__ == "__main__":
    main()
```

---

## 4. 修改三：修正任务书对照文案

新建：

```text
scripts/update_taskbook_compliance_round8.py
```

作用：

1. 更新 `round7_taskbook_compliance.csv` 中过期遗留问题。
2. 重新生成 `任务书完成情况_Round7.md`。
3. 将“需 archive 过期产物”改为“已归档，后续只需整理最终交付包”。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"

CSV = METRICS / "round7_taskbook_compliance.csv"
MD = DOCS / "任务书完成情况_Round7.md"


def main():
    if not CSV.exists():
        raise FileNotFoundError(CSV)

    df = pd.read_csv(CSV)

    replacements = {
        "需清理过期候选结果，避免交付混乱": "Round7/Round8 已归档过期候选结果，正式交付保留 final 与诊断文件",
        "需归档过期产物，输出最终交付清单": "过期产物已归档，Round8 输出最终交付清单",
        "需 archive 过期产物，输出最终交付清单": "过期产物已归档，Round8 输出最终交付清单",
    }

    def repl(x):
        if not isinstance(x, str):
            return x
        for old, new in replacements.items():
            x = x.replace(old, new)
        return x

    df["遗留问题"] = df["遗留问题"].apply(repl)
    df.to_csv(CSV, index=False, encoding="utf-8-sig")

    lines = ["# 任务书完成情况 Round7", ""]
    lines.append("> 本文件由 Round8 更新，反映归档和最终交付清理后的状态。")
    lines.append("")
    lines.append("| 任务书要求方向 | 当前证据 | 关键文件 | 完成状态 | 遗留问题 |")
    lines.append("|---|---|---|---|---|")
    for _, r in df.iterrows():
        lines.append(
            f"| {r['任务书要求方向']} | {r['当前证据']} | `{r['关键文件']}` | {r['完成状态']} | {r['遗留问题']} |"
        )
    lines.append("")
    lines.append("## 总体判断")
    lines.append("")
    lines.append("当前项目在既有数据集上的模型能力评估、分布式功率预测、逐小时 NRMSE 诊断、站点级与城市级输出方面基本满足任务书实现要求。")
    lines.append("Round8 已完成最终交付清理：核心 final 文件保留，历史无效候选已归档。")
    lines.append("主要未闭环问题仍是少数高误差站点的数据映射/别名字典/功率列来源需要人工核查。")
    lines.append("")

    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"已更新: {CSV}")
    print(f"已更新: {MD}")


if __name__ == "__main__":
    main()
```

---

## 5. 修改四：新增最终交付清单生成脚本

新建：

```text
scripts/generate_final_delivery_manifest_round8.py
```

作用：

1. 输出正式交付清单。
2. 明确哪些文件是“正式交付”、哪些是“诊断保留”、哪些是“归档历史”。
3. 防止交付时把 archive 文件当 final。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
DOCS = OUT / "docs"

DELIVERY_CSV = DOCS / "最终交付文件清单_Round8.csv"
DELIVERY_MD = DOCS / "最终交付文件清单_Round8.md"


def size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1024 / 1024, 3) if path.exists() else 0.0


def row(category, path, purpose, required=True):
    p = PROJECT_ROOT / path
    return {
        "类别": category,
        "文件": path,
        "用途": purpose,
        "是否必须": "是" if required else "否",
        "是否存在": "是" if p.exists() else "否",
        "大小MB": size_mb(p) if p.exists() else 0,
    }


def main():
    rows = [
        row("正式交付-预测表", "output/pv_pipeline/tables/distributed_predictions_final_eval.pkl", "最终测试集评估表，所有最终指标唯一来源"),
        row("正式交付-预测表", "output/pv_pipeline/tables/distributed_predictions_final_full.pkl", "最终全量预测表，包含 train/valid/test/future"),
        row("正式交付-安全基准", "output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_eval.pkl", "10-14 点安全基准 eval"),
        row("正式交付-安全基准", "output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_full.pkl", "10-14 点安全基准 full"),
        row("正式交付-指标", "output/pv_pipeline/metrics/round7_final_overall_metrics.csv", "最终整体指标"),
        row("正式交付-指标", "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv", "6-19 点逐小时站点/城市 NRMSE"),
        row("正式交付-指标", "output/pv_pipeline/metrics/final_version_selection_by_hour.csv", "逐小时最终版本选择表"),
        row("正式交付-指标", "output/pv_pipeline/metrics/round7_final_metrics_manifest.csv", "final metrics 来源与 hash 清单"),
        row("正式交付-报告", "output/pv_pipeline/docs/当前最终结果摘要.md", "最终结果摘要"),
        row("正式交付-报告", "output/pv_pipeline/docs/任务书完成情况_Round7.md", "任务书对照验收"),
        row("正式交付-报告", "output/pv_pipeline/docs/最终交付文件清单_Round8.md", "最终交付文件说明", required=False),
        row("诊断保留", "output/pv_pipeline/metrics/round6_watch_site_diagnosis.csv", "高误差重点站点诊断"),
        row("诊断保留", "output/pv_pipeline/metrics/round6_site_capacity_mapping_diagnosis.csv", "容量/映射诊断"),
        row("诊断保留", "output/pv_pipeline/metrics/round6_midday_bias_stability_summary.csv", "正午偏差稳定性诊断"),
        row("诊断保留", "output/pv_pipeline/metrics/round6_stable_extreme_bias_candidates.csv", "稳定极端偏差候选，仅诊断"),
        row("流程验收", "output/pv_pipeline/metrics/round7_end_to_end_deliverables_check.csv", "端到端交付物检查"),
        row("流程验收", "output/pv_pipeline/metrics/round7_taskbook_compliance.csv", "任务书对照 CSV"),
    ]

    df = pd.DataFrame(rows)
    df.to_csv(DELIVERY_CSV, index=False, encoding="utf-8-sig")

    lines = ["# 最终交付文件清单 Round8", ""]
    lines.append("> 本清单用于区分正式交付文件、诊断保留文件和历史归档文件。")
    lines.append("")
    lines.append("| 类别 | 文件 | 用途 | 是否必须 | 是否存在 | 大小MB |")
    lines.append("|---|---|---|---|---|---:|")
    for _, r in df.iterrows():
        lines.append(
            f"| {r['类别']} | `{r['文件']}` | {r['用途']} | {r['是否必须']} | {r['是否存在']} | {r['大小MB']} |"
        )

    lines.append("")
    lines.append("## 交付说明")
    lines.append("")
    lines.append("1. 正式指标以 `distributed_predictions_final_eval.pkl` 为唯一来源。")
    lines.append("2. `archive_round7/` 中的文件仅用于历史追溯，不作为最终结果。")
    lines.append("3. Round5/Round6 的历史候选未进入 final，不应在正式汇报中作为有效模型结果。")
    lines.append("4. 后续提升精度应优先核查 S012/S055/S050/S032 的功率列映射和别名字典。")
    lines.append("")

    DELIVERY_MD.write_text("\n".join(lines), encoding="utf-8")

    missing = df[(df["是否必须"] == "是") & (df["是否存在"] != "是")]
    if not missing.empty:
        print(missing.to_string(index=False))
        raise SystemExit("[FAIL] 存在必须交付文件缺失")

    print(f"已生成: {DELIVERY_CSV}")
    print(f"已生成: {DELIVERY_MD}")


if __name__ == "__main__":
    main()
```

---

## 6. 修改五：新增 Round8 最终检查脚本

新建：

```text
scripts/check_round8_final_package.py
```

作用：

1. 检查 final 指标一致。
2. 检查非 archive 目录是否还残留无效候选文件。
3. 检查最终摘要是否没有 Round5 参数段落。
4. 检查最终交付清单存在。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
DOCS = OUT / "docs"

BAD_PATTERNS = [
    "midday_residual_specialist",
    "midday_selective_site_correction",
    "distributed_predictions_midday_residual_specialist",
    "distributed_predictions_midday_selective_site_corrected",
    "distributed_predictions_round6_stable_bias",
    "round6_stable_bias_test_hourly_nrmse",
    "round6_stable_bias_correction_params",
    "round6_stable_bias_valid_ablation",
    "当前结果_vs_周二基准",
    "midday_nrmse_acceptance",
]


def main():
    errors = []

    # 1. 非 archive 区域不应残留无效候选文件
    for base in [METRICS, TABLES, DOCS]:
        if not base.exists():
            continue
        for path in base.iterdir():
            if not path.is_file():
                continue
            if any(p in path.name for p in BAD_PATTERNS):
                errors.append(f"非 archive 目录仍残留过期文件: {path.relative_to(PROJECT_ROOT)}")

    # 2. 最终摘要不应再有 Round5 参数段落
    summary = DOCS / "当前最终结果摘要.md"
    if not summary.exists():
        errors.append("缺少 当前最终结果摘要.md")
    else:
        text = summary.read_text(encoding="utf-8")
        if "选择性站点修正参数（Round5" in text:
            errors.append("当前最终结果摘要.md 仍包含 Round5 选择性修正参数段落")
        if "本报告所有最终预测指标均来自" not in text:
            errors.append("当前最终结果摘要.md 缺少 final_eval 来源声明")

    # 3. 最终交付清单
    if not (DOCS / "最终交付文件清单_Round8.md").exists():
        errors.append("缺少 最终交付文件清单_Round8.md")
    if not (DOCS / "最终交付文件清单_Round8.csv").exists():
        errors.append("缺少 最终交付文件清单_Round8.csv")

    # 4. 核心 final 文件必须存在
    required = [
        TABLES / "distributed_predictions_final_eval.pkl",
        TABLES / "distributed_predictions_final_full.pkl",
        METRICS / "round7_final_overall_metrics.csv",
        METRICS / "分布式光伏预测_逐小时平均NRMSE.csv",
        METRICS / "final_version_selection_by_hour.csv",
        DOCS / "任务书完成情况_Round7.md",
    ]
    for p in required:
        if not p.exists():
            errors.append(f"缺少核心文件: {p.relative_to(PROJECT_ROOT)}")

    if errors:
        print("[FAIL] Round8 final package check failed:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print("[OK] Round8 final package check passed.")


if __name__ == "__main__":
    main()
```

---

## 7. 修改六：更新 train_fixed.py

打开：

```text
scripts/train_fixed.py
```

将 Round8 脚本加入末尾，但不要默认自动归档，建议归档手动执行。

建议在 `FIX_SCRIPTS` 末尾加入：

```python
"regenerate_final_metrics_round7.py",
"assert_final_metrics_consistency_round7.py",
"check_end_to_end_deliverables_round7.py",
"generate_taskbook_compliance_round7.py",
"clean_final_summary_round8.py",
"update_taskbook_compliance_round8.py",
"generate_final_delivery_manifest_round8.py",
"check_round8_final_package.py",
```

`archive_stale_outputs_round7.py` 不建议放进自动训练流程，避免训练过程中误移动诊断文件。归档应作为交付前手动步骤。

---

## 8. Cursor 执行顺序

在项目根目录执行：

```bash
python scripts/regenerate_final_metrics_round7.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/check_end_to_end_deliverables_round7.py
python scripts/archive_stale_outputs_round7.py
python scripts/clean_final_summary_round8.py
python scripts/update_taskbook_compliance_round8.py
python scripts/generate_final_delivery_manifest_round8.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/check_end_to_end_deliverables_round7.py
python scripts/check_round8_final_package.py
```

执行后确认：

```text
output/pv_pipeline/docs/最终交付文件清单_Round8.md
output/pv_pipeline/docs/最终交付文件清单_Round8.csv
```

已经生成。

---

## 9. Round8 验收标准

### 9.1 final 指标不变

Round8 不改模型，最终指标必须保持：

| 指标 | 值 |
|---|---:|
| final_eval 行数 | 68,888 |
| 站点数 | 53 |
| pred_actual_ratio | 0.9859 |
| MAE | 0.5893 MW |
| RMSE | 1.2047 MW |

10-14 点：

| 小时 | NRMSE |
|---:|---:|
| 10 | 13.29% |
| 11 | 14.68% |
| 12 | 15.36% |
| 13 | 15.31% |
| 14 | 13.51% |

### 9.2 非 archive 目录无过期候选

以下模式不应出现在主目录：

```text
midday_residual_specialist
midday_selective_site_correction
round6_stable_bias_test_hourly_nrmse
round6_stable_bias_correction_params
round6_stable_bias_valid_ablation
当前结果_vs_周二基准
midday_nrmse_acceptance
```

如果需要保留，只能在：

```text
output/pv_pipeline/archive_round7/
```

### 9.3 最终摘要无误导段落

`当前最终结果摘要.md` 中不应出现：

```text
选择性站点修正参数（Round5，共 225 个站点小时对）
```

应该出现：

```text
历史候选说明
本报告所有最终预测指标均来自 distributed_predictions_final_eval.pkl
```

### 9.4 任务书对照更新

`任务书完成情况_Round7.md` 中不应再写：

```text
需 archive 过期产物
需清理过期候选结果
```

应该写：

```text
过期产物已归档
Round8 输出最终交付清单
```

### 9.5 交付清单完整

必须生成：

```text
output/pv_pipeline/docs/最终交付文件清单_Round8.md
output/pv_pipeline/docs/最终交付文件清单_Round8.csv
```

---

## 10. Round8 完成后的交付判断

Round8 完成后，可以给出如下结论：

```text
Round8 未修改模型结果，仅完成最终交付清理。

1. final 指标保持不变；
2. 过期候选和历史对比文件已全部归档；
3. 当前最终结果摘要不再包含误导性的 Round5 参数段落；
4. 任务书完成情况文案已同步归档状态；
5. 已生成最终交付文件清单；
6. 当前项目可作为“既有数据集上的分布式光伏预测模型能力评估与工程化结果包”提交。
```

---

## 11. 后续真正提升模型的方向

Round8 之后，不建议继续做自动后处理。真正提升模型效果，需要人工核查：

1. S012/S055/S050/S032 的原始功率列名和别名字典。
2. 这些站点是否与其他站点功率列互换、重复或错位。
3. 这些站点的坐标、装机容量、台账名称是否与功率列一致。
4. 修正映射后从数据清洗阶段重新跑全流程。

