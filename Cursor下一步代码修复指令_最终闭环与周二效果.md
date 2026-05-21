# Cursor 下一步代码修复指令：修复最终闭环并恢复周二效果

## 目标

当前项目已经补上了 `distributed_model.py`，但还没有真正恢复周二效果。现在主要问题是：

1. `distributed_predictions_final_eval.pkl`、`distributed_predictions_final_full.pkl` 没有真实生成。
2. `distributed_metrics_fixed.csv` 仍然显示低估版本：`pred_actual_ratio ≈ 0.7572`，不是周二的 `0.9488`。
3. `select_final_prediction_by_guard.py` 和部分脚本仍有 `StringDtype.__init` 拼写错误。
4. `select_final_prediction_v3.py` 仍有文件名不一致、`power_pred` 不存在、`cmp` 未定义问题。
5. `train_fixed.py` 对关键输出检查不够严格，导致报告可能“假通过”。

本轮修改目标：

- 让 `train_fixed.py --skip-training` 必须重新生成 final pkl。
- 如果 final pkl 未生成，必须失败退出，不能继续写报告。
- 最终指标必须接近周二效果：

```text
final_eval 行数：约 67,102
站点数：53
pred_actual_ratio：约 0.9488
bias：约 -5.12%
MAE：约 0.4547 MW
RMSE：约 0.9676 MW
```

---

## 1. 修复 pandas StringDtype 拼写错误

全项目搜索：

```text
StringDtype.__init =
```

必须全部改成：

```text
StringDtype.__init__ =
```

重点文件：

```text
scripts/fix_dawn_dusk_conservative.py
scripts/select_final_prediction_by_guard.py
```

可直接在 Cursor 中执行全局替换：

```text
查找：StringDtype.__init =
替换：StringDtype.__init__ =
```

注意：不要替换已经正确的：

```text
StringDtype.__init__
```

---

## 2. 修复 `scripts/train_fixed.py`

### 2.1 把 `apply_p0_p1_fix_v2.py` 设为关键脚本

找到：

```python
CRITICAL_SCRIPTS = {
    'rebuild_fixed_predictions.py',
    'fix_hourly_bias.py',
    'evaluate_fixed_predictions.py',
    'select_final_prediction_by_guard.py',
    'regenerate_chinese_metrics.py',
    'check_pipeline_consistency.py',
}
```

改成：

```python
CRITICAL_SCRIPTS = {
    'rebuild_fixed_predictions.py',
    'fix_hourly_bias.py',
    'apply_p0_p1_fix_v2.py',
    'evaluate_fixed_predictions.py',
    'select_final_prediction_by_guard.py',
    'regenerate_chinese_metrics.py',
    'check_pipeline_consistency.py',
}
```

原因：当前低估修正主要依赖 P0/P1，如果它失败，不能继续。

---

### 2.2 关键输出文件必须包含 fixed 和 final

找到：

```python
KEY_OUTPUT_FILES = [
    'tables/distributed_predictions_fixed.pkl',
    'metrics/distributed_metrics_fixed.csv',
    'metrics/distributed_metrics_by_scene_fixed.csv',
    'metrics/distributed_metrics_by_hour_fixed.csv',
]
```

改成：

```python
KEY_OUTPUT_FILES = [
    'tables/distributed_predictions_fixed.pkl',
    'tables/distributed_predictions_fixed_eval.pkl',
    'tables/distributed_predictions_fixed_full.pkl',
    'tables/distributed_predictions_final_eval.pkl',
    'tables/distributed_predictions_final_full.pkl',
    'metrics/distributed_metrics_fixed.csv',
    'metrics/distributed_metrics_by_scene_fixed.csv',
    'metrics/distributed_metrics_by_hour_fixed.csv',
    'metrics/分布式光伏预测_逐小时平均NRMSE.csv',
    'metrics/分布式光伏预测_周报_整体统计.csv',
]
```

原因：当前报告声称 final 文件存在，但目录里实际没有。这里必须硬性检查。

---

### 2.3 增加 final 结果数值验收函数

在 `assert_scene_metrics_valid()` 后面新增：

```python
def assert_final_metrics_valid(output_root):
    """检查 final_eval 是否真实可读，并且整体结果接近周二效果。"""
    import pandas as pd
    import numpy as np

    output_path = ROOT / output_root
    final_eval = output_path / "tables" / "distributed_predictions_final_eval.pkl"

    if not final_eval.exists():
        print(f"[ERROR] final_eval 不存在: {final_eval}")
        return False

    try:
        from pv_forecasting.core.utils import safe_pickle_load
        df = safe_pickle_load(final_eval)
    except Exception as e:
        print(f"[ERROR] final_eval 读取失败: {e}")
        return False

    if df.empty:
        print("[ERROR] final_eval 为空")
        return False

    required_cols = {"time", "site_id", "power_mw", "power_pred"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"[ERROR] final_eval 缺少字段: {sorted(missing)}")
        return False

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    rows = len(df)
    n_sites = df["site_id"].nunique()
    h_min = int(df["hour"].min())
    h_max = int(df["hour"].max())
    actual = float(pd.to_numeric(df["power_mw"], errors="coerce").sum())
    pred = float(pd.to_numeric(df["power_pred"], errors="coerce").sum())
    ratio = pred / max(actual, 1e-9)
    bias = (pred - actual) / max(actual, 1e-9) * 100
    mae = float(np.mean(np.abs(df["power_pred"] - df["power_mw"])))
    rmse = float(np.sqrt(np.mean((df["power_pred"] - df["power_mw"]) ** 2)))

    print("[FINAL CHECK]")
    print(f"  rows={rows:,}")
    print(f"  sites={n_sites}")
    print(f"  hour_range={h_min}-{h_max}")
    print(f"  actual={actual:.2f}")
    print(f"  pred={pred:.2f}")
    print(f"  pred_actual_ratio={ratio:.4f}")
    print(f"  bias_pct={bias:.2f}%")
    print(f"  MAE={mae:.4f}")
    print(f"  RMSE={rmse:.4f}")

    ok = True
    if not (66000 <= rows <= 68000):
        print("[ERROR] final_eval 行数异常，应接近 67,102")
        ok = False
    if n_sites != 53:
        print("[ERROR] final_eval 站点数异常，应为 53")
        ok = False
    if not (h_min >= 6 and h_max <= 19):
        print("[ERROR] final_eval 小时范围异常，应为 6-19")
        ok = False
    if ratio < 0.90:
        print("[ERROR] pred_actual_ratio 仍然过低，说明系统性低估没有修复")
        ok = False
    if abs(bias) > 10:
        print("[ERROR] bias 超过 10%，没有恢复周二效果")
        ok = False

    return ok
```

---

### 2.4 在主流程中调用 final 验收

找到：

```python
if not assert_scene_metrics_valid(metrics_dir):
    print("[ABORT] 场景指标检查失败")
    sys.exit(1)
```

在其后加入：

```python
if not assert_final_metrics_valid(args.output_root):
    print("[ABORT] final 预测结果验收失败")
    sys.exit(1)
```

这样如果还是低估版，训练流程会直接失败，不再生成误导性报告。

---

### 2.5 修复 `clean_stale_outputs` 路径问题

当前 `clean_stale_outputs(output_root)` 里：

```python
root = Path(output_root)
```

如果在项目根目录运行没问题，但更稳妥应改成：

```python
root = ROOT / output_root
```

完整替换为：

```python
def clean_stale_outputs(output_root):
    """删除旧的修复结果，防止失败后静默复用假数据"""
    stale_outputs = [
        "tables/distributed_predictions_fixed.pkl",
        "tables/distributed_predictions_fixed_eval.pkl",
        "tables/distributed_predictions_fixed_full.pkl",
        "tables/distributed_predictions_final_eval.pkl",
        "tables/distributed_predictions_final_full.pkl",
        "metrics/final_version_selection_by_hour.csv",
        "metrics/final_guard_reject_reasons.csv",
        "metrics/分布式光伏预测_逐小时平均NRMSE.csv",
        "metrics/分布式光伏预测_周报_整体统计.csv",
    ]
    root = ROOT / output_root
    for rel in stale_outputs:
        p = root / rel
        if p.exists():
            print(f"[CLEAN] remove stale output: {p}")
            p.unlink()
```

---

## 3. 修复 `scripts/select_final_prediction_v3.py`

虽然当前主链路使用 `select_final_prediction_by_guard.py`，但 V3 文件也要修，否则后续检查会继续混乱。

### 3.1 修复 V3 文件名

找到：

```python
v3_path = TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl"
if not v3_path.exists():
    print(f"[ERROR] V3 预测不存在: {v3_path}")
    sys.exit(1)
```

改成：

```python
v3_path = TABLES_DIR / "distributed_predictions_v3_full.pkl"
if not v3_path.exists():
    alt = TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl"
    if alt.exists():
        v3_path = alt
    else:
        print(f"[ERROR] V3 预测不存在: {v3_path} 或 {alt}")
        sys.exit(1)
```

---

### 3.2 修复 valid 阶段 `power_pred` 不存在问题

找到：

```python
v_valid = build_eval_frame(base, pred_col="power_pred", split="valid",
                            active_only=True, bad_sites=BAD_SITES)
```

改成：

```python
v_valid = build_eval_frame(base, pred_col="pred_v2", split="valid",
                            active_only=True, bad_sites=BAD_SITES)
```

原因：此时 `base["power_pred"]` 还没有生成。

---

### 3.3 修复 `cmp` 未定义

找到：

```python
cmp_out = METRICS_DIR / "hourly_nrmse_compare_v2_v3.csv"
cmp.to_csv(cmp_out, index=False, encoding="utf-8-sig")
```

在这两行前面加入：

```python
from pv_forecasting.core.evaluation import compare_two_versions

test_eval = build_eval_frame(
    base,
    pred_col="power_pred",
    split="test",
    active_only=True,
    bad_sites=BAD_SITES,
)

cmp = compare_two_versions(
    test_eval,
    "pred_v2",
    "power_pred",
    version_labels=("V2", "Final"),
)
```

---

## 4. 修复 `scripts/select_final_prediction_by_guard.py`

### 4.1 修复 StringDtype 拼写

找到：

```python
_sm.StringDtype.__init = _patch
```

改成：

```python
_sm.StringDtype.__init__ = _patch
```

---

### 4.2 兼容 V3 文件名

搜索：

```python
distributed_predictions_fixed_full_v3.pkl
```

如果只是作为候选文件读取，改为兼容两种命名：

```python
v3_path = TABLES_DIR / "distributed_predictions_v3_full.pkl"
if not v3_path.exists():
    v3_path = TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl"
```

如果 V3 文件不存在，guard 不应该失败；它应该跳过 V3 候选，继续用 V1/V2 稳定候选生成 final。

要求：

```text
V3 缺失：警告并跳过
V1/V2/fixed_full 缺失：关键失败
final_full/final_eval 必须写出
```

---

## 5. 修复 `scripts/check_pipeline_consistency.py`

当前一致性检查容易把 V3 文件当作必须存在，导致逻辑混乱。

要求改成：

1. `distributed_predictions_final_eval.pkl` 必须存在。
2. `distributed_predictions_final_full.pkl` 必须存在。
3. V3 文件如果不存在，只警告，不作为失败。
4. final_eval 必须按最终口径检查：

```text
split == test
hour 6-19
power_mw > 0
site_id 排除异常站点后为 53 座
```

如果脚本里有类似：

```python
"V3 完整预测表": TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl"
```

改成可选检查：

```python
optional_files = {
    "V3 完整预测表": [
        TABLES_DIR / "distributed_predictions_v3_full.pkl",
        TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl",
    ],
}

for name, paths in optional_files.items():
    if not any(p.exists() and p.stat().st_size > 0 for p in paths):
        warn(f"{name} 不存在，跳过 V3 可选检查")
```

---

## 6. 修复 `scripts/regenerate_chinese_metrics.py`

要求：

1. 必须优先读取：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
```

2. 如果 final_eval 不存在，直接失败，不允许静默回退到 fixed 或 v159。

把类似这种逻辑：

```python
if final 不存在:
    读取 fixed
```

改成：

```python
PRED_PKL = TABLES_DIR / "distributed_predictions_final_eval.pkl"
if not PRED_PKL.exists():
    raise FileNotFoundError(
        f"缺少最终预测文件: {PRED_PKL}，请先运行 select_final_prediction_by_guard.py"
    )
```

3. 生成逐小时 NRMSE 时，必须使用 final_eval，且口径固定：

```text
split == test
hour 6-19
power_mw > 0
排除异常站点
```

4. 输出文件必须包含：

```text
metrics/分布式光伏预测_逐小时平均NRMSE.csv
metrics/分布式光伏预测_周报_整体统计.csv
```

---

## 7. 重新运行

完成以上修改后，在项目根目录运行：

```bash
python scripts/train_fixed.py --smoke-test
```

然后运行：

```bash
python scripts/train_fixed.py --skip-training --data-root data --output-root output/pv_pipeline
```

如果它失败，不要继续写报告，先看失败脚本。

---

## 8. 运行后必须检查

运行：

```bash
python scripts/check_pipeline_consistency.py
```

然后手动检查：

```bash
python - <<'PY'
from pathlib import Path
import pandas as pd
import numpy as np

root = Path("output/pv_pipeline")
df = pd.read_pickle(root / "tables" / "distributed_predictions_final_eval.pkl")

actual = df["power_mw"].sum()
pred = df["power_pred"].sum()
ratio = pred / actual
bias = (pred - actual) / actual * 100
mae = np.mean(np.abs(df["power_pred"] - df["power_mw"]))
rmse = np.sqrt(np.mean((df["power_pred"] - df["power_mw"]) ** 2))

print("rows =", len(df))
print("sites =", df["site_id"].nunique())
print("hour range =", df["hour"].min(), df["hour"].max())
print("actual =", round(actual, 2))
print("pred =", round(pred, 2))
print("ratio =", round(ratio, 4))
print("bias =", round(bias, 2))
print("MAE =", round(mae, 4))
print("RMSE =", round(rmse, 4))
PY
```

验收标准：

```text
rows ≈ 67102
sites = 53
hour range = 6 19
ratio >= 0.90
bias 绝对值 <= 10%
```

如果要达到周二效果，应接近：

```text
actual ≈ 83409.19
pred ≈ 79138.30
ratio ≈ 0.9488
bias ≈ -5.12
MAE ≈ 0.4547
RMSE ≈ 0.9676
```

---

## 9. 当前不要做

本轮不要做这些事：

1. 不要继续写新的总结报告。
2. 不要把 `distributed_predictions.pkl` 或 `distributed_predictions_v159.pkl` 直接当 final。
3. 不要让 `regenerate_chinese_metrics.py` 回退读取 fixed/v159。
4. 不要把 V3 作为必须成功项。
5. 不要删除 `power_clean.pkl`、`site_irradiance.pkl`、`distributed_train_table_v159.pkl`、`distributed_predictions_v159.pkl`。

本轮只做一件事：

> 让 final_full/final_eval 真实生成，并让 pred_actual_ratio 从当前约 0.757 恢复到 0.90 以上，最好回到周二约 0.9488。

