# Round62 保存 Round61 稳定基线并准备模型结构实验报告

**日期**: 2026-06-01
**分支**: experiment/model-structure-round62

---

## 1. 本轮目标

将 Round61 固化为可回退的稳定基线，创建 Git tag 和 baseline manifest，并准备下一阶段模型结构实验设计文档。

---

## 2. Round61 验证结果

执行 `audit-only` 模式验证：

```
校验结果: 36 项 | 34 PASS | 0 FAIL | 2 WARN
```

- 34 PASS：无错误
- 0 FAIL：无失败
- 2 WARN：均为 GEO4 低置信度警告（S116 精确光伏场区中心待甲方/运维台账确认），不影响预测结果

C16 manifest hash 同步问题已在上轮修复，本次不再出现。

---

## 3. Round61 报告矛盾修正

修正了 `docs/Round61_城市总量校准与站点稳定性保护报告.md` 中的表述矛盾：

- 原：`posttrain_validation 无 FAIL` + `36项 32PASS 1FAIL 3WARN` + `C16 FAIL 为预期`
- 改为：`posttrain_validation 无真实 FAIL` + `36项 34PASS 0FAIL 2WARN（GEO4低置信度警告，不影响预测）`

---

## 4. Git 提交信息

| 项目 | 值 |
|------|---|
| 稳定分支 | `main` |
| 实验分支 | `experiment/model-structure-round62` |
| 最新 commit | `b3633b9` (Auto-sync: docs/Round62_模型结构实验设计.md) |
| Round61 稳定 commit | `50128e2` (Auto-sync: docs/Round61_稳定基线说明.md ...) |
| remote | origin (git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git) |

---

## 5. baseline 文件清单

| 文件 | 大小 | SHA256 已记录 |
|------|------|:---:|
| `distributed_predictions_final_full.pkl` | 320.5 MB | ✓ |
| `distributed_predictions_final_final_eval.pkl` | 31.7 MB | ✓ |
| `hourly_nrmse_consistent.csv` | 1.6 KB | ✓ |
| `site_metrics_consistent.csv` | 7.5 KB | ✓ |
| `manifest.json` | 3.0 KB | ✓ |
| `round61_baseline_manifest.json` | ✓ | ✓ |
| `round61_baseline_files.csv` | ✓ | ✓ |
| `round61_compare_summary.csv` | ✓ | ✓ |
| `round61_compare_hourly.csv` | ✓ | ✓ |
| `round61_compare_site.csv` | ✓ | ✓ |

完整 SHA256 列表见 `output/pv_pipeline/baselines/round61/round61_baseline_files.csv`。

---

## 6. 是否提交大型产物

**否。**

`.gitignore` 已正确忽略所有大型文件：

```
*.pkl    ← 包含两个 pkl（320MB + 32MB）
*.pth
*.npy
*.parquet
*.joblib
```

baseline 中的 pkl 仅保存在本地 `output/pv_pipeline/baselines/round61/`，不进入 Git。`round61_baseline_manifest.json` 中记录了 SHA256，用于本地完整性验证。

---

## 7. Git Tag

```
round61-stable-20260601
```

**Message**: "Round61 stable baseline before model-structure experiments"

已推送至 `origin`。

---

## 8. 实验分支

```
experiment/model-structure-round62
```

- 从 `main` 分支创建（基于 `50128e2`，即 Round61 稳定版）
- 已推送至 `origin`
- 后续所有模型结构实验在该分支进行，不直接污染 `main`

---

## 9. Round61 稳定基线说明

见 `docs/Round61_稳定基线说明.md`。

核心指标（test 6-19h）：

| 指标 | 值 |
|------|---:|
| city_nrmse_6_19 | 3.9531% |
| city_nrmse_10_14 | 6.2359% |
| site_mean_nrmse_6_19 | 11.4095% |
| bias_6_19 | +1.42% |
| bias_10_14 | +8.40% |
| 变差 > +1pp 站点数 | 0 |

预测来源：`power_pred_final` = `power_pred_round61_city_safe`

含三层后处理校准：
1. Round60 hour_scene calibrator（保守，valid 回退）
2. Round60 site calibrator（保守，valid 回退）
3. Round61 city_total calibrator（小时级，站点/小时保护）

---

## 10. 模型结构实验设计摘要

见 `docs/Round62_模型结构实验设计.md`。

三大方向：
1. **发电状态分类器**：先判断有效发电状态（active/weak/inactive），再预测功率
2. **分场景残差模型**：按 dawn/day_clear/day_cloudy/dusk 拆分训练 Ridge 残差修正
3. **站点特性增强**：加入历史 PR、zero_ratio、geo_confidence 等元特征

实验边界：
- 不使用 test 调参
- Round61 作为固定 baseline
- offline candidate 机制，不覆盖正式结果

---

## 11. 回退方式

如果后续实验导致结果恶化：

```bash
# 恢复代码到 Round61 稳定版本
git checkout round61-stable-20260601

# 恢复产物（需从备份目录手动复制）
# 产物位于: output/pv_pipeline/baselines/round61/
# 完整文件清单: output/pv_pipeline/baselines/round61/round61_baseline_files.csv
```

---

## 12. 验收标准

| 标准 | 结果 |
|------|------|
| [PASS] Round61 audit-only 无真实 FAIL | ✓ 36项 34PASS 0FAIL 2WARN |
| [PASS] Round61 报告矛盾已修正 | ✓ |
| [PASS] round61_baseline_manifest.json 已生成 | ✓ |
| [PASS] round61_baseline_files.csv 已生成 | ✓ |
| [PASS] 未提交大型 pkl/parquet/joblib/npy 文件 | ✓ .gitignore 正确 |
| [PASS] Git commit 已完成 | ✓ auto-sync 机制 |
| [PASS] Git tag round61-stable-20260601 已推送 | ✓ |
| [PASS] experiment/model-structure-round62 分支已创建 | ✓ |
| [PASS] Round62 模型结构实验设计文档已提交 | ✓ |
| [PASS] 回退方式明确 | ✓ |

---

## 13. 后续建议

1. **切换到实验分支**：后续所有模型结构实验在 `experiment/model-structure-round62` 进行
2. **Round63 目标**：实现 offline 分场景残差 candidate，不覆盖 Round61 正式结果
3. **重点小时改善**：7点低估和17点低估是当前最可改善的误差模式
4. **保持回退意识**：任何实验必须满足安全约束，否则自动保留 Round61
