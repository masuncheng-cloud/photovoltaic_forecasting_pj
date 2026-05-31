# Cursor 执行方案 Round54：经纬度特征链路修复与全训练链路审计

## 目标

Round53 已经完成 BIAS、manifest、canonical 路径等工程口径修正，但暴露出一个更关键的问题：

```text
S115/S116 虽然在 GEO 检查中显示经纬度已补齐，
但最终预测表中仍然 has_geo=0、clear_sky_ghi=0、g_blend_pred=0、scene_v151=night，
导致白天预测全为 0。
```

这说明人工经纬度覆盖没有真正进入训练预测特征链路。

本轮目标：

1. 追踪并修复 `manual_station_geo_overrides.csv` 到最终预测特征表的传递链路。
2. 确保 S115/S116 在训练、评估、可视化中都有有效经纬度和白天太阳/辐照特征。
3. 重新完整训练，验证修改是否生效。
4. 对整个训练链路做一次结构化审计，输出后续模型和流程改进依据。
5. 禁止关键环节静默 fallback 到旧 round 文件。

---

## 一、先做链路定位，不要直接重训

进入项目目录：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
```

创建诊断脚本：

```text
scripts/diagnose_geo_feature_flow.py
```

该脚本检查 S115/S116 在以下文件中的经纬度、has_geo、辐照、场景字段是否一致：

```text
configs/manual_station_geo_overrides.csv
output/pv_pipeline/**/station*.pkl
output/pv_pipeline/**/site*.pkl
output/pv_pipeline/**/train*.pkl
output/pv_pipeline/**/distributed_predictions*.pkl
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
```

脚本内容参考：

```python
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(".")
TARGETS = {"S115", "S116"}
OUT = ROOT / "output/pv_pipeline/validation/round54_geo_feature_flow.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

rows = []

def inspect_df(path, df):
    if "station_id" not in df.columns:
        return
    hit = df[df["station_id"].astype(str).isin(TARGETS)].copy()
    if hit.empty:
        return
    for sid, sdf in hit.groupby(hit["station_id"].astype(str)):
        row = {
            "file": str(path),
            "station_id": sid,
            "rows": len(sdf),
        }
        for col in [
            "station_name", "capacity_mw",
            "latitude", "longitude", "lat", "lon",
            "has_geo", "geo_source", "geo_confidence",
            "clear_sky_ghi", "clearsky_ghi", "g_blend_pred",
            "solar_elevation_deg", "solar_altitude_deg",
            "scene_v151", "split",
            "power_mw", "power_pred_final"
        ]:
            if col in sdf.columns:
                s = sdf[col]
                if s.dtype == object:
                    vals = s.dropna().astype(str).unique()[:8]
                    row[col] = "|".join(vals)
                else:
                    row[f"{col}_non_null"] = int(s.notna().sum())
                    row[f"{col}_mean"] = float(pd.to_numeric(s, errors="coerce").mean()) if s.notna().any() else np.nan
                    row[f"{col}_min"] = float(pd.to_numeric(s, errors="coerce").min()) if s.notna().any() else np.nan
                    row[f"{col}_max"] = float(pd.to_numeric(s, errors="coerce").max()) if s.notna().any() else np.nan
        if "scene_v151" in sdf.columns:
            vc = sdf["scene_v151"].astype(str).value_counts().head(10).to_dict()
            row["scene_v151_counts"] = str(vc)
        if "timestamp" in sdf.columns:
            ts = pd.to_datetime(sdf["timestamp"], errors="coerce")
            row["time_min"] = str(ts.min())
            row["time_max"] = str(ts.max())
        rows.append(row)

for path in ROOT.rglob("*.csv"):
    if "archive" in path.parts:
        continue
    if any(key in path.name.lower() for key in ["station", "site", "geo", "metric"]):
        try:
            inspect_df(path, pd.read_csv(path))
        except Exception:
            pass

for path in ROOT.rglob("*.pkl"):
    if "archive" in path.parts:
        continue
    try:
        inspect_df(path, pd.read_pickle(path))
    except Exception:
        pass

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"[OK] written {OUT}, rows={len(out)}")
print(out[["file", "station_id", "rows"]].to_string(index=False) if len(out) else "no rows")
```

执行：

```bash
python scripts/diagnose_geo_feature_flow.py
```

查看：

```bash
python - <<'PY'
import pandas as pd
df = pd.read_csv("output/pv_pipeline/validation/round54_geo_feature_flow.csv")
cols = [c for c in [
    "file", "station_id", "rows",
    "latitude_mean", "longitude_mean", "lat_mean", "lon_mean",
    "has_geo_mean",
    "clear_sky_ghi_mean", "clear_sky_ghi_max",
    "g_blend_pred_mean", "g_blend_pred_max",
    "solar_elevation_deg_mean", "solar_elevation_deg_max",
    "scene_v151_counts"
] if c in df.columns]
print(df[cols].to_string(index=False))
PY
```

判断问题断点：

- 如果 `configs/manual_station_geo_overrides.csv` 有坐标，但 station metadata 没有：覆盖脚本未接入 Stage 01。
- 如果 station metadata 有坐标，但训练表/预测表没有：中间 merge 丢字段或没有重新生成特征。
- 如果最终表有坐标但 `has_geo=0`：`has_geo` 计算逻辑没有按覆盖后坐标重算。
- 如果 `has_geo=1` 但 `clear_sky_ghi/g_blend_pred=0`：太阳/辐照特征生成没有覆盖 S115/S116。
- 如果辐照正常但 `scene_v151=night`：场景判断函数 `_scene_v151()` 逻辑或字段名有问题。

---

## 二、修复人工经纬度覆盖接入点

检查 `scripts/run_full_pipeline.py` 中人工覆盖位置。

要求：

```text
manual_station_geo_overrides.csv 必须在所有太阳/辐照/空间融合/气象匹配特征生成之前应用。
```

正确顺序：

```text
读取原始站点元数据
→ 标准化 station_id/station_name/capacity
→ 应用 manual_station_geo_overrides.csv
→ 重算 has_geo
→ 写出 canonical station metadata
→ 后续所有 Stage 01/02/模型脚本读取该 canonical station metadata
```

新增正式站点元数据路径：

```text
output/pv_pipeline/tables/station_metadata_canonical.pkl
output/pv_pipeline/tables/station_metadata_canonical.csv
```

`apply_manual_geo_overrides.py` 必须输出这两个文件。

要求代码里不要只修改某个局部 DataFrame 后丢弃。

---

## 三、重算 has_geo 与太阳/辐照特征

在站点元数据和训练/预测特征表中统一：

```python
has_geo = latitude.notna() & longitude.notna()
```

如果项目中使用 `lat/lon` 字段，也要同步：

```python
df["lat"] = df["latitude"]
df["lon"] = df["longitude"]
```

在特征生成脚本中增加断言：

```python
targets = ["S115", "S116"]
check = feature_df[feature_df["station_id"].isin(targets)]
if not check.empty:
    bad = check[
        check["timestamp"].dt.hour.between(10, 14)
        & (
            (check["has_geo"] != 1)
            | (check["solar_elevation_deg"].fillna(0) <= 0)
            | (check["clear_sky_ghi"].fillna(0) <= 0)
        )
    ]
    if len(bad) > 0:
        raise ValueError("S115/S116 geo/solar features still invalid at 10-14")
```

如果项目字段名不是 `solar_elevation_deg/clear_sky_ghi`，请用实际字段名，但最终诊断表必须输出对应字段。

---

## 四、修复 `_scene_v151()` 的 fallback 逻辑

定位函数：

```bash
grep -R "def _scene_v151\\|scene_v151\\|elev <= 0\\|night" -n scripts src stages | head -100
```

当前问题：

```text
solar_elevation_deg 不可用时 fallback 到 elev=0，直接判为 night。
```

修改原则：

1. 白天时间段不得因为缺字段直接全部判为 night。
2. 如果太阳高度角缺失，但 timestamp 在 6-19 且站点有经纬度，应先补算太阳高度角。
3. 如果无法补算，应标记为 `unknown_geo_solar` 或 `low_confidence_day`，不要静默置为 night。
4. 对 `has_geo=0` 的站点，在白天也不要直接预测全 0，应使用城市/区域 fallback 辐照或 ERA5 背景场。

建议逻辑：

```python
def _scene_v151(row):
    hour = int(row.get("hour", pd.Timestamp(row["timestamp"]).hour))
    elev = row.get("solar_elevation_deg", np.nan)
    ghi = row.get("g_blend_pred", row.get("clear_sky_ghi", np.nan))

    if pd.notna(elev):
        if elev <= 0:
            return "night"
    else:
        if hour < 6 or hour > 19:
            return "night"
        return "day_missing_solar"

    if pd.notna(ghi) and ghi <= 5 and 8 <= hour <= 16:
        return "low_ghi_day"
    if hour in [6, 7]:
        return "dawn"
    if hour in [17, 18, 19]:
        return "dusk"
    return "day"
```

同时，模型预测或后处理必须能处理：

```text
day_missing_solar
low_ghi_day
```

不能把它们直接裁剪成 0。

---

## 五、禁止 canonical 缺失时 fallback 到 legacy

Round53 仍保留：

```text
canonical 不存在时 fallback 到 legacy
```

本轮改为：

```text
正式训练、评估、dashboard 导出中 canonical 缺失必须 FAIL。
```

修改：

```text
scripts/export_interactive_dashboard_data.py
scripts/posttrain_validation.py
scripts/check_dashboard_prediction_values.py
scripts/run_full_pipeline.py
```

搜索：

```bash
grep -R "fallback\\|round36\\|round46\\|legacy" -n scripts | head -200
```

要求：

- `round36/round46/legacy` 只能出现在兼容同步函数或 archive 文件中。
- 正式读取逻辑不得 fallback。
- 如果 canonical 不存在，直接 `raise FileNotFoundError`。

---

## 六、完整重训

完成修复后执行：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round54_full_pipeline.log
```

如果失败，不要跳过，先修失败点。

检查日志：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|FileNotFound|KeyError|ValueError" \
  output/pv_pipeline/logs/round54_full_pipeline.log || true
```

---

## 七、重训后验证 S115/S116 是否生效

重新运行链路诊断：

```bash
python scripts/diagnose_geo_feature_flow.py
```

重点检查最终预测表：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

path = Path("output/pv_pipeline/predictions/distributed_predictions_final_full.pkl")
df = pd.read_pickle(path)
df["timestamp"] = pd.to_datetime(df["timestamp"])
targets = df[df["station_id"].isin(["S115", "S116"])].copy()

cols = [c for c in [
    "station_id", "station_name", "timestamp", "split",
    "latitude", "longitude", "has_geo",
    "solar_elevation_deg", "clear_sky_ghi", "g_blend_pred",
    "scene_v151", "power_mw", "power_pred_final"
] if c in targets.columns]

print("rows:", len(targets))
print("columns:", cols)

day = targets[
    targets["timestamp"].dt.hour.between(10, 14)
    & targets["split"].eq("test")
]
print("\n10-14 test summary:")
for sid, sdf in day.groupby("station_id"):
    print("\n", sid)
    for col in ["has_geo", "solar_elevation_deg", "clear_sky_ghi", "g_blend_pred", "power_pred_final"]:
        if col in sdf.columns:
            print(col, "non_null", sdf[col].notna().sum(), "min", sdf[col].min(), "mean", sdf[col].mean(), "max", sdf[col].max())
    if "scene_v151" in sdf.columns:
        print("scene counts:", sdf["scene_v151"].value_counts().to_dict())

print("\nSample rows:")
print(day[cols].head(30).to_string(index=False))
PY
```

验收：

```text
S115/S116 has_geo = 1
S115/S116 10-14 点 solar_elevation_deg > 0
S115/S116 10-14 点 clear_sky_ghi 或 g_blend_pred > 0
S115/S116 10-14 点 scene_v151 不应全为 night
S115/S116 10-14 点 power_pred_final 不应全为 0
```

---

## 八、运行训练后验证与 dashboard 校验

```bash
python scripts/posttrain_validation.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round54_posttrain_validation.log

python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round54_dashboard_check.log
```

检查：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|FileNotFound|KeyError|ValueError" \
  output/pv_pipeline/logs/round54_posttrain_validation.log \
  output/pv_pipeline/logs/round54_dashboard_check.log || true
```

要求：

- `posttrain_validation` 无 FAIL。
- dashboard check 无 FAIL。
- S116 low confidence 仍保留 WARN 可以接受。
- 不能再出现 S115/S116 `scene_v151 全 night`。

---

## 九、全训练链路审计

新增脚本：

```text
scripts/audit_training_pipeline_flow.py
```

输出：

```text
output/pv_pipeline/validation/round54_pipeline_flow_audit.csv
output/pv_pipeline/validation/round54_pipeline_flow_audit.md
```

审计内容：

### 1. 数据入口审计

检查：

```text
原始功率文件
站点元数据文件
气象/ERA5 文件
集中式站点文件
分布式站点文件
manual geo override 文件
```

输出：

```text
file_path
exists
rows
columns
min_time
max_time
station_count
```

### 2. 时间切分审计

输出 train/valid/test：

```text
split
row_count
station_count
min_time
max_time
positive_power_rows
zero_ratio_6_19
```

### 3. 特征完整性审计

按站点统计：

```text
station_id
station_name
has_geo_ratio
solar_feature_non_null_ratio
irradiance_non_null_ratio
g_blend_non_null_ratio
weather_feature_non_null_ratio
scene_night_ratio_6_19
```

### 4. 预测链路审计

按站点统计：

```text
station_id
actual_mean
pred_mean
pred_zero_ratio_6_19
pred_actual_ratio
bias_pct
nrmse_percent
```

### 5. 风险分层

生成字段：

```text
risk_flags
```

规则示例：

```text
missing_geo
low_confidence_geo
solar_feature_missing
all_day_scene_night
prediction_all_zero
high_bias
high_nrmse
low_positive_train_samples
high_test_zero_ratio
capacity_mapping_suspicious
```

输出最重要的风险站点前 20 个。

---

## 十、检查指标是否受影响

重训后输出：

```bash
python - <<'PY'
import pandas as pd

hourly = pd.read_csv("output/pv_pipeline/metrics/hourly_nrmse_consistent.csv")
print("\n逐小时 NRMSE:")
print(hourly.to_string(index=False))

site = pd.read_csv("output/pv_pipeline/metrics/site_metrics_consistent.csv")
print("\nS115/S116:")
print(site[site["station_id"].isin(["S115", "S116"])].to_string(index=False))

print("\nWorst 10:")
print(site.sort_values("nrmse_percent", ascending=False).head(10).to_string(index=False))
PY
```

判断：

- 如果 S115/S116 从预测全 0 变为正常预测，即使 NRMSE 未显著下降，也说明链路修复有效。
- 如果 NRMSE 变差，但预测链路变得真实，应保留真实链路，不要回退到全 0 的错误链路。
- 后续模型改进应基于真实有效特征继续做。

---

## 十一、更新可视化

`run_full_pipeline.py` 应自动导出可视化数据。

手动确认：

```bash
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
python -m http.server 8060
```

访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

检查 S115/S116：

- 单站点曲线能显示。
- 白天预测不再全 0。
- 站点信息卡片保留 S116 低置信度说明。

---

## 十二、生成 Round54 报告

新增：

```text
docs/Round54_经纬度特征链路修复与训练链路审计报告.md
```

模板：

```markdown
# Round54 经纬度特征链路修复与训练链路审计报告

## 1. 本轮目标

## 2. S115/S116 问题根因

## 3. 修改内容

## 4. 经纬度到特征链路验证

| station_id | has_geo | solar_elevation_10_14 | clear_sky_ghi_10_14 | g_blend_10_14 | scene_v151_10_14 | pred_all_zero |
|---|---:|---:|---:|---:|---|---:|

## 5. 完整重训结果

## 6. posttrain_validation 结果

## 7. dashboard 校验结果

## 8. 指标变化

## 9. 全训练链路审计结果

## 10. 后续模型与流程改进建议
```

---

## 十三、验收标准

本轮必须满足：

```text
[PASS] manual geo overrides 在特征生成前应用
[PASS] station_metadata_canonical 存在
[PASS] S115/S116 final_full 中 has_geo=1
[PASS] S115/S116 test 10-14 点太阳高度角 > 0
[PASS] S115/S116 test 10-14 点辐照特征不全为 0
[PASS] S115/S116 test 10-14 点 scene_v151 不全为 night
[PASS] S115/S116 test 10-14 点 power_pred_final 不全为 0
[PASS] canonical 缺失时不再 fallback 到 legacy
[PASS] posttrain_validation 无 FAIL
[PASS] dashboard check 无 FAIL
[PASS] 输出 round54_pipeline_flow_audit.csv/md
```

---

## 十四、注意事项

1. 不要为了让 S115/S116 指标变好而回退到错误的全 0 预测。
2. S116 坐标仍是 low confidence，修复后也要保留这个说明。
3. 如果 S115/S116 修复后 NRMSE 仍高，下一步再查容量映射、限电、遮挡、功率接入异常。
4. 本轮核心是让训练链路真实有效，不是追求单轮指标最优。

