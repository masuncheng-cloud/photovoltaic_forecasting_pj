# Cursor 下一步修改方案：10-14 点站点级 NRMSE 专项优化

## 一、当前问题

当前版本相比周二版，工程闭环更完整，但 **10-14 点主体发电时段的站点平均 NRMSE 明显偏高**，这是 MAE/RMSE 无法恢复周二效果的主要原因。

当前 vs 周二逐小时站点平均 NRMSE：

| 小时 | 周二站点平均 NRMSE（%） | 当前站点平均 NRMSE（%） | 差值 |
|:---:|---:|---:|---:|
| 10 | 11.63 | 13.43 | +1.80 |
| 11 | 12.02 | 14.93 | +2.91 |
| 12 | 12.48 | 15.54 | +3.06 |
| 13 | 12.50 | 15.51 | +3.01 |
| 14 | 11.55 | 13.60 | +2.05 |

说明：

- 当前 `BlendTotal_a10` 对城市聚合 NRMSE 很友好，但对站点级 NRMSE 不够友好。
- 10-14 点是主体发电时段，真实功率高、样本多，站点级误差应该优先优化。
- 本轮目标不是继续压低城市 NRMSE，而是降低 10-14 点站点平均 NRMSE。

本轮优化优先级：

```text
10-14 点站点平均 NRMSE 降低
> 全局 MAE/RMSE 不明显变差
> pred_actual_ratio 保持在 0.90~0.98
> 城市 NRMSE 可小幅波动
```

---

## 二、核心策略

新增一个 **midday 站点级校准器**，只作用于 10-14 点。

思路：

1. 仍保留当前 V1 / BlendTotal 候选。
2. 对 10-14 点，使用 valid 集学习站点级缩放系数。
3. 校准目标改为容量归一化 RMSE，即：

```text
NRMSE_site = RMSE(site, hour) / capacity_mw × 100%
```

4. 对每个 `(site_id, hour)` 学一个 shrinkage 后的乘法校准系数：

```text
P_calibrated = clip(P_base_candidate × k_site_hour, 0, capacity_mw)
```

5. `k_site_hour` 从 valid 集估计，样本少时向小时整体系数收缩，避免过拟合。
6. final 选择时，10-14 点优先比较：

```text
V1
BlendTotal_a10~a90
MiddaySiteCalibrated
```

7. test 集只用于最终评估，不参与参数学习和版本选择。

---

## 三、新增脚本：`scripts/apply_midday_site_nrmse_calibration.py`

新建文件：

`scripts/apply_midday_site_nrmse_calibration.py`

写入以下完整代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点站点级 NRMSE 专项校准
============================

只使用 valid 集学习校准参数，然后应用到 full 表。

输出：
- tables/distributed_predictions_midday_site_calibrated_full.pkl
- tables/distributed_predictions_midday_site_calibrated_eval.pkl
- metrics/midday_site_calibration_params.csv
- metrics/midday_site_calibration_valid_ablation.csv
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics


TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

IN_FULL = TABLES_DIR / "distributed_predictions_final_full.pkl"
if not IN_FULL.exists():
    IN_FULL = TABLES_DIR / "distributed_predictions_fixed_full.pkl"

OUT_FULL = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_midday_site_calibrated_eval.pkl"
OUT_PARAMS = METRICS_DIR / "midday_site_calibration_params.csv"
OUT_VALID = METRICS_DIR / "midday_site_calibration_valid_ablation.csv"


def _ensure_basic_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.date
    return out


def _site_hour_scale(y_true, y_pred, cap, min_rows=40):
    """最小二乘乘法校准系数，目标 y ≈ k * pred。"""
    yt = pd.to_numeric(y_true, errors="coerce").to_numpy(dtype=float)
    yp = pd.to_numeric(y_pred, errors="coerce").to_numpy(dtype=float)
    cp = pd.to_numeric(cap, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(yt) & np.isfinite(yp) & np.isfinite(cp) & (yt > 0) & (yp > 0) & (cp > 0)
    if int(m.sum()) < min_rows:
        return np.nan, int(m.sum())
    denom = float(np.sum(yp[m] ** 2))
    if denom <= 1e-9:
        return np.nan, int(m.sum())
    k = float(np.sum(yt[m] * yp[m]) / denom)
    return k, int(m.sum())


def _capacity_nrmse(df: pd.DataFrame, pred_col: str = "power_pred") -> float:
    yt = pd.to_numeric(df["power_mw"], errors="coerce").to_numpy(dtype=float)
    yp = pd.to_numeric(df[pred_col], errors="coerce").to_numpy(dtype=float)
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(yt) & np.isfinite(yp) & np.isfinite(cap) & (cap > 0)
    if not m.any():
        return np.nan
    rmse = float(np.sqrt(np.mean((yt[m] - yp[m]) ** 2)))
    return rmse / float(np.nanmean(cap[m])) * 100.0


def _make_pred_candidate(df: pd.DataFrame, alpha: float) -> pd.Series:
    """alpha * 当前模型预测 + (1-alpha) * pred_baseline。"""
    ml = pd.to_numeric(df["power_pred"], errors="coerce")
    if "pred_baseline" not in df.columns:
        return ml
    bl = pd.to_numeric(df["pred_baseline"], errors="coerce")
    pred = alpha * ml + (1.0 - alpha) * bl
    return pred.fillna(ml).fillna(bl)


def learn_params(df: pd.DataFrame) -> pd.DataFrame:
    """在 valid 集上学习小时级、站点小时级校准参数。"""
    valid = df[
        (df["split"] == "valid")
        & (df["hour"].isin(MIDDAY_HOURS))
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    if valid.empty:
        raise RuntimeError("valid 集为空，无法学习 midday 校准参数")

    rows = []

    # 候选 alpha：主体时段不应过度靠 baseline，保留偏 ML 的候选。
    alpha_grid = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

    for h in MIDDAY_HOURS:
        vh = valid[valid["hour"] == h].copy()
        if vh.empty:
            continue

        # 先在 valid 上选一个小时级最优 alpha，目标是站点平均 NRMSE。
        alpha_scores = []
        for alpha in alpha_grid:
            vh[f"pred_alpha"] = _make_pred_candidate(vh, alpha)
            site_scores = []
            for _, sg in vh.groupby("site_id"):
                nr = _capacity_nrmse(sg.rename(columns={"pred_alpha": "power_pred"}), "power_pred")
                if np.isfinite(nr):
                    site_scores.append(nr)
            score = float(np.nanmean(site_scores)) if site_scores else np.nan
            alpha_scores.append((alpha, score))

        alpha_scores = [(a, s) for a, s in alpha_scores if np.isfinite(s)]
        best_alpha = min(alpha_scores, key=lambda x: x[1])[0] if alpha_scores else 1.0
        vh["pred_alpha"] = _make_pred_candidate(vh, best_alpha)

        # 小时整体 k
        hour_k, hour_n = _site_hour_scale(vh["power_mw"], vh["pred_alpha"], vh["capacity_mw"], min_rows=80)
        if not np.isfinite(hour_k):
            hour_k = 1.0

        for sid, sg in vh.groupby("site_id"):
            site_k, n = _site_hour_scale(sg["power_mw"], sg["pred_alpha"], sg["capacity_mw"], min_rows=30)

            # shrinkage：样本少时向小时整体系数收缩。
            if np.isfinite(site_k):
                weight = n / (n + 80.0)
                k = weight * site_k + (1.0 - weight) * hour_k
            else:
                weight = 0.0
                k = hour_k

            # 防止过度校准。
            k = float(np.clip(k, 0.75, 1.25))

            rows.append({
                "hour": int(h),
                "site_id": sid,
                "best_alpha": float(best_alpha),
                "hour_k": float(hour_k),
                "site_k_raw": float(site_k) if np.isfinite(site_k) else np.nan,
                "k_final": k,
                "n_valid": int(n),
                "shrink_weight": round(float(weight), 4),
            })

    params = pd.DataFrame(rows)
    if params.empty:
        raise RuntimeError("未学习到任何 midday 校准参数")
    return params


def apply_params(df: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_row_order"] = np.arange(len(out))

    p = params[["hour", "site_id", "best_alpha", "k_final"]].copy()
    out = out.merge(p, on=["hour", "site_id"], how="left")

    mask = out["hour"].isin(MIDDAY_HOURS) & out["best_alpha"].notna()
    pred_alpha = _make_pred_candidate(out, 1.0)

    # 对有 best_alpha 的行逐行计算 alpha blend。
    if "pred_baseline" in out.columns:
        ml = pd.to_numeric(out["power_pred"], errors="coerce")
        bl = pd.to_numeric(out["pred_baseline"], errors="coerce")
        pred_alpha = out["best_alpha"].astype(float) * ml + (1.0 - out["best_alpha"].astype(float)) * bl
        pred_alpha = pred_alpha.fillna(ml).fillna(bl)

    calibrated = pred_alpha * pd.to_numeric(out["k_final"], errors="coerce")
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(0.0)
    calibrated = calibrated.clip(lower=0.0, upper=cap)

    out["power_pred_before_midday_calibration"] = out["power_pred"]
    out.loc[mask, "power_pred"] = calibrated[mask]

    out = out.sort_values("_row_order").drop(columns=["_row_order", "best_alpha", "k_final"])
    return out


def valid_ablation(df_before: pd.DataFrame, df_after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    before = df_before[
        (df_before["split"] == "valid")
        & (df_before["hour"].isin(MIDDAY_HOURS))
        & (~df_before["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df_before["power_mw"], errors="coerce") > 0)
    ].copy()
    after = df_after[
        (df_after["split"] == "valid")
        & (df_after["hour"].isin(MIDDAY_HOURS))
        & (~df_after["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df_after["power_mw"], errors="coerce") > 0)
    ].copy()

    for h in MIDDAY_HOURS:
        b = before[before["hour"] == h]
        a = after[after["hour"] == h]
        if len(b) == 0 or len(a) == 0:
            continue
        rows.append({
            "hour": h,
            "valid_rows": len(a),
            "before_site_nrmse_mean_pct": hourly_nrmse_metrics(b).iloc[0]["site_nrmse_mean_pct"],
            "after_site_nrmse_mean_pct": hourly_nrmse_metrics(a).iloc[0]["site_nrmse_mean_pct"],
            "before_city_nrmse_pct": hourly_nrmse_metrics(b).iloc[0]["city_nrmse_pct"],
            "after_city_nrmse_pct": hourly_nrmse_metrics(a).iloc[0]["city_nrmse_pct"],
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("10-14 点站点级 NRMSE 专项校准")
    print("=" * 70)
    print(f"读取: {IN_FULL}")

    df = safe_pickle_load(IN_FULL)
    df = _ensure_basic_columns(df)

    params = learn_params(df)
    params.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"已保存参数: {OUT_PARAMS}")

    df_cal = apply_params(df, params)

    ab = valid_ablation(df, df_cal)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print(f"已保存 valid 消融: {OUT_VALID}")
    print(ab.to_string(index=False))

    eval_cal = build_eval_frame(
        df_cal,
        pred_col="power_pred",
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        df_cal,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    write_prediction_pickle_atomic(
        eval_cal,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )

    print(f"已保存: {OUT_FULL}")
    print(f"已保存: {OUT_EVAL}")
    print("Done.")


if __name__ == "__main__":
    main()
```

---

## 四、修改最终选择脚本，加入 MiddayCalibrated 候选

文件：

`scripts/select_final_prediction_by_guard.py`

### 4.1 新增常量

在常量区加入：

```python
MIDDAY_NRMSE_PRIORITY_HOURS = [10, 11, 12, 13, 14]
```

---

### 4.2 加载 MiddayCalibrated 候选

在 `load_candidates()` 里，加载 V3 后、BaselineTotal 前，加入：

```python
# Midday site NRMSE calibrated candidate
try:
    midday_path = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
    if midday_path.exists():
        df = pd.read_pickle(midday_path)
        df["time"] = pd.to_datetime(df["time"])
        df["hour"] = df["time"].dt.hour
        candidates["MiddaySiteCalibrated"] = df
        print(f"  MiddaySiteCalibrated: {len(df):,} 行")
    else:
        print("  MiddaySiteCalibrated: 文件不存在，跳过")
except Exception as e:
    print(f"  MiddaySiteCalibrated 加载失败: {e}")
```

---

### 4.3 修改 score：10-14 点更重视站点 NRMSE

当前 `score_candidates(metrics)` 没有 hour 参数。改成：

```python
def score_candidates(metrics, hour=None):
```

然后在函数开头加：

```python
is_midday_priority = hour in MIDDAY_NRMSE_PRIORITY_HOURS if hour is not None else False
```

将 return 改为：

```python
if is_midday_priority:
    return (
        0.45 * nrmse +
        0.25 * rmse_val +
        0.15 * mae_val +
        0.08 * city +
        0.04 * ratio_err +
        0.02 * (n100 * 5) +
        0.01 * (n200 * 10)
    )

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

同时把所有调用：

```python
score_candidates(...)
```

改成：

```python
score_candidates(..., hour=h)
```

包括：

```python
base_score = score_candidates(base_metrics, hour=h)
sc = score_candidates(cand_metrics, hour=h)
```

---

### 4.4 对 MiddaySiteCalibrated 使用更合适的 guard

在 `select_per_hour()` 遍历候选时，找到：

```python
elif ver.startswith("BlendTotal"):
```

在它前面加入：

```python
elif ver == "MiddaySiteCalibrated":
    reasons = []
    passed = True

    if h not in MIDDAY_NRMSE_PRIORITY_HOURS:
        passed = False
        reasons.append("MiddaySiteCalibrated 只允许用于 10-14 点")
    else:
        base_nrmse = base_metrics.get("nrmse_capacity_pct", np.nan)
        cand_nrmse = cand_metrics.get("nrmse_capacity_pct", np.nan)
        base_rmse = base_metrics.get("rmse", np.nan)
        cand_rmse = cand_metrics.get("rmse", np.nan)
        base_ratio = base_metrics.get("pred_actual_ratio", np.nan)
        cand_ratio = cand_metrics.get("pred_actual_ratio", np.nan)

        # 10-14 点目标：站点 NRMSE 必须不劣化，最好改善。
        if np.isfinite(base_nrmse) and np.isfinite(cand_nrmse):
            if cand_nrmse > base_nrmse * 1.01:
                passed = False
                reasons.append(
                    f"Midday nrmse 未改善: {cand_nrmse:.2f} > 1.01*base {base_nrmse:.2f}"
                )

        # RMSE 不允许明显变差。
        if np.isfinite(base_rmse) and np.isfinite(cand_rmse):
            if cand_rmse > base_rmse * 1.03:
                passed = False
                reasons.append(
                    f"Midday rmse 恶化: {cand_rmse:.4f} > 1.03*base {base_rmse:.4f}"
                )

        # ratio 只设置宽松底线，防止明显异常。
        if np.isfinite(cand_ratio) and cand_ratio < 0.80:
            passed = False
            reasons.append(f"Midday ratio 过低: {cand_ratio:.3f} < 0.80")
```

---

### 4.5 选择表增加 midday 标记

保存 `final_version_selection_by_hour.csv` 时，在 rows 中加入：

```python
"is_midday_nrmse_priority": int(h in MIDDAY_NRMSE_PRIORITY_HOURS),
```

---

## 五、修改训练流水线，加入 midday 校准脚本

文件：

`scripts/train_fixed.py`

找到 `FIX_SCRIPTS`，在：

```python
ROOT / 'scripts' / 'evaluate_fixed_predictions.py',
ROOT / 'scripts' / 'select_final_prediction_by_guard.py',
```

之间插入：

```python
ROOT / 'scripts' / 'apply_midday_site_nrmse_calibration.py',
```

也就是：

```python
FIX_SCRIPTS = [
    ROOT / 'scripts' / 'rebuild_fixed_predictions.py',
    ROOT / 'scripts' / 'check_gblend_time_alignment.py',
    ROOT / 'scripts' / 'fix_hourly_bias.py',
    ROOT / 'scripts' / 'apply_p0_p1_fix_v2.py',
    ROOT / 'scripts' / 'evaluate_fixed_predictions.py',
    ROOT / 'scripts' / 'apply_midday_site_nrmse_calibration.py',
    ROOT / 'scripts' / 'select_final_prediction_by_guard.py',
    ROOT / 'scripts' / 'regenerate_chinese_metrics.py',
    ROOT / 'scripts' / 'compare_with_week2_reference.py',
    ROOT / 'scripts' / 'update_project_md_metrics.py',
    ROOT / 'scripts' / 'check_pipeline_consistency.py',
]
```

同时在 `CRITICAL_SCRIPTS` 加入：

```python
'apply_midday_site_nrmse_calibration.py',
```

在 `KEY_OUTPUT_FILES` 加入：

```python
'tables/distributed_predictions_midday_site_calibrated_full.pkl',
'tables/distributed_predictions_midday_site_calibrated_eval.pkl',
'metrics/midday_site_calibration_params.csv',
'metrics/midday_site_calibration_valid_ablation.csv',
```

---

## 六、修改中文指标和报告输出

文件：

`scripts/update_project_md_metrics.py`

在生成“当前最终结果摘要.md”时，加入 10-14 点专项表。

在逐小时 NRMSE 后面追加：

```python
midday = h[h["hour"].isin([10, 11, 12, 13, 14])].copy()
lines.append("\n## 10-14 点专项 NRMSE\n")
lines.append(midday.to_string(index=False))
lines.append(
    "\n说明：10-14 点为主体发电时段，本轮优先优化站点平均 NRMSE；"
    "若城市 NRMSE 小幅波动但站点 NRMSE 下降，视为有效改善。"
)
```

如果存在：

```text
output/pv_pipeline/metrics/midday_site_calibration_valid_ablation.csv
```

也读取并写入：

```python
midday_ab_path = METRICS / "midday_site_calibration_valid_ablation.csv"
if midday_ab_path.exists():
    ab = pd.read_csv(midday_ab_path)
    lines.append("\n## Midday 校准 Valid 消融\n")
    lines.append(ab.to_string(index=False))
```

---

## 七、新增检查脚本：10-14 点 NRMSE 专项验收

新建：

`scripts/check_midday_nrmse_improvement.py`

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
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics
from pv_forecasting.core.week2_reference import WEEK2_HOURLY_NRMSE

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]


def main():
    final_df = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
    final_eval = build_eval_frame(final_df, target_site_count=53)
    h = hourly_nrmse_metrics(final_eval)

    rows = []
    ok_count = 0
    for _, r in h[h["hour"].isin(MIDDAY)].iterrows():
        hour = int(r["hour"])
        current = float(r["site_nrmse_mean_pct"])
        ref = float(WEEK2_HOURLY_NRMSE[hour]["site_nrmse_mean_pct"])
        diff = current - ref
        ok = current <= ref + 0.50
        if ok:
            ok_count += 1
        rows.append({
            "hour": hour,
            "current_site_nrmse_pct": current,
            "week2_site_nrmse_pct": ref,
            "diff_current_minus_week2": round(diff, 3),
            "pass_within_0_5pct": ok,
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "midday_nrmse_acceptance.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if ok_count < 3:
        raise SystemExit(
            f"10-14 点站点 NRMSE 改善不足：只有 {ok_count}/5 个小时接近周二水平"
        )
    print(f"[OK] 10-14 点 NRMSE 验收通过：{ok_count}/5 个小时接近周二水平")


if __name__ == "__main__":
    main()
```

说明：

- 目标不是一次全部超过周二，而是先要求至少 3/5 个小时接近周二。
- 阈值 `周二 + 0.5 个百分点`，比当前状态严格得多。

---

## 八、执行命令

本轮先不完整重训，只跑后处理：

```bash
cd /root/autodl-tmp/photovoltaic_forecasting_pj

python scripts/apply_midday_site_nrmse_calibration.py
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_chinese_metrics.py
python scripts/compare_with_week2_reference.py
python scripts/update_project_md_metrics.py
python scripts/check_midday_nrmse_improvement.py
python scripts/check_pipeline_consistency.py
```

如果通过，再跑：

```bash
python scripts/train_fixed.py --skip-training --data-root data --output-root output/pv_pipeline
```

暂时不要完整重训，先确认后处理能不能压低 10-14 点站点 NRMSE。

---

## 九、验收标准

### 9.1 主验收

查看：

```text
output/pv_pipeline/metrics/midday_nrmse_acceptance.csv
```

要求：

```text
10、11、12、13、14 中至少 3 个小时：
current_site_nrmse_pct <= week2_site_nrmse_pct + 0.50
```

### 9.2 辅助验收

整体指标要求：

```text
pred_actual_ratio 仍在 0.90~0.98
MAE/RMSE 不得明显高于当前 0.5927 / 1.2164
城市 NRMSE 可以小幅波动
```

版本选择要求：

```text
final_version_selection_by_hour.csv 中，
10-14 点应允许出现 MiddaySiteCalibrated。
```

---

## 十、如果没有改善，下一步怎么做

如果 `MiddaySiteCalibrated` 没有改善 10-14 点 NRMSE，说明简单后处理已到上限，需要回到训练层：

1. 在 `train_distributed_model_v159.py` 中对 10-14 点样本增加权重。
2. 训练目标从全样本 RMSE 改成容量归一化目标：

```text
target = power_mw / capacity_mw
sample_weight = hour_weight * site_balance_weight
```

3. 对高误差站点 S019、S053、S072、S002、S059 做单独残差模型。
4. 增加 midday 特征：

```text
solar_elevation_deg
clear_sky_ghi
clear_sky_index
g_blend_pred / clear_sky_ghi
hour_centered = abs(hour - 12)
```

5. 建议新增 `train_distributed_model_midday_specialist.py`，只训练 10-14 点专家模型，再由 final selector 只在 10-14 点调用。

