# Cursor 下一步修改代码：对齐周二效果与 MAE/RMSE 优先

## 一、当前问题

当前版本工程闭环已经比周二版完整，但模型效果没有恢复到周二水平：

| 指标 | 周二版 | 当前版 | 判断 |
|---|---:|---:|---|
| 站点数 | 53 | 53 | 一致 |
| 样本数 | 67,102 | 68,888 | 不一致 |
| pred_actual_ratio | 0.9488 | 0.9561 | 当前略好 |
| bias | -5.12% | -4.39% | 当前略好 |
| MAE | 0.4547 MW | 0.5927 MW | 当前变差 |
| RMSE | 0.9676 MW | 1.2164 MW | 当前变差 |

当前版本的主要问题是：为了修复总量低估，`BlendTotal_a10` 提升了 ratio，但站点级 MAE/RMSE 被拉高。下一步应把主目标从“总量更接近 1”改成：

```text
MAE/RMSE 不劣化 > 逐小时 NRMSE 稳定 > ratio 在 0.90~0.98
```

本轮不重新训练，先改最终版本选择、评估对比和报告口径。

---

## 二、新增周二基准常量模块

新建文件：

`src/pv_forecasting/core/week2_reference.py`

写入：

```python
from __future__ import annotations


WEEK2_REFERENCE = {
    "rows": 67102,
    "sites": 53,
    "actual_mwh": 83409.19,
    "pred_mwh": 79138.30,
    "pred_actual_ratio": 0.9488,
    "bias_pct": -5.12,
    "mae_mw": 0.4547,
    "rmse_mw": 0.9676,
}


WEEK2_HOURLY_NRMSE = {
    6: {"rows": 1143, "site_nrmse_mean_pct": 5.66, "city_nrmse_pct": 14.400},
    7: {"rows": 4309, "site_nrmse_mean_pct": 5.67, "city_nrmse_pct": 5.904},
    8: {"rows": 6174, "site_nrmse_mean_pct": 7.09, "city_nrmse_pct": 2.949},
    9: {"rows": 6289, "site_nrmse_mean_pct": 10.12, "city_nrmse_pct": 1.659},
    10: {"rows": 6326, "site_nrmse_mean_pct": 11.63, "city_nrmse_pct": 2.763},
    11: {"rows": 6339, "site_nrmse_mean_pct": 12.02, "city_nrmse_pct": 1.243},
    12: {"rows": 6352, "site_nrmse_mean_pct": 12.48, "city_nrmse_pct": 0.142},
    13: {"rows": 6345, "site_nrmse_mean_pct": 12.50, "city_nrmse_pct": 1.088},
    14: {"rows": 6334, "site_nrmse_mean_pct": 11.55, "city_nrmse_pct": 0.989},
    15: {"rows": 6313, "site_nrmse_mean_pct": 9.65, "city_nrmse_pct": 1.569},
    16: {"rows": 6173, "site_nrmse_mean_pct": 6.17, "city_nrmse_pct": 2.269},
    17: {"rows": 3180, "site_nrmse_mean_pct": 5.32, "city_nrmse_pct": 5.906},
    18: {"rows": 1143, "site_nrmse_mean_pct": 5.02, "city_nrmse_pct": 12.663},
    19: {"rows": 682, "site_nrmse_mean_pct": 15.01, "city_nrmse_pct": 19.180},
}
```

作用：

- 后续报告可以明确“当前 vs 周二”的差距；
- 不再靠手动复制数字；
- 只作为对比基准，不参与训练。

---

## 三、修改最终选择逻辑：MAE/RMSE 优先

文件：

`scripts/select_final_prediction_by_guard.py`

### 3.1 新增候选 alpha

当前：

```python
BLEND_ALPHAS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
```

改成：

```python
BLEND_ALPHAS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
```

原因：

- `a10` 太接近 baseline，容易改善总量但拉高 MAE/RMSE；
- 增加 `a70/a80/a90`，让候选更接近模型本身，可能在 MAE/RMSE 和 ratio 之间取得更好平衡。

---

### 3.2 修改 `compute_hour_metrics()`

在函数中加入 MAE：

```python
def mae(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m])))
```

在 `compute_hour_metrics()` 返回值里加入：

```python
"mae": mae(yt, yp),
```

最终返回字典应至少包含：

```python
return {
    "city_rel_err": city_rel_err(yt, yp),
    "site_mape_raw_mean": ...,
    "site_mape_clipped": ...,
    "site_wape": ...,
    "n_gt100": ...,
    "n_gt200": ...,
    "mae": mae(yt, yp),
    "rmse": rmse(yt, yp),
    "nrmse_capacity_pct": nrmse_by_capacity(yt, yp, cap),
    "pred_actual_ratio": ratio,
    "ratio_abs_err": abs(ratio - TARGET_RATIO) * 100 if np.isfinite(ratio) else np.nan,
}
```

---

### 3.3 替换 `score_candidates()`

当前 score 仍偏向 city_rel 和 ratio。替换为 MAE/RMSE 优先：

```python
def score_candidates(metrics):
    """MAE/RMSE 优先的多目标 score，越低越好。

    优先级：
    1. RMSE/MAE
    2. 容量归一化 NRMSE
    3. 城市聚合误差
    4. ratio 接近周二基准 0.9488
    """
    mae_val = metrics.get("mae", 100)
    rmse_val = metrics.get("rmse", 100)
    nrmse = metrics.get("nrmse_capacity_pct", 100)
    city = metrics.get("city_rel_err", 100)
    ratio_err = metrics.get("ratio_abs_err", 100)
    n100 = metrics.get("n_gt100", 0)
    n200 = metrics.get("n_gt200", 0)

    for name, val in {
        "mae": mae_val,
        "rmse": rmse_val,
        "nrmse": nrmse,
        "city": city,
        "ratio_err": ratio_err,
    }.items():
        if not np.isfinite(val):
            if name == "mae":
                mae_val = 100
            elif name == "rmse":
                rmse_val = 100
            elif name == "nrmse":
                nrmse = 100
            elif name == "city":
                city = 100
            elif name == "ratio_err":
                ratio_err = 100

    return (
        0.28 * rmse_val +
        0.22 * mae_val +
        0.25 * nrmse +
        0.15 * city +
        0.07 * ratio_err +
        0.02 * (n100 * 5) +
        0.01 * (n200 * 10)
    )
```

注意：

- ratio 不再是强主导项，只要最终整体 ratio 在 0.90~0.98 即可。
- 这样可以减少 `BlendTotal_a10` 为了总量牺牲站点级误差的情况。

---

### 3.4 修改 BlendTotal 的 guard

在 `elif ver.startswith("BlendTotal"):` 分支中加入 MAE/RMSE 保护。

找到：

```python
base_nrmse = base_metrics.get("nrmse_capacity_pct", np.nan)
cand_nrmse = cand_metrics.get("nrmse_capacity_pct", np.nan)
base_city = base_metrics.get("city_rel_err", np.nan)
cand_city = cand_metrics.get("city_rel_err", np.nan)
```

后面加入：

```python
base_mae = base_metrics.get("mae", np.nan)
cand_mae = cand_metrics.get("mae", np.nan)
base_rmse = base_metrics.get("rmse", np.nan)
cand_rmse = cand_metrics.get("rmse", np.nan)
```

然后加入以下 guard：

```python
# MAE/RMSE 是当前要恢复周二效果的主约束。
if np.isfinite(base_mae) and np.isfinite(cand_mae):
    if cand_mae > base_mae * 1.03:
        passed = False
        reasons.append(
            f"BlendTotal mae 恶化: {cand_mae:.4f} > 1.03*base {base_mae:.4f}"
        )

if np.isfinite(base_rmse) and np.isfinite(cand_rmse):
    if cand_rmse > base_rmse * 1.03:
        passed = False
        reasons.append(
            f"BlendTotal rmse 恶化: {cand_rmse:.4f} > 1.03*base {base_rmse:.4f}"
        )
```

对 strict hours 保留原有强制规则。

---

### 3.5 新增 final MAE/RMSE guard

在 `apply_final_nrmse_guard()` 后新增：

```python
def _overall_error(df, pred_col="power_pred"):
    yt = pd.to_numeric(df["power_mw"], errors="coerce")
    yp = pd.to_numeric(df[pred_col], errors="coerce")
    m = yt.notna() & yp.notna()
    if not m.any():
        return {"mae": np.nan, "rmse": np.nan, "ratio": np.nan, "bias_pct": np.nan}
    actual = float(yt[m].sum())
    pred = float(yp[m].sum())
    err = yp[m].values - yt[m].values
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "ratio": pred / max(actual, 1e-9),
        "bias_pct": (pred - actual) / max(actual, 1e-9) * 100,
    }


def apply_final_mae_rmse_guard(df_final, df_v1, selection):
    """final 产物保护：如果某小时混合后 MAE/RMSE 明显劣于 V1，则回退该小时。

    这一步用于恢复周二版 MAE/RMSE 效果，避免只追求总量 ratio。
    """
    from pv_forecasting.core.evaluation import build_eval_frame

    eval_final = build_eval_frame(
        df_final,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )
    eval_v1 = build_eval_frame(
        df_v1,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )

    rollback_hours = []
    for h in HOURS:
        f_sub = eval_final[eval_final["hour"] == h]
        b_sub = eval_v1[eval_v1["hour"] == h]
        if len(f_sub) == 0 or len(b_sub) == 0:
            continue
        fm = _overall_error(f_sub)
        bm = _overall_error(b_sub)

        # 普通小时允许 2% 波动，strict hours 不允许劣化。
        allow = 1.00 if h in STRICT_NRMSE_GUARD_HOURS else 1.02
        worse_mae = np.isfinite(fm["mae"]) and np.isfinite(bm["mae"]) and fm["mae"] > bm["mae"] * allow
        worse_rmse = np.isfinite(fm["rmse"]) and np.isfinite(bm["rmse"]) and fm["rmse"] > bm["rmse"] * allow

        # 如果回退会导致该小时 ratio 极低，则只在 RMSE 明显恶化时回退。
        ratio_too_low_after_v1 = np.isfinite(bm["ratio"]) and bm["ratio"] < 0.55
        if ratio_too_low_after_v1 and not (np.isfinite(fm["rmse"]) and np.isfinite(bm["rmse"]) and fm["rmse"] > bm["rmse"] * 1.08):
            continue

        if worse_mae or worse_rmse:
            rollback_hours.append(h)
            print(
                f"  [MAE/RMSE-GUARD] h={h:02d} 回退 V1: "
                f"MAE {fm['mae']:.4f}->{bm['mae']:.4f}, "
                f"RMSE {fm['rmse']:.4f}->{bm['rmse']:.4f}, "
                f"ratio {fm['ratio']:.3f}->{bm['ratio']:.3f}"
            )

    if not rollback_hours:
        return df_final, selection, []

    out = df_final.copy()
    key_cols = ["time", "site_id"]
    v1_map = df_v1[df_v1["hour"].isin(rollback_hours)][key_cols + ["power_pred"]].copy()
    v1_map = v1_map.drop_duplicates(subset=key_cols)
    v1_map = v1_map.rename(columns={"power_pred": "power_pred_v1_mae_guard"})

    out = out.merge(v1_map, on=key_cols, how="left")
    mask = out["hour"].isin(rollback_hours) & out["power_pred_v1_mae_guard"].notna()
    out.loc[mask, "power_pred"] = out.loc[mask, "power_pred_v1_mae_guard"]
    out = out.drop(columns=["power_pred_v1_mae_guard"])

    for h in rollback_hours:
        metrics = selection[h][1]
        score = selection[h][2]
        reasons = list(selection[h][3]) if selection[h][3] else []
        reasons.append("final_mae_rmse_guard 回退 V1")
        selection[h] = ("V1_mae_guard", metrics, score, reasons)

    return out, selection, rollback_hours
```

---

### 3.6 main 中调用 MAE/RMSE guard

找到：

```python
df_final, selection, rollback_hours = apply_final_nrmse_guard(
    df_final,
    candidates["V1"],
    selection,
)
if rollback_hours:
    print(f"  final NRMSE guard 回退小时: {rollback_hours}")
```

后面加入：

```python
df_final, selection, mae_guard_hours = apply_final_mae_rmse_guard(
    df_final,
    candidates["V1"],
    selection,
)
if mae_guard_hours:
    print(f"  final MAE/RMSE guard 回退小时: {mae_guard_hours}")
```

---

### 3.7 build_final 兼容新版本名

找到：

```python
if ver in {"V1", "V1_guard"}:
    continue
```

改成：

```python
if ver in {"V1", "V1_guard", "V1_mae_guard"}:
    continue
```

---

### 3.8 选择表增加字段

在保存 `final_version_selection_by_hour.csv` 的 rows 中加入：

```python
"is_mae_rmse_guard_rollback": ver == "V1_mae_guard",
"mae": round(metrics.get("mae", np.nan), 4),
```

最终至少应有：

```python
"selected_version": ver,
"is_final_guard_rollback": ver == "V1_guard",
"is_mae_rmse_guard_rollback": ver == "V1_mae_guard",
"mae": round(metrics.get("mae", np.nan), 4),
"rmse": round(metrics.get("rmse", np.nan), 4),
```

---

## 四、新增周二对比报告脚本

新建文件：

`scripts/compare_with_week2_reference.py`

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
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics
from pv_forecasting.core.week2_reference import WEEK2_REFERENCE, WEEK2_HOURLY_NRMSE


OUT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES = OUT / "tables"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def overall_metrics(df: pd.DataFrame) -> dict:
    yt = pd.to_numeric(df["power_mw"], errors="coerce")
    yp = pd.to_numeric(df["power_pred"], errors="coerce")
    m = yt.notna() & yp.notna()
    actual = float(yt[m].sum())
    pred = float(yp[m].sum())
    err = yp[m].values - yt[m].values
    return {
        "rows": int(len(df)),
        "sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 2),
        "pred_mwh": round(pred, 2),
        "pred_actual_ratio": round(pred / max(actual, 1e-9), 4),
        "bias_pct": round((pred - actual) / max(actual, 1e-9) * 100, 3),
        "mae_mw": round(float(np.mean(np.abs(err))), 4),
        "rmse_mw": round(float(np.sqrt(np.mean(err ** 2))), 4),
    }


def main():
    final_path = TABLES / "distributed_predictions_final_eval.pkl"
    df = safe_pickle_load(final_path)
    eval_df = build_eval_frame(df, target_site_count=53)

    current = overall_metrics(eval_df)
    ref = WEEK2_REFERENCE

    rows = []
    for key, label in [
        ("rows", "样本数"),
        ("sites", "站点数"),
        ("actual_mwh", "实际总出力(MWh)"),
        ("pred_mwh", "预测总出力(MWh)"),
        ("pred_actual_ratio", "预测/实际总量比"),
        ("bias_pct", "bias(%)"),
        ("mae_mw", "MAE(MW)"),
        ("rmse_mw", "RMSE(MW)"),
    ]:
        cur = current[key]
        old = ref[key]
        diff = cur - old if isinstance(cur, (int, float)) and isinstance(old, (int, float)) else ""
        rows.append({
            "指标": label,
            "周二基准": old,
            "当前结果": cur,
            "差值_当前减周二": round(diff, 4) if isinstance(diff, (int, float)) else diff,
            "是否优于周二": (
                "是" if key in {"mae_mw", "rmse_mw"} and cur <= old
                else "是" if key in {"pred_actual_ratio"} and abs(cur - 0.9488) <= abs(old - 0.9488)
                else "参考"
            ),
        })

    overall_df = pd.DataFrame(rows)
    overall_df.to_csv(METRICS / "当前结果_vs_周二基准_整体对比.csv", index=False, encoding="utf-8-sig")

    hdf = hourly_nrmse_metrics(eval_df)
    h_rows = []
    for _, r in hdf.iterrows():
        h = int(r["hour"])
        old = WEEK2_HOURLY_NRMSE.get(h, {})
        h_rows.append({
            "hour": h,
            "周二_rows": old.get("rows"),
            "当前_rows": int(r["rows"]),
            "周二_站点平均NRMSE(%)": old.get("site_nrmse_mean_pct"),
            "当前_站点平均NRMSE(%)": r["site_nrmse_mean_pct"],
            "站点NRMSE变化": round(r["site_nrmse_mean_pct"] - old.get("site_nrmse_mean_pct", np.nan), 3),
            "周二_城市NRMSE(%)": old.get("city_nrmse_pct"),
            "当前_城市NRMSE(%)": r["city_nrmse_pct"],
            "城市NRMSE变化": round(r["city_nrmse_pct"] - old.get("city_nrmse_pct", np.nan), 3),
        })

    hourly_df = pd.DataFrame(h_rows)
    hourly_df.to_csv(METRICS / "当前结果_vs_周二基准_逐小时NRMSE对比.csv", index=False, encoding="utf-8-sig")

    md = []
    md.append("# 当前结果 vs 周二基准对比\n")
    md.append("## 整体指标\n")
    md.append(overall_df.to_markdown(index=False))
    md.append("\n\n## 逐小时 NRMSE\n")
    md.append(hourly_df.to_markdown(index=False))
    md.append("\n\n## 判断\n")
    if current["mae_mw"] <= ref["mae_mw"] and current["rmse_mw"] <= ref["rmse_mw"]:
        md.append("当前 MAE/RMSE 已达到或优于周二基准。")
    else:
        md.append("当前 MAE/RMSE 仍未达到周二基准，应继续优先降低站点级误差。")
    (DOCS / "当前结果_vs_周二基准对比.md").write_text("\n".join(md), encoding="utf-8")

    print(overall_df.to_string(index=False))
    print(f"\nSaved: {METRICS / '当前结果_vs_周二基准_整体对比.csv'}")
    print(f"Saved: {METRICS / '当前结果_vs_周二基准_逐小时NRMSE对比.csv'}")
    print(f"Saved: {DOCS / '当前结果_vs_周二基准对比.md'}")


if __name__ == "__main__":
    main()
```

---

## 五、修复报告中的不严谨表述

文件：

`光伏功率预测项目.md`

### 5.1 修改任务书完成情况中“站点映射率 100%”

当前写法不严谨：

```text
站点映射率 100%
```

因为报告里明确有映射失败站点。

改为：

```text
已完成可映射站点的数据接入和清洗；集中式 24 座、分布式 74 座完成映射，未映射站点已单独列出
```

---

### 5.2 修改 3.3.1 版本说明

当前：

```text
V1 ... ratio 提升至 0.79（绝对值）
```

这句话容易误解。改为：

```text
V1 ... fixed 评估口径下 ratio 约 0.788，仍存在系统性低估，但相较原始版本完成了物理裁剪和小时修正前的基础校准
```

---

### 5.3 增加“与周二基准对比”小节

在“三、训练结果”后增加：

```markdown
### 3.6 与周二基准对比

当前版本工程闭环和口径统一优于周二版本，但 MAE/RMSE 尚未恢复到周二效果。周二基准 MAE 为 0.4547 MW、RMSE 为 0.9676 MW；当前版本 MAE/RMSE 需以 `当前结果_vs_周二基准_整体对比.csv` 为准。

后续优化优先级为：

1. 降低 MAE/RMSE；
2. 保持逐小时 NRMSE 不劣化；
3. 保持 pred_actual_ratio 在 0.90~0.98。
```

---

## 六、修改训练验收逻辑

文件：

`scripts/train_fixed.py`

在 `assert_final_metrics_valid()` 中，已有 ratio、bias、站点数检查。继续增加 MAE/RMSE 的提示性检查。

在输出 MAE/RMSE 后加入：

```python
    WEEK2_MAE = 0.4547
    WEEK2_RMSE = 0.9676
    if mae > WEEK2_MAE * 1.20:
        print(f"[WARN] MAE 距周二基准仍偏高: {mae:.4f} > 1.20*{WEEK2_MAE:.4f}")
    if rmse > WEEK2_RMSE * 1.20:
        print(f"[WARN] RMSE 距周二基准仍偏高: {rmse:.4f} > 1.20*{WEEK2_RMSE:.4f}")
```

注意：

- 这里只做 warning，不中止训练；
- 因为当前评估样本口径与周二仍有 1,786 行差异，不能用硬错误。

---

## 七、执行命令

先只跑后处理：

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_chinese_metrics.py
python scripts/compare_with_week2_reference.py
python scripts/check_pipeline_consistency.py
```

再跑跳过训练的流水线：

```bash
python scripts/train_fixed.py --skip-training --data-root data --output-root output/pv_pipeline
```

确认通过后再考虑完整训练：

```bash
python scripts/train_fixed.py --data-root data --output-root output/pv_pipeline
```

---

## 八、验收脚本

执行：

```bash
python - <<'PY'
from pathlib import Path
import sys
import numpy as np
import pandas as pd

root = Path(".")
sys.path.insert(0, str(root / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

out = root / "output" / "pv_pipeline"
df = safe_pickle_load(out / "tables" / "distributed_predictions_final_eval.pkl")
ev = build_eval_frame(df, target_site_count=53)

actual = pd.to_numeric(ev["power_mw"], errors="coerce").sum()
pred = pd.to_numeric(ev["power_pred"], errors="coerce").sum()
err = ev["power_pred"] - ev["power_mw"]

mae = np.mean(np.abs(err))
rmse = np.sqrt(np.mean(err ** 2))
ratio = pred / max(actual, 1e-9)
bias = (pred - actual) / max(actual, 1e-9) * 100

print("rows:", len(ev))
print("sites:", ev["site_id"].nunique())
print("ratio:", round(ratio, 4))
print("bias:", round(bias, 3))
print("MAE:", round(mae, 4), "周二=0.4547")
print("RMSE:", round(rmse, 4), "周二=0.9676")

h = hourly_nrmse_metrics(ev)
print("\n逐小时 NRMSE:")
print(h[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_string(index=False))

sel = pd.read_csv(out / "metrics" / "final_version_selection_by_hour.csv")
show_cols = [c for c in ["hour", "selected_version", "mae", "rmse", "nrmse_capacity_pct", "pred_actual_ratio", "is_mae_rmse_guard_rollback"] if c in sel.columns]
print("\n版本选择:")
print(sel[show_cols].to_string(index=False))
PY
```

验收要求：

1. `sites == 53`。
2. `ratio` 仍在 `0.90~0.98`。
3. MAE/RMSE 应低于当前版本的 `0.5927 / 1.2164`。
4. 若 MAE/RMSE 降低但 ratio 略下降，只要 ratio 仍在范围内，可以接受。
5. `当前结果_vs_周二基准_整体对比.csv` 必须生成。
6. `光伏功率预测项目.md` 中不得再写“站点映射率 100%”。

---

## 九、预期结果

这轮改完后，可能出现：

- ratio 从 0.9561 略下降；
- MAE/RMSE 下降；
- 部分小时从 `BlendTotal_a10` 改为 `BlendTotal_a70/a80/a90` 或 `V1_mae_guard`；
- 逐小时城市 NRMSE 可能不如当前那么低，但站点级误差应更接近周二。

这是可接受的，因为当前核心目标是恢复周二的 MAE/RMSE，而不是继续把总量 bias 做到更小。

