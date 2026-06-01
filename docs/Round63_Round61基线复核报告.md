# Round63_Round61基线复核报告

## 复核结果

| 项目 | 内容 | 状态 |
|------|------|:----:|
| 当前分支 | `experiment/model-structure-round62` | ✓ |
| 当前 commit | `7a08990f` | ✓ |
| Round61 tag | `round61-stable-20260601` | ✓ |
| Tag commit | `50128e2a` | ✓ |
| manifest.json | `round61_baseline_manifest.json` | ✓ |
| manifest.csv | `round61_baseline_files.csv` | ✓ |
| 基线说明 | `docs/Round61_稳定基线说明.md` | ✗ |

## SHA256 完整性

| 状态 | 数量 |
|:----:|-----:|
| PASS | 19 |
| FAIL | 2 |

## 失败项

> 发现 2 个问题：

- 关键文件缺失: docs/Round61_稳定基线说明.md
- 文件不存在: docs/Round61_城市总量校准与站点稳定性保护报告.md

## 详细 SHA256

详细 SHA256 对比见: `output/pv_pipeline/baselines/round61/round61_baseline_verify_report.csv`

## 结论

**FAIL - 需要修复后继续**
