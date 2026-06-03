# Round53 口径修正与 Manifest 自动化验证报告

**生成时间**：2026-05-31 16:05 (UTC+8)
**执行人**：Cursor AI

---

## 1. 本轮修改目标

Round52 遗留以下口径问题，本轮全部解决：

1. `bias < 0` 文字描述为"预测偏高"（应为"预测偏低"）
2. manifest.json 验证为 WARN（应自动 PASS）
3. canonical 正式文件从 round36/round46 同步，而非直接输出
4. 69 站 / 68 站差异未说明
5. S115/S116 预测全 0 的根因未澄清

---

## 2. BIAS 口径修正

**统一 BIAS 定义**：`BIAS = mean(power_pred_final − power_mw)`（单位 MW）

**解释**：
- BIAS > 0：预测偏高（高估）
- BIAS < 0：预测偏低（低估）

**验证**：

| station_id | 预测均值(MW) | 实际均值(MW) | BIAS(MW) | 方向 |
|-----------|------------|-----------|---------|------|
| S062（最佳站点） | 0.5861 | 0.5243 | **+0.0618** | 预测偏高 ✅ |
| S115 | 0.0000 | 1.5252 | **-1.5252** | 预测偏低（严重低估）✅ |
| S116 | 0.0000 | 4.8803 | **-4.8803** | 预测偏低（严重低估）✅ |

### S115/S116 预测全 0 根因

经排查，S115/S116 的 `scene_v151` 在全部时间段均为 "night"（白天场景），导致所有预测列为 0。

**根因链**：
1. S115/S116 的 `has_geo=0`（地理信息缺失）
2. 无辐照数据（`clear_sky_ghi=0`，`g_blend_pred=0`）
3. `solar_elevation_deg` 不可用，`_scene_v151()` 逻辑 fallback 到 `elev=0`，触发 `elev <= 0 → 'night'` 分支
4. 所有行被判定为夜间 → 模型输出全 0

**结论**：这是数据接入问题（辐照数据缺失），不是模型参数问题。应修复辐照数据接入解决，而非盲目调模型。

---

## 3. Manifest 自动生成验证

| 检查项 | 结果 |
|--------|------|
| manifest.json 由 `run_full_pipeline.py` 自动生成 | ✅ |
| `pipeline_entry == scripts/run_full_pipeline.py` | ✅ |
| `final_prediction_column == power_pred_final` | ✅ |
| artifacts 全部存在（6 个文件） | ✅ |
| manifest mtime 晚于 canonical full pkl | ✅ 1.45h |

---

## 4. Canonical 文件源头收口

| 文件 | 源脚本直接写入 | 状态 |
|------|--------------|------|
| `predictions/distributed_predictions_final_full.pkl` | `build_round36_predictions.py` | ✅ |
| `predictions/distributed_predictions_final_eval.pkl` | `build_round36_predictions.py` | ✅ |
| `metrics/hourly_nrmse_consistent.csv` | `round46_recompute_hourly_nrmse_consistent.py` | ✅ |
| `metrics/site_metrics_consistent.csv` | `compute_round36_metrics.py` | ✅ |

**兼容路径**（round36/round46）从 canonical 同步，仅用于兼容历史脚本，不再作为正式输入。

**评估脚本读取优先级**：
1. canonical 路径（`predictions/`, `metrics/`）
2. fallback 到 legacy 路径（`tables/`, `round36/round46`）

---

## 5. 69 站 / 68 站差异说明

**差异**：final_full = 69 站，final_eval/dashboard = 68 站，差 1 站。

**原因**：S001（智邦纺织光伏电站）有 full_rows = 2005，但 test 6-19 点评估记录为 0 行，被排除在 eval 之外。

| station_id | station_name | capacity_mw | reason | full_rows | test_6_19_rows |
|-----------|------------|------------|--------|-----------|----------------|
| S001 | 智邦纺织光伏电站 | 5.99 | 无有效 test 6-19 点评估记录 | 2005 | 0 |

**说明**：final_full 保留全量站点和全量时间行；final_eval/dashboard 仅保留参与测试集 6-19 点评估且有有效记录的站点。

已输出：`output/pv_pipeline/validation/excluded_from_eval_sites.csv`

---

## 6. S116 低置信度坐标说明

| 字段 | 值 |
|------|-----|
| station_id | S116 |
| station_name | 林洋伊山光伏电站 |
| latitude | 34.2983 |
| longitude | 119.2318 |
| geo_source | manual_wiki_town_center（维基百科伊山镇政府坐标） |
| confidence | **low** |
| note | 仅用于避免空间特征缺失；精确光伏场区中心有待甲方/运维台账确认 |

S116 坐标为镇级近似，不是光伏场区中心坐标。

**已在以下位置说明**：
- `configs/manual_station_geo_overrides.csv` 的 `note` 字段
- `manifest.json` 的 `geo_overrides.low_confidence_sites`
- `posttrain_validation.py` 的 GEO4 WARN
- 本报告

---

## 7. posttrain_validation 结果

**29 项检查 | 27 PASS | 0 FAIL | 2 WARN**

| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| C1 | ✅ | 最终预测 pkl 存在且可读 | canonical, 1,172,180 行 |
| C2 | ✅ | eval pkl 数据范围正确 | canonical, test 6-19h, 116,144 行 |
| C3 | ✅ | 最终预测列存在 | power_pred_final: 100% |
| C4 | ✅ | 真实功率列存在 | power_mw: 100% |
| C5 | ✅ | split 口径正确 | test=199,104 行 |
| C6 | ✅ | 测试集时间切分正确 | 2025-09-01~2025-12-31 |
| C7 | ✅ | 使用正式预测列 | power_pred_final 就绪 |
| C8 | ✅ | 测试集有预测结果 | 199,104 行 |
| C9 | ⚠ WARN | 夜间/future 不参与评估 | 设计如此 |
| C10 | ✅ | hourly_nrmse_consistent.csv 正确 | 14 小时 |
| C11 | ✅ | dashboard 一致性校验 | 68 站全部 PASS |
| C12 | ✅ | dashboard 数据新鲜 | 晚于 final pkl 0.04h |
| C13 | ✅ | Git 不追踪 pkl | 0 个 |
| C14 | ✅ | 训练集样本量 | 421,771 行 |
| C15 | ✅ | 站点数量合理 | 69 个站点 |
| C16 | ✅ | manifest.pipeline_entry | scripts/run_full_pipeline.py |
| C16 | ✅ | manifest.final_prediction_column | power_pred_final |
| C16 | ✅ | manifest artifacts 全部存在 | 6 个文件 |
| C16 | ✅ | manifest 生成时间 | 晚于 canonical pkl 1.45h |
| GEO1 | ✅ | S115/S116 经纬度覆盖 | 34.5933/119.2172, 34.2983/119.2318 |
| GEO2 | ✅ | 坐标在连云港范围内 | 均在 [33.9-35.2N, 118.4-119.9E] |
| GEO3 | ✅ | 置信度非空 | S115=medium, S116=low |
| GEO4 | ⚠ WARN | S116 低置信度 | 精确场区坐标有待甲方确认 |
| C17 | ✅ | 站点数量一致性 | full=69, eval=68，相差1站 |
| BIAS | ✅ | BIAS 口径说明 | BIAS < 0 = 预测偏低 |

---

## 8. Dashboard 校验结果

- **68/68 PASS**，0 FAIL
- max pred 误差: 0.00e+00（容差 1e-09）
- max actual 误差: 0.00e+00

---

## 9. 验收标准

| 标准 | 结果 |
|------|------|
| ✅ BIAS 公式和解释全项目统一 | `bias_MW = mean(pred - actual)` |
| ✅ bias < 0 不再被写成预测偏高 | 统一为"预测偏低" |
| ✅ manifest.json 由 run_full_pipeline.py 自动生成 | `pipeline_entry` 字段已写入 |
| ✅ posttrain_validation 中 manifest 检查为 PASS | C16 全项 PASS |
| ✅ 正式评估和可视化读取 canonical 文件 | C1/C2 显示 "canonical" |
| ✅ 历史 round 文件不再作为正式输入 | 评估脚本优先读 canonical |
| ✅ 69/68 站差异有 excluded_from_eval_sites.csv | S001 被排除 |
| ✅ S116 low confidence 在 manifest/report/metadata 中均有说明 | GEO4 WARN + manifest + CSV note |
| ✅ posttrain_validation 无 FAIL | 27 PASS / 0 FAIL |
| ✅ dashboard check 无 FAIL | 68/68 PASS |

---

## 10. 当前仍需注意的问题

1. **S115/S116 辐照数据缺失**：scene_v151 全为 night，导致预测全 0。应修复辐照数据接入（`has_geo=0` → `has_geo=1`）以恢复正常的场景判断和预测。
2. **S001 无测试期数据**：全 2005 行均在夜间（6-19 点无记录），被排除在 eval 之外，建议确认是否接入正确。
3. **S116 坐标需实地确认**：置信度 low，光伏场区中心有待运维台账确认，不应用于精确气象分析。
