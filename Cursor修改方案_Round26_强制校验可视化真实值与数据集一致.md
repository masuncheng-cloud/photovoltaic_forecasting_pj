# Cursor 修改方案 Round26：强制校验可视化真实值与数据集一致

## 一、先说明当前核对结论

对当前上传的 `photovoltaic_forecasting_pj.zip` 进行核对后，发现：

```text
output/pv_pipeline/interactive_dashboard/site_series/S012.json
```

中的 `actual_mw` 与以下两个数据源在同一时间点完全一致：

```text
output/pv_pipeline/tables/power_clean.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
```

核对范围：

```text
站点：S012 泰富如意情光伏
时间：2025-09-01 至 2025-12-31
小时：6-19
```

结果：

```text
site_series/S012.json 行数：1708
power_clean.pkl 行数：1708
distributed_predictions_final_full.pkl 行数：1708
actual_mw 最大差值：0
```

也就是说，在当前 zip 中，**可视化 JSON 里的真实值并没有和数据集不一致**。

但是页面上仍可能出现“看起来不一致”，主要有三种风险：

1. 页面读取的是旧的 JSON 缓存。
2. 页面展示的是 `full` 历史数据，而用户对照的是 `final_eval` 正式评估数据。
3. 前端绘图或指标卡使用了不一致的过滤口径。

本轮修复目标是：

- 强制可视化真实值来源可追溯。
- 强制导出后自动校验 `site_series/*.json` 与 `power_clean.pkl` / `final_full.pkl` 一致。
- 前端页面显示当前真实值来源、数据更新时间、评估口径。
- 防止浏览器缓存旧 JSON。
- 明确区分“展示真实值”和“正式评估真实值”。

本轮不重新训练模型，不修改真实功率值，不手动改 CSV/JSON 数值。

## 二、涉及文件

主要修改：

```text
scripts/export_interactive_dashboard_data.py
stages/05_visualization/interactive_forecast_dashboard.html
```

新增输出：

```text
output/pv_pipeline/interactive_dashboard/data_integrity_check.json
output/pv_pipeline/metrics/dashboard_actual_value_consistency.csv
```

## 三、修复原则

必须遵守：

```text
可视化页面的真实值 actual_mw 只能来自 power_clean.pkl / distributed_predictions_final_full.pkl 中的 power_mw。
```

不允许：

```text
前端重新计算真实功率
前端用预测值回填真实值
前端用 final_eval 覆盖 full 展示值
前端把 0 当作缺失值插值
手动修改 site_series JSON 中的 actual_mw
```

## 四、后端增加真实值一致性校验

在 `scripts/export_interactive_dashboard_data.py` 中新增函数：

```python
def validate_dashboard_actual_values(df: pd.DataFrame, dashboard_root, output_root):
    """校验 site_series/*.json 中的 actual_mw 与 final_full/power_mw 是否一致。"""
    site_dir = Path(dashboard_root) / "site_series"
    rows = []

    if "time" in df.columns:
        source = df.copy()
        source["time"] = pd.to_datetime(source["time"], errors="coerce")
    else:
        raise ValueError("prediction df missing time column")

    source = source[
        source["split"].isin(["train", "valid", "test"])
        & source["hour"].between(6, 19)
        & source["power_mw"].notna()
    ].copy()

    source_key = source.set_index(["site_id", "time"])["power_mw"]

    for path in sorted(site_dir.glob("*.json")):
        site_id = path.stem
        js = pd.read_json(path)
        if js.empty:
            rows.append({
                "site_id": site_id,
                "json_rows": 0,
                "matched_rows": 0,
                "missing_in_source": 0,
                "max_abs_diff": None,
                "status": "FAIL_EMPTY_JSON",
            })
            continue

        js["time"] = pd.to_datetime(js["time"], errors="coerce")
        js["site_id"] = site_id

        merged = js[["site_id", "time", "actual_mw"]].merge(
            source[["site_id", "time", "power_mw"]],
            on=["site_id", "time"],
            how="left",
        )

        missing = int(merged["power_mw"].isna().sum())
        matched = int(merged["power_mw"].notna().sum())

        if matched > 0:
            diff = (merged["actual_mw"].astype(float) - merged["power_mw"].astype(float)).abs()
            max_diff = float(diff.max())
            bad_rows = int((diff > 1e-9).sum())
        else:
            max_diff = None
            bad_rows = len(merged)

        status = "PASS" if missing == 0 and bad_rows == 0 else "FAIL"

        rows.append({
            "site_id": site_id,
            "json_rows": int(len(js)),
            "matched_rows": matched,
            "missing_in_source": missing,
            "bad_value_rows": bad_rows,
            "max_abs_diff": max_diff,
            "status": status,
        })

    result = pd.DataFrame(rows)
    metrics_path = Path(output_root) / "metrics" / "dashboard_actual_value_consistency.csv"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(metrics_path, index=False, encoding="utf-8-sig")

    summary = {
        "checked_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "distributed_predictions_final_full.pkl power_mw",
        "dashboard_site_series": "interactive_dashboard/site_series/*.json actual_mw",
        "site_count": int(len(result)),
        "fail_count": int((result["status"] != "PASS").sum()) if len(result) else 0,
        "max_abs_diff": float(result["max_abs_diff"].dropna().max()) if result["max_abs_diff"].notna().any() else 0.0,
        "status": "PASS" if len(result) and (result["status"] == "PASS").all() else "FAIL",
    }

    out_json = Path(dashboard_root) / "data_integrity_check.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if summary["status"] != "PASS":
        bad = result[result["status"] != "PASS"].head(10)
        raise RuntimeError(
            "Dashboard actual_mw differs from source power_mw. "
            f"See {metrics_path}. Bad examples: {bad.to_dict(orient='records')}"
        )

    print(f"  [OK] dashboard actual value consistency: {summary['site_count']} sites, max_diff={summary['max_abs_diff']}")
    return summary
```

在 `main()` 的所有 `site_series` 导出完成后调用：

```python
print("\n[11b] Validating dashboard actual values...")
integrity_summary = validate_dashboard_actual_values(df, dashboard_root, output_root)
```

并在最后 validation 中加入：

```python
assert integrity_summary["status"] == "PASS"
assert integrity_summary["max_abs_diff"] <= 1e-9
```

## 五、可选：与 `power_clean.pkl` 再做二次校验

如果希望更严格，可增加 `power_clean.pkl` 校验。

```python
def validate_against_power_clean(dashboard_root, output_root):
    clean_path = Path(output_root) / "tables" / "power_clean.pkl"
    if not clean_path.exists():
        print(f"  [WARN] power_clean.pkl not found, skip clean validation")
        return None

    power_clean = pd.read_pickle(clean_path)
    power_clean["time"] = pd.to_datetime(power_clean["time"], errors="coerce")
    power_clean = power_clean[
        power_clean["site_id"].notna()
        & power_clean["time"].notna()
        & power_clean["power_mw"].notna()
    ].copy()

    # 只校验 dashboard 已导出的 6-19 train/valid/test 记录
    site_dir = Path(dashboard_root) / "site_series"
    rows = []

    for path in sorted(site_dir.glob("*.json")):
        site_id = path.stem
        js = pd.read_json(path)
        if js.empty:
            continue
        js["time"] = pd.to_datetime(js["time"], errors="coerce")
        js["site_id"] = site_id

        clean_site = power_clean[power_clean["site_id"].astype(str).eq(site_id)]
        merged = js[["site_id", "time", "actual_mw"]].merge(
            clean_site[["site_id", "time", "power_mw"]],
            on=["site_id", "time"],
            how="left",
        )

        diff = (merged["actual_mw"].astype(float) - merged["power_mw"].astype(float)).abs()
        rows.append({
            "site_id": site_id,
            "json_rows": len(js),
            "matched_rows": int(merged["power_mw"].notna().sum()),
            "missing_in_power_clean": int(merged["power_mw"].isna().sum()),
            "max_abs_diff_power_clean": float(diff.max()) if diff.notna().any() else None,
            "bad_rows": int((diff > 1e-9).sum()) if diff.notna().any() else len(js),
        })

    result = pd.DataFrame(rows)
    out = Path(output_root) / "metrics" / "dashboard_vs_power_clean_consistency.csv"
    result.to_csv(out, index=False, encoding="utf-8-sig")

    bad = result[
        (result["missing_in_power_clean"] > 0)
        | (result["bad_rows"] > 0)
    ]
    if len(bad):
        raise RuntimeError(f"Dashboard values differ from power_clean. See {out}")

    print(f"  [OK] dashboard actual values match power_clean: {len(result)} sites")
    return result
```

调用位置：

```python
validate_against_power_clean(dashboard_root, output_root)
```

## 六、防止浏览器读取旧 JSON 缓存

在 `interactive_forecast_dashboard.html` 的 `fetchJson` 函数中增加 cache bust。

找到：

```js
async function fetchJson(url) {
  const res = await fetch(url);
  ...
}
```

改为：

```js
async function fetchJson(url) {
  const sep = url.includes("?") ? "&" : "?";
  const bustUrl = `${url}${sep}v=${Date.now()}`;
  const res = await fetch(bustUrl, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load ${url}: ${res.status}`);
  }
  return await res.json();
}
```

这样每次刷新页面都会读取最新 JSON。

## 七、页面显示数据一致性状态

页面加载：

```js
const gDataIntegrity = await fetchJson(`${DATA_ROOT}/data_integrity_check.json`);
```

在页面顶部或说明区加入：

```html
<div id="data-integrity-note" class="data-integrity-note"></div>
```

渲染：

```js
function renderDataIntegrityNote() {
  const el = document.getElementById("data-integrity-note");
  if (!el || !gDataIntegrity) return;

  const ok = gDataIntegrity.status === "PASS";
  el.className = ok ? "data-integrity-note ok" : "data-integrity-note bad";
  el.textContent = ok
    ? `真实值校验通过：页面 actual_mw 与 final_full/power_mw 一致；最大差值 ${gDataIntegrity.max_abs_diff}。`
    : `真实值校验失败：页面 actual_mw 与数据源不一致，请重新生成可视化数据。`;
}
```

CSS：

```css
.data-integrity-note {
  margin: 6px 0;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
}

.data-integrity-note.ok {
  background: #ecfdf5;
  border: 1px solid #bbf7d0;
  color: #047857;
}

.data-integrity-note.bad {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}
```

初始化后调用：

```js
renderDataIntegrityNote();
```

## 八、前端绘图不要改写真实值

检查 `drawLineChart(rows)`。

禁止这种写法：

```js
const actual = d.actual_mw || null;
const actual = d.actual_mw || d.pred_mw;
const actual = Number(d.actual_mw) || 0;
```

建议统一：

```js
function getActualMw(d) {
  const v = Number(d.actual_mw);
  return Number.isFinite(v) ? v : null;
}

function getPredMw(d) {
  const v = Number(d.pred_mw);
  return Number.isFinite(v) ? v : null;
}
```

绘图时：

```js
.y(d => y(getActualMw(d)))
```

line defined：

```js
.defined(d => getActualMw(d) !== null)
```

注意：

```text
0 是合法真实值，不能被当成 null 或 false。
```

## 九、明确页面数据口径

将页面说明改为：

```text
当前折线图真实值 actual_mw 直接来自 distributed_predictions_final_full.pkl 的 power_mw；
该字段与 power_clean.pkl 中同一站点、同一时间的 power_mw 一致。
正式测试集指标来自 distributed_predictions_final_eval.pkl，通常会排除非正功率样本，因此可能与 full 展示曲线的样本范围不同。
```

这句话必须放在页面上，避免用户把 `final_full` 展示值和 `final_eval` 评估值混为一谈。

## 十、增加一键核对 S012 的调试输出

可选新增脚本：

```text
scripts/check_dashboard_actual_values.py
```

内容：

```python
#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="output/pv_pipeline")
    parser.add_argument("--site-id", default="S012")
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end", default="2025-12-31")
    args = parser.parse_args()

    root = Path(args.output_root)
    site_json = root / "interactive_dashboard" / "site_series" / f"{args.site_id}.json"
    final_full = root / "tables" / "distributed_predictions_final_full.pkl"
    power_clean = root / "tables" / "power_clean.pkl"

    js = pd.DataFrame(json.loads(site_json.read_text(encoding="utf-8")))
    js["time"] = pd.to_datetime(js["time"])
    js = js[(js["time"] >= args.start) & (js["time"] <= pd.Timestamp(args.end) + pd.Timedelta(days=1))]

    ff = pd.read_pickle(final_full)
    ff["time"] = pd.to_datetime(ff["time"])
    ff = ff[
        ff["site_id"].astype(str).eq(args.site_id)
        & (ff["time"] >= args.start)
        & (ff["time"] <= pd.Timestamp(args.end) + pd.Timedelta(days=1))
        & ff["hour"].between(6, 19)
    ]

    pc = pd.read_pickle(power_clean)
    pc["time"] = pd.to_datetime(pc["time"])
    pc["hour"] = pc["time"].dt.hour
    pc = pc[
        pc["site_id"].astype(str).eq(args.site_id)
        & (pc["time"] >= args.start)
        & (pc["time"] <= pd.Timestamp(args.end) + pd.Timedelta(days=1))
        & pc["hour"].between(6, 19)
    ]

    m1 = js[["time", "actual_mw"]].merge(ff[["time", "power_mw"]], on="time", how="outer", indicator=True)
    m1["diff"] = (m1["actual_mw"] - m1["power_mw"]).abs()

    m2 = js[["time", "actual_mw"]].merge(pc[["time", "power_mw"]], on="time", how="outer", indicator=True)
    m2["diff"] = (m2["actual_mw"] - m2["power_mw"]).abs()

    print(f"site={args.site_id}, range={args.start}~{args.end}")
    print("json rows:", len(js), "sum:", js["actual_mw"].sum(), "zero:", int((js["actual_mw"] == 0).sum()))
    print("final_full rows:", len(ff), "sum:", ff["power_mw"].sum(), "zero:", int((ff["power_mw"] == 0).sum()))
    print("power_clean rows:", len(pc), "sum:", pc["power_mw"].sum(), "zero:", int((pc["power_mw"] == 0).sum()))
    print("json vs final_full max diff:", m1["diff"].max())
    print("json vs power_clean max diff:", m2["diff"].max())

    assert m1["_merge"].eq("both").all()
    assert m2["_merge"].eq("both").all()
    assert m1["diff"].fillna(0).max() <= 1e-9
    assert m2["diff"].fillna(0).max() <= 1e-9
    print("[OK] dashboard actual values match source tables")


if __name__ == "__main__":
    main()
```

运行：

```bash
python scripts/check_dashboard_actual_values.py \
  --output-root output/pv_pipeline \
  --site-id S012 \
  --start 2025-09-01 \
  --end 2025-12-31
```

## 十一、重新生成可视化数据

执行：

```bash
cd /path/to/photovoltaic_forecasting_pj
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

然后运行：

```bash
python scripts/check_dashboard_actual_values.py \
  --output-root output/pv_pipeline \
  --site-id S012 \
  --start 2025-09-01 \
  --end 2025-12-31
```

预期输出：

```text
json vs final_full max diff: 0.0
json vs power_clean max diff: 0.0
[OK] dashboard actual values match source tables
```

## 十二、启动页面验证

```bash
cd /path/to/photovoltaic_forecasting_pj
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新浏览器：

```text
Windows/Linux: Ctrl + F5
macOS: Command + Shift + R
```

页面需要显示：

```text
真实值校验通过：页面 actual_mw 与 final_full/power_mw 一致；最大差值 0。
```

## 十三、验收标准

本轮通过标准：

- `site_series/*.json` 的 `actual_mw` 与 `distributed_predictions_final_full.pkl` 的 `power_mw` 完全一致。
- `site_series/*.json` 的 `actual_mw` 与 `power_clean.pkl` 的 `power_mw` 完全一致。
- 如果不一致，导出脚本直接报错，不允许生成“看似正常”的页面。
- 页面不缓存旧 JSON。
- 页面说明明确区分 `final_full` 展示口径和 `final_eval` 正式评估口径。
- 前端绘图不把 0 当作缺失值，不插值、不回填、不改写真实值。

