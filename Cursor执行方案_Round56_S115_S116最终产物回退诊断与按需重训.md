# Cursor 执行方案 Round56：S115/S116 最终产物回退诊断与按需重训

## 目标

Round55 报告中出现异常：

```text
中间文件 distributed_predictions_v159.pkl 中 S115/S116 scene_v151 有效；
但 final_full 中 S115/S116 scene_v151 = all night。
```

这说明问题可能不是模型训练本身，而是：

1. 后处理/校准阶段覆盖了预测结果；
2. canonical 文件同步时读到了旧文件；
3. dashboard 导出读错路径；
4. cache/legacy fallback 导致 final 文件回退；
5. 或 v159 实际也已异常，只是诊断口径不一致。

本轮先诊断，不要直接完整重训。根据诊断结果决定执行：

- `eval-only`
- `dashboard-only`
- `geo-refresh --force`
- 或最终才执行 `full --force`

---

## 一、进入项目目录

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/validation
mkdir -p output/pv_pipeline/logs
```

---

## 二、新增 S115/S116 产物链路诊断脚本

新增：

```text
scripts/diagnose_s115_s116_prediction_flow.py
```

内容：

```python
from pathlib import Path
import json
import pandas as pd
import numpy as np

ROOT = Path(".")
OUT = ROOT / "output/pv_pipeline/validation/round56_s115_s116_prediction_flow.csv"
TARGETS = ["S115", "S116"]

FILES = [
    "output/pv_pipeline/tables/distributed_predictions_v159.pkl",
    "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl",
    "output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
]

def summarize_frame(path: Path, df: pd.DataFrame):
    rows = []
    if "station_id" not in df.columns:
        return rows

    sdf_all = df[df["station_id"].astype(str).isin(TARGETS)].copy()
    if sdf_all.empty:
        return rows

    if "timestamp" in sdf_all.columns:
        sdf_all["timestamp"] = pd.to_datetime(sdf_all["timestamp"], errors="coerce")
        sdf_all["hour"] = sdf_all["timestamp"].dt.hour
    elif "hour" not in sdf_all.columns:
        sdf_all["hour"] = np.nan

    for sid, sdf in sdf_all.groupby(sdf_all["station_id"].astype(str)):
        for label, part in {
            "all": sdf,
            "test_6_19": sdf[(sdf.get("split", "") == "test") & (sdf["hour"].between(6, 19))] if "split" in sdf.columns else sdf[sdf["hour"].between(6, 19)],
            "test_10_14": sdf[(sdf.get("split", "") == "test") & (sdf["hour"].between(10, 14))] if "split" in sdf.columns else sdf[sdf["hour"].between(10, 14)],
        }.items():
            row = {
                "file": str(path),
                "station_id": sid,
                "scope": label,
                "rows": len(part),
                "mtime": path.stat().st_mtime if path.exists() else np.nan,
            }
            for col in [
                "station_name", "capacity_mw",
                "latitude", "longitude", "lat", "lon",
                "has_geo", "solar_elevation_deg", "clear_sky_ghi",
                "g_blend_pred", "scene_v151",
                "power_mw", "power_pred", "power_pred_cal", "power_pred_final",
            ]:
                if col not in part.columns:
                    continue
                s = part[col]
                if s.dtype == object:
                    vc = s.astype(str).value_counts(dropna=False).head(8).to_dict()
                    row[f"{col}_values"] = json.dumps(vc, ensure_ascii=False)
                else:
                    sn = pd.to_numeric(s, errors="coerce")
                    row[f"{col}_non_null"] = int(sn.notna().sum())
                    row[f"{col}_zero_ratio"] = float((sn.fillna(0).abs() < 1e-12).mean()) if len(sn) else np.nan
                    row[f"{col}_min"] = float(sn.min()) if sn.notna().any() else np.nan
                    row[f"{col}_mean"] = float(sn.mean()) if sn.notna().any() else np.nan
                    row[f"{col}_max"] = float(sn.max()) if sn.notna().any() else np.nan
            rows.append(row)
    return rows

all_rows = []
for f in FILES:
    path = ROOT / f
    if not path.exists():
        all_rows.append({"file": f, "station_id": "", "scope": "missing", "rows": 0})
        continue
    try:
        if path.suffix == ".pkl":
            df = pd.read_pickle(path)
        elif path.suffix == ".csv":
            df = pd.read_csv(path)
        else:
            continue
        all_rows.extend(summarize_frame(path, df))
    except Exception as exc:
        all_rows.append({"file": f, "station_id": "", "scope": "error", "rows": 0, "error": repr(exc)})

out = pd.DataFrame(all_rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"[OK] written {OUT}, rows={len(out)}")

show_cols = [c for c in [
    "file", "station_id", "scope", "rows",
    "has_geo_mean",
    "solar_elevation_deg_mean", "solar_elevation_deg_max",
    "clear_sky_ghi_mean", "clear_sky_ghi_max",
    "g_blend_pred_mean", "g_blend_pred_max",
    "scene_v151_values",
    "power_mw_mean",
    "power_pred_final_mean", "power_pred_final_max",
] if c in out.columns]
print(out[show_cols].to_string(index=False))
```

执行：

```bash
python scripts/diagnose_s115_s116_prediction_flow.py 2>&1 | tee output/pv_pipeline/logs/round56_diagnose_s115_s116.log
```

---

## 三、判断是哪一步回退

查看诊断 CSV：

```bash
python - <<'PY'
import pandas as pd
path = "output/pv_pipeline/validation/round56_s115_s116_prediction_flow.csv"
df = pd.read_csv(path)
cols = [c for c in [
    "file", "station_id", "scope", "rows",
    "has_geo_mean",
    "g_blend_pred_mean", "g_blend_pred_max",
    "scene_v151_values",
    "power_pred_final_mean", "power_pred_final_max"
] if c in df.columns]
print(df[cols].to_string(index=False))
PY
```

按以下规则判断：

### 情况 A：v159 正常，legacy final 异常，canonical final 异常

表现：

```text
distributed_predictions_v159.pkl: scene 有 mid/low/clear_peak，g_blend_pred > 0
distributed_predictions_final_round36.pkl: scene all night 或 pred_final 全 0
distributed_predictions_final_full.pkl: scene all night 或 pred_final 全 0
```

说明：

```text
后处理/校准/构建 final 阶段覆盖了结果。
```

处理：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only --force 2>&1 | tee output/pv_pipeline/logs/round56_eval_only_after_fix.log
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round56_dashboard_only_after_fix.log
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round56_audit_after_fix.log
```

同时检查 final 构建脚本，不允许从旧 `round36` 文件反向覆盖 canonical。

### 情况 B：v159 正常，canonical final 正常，但 dashboard 异常

说明：

```text
dashboard 导出或前端读取旧 JSON。
```

处理：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only --force
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
```

### 情况 C：v159 异常

说明：

```text
训练/特征阶段仍异常。
```

先跑地理刷新：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode geo-refresh --force 2>&1 | tee output/pv_pipeline/logs/round56_geo_refresh.log
```

再诊断：

```bash
python scripts/diagnose_s115_s116_prediction_flow.py
```

如果仍异常，再完整重训：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode full --force 2>&1 | tee output/pv_pipeline/logs/round56_full_force.log
```

### 情况 D：诊断结果自相矛盾

比如同一文件里 `scene_v151 all night`，但 `g_blend_pred > 0` 且 `power_pred_final > 0`。

说明：

```text
scene_v151 字段可能不是最终预测实际使用的场景字段，或 final 阶段没有同步 scene 字段。
```

处理：

- 找出最终预测实际使用的场景字段。
- 不再只用 `scene_v151` 判断链路是否正常。
- 新增 `final_scene` 或 `prediction_scene` 字段并在 final_full 中写出。

---

## 四、修复 final 构建脚本的覆盖风险

搜索：

```bash
grep -R "distributed_predictions_final_round36\\|distributed_predictions_v159\\|power_pred_final\\|copy2\\|shutil.copy\\|round36" -n scripts src | sed -n '1,240p'
```

重点检查：

```text
scripts/build_round36_predictions.py
scripts/post_training_finalize_outputs.py
scripts/run_full_pipeline.py
scripts/export_interactive_dashboard_data.py
```

要求：

1. `distributed_predictions_v159.pkl` 如果是模型输出源，final 构建必须从它读取最新版本。
2. canonical final 必须直接由最新模型输出生成。
3. legacy round 文件只能从 canonical 复制，不能反向覆盖 canonical。
4. `eval-only` 不应重新训练，但可以重建 final/eval/metrics/dashboard。
5. `dashboard-only` 只能读 canonical final，不能读 legacy。

---

## 五、禁止诊断报告误判 all night 为正常

修改：

```text
scripts/audit_training_pipeline_flow.py
scripts/posttrain_validation.py
scripts/diagnose_geo_feature_flow.py
```

新增规则：

```text
对于 has_geo=1 且 test 10-14 点有真实功率或有效样本的站点：
如果 scene_v151 全为 night，必须 WARN 或 FAIL。
如果 power_pred_final 全为 0，必须 WARN 或 FAIL。
```

建议：

- 对 S115/S116 这类已人工补坐标站点，`scene all night` 直接 FAIL。
- 对无测试有效样本的站点，只 WARN。

验证代码：

```python
targets = ["S115", "S116"]
day = df[
    df["station_id"].isin(targets)
    & df["split"].eq("test")
    & pd.to_datetime(df["timestamp"]).dt.hour.between(10, 14)
]
if len(day):
    for sid, sdf in day.groupby("station_id"):
        if "scene_v151" in sdf.columns and sdf["scene_v151"].astype(str).eq("night").all():
            raise AssertionError(f"{sid} test 10-14 scene_v151 all night")
        if sdf["power_pred_final"].fillna(0).abs().lt(1e-12).all():
            raise AssertionError(f"{sid} test 10-14 power_pred_final all zero")
```

---

## 六、实测增量模式，不要只测 audit-only

Round55 只实测了 audit-only，本轮至少实测：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round56_dashboard_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only --force 2>&1 | tee output/pv_pipeline/logs/round56_eval_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round56_audit_only.log
```

检查这三个模式是否触发训练：

```bash
grep -Ei "train|fit|model training|分布式功率模型训练|Step 6|训练模型" \
  output/pv_pipeline/logs/round56_dashboard_only.log \
  output/pv_pipeline/logs/round56_eval_only.log \
  output/pv_pipeline/logs/round56_audit_only.log || true
```

要求：

- `dashboard-only` 不触发 Step 6。
- `eval-only` 不触发 Step 6。
- `audit-only` 不触发 Step 6。

输出耗时：

```bash
cat output/pv_pipeline/logs/pipeline_timing_latest.csv
```

---

## 七、最终验证

执行：

```bash
python scripts/diagnose_s115_s116_prediction_flow.py
python scripts/posttrain_validation.py --config configs/pipeline.yaml
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
```

必须满足：

```text
S115/S116 final_full test 10-14 scene_v151 不全为 night
S115/S116 final_full test 10-14 g_blend_pred > 0
S115/S116 final_full test 10-14 power_pred_final 不全为 0
posttrain_validation 无 FAIL
dashboard check 无 FAIL
```

---

## 八、什么时候才允许完整重训

只有满足以下任一条件，才执行完整重训：

```text
v159 本身异常
训练特征文件异常
模型训练代码被修改
geo-refresh 后仍无法修复
```

完整重训命令：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode full --force 2>&1 | tee output/pv_pipeline/logs/round56_full_force.log
```

如果只是 final/eval/dashboard 层异常，不要完整重训。

---

## 九、生成 Round56 报告

新增：

```text
docs/Round56_S115_S116最终产物回退诊断与按需重训报告.md
```

模板：

```markdown
# Round56 S115/S116 最终产物回退诊断与按需重训报告

## 1. 本轮目标

## 2. 是否直接完整重训

结论：先诊断 / 已重训 / 未重训

## 3. S115/S116 各产物层级对比

| 文件 | S115 scene | S115 pred 是否全0 | S116 scene | S116 pred 是否全0 | 结论 |
|---|---|---|---|---|---|

## 4. 异常断点

## 5. 修复内容

## 6. 增量模式实测耗时

| mode | 是否触发训练 | 耗时 | 结果 |
|---|---:|---:|---|
| dashboard-only | 否 |  |  |
| eval-only | 否 |  |  |
| audit-only | 否 |  |  |

## 7. 最终验证结果

## 8. 是否需要完整重训

## 9. 后续建议
```

---

## 十、验收标准

```text
[PASS] 新增 round56_s115_s116_prediction_flow.csv
[PASS] 明确 v159/final_full/final_eval/dashboard 哪一步异常
[PASS] 不把 S115/S116 all night 误判为正常
[PASS] 如果 v159 正常，则不完整重训
[PASS] dashboard-only/eval-only/audit-only 均实测
[PASS] dashboard-only/eval-only/audit-only 不触发 Step 6 训练
[PASS] S115/S116 final_full test 10-14 预测不全 0
[PASS] posttrain_validation 无 FAIL
[PASS] dashboard check 无 FAIL
```

