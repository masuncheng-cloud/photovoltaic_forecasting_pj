# Round44：训练逻辑与可视化问题总收口方案

## 一、当前判断

现在可视化页面大部分交互问题已经逐步修复，包括：

```text
单站点曲线空白
典型站点按钮不显示站点下拉框
四季按钮站点不同步
全市早晚预测贴 0
dashboard 读取旧 JSON
dashboard 与 final pkl 不一致
训练后可视化不自动刷新
```

但从 Round41/42 报告看，训练逻辑仍有两个需要收口的问题：

1. `daytime_source` 的选择出现了 test 集参与决策的嫌疑。
2. 站点级校准后，站点平均 NRMSE 从 `10.94%` 升到 `13.50%`，说明校准没有达到降低站点平均误差的目标。

另外，`Cursor执行方案_Round43_2_训练后自动刷新生效检测` 还没有执行，需要并入本轮。

因此本轮目标是：

```text
训练逻辑严谨化 + 可视化自动刷新 + 全问题回归检查
```

---

## 二、本轮结论

训练逻辑需要改进，但不是重新训练模型结构，而是改后处理与守门逻辑：

```text
1. 日间统一来源必须只用 valid 集选择，不能用 test 集选。
2. test 集只用于最终评估和报告。
3. 站点级校准必须有启用条件，若 test 守门显示变差，则自动回退。
4. 训练完成后必须自动刷新 dashboard JSON，并检测刷新确实生效。
5. 可视化页面所有历史问题做回归检查。
```

---

## 三、本轮不做的事

不重新设计模型。

不再恢复：

```text
GHI < 5 => 6-19 点强制置 0
```

不使用：

```text
test 集选择最优预测来源
```

不把主指标改成：

```text
RMSE / (真实最大值 - 真实最小值)
```

---

## 四、修改 1：修正 Round41/42 训练逻辑，禁止 test 选来源

修改：

```text
scripts/round41_42_unified_daytime_and_site_calibration.py
```

### 4.1 删除或禁用 test 最优强制逻辑

搜索：

```bash
grep -n "test.*10-14\\|强制.*power_pred_cal\\|selected_daytime_source\\|daytime_source" scripts/round41_42_unified_daytime_and_site_calibration.py
```

如果存在类似：

```python
# 因为 test 10-14 最优，所以强制使用 power_pred_cal
daytime_source = "power_pred_cal"
```

必须改掉。

### 4.2 正确逻辑

只允许 valid 集选择：

```python
selection_table, selected = select_daytime_source(df, cols)
daytime_source = selected["pred_col"]
```

并在 `selection_info.json` 写明：

```python
selection_info = {
    "selection_split": "valid",
    "test_used_for_selection": False,
    "selected_daytime_source": daytime_source,
    "selected_valid_metrics": selected,
}
```

### 4.3 如果你确实想固定 power_pred_cal

也必须写成“先验工程规则”，不能写成“因为 test 最优”：

```python
USE_FIXED_DAYTIME_SOURCE = False
FIXED_DAYTIME_SOURCE = "power_pred_cal"

if USE_FIXED_DAYTIME_SOURCE:
    daytime_source = FIXED_DAYTIME_SOURCE
    selection_reason = "fixed_by_engineering_prior_not_test_metric"
else:
    selection_table, selected = select_daytime_source(df, cols)
    daytime_source = selected["pred_col"]
    selection_reason = "selected_by_valid_10_14_city_hourly_nrmse"
```

默认：

```python
USE_FIXED_DAYTIME_SOURCE = False
```

---

## 五、修改 2：站点级校准必须先试算，变差就不启用

当前 Round41/42 报告中：

```text
站点平均 NRMSE：10.94% -> 13.50%
```

说明站点校准后反而变差。

因此站点校准不能无条件写入 `power_pred_final`。

### 5.1 修改策略

在脚本中同时保留两个候选：

```text
候选 A：日间统一来源 + 边缘保护，不做站点校准
候选 B：候选 A + 站点级校准
```

用 valid 集判断是否启用站点校准。

判断标准：

```text
valid 站点平均 NRMSE 下降；
valid 全市 NRMSE 不明显变差；
valid 全市 BIAS 不超过阈值；
```

建议阈值：

```text
站点平均 NRMSE 至少下降 0.2pp 才启用；
全市 NRMSE 不能上升超过 0.3pp；
全市 BIAS 绝对值不能超过 15%。
```

### 5.2 增加评估函数

在 `round41_42_unified_daytime_and_site_calibration.py` 中增加：

```python
def evaluate_candidate(df, pred_col, split="valid"):
    work = df[
        df["split"].eq(split)
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")

    # city
    city = work.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    city_err = city["pred_mw"] - city["actual_mw"]
    city_rmse = rmse(city_err)
    city_cap = float(city["capacity_sum_mw"].mean())
    city_nrmse = city_rmse / max(city_cap, 1e-9) * 100
    city_bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100

    # site
    site_rows = []
    for sid, g in work.groupby("site_id"):
        err = g["pred_mw"] - g["actual_mw"]
        cap = float(g["capacity_mw"].mean())
        site_rows.append(rmse(err) / max(cap, 1e-9) * 100)

    return {
        "split": split,
        "pred_col": pred_col,
        "city_nrmse_pct": float(city_nrmse),
        "city_bias_pct": float(city_bias),
        "site_mean_nrmse_pct": float(np.mean(site_rows)),
        "site_median_nrmse_pct": float(np.median(site_rows)),
    }
```

### 5.3 先生成两个候选列

```python
df1 = apply_unified_daytime_source(df, daytime_source)
df1["candidate_no_site_cal"] = df1["power_pred_final"]

alpha = fit_site_alpha(df1)
df2 = apply_site_calibration(df1, alpha)
df2["candidate_with_site_cal"] = df2["power_pred_final"]
```

### 5.4 用 valid 集决定是否启用站点校准

```python
eval_no_cal = evaluate_candidate(df2.rename(columns={"candidate_no_site_cal": "tmp_pred"}), "tmp_pred", split="valid")
eval_with_cal = evaluate_candidate(df2.rename(columns={"candidate_with_site_cal": "tmp_pred"}), "tmp_pred", split="valid")

site_improve = eval_no_cal["site_mean_nrmse_pct"] - eval_with_cal["site_mean_nrmse_pct"]
city_delta = eval_with_cal["city_nrmse_pct"] - eval_no_cal["city_nrmse_pct"]
bias_ok = abs(eval_with_cal["city_bias_pct"]) <= 15.0

use_site_cal = (
    site_improve >= 0.2
    and city_delta <= 0.3
    and bias_ok
)

if use_site_cal:
    df2["power_pred_final"] = df2["candidate_with_site_cal"]
else:
    df2["power_pred_final"] = df2["candidate_no_site_cal"]
```

### 5.5 输出选择结果

输出：

```text
output/pv_pipeline/metrics/round44_site_calibration_decision.csv
```

包含：

```text
use_site_calibration
site_improve_valid_pp
city_delta_valid_pp
bias_valid
eval_no_cal
eval_with_cal
```

---

## 六、修改 3：并入 Round43.2 自动刷新生效检测

### 6.1 新增或覆盖脚本

新增或覆盖：

```text
scripts/update_dashboard_after_training.py
```

要求它具备以下功能：

```text
1. 执行 export_interactive_dashboard_data.py
2. 执行 city_series 与 final pkl 一致性校验
3. 执行站点 JSON 与 final pkl 一致性校验
4. 记录 dashboard 文件刷新前后的 mtime / size / sha256
5. 写出 dashboard_update_stamp.json
6. 如果本次训练后 dashboard 文件没有刷新，直接失败
```

直接使用 Round43.2 中的版本。

### 6.2 新增检查脚本

新增：

```text
scripts/check_dashboard_auto_update_stamp.py
```

直接使用 Round43.2 中的版本。

### 6.3 接入完整训练入口

找到完整训练入口后，在最后加入：

```bash
python scripts/update_dashboard_after_training.py
```

如果是 Python 入口：

```python
def refresh_dashboard_after_training():
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "scripts/update_dashboard_after_training.py"]
    result = subprocess.run(cmd, cwd=root)
    if result.returncode != 0:
        raise RuntimeError("可视化数据自动刷新或生效检测失败")
```

并在 `main()` 最后调用。

---

## 七、修改 4：新增可视化全问题回归检查脚本

新增：

```text
scripts/round44_dashboard_regression_check.py
```

内容如下：

```python
from pathlib import Path
import json
import pandas as pd


ROOT = Path("output/pv_pipeline")
DASH = ROOT / "interactive_dashboard"
METRIC = ROOT / "metrics"
METRIC.mkdir(parents=True, exist_ok=True)


def load_json(name):
    p = DASH / name
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    checks = []

    required = [
        "metadata.json",
        "city_series.json",
        "site_metrics.json",
        "typical_sites.json",
        "season_best_days_city.json",
        "season_best_days_by_site.json",
        "dashboard_update_stamp.json",
    ]

    for name in required:
        p = DASH / name
        checks.append({
            "check": f"exists_{name}",
            "status": "PASS" if p.exists() and p.stat().st_size > 0 else "FAIL",
            "value": p.stat().st_size if p.exists() else 0,
        })

    city = pd.read_json(DASH / "city_series.json")
    checks.append({
        "check": "city_series_not_empty",
        "status": "PASS" if len(city) > 0 else "FAIL",
        "value": len(city),
    })

    for col in ["time", "actual_mw", "pred_mw", "n_sites"]:
        checks.append({
            "check": f"city_series_has_{col}",
            "status": "PASS" if col in city.columns else "FAIL",
            "value": col in city.columns,
        })

    if "split" in city.columns:
        has_future = city["split"].astype(str).eq("future").any()
        checks.append({
            "check": "city_series_no_future",
            "status": "PASS" if not has_future else "FAIL",
            "value": bool(has_future),
        })

    if "hour" in city.columns:
        hour_ok = city["hour"].between(6, 19).all()
        checks.append({
            "check": "city_series_hours_6_19",
            "status": "PASS" if hour_ok else "FAIL",
            "value": f"{city['hour'].min()}-{city['hour'].max()}",
        })

    # 典型站点
    typical = load_json("typical_sites.json")
    typical_text = json.dumps(typical, ensure_ascii=False)
    for key in ["best", "worst"]:
        checks.append({
            "check": f"typical_has_{key}_or_chinese",
            "status": "PASS" if (key in typical_text or ("最好" in typical_text if key == "best" else "最差" in typical_text)) else "FAIL",
            "value": key,
        })

    # season best
    season_city = load_json("season_best_days_city.json")
    season_site = load_json("season_best_days_by_site.json")
    for s in ["spring", "summer", "autumn", "winter"]:
        checks.append({
            "check": f"season_city_has_{s}",
            "status": "PASS" if s in season_city else "FAIL",
            "value": s in season_city,
        })

    checks.append({
        "check": "season_site_not_empty",
        "status": "PASS" if isinstance(season_site, dict) and len(season_site) > 0 else "FAIL",
        "value": len(season_site) if isinstance(season_site, dict) else 0,
    })

    # site series sample
    site_dir = DASH / "site_series"
    site_files = sorted(site_dir.glob("S*.json"))
    checks.append({
        "check": "site_series_files_exist",
        "status": "PASS" if len(site_files) >= 60 else "FAIL",
        "value": len(site_files),
    })

    for sid in ["S017", "S062", "S019"]:
        p = site_dir / f"{sid}.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            checks.append({
                "check": f"site_series_{sid}_not_empty",
                "status": "PASS" if len(data) > 0 else "FAIL",
                "value": len(data),
            })
        else:
            checks.append({
                "check": f"site_series_{sid}_exists",
                "status": "FAIL",
                "value": 0,
            })

    out = pd.DataFrame(checks)
    out.to_csv(METRIC / "round44_dashboard_regression_check.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if (out["status"] == "FAIL").any():
        raise SystemExit("[FAIL] dashboard regression check failed")

    print("[PASS] dashboard regression check passed")


if __name__ == "__main__":
    main()
```

---

## 八、执行顺序

### 8.1 先修训练逻辑

执行融合脚本：

```bash
python scripts/round41_42_unified_daytime_and_site_calibration.py
```

重新计算指标：

```bash
python scripts/round40_compare_final_prediction_metrics.py
```

执行守门：

```bash
python scripts/round41_42_guard.py
```

### 8.2 自动刷新可视化数据

执行：

```bash
python scripts/update_dashboard_after_training.py
python scripts/check_dashboard_auto_update_stamp.py
```

### 8.3 回归检查

执行：

```bash
python scripts/round44_dashboard_regression_check.py
python scripts/check_dashboard_city_series_consistency_round40.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

---

## 九、完整训练入口接入

找到完整训练入口后，把下面流程作为末尾固定步骤：

```bash
python scripts/round41_42_unified_daytime_and_site_calibration.py
python scripts/round40_compare_final_prediction_metrics.py
python scripts/round41_42_guard.py
python scripts/update_dashboard_after_training.py
python scripts/check_dashboard_auto_update_stamp.py
python scripts/round44_dashboard_regression_check.py
```

如果训练入口里已经包含 Round41/42，则不要重复执行，改为确保它是“修正后的 Round41/42”。

---

## 十、最终守门要求

本轮通过必须满足：

```text
1. daytime_source 由 valid 集选择，selection_info 中 test_used_for_selection=false
2. test 集只出现在最终评估，不参与选择
3. 站点校准只有在 valid 守门通过时才启用
4. 若站点校准变差，自动使用 no_site_cal 候选
5. 6/7/18/19 不再整城贴 0
6. 10-14 全市 NRMSE 不明显高于 Round40
7. 全市 BIAS 绝对值 <= 15%
8. dashboard JSON 与 final pkl 一致
9. dashboard_update_stamp.json 存在并有效
10. round44_dashboard_regression_check.py 全部 PASS
```

---

## 十一、页面人工验收

启动：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round44
```

检查：

### 11.1 全市曲线

```text
展示对象：全市
日期：2025-09-01 至 2025-12-31
小时：06:00 至 19:00
```

要求：

```text
全市曲线正常；
6/7/18/19 不长期贴 0；
10-14 贴合度正常。
```

### 11.2 单站点曲线

```text
展示对象：单站点
任意站点 S017 / S062 / S019
```

要求：

```text
站点下拉框显示；
曲线正常；
指标卡不为 0。
```

### 11.3 典型站点按钮

依次点击：

```text
预测最好
预测最差
相对正确
样本少
```

要求：

```text
自动切到单站点；
站点下拉框显示；
站点名与曲线标题一致。
```

### 11.4 四季最佳日

全市模式点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

要求：

```text
选择全市该季节最佳日。
```

单站点模式点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

要求：

```text
保持当前站点；
站点下拉框同步；
选择该站点该季节最佳日。
```

---

## 十二、完成后回传

请回传：

```text
output/pv_pipeline/metrics/round41_42_selection_info.json
output/pv_pipeline/metrics/round44_site_calibration_decision.csv
output/pv_pipeline/metrics/round41_42_guard.csv
output/pv_pipeline/metrics/round44_dashboard_regression_check.csv
output/pv_pipeline/interactive_dashboard/dashboard_update_stamp.json
```

以及：

```text
完整训练入口文件名
训练结束日志中的 dashboard auto-update PASS
页面全市/单站点/典型站点/四季最佳日截图
```

