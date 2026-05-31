# Cursor 执行方案 Round52：主流程闭环与 S115/S116 经纬度人工补齐

## 目标

针对 Round51 暴露的问题，本轮只做工程闭环和数据基础修复，不继续新增临时模型策略。

需要解决：

1. `run_full_pipeline.py` 未真正一键完整执行，仍依赖手动分步。
2. `manifest.json` 未生成。
3. 最终产物文件名仍带 `round36/round46` 等历史痕迹。
4. S115/S116 缺经纬度，影响空间插值、气象匹配和站点误差解释。
5. 训练完成后必须自动导出最新可视化数据并校验。

---

## 一、公开资料线索

### S115：鑫众墩尚光伏电站

当前项目站点：

```text
station_id: S115
station_name: 鑫众墩尚光伏电站
capacity_mw: 7
```

公开资料线索：

- Global Energy Monitor 记录的项目名为 `Lianyungang Xinzhong Photovoltaic Power Dunshang Town Fishing and Light Complementary solar project`，中文为“连云港鑫众光伏电力有限公司墩尚镇 7MWp 渔光互补分布式光伏发电项目”，状态为 operating，容量为 7 MWp/dc。
- 智联招聘企业信息显示“连云港鑫众光伏电力有限公司”公司地址为“连云港市赣榆区墩尚镇黄海水产养殖场”。

参考来源：

- https://www.gem.wiki/Lianyungang_Xinzhong_Photovoltaic_Power_Dunshang_Town_Fishing_and_Light_Complementary_solar_project
- https://www.zhaopin.com/companydetail/9132HJ9HOAKAOJ0UFJ.htm

本轮要求：

- 使用“连云港市赣榆区墩尚镇黄海水产养殖场”作为人工定位地址。
- 用高德地图、百度地图、天地图、Google Maps 或其他可用地图服务人工确认光伏区中心点。
- 不要只用镇政府坐标。
- 如果只能定位到水产养殖场或墩尚镇范围，记录为 `confidence=medium` 或 `low`，不得标为 `high`。

### S116：林洋伊山光伏电站

当前项目站点：

```text
station_id: S116
station_name: 林洋伊山光伏电站
capacity_mw: 22
```

公开资料线索：

- “灌云林洋新能源科技有限公司林洋伊山 6MWp 农光互补光伏发电项目”有竣工环保验收公示记录。
- 林洋能源公告中，“灌云林洋新能源科技有限公司”注册地址为“连云港市灌云县伊山镇丁庄村丁庄路”。

参考来源：

- https://longzhanhuanbao.com/nd.jsp?fromColId=2&id=159
- https://static.cninfo.com.cn/finalpage/2023-11-29/1218466281.PDF
- https://finance.sina.cn/2023-11-29/detail-imzwfexe4318015.d.html

本轮要求：

- 使用“连云港市灌云县伊山镇丁庄村丁庄路”作为人工定位地址。
- 人工地图确认时优先寻找“林洋伊山”“灌云林洋新能源”“伊山农光互补”等光伏区或项目位置。
- 如果只能定位到丁庄村/丁庄路范围，记录为 `confidence=medium` 或 `low`。
- 注意当前项目中 S116 容量为 22MW，而公开资料中可见“林洋伊山 6MWp”线索，可能存在同一区域多期项目或站名归并，必须在备注中说明。

---

## 二、创建人工经纬度覆盖表

新增文件：

```text
configs/manual_station_geo_overrides.csv
```

字段：

```csv
station_id,station_name,latitude,longitude,geo_source,geo_address,confidence,note
```

请先创建模板：

```csv
station_id,station_name,latitude,longitude,geo_source,geo_address,confidence,note
S115,鑫众墩尚光伏电站,,,,连云港市赣榆区墩尚镇黄海水产养殖场,,连云港鑫众光伏电力有限公司墩尚镇7MWp渔光互补项目；需人工地图确认光伏区中心点
S116,林洋伊山光伏电站,,,,连云港市灌云县伊山镇丁庄村丁庄路,,灌云林洋新能源科技有限公司林洋伊山项目；公开资料容量线索与项目容量可能存在多期/归并差异
```

然后人工补齐：

```text
latitude
longitude
geo_source
confidence
```

`geo_source` 示例：

```text
manual_amap
manual_baidu
manual_tianditu
manual_google
```

`confidence` 取值：

```text
high    精确到光伏场区/组件区中心
medium  精确到水产养殖场、村、道路或项目厂区附近
low     仅精确到乡镇或公司注册地址，不能确认具体场区
```

要求：

- 经纬度使用 WGS84 或明确坐标系。
- 如果使用高德/百度拾取坐标，要注意 GCJ-02/BD-09 与 WGS84 的差异。
- 项目后续若使用 ERA5/空间距离，建议统一转为 WGS84。
- 在 `note` 中写清是否经过坐标系转换。

---

## 三、新增坐标覆盖加载逻辑

新增或修改脚本：

```text
scripts/apply_manual_geo_overrides.py
```

功能：

1. 读取站点主数据表。
2. 读取 `configs/manual_station_geo_overrides.csv`。
3. 对 `station_id` 匹配的站点覆盖 `latitude/longitude`。
4. 写出修正后的站点表。
5. 输出覆盖日志。

建议兼容以下可能路径，按项目实际存在的文件调整：

```text
output/pv_pipeline/tables/station_metadata.pkl
output/pv_pipeline/tables/site_metadata.pkl
output/pv_pipeline/tables/station_mapping_clean.pkl
data/station_metadata.csv
```

代码要求：

```python
import pandas as pd
from pathlib import Path


def apply_manual_geo_overrides(station_df: pd.DataFrame, overrides_path: Path) -> pd.DataFrame:
    if not overrides_path.exists():
        return station_df

    overrides = pd.read_csv(overrides_path)
    required = ["station_id", "latitude", "longitude", "confidence"]
    missing = [c for c in required if c not in overrides.columns]
    if missing:
        raise KeyError(f"manual geo override missing columns: {missing}")

    valid = overrides.dropna(subset=["station_id", "latitude", "longitude"])
    out = station_df.copy()

    for _, row in valid.iterrows():
        sid = str(row["station_id"])
        mask = out["station_id"].astype(str).eq(sid)
        if not mask.any():
            raise ValueError(f"manual geo override station_id not found: {sid}")
        out.loc[mask, "latitude"] = float(row["latitude"])
        out.loc[mask, "longitude"] = float(row["longitude"])
        out.loc[mask, "geo_source"] = row.get("geo_source", "manual")
        out.loc[mask, "geo_confidence"] = row.get("confidence", "")
        out.loc[mask, "geo_note"] = row.get("note", "")

    return out
```

---

## 四、接入 Stage 01/02 和主流程

修改：

```text
scripts/run_full_pipeline.py
```

要求主流程顺序变为：

```text
0. 读取 configs/pipeline.yaml
1. Stage 01 数据读取、站点映射、基础清洗
2. 应用 manual_station_geo_overrides.csv
3. Stage 02 数据质量审计与训练表构建
4. 集中式辐照估计
5. 辐照空间扩展与 ERA5 融合
6. 分布式功率训练与预测
7. 校准并生成 power_pred_final
8. 写出正式 final_full/final_eval
9. 重算正式 metrics
10. 导出 interactive_dashboard
11. 运行 posttrain_validation
12. 运行 check_dashboard_prediction_values
13. 写出 manifest.json
```

注意：

- 不允许再要求用户手动先跑 Stage 01/02。
- 如果已有 Stage 01/02 脚本名不同，请在 `run_full_pipeline.py` 中统一调度。
- 每一步失败必须停止。

---

## 五、统一正式产物文件名

保留历史 round 文件作为兼容输出，但正式文件必须写出：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/metrics/hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/site_metrics_consistent.csv
```

如果当前代码仍写到：

```text
output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/round36_site_metrics.csv
```

则在主流程最后增加同步复制：

```python
from pathlib import Path
import shutil

def copy_if_exists(src, dst):
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

copy_if_exists(
    "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
)
copy_if_exists(
    "output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
)
copy_if_exists(
    "output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
)
copy_if_exists(
    "output/pv_pipeline/metrics/round36_site_metrics.csv",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
)
```

更推荐从源头改正式输出名，复制只作为兼容过渡。

---

## 六、生成 manifest.json

在 `run_full_pipeline.py` 最后新增：

```python
import json
from datetime import datetime
from pathlib import Path


def write_manifest(cfg, output_root):
    output_root = Path(output_root)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": "configs/pipeline.yaml",
        "split": cfg.get("split", {}),
        "eval": cfg.get("eval", {}),
        "final_prediction_column": cfg.get("prediction", {}).get("final_prediction_column", "power_pred_final"),
        "artifacts": {
            "final_full_pkl": "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
            "final_eval_pkl": "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
            "hourly_nrmse_csv": "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
            "site_metrics_csv": "output/pv_pipeline/metrics/site_metrics_consistent.csv",
            "dashboard_dir": "output/pv_pipeline/interactive_dashboard",
            "dashboard_index": "output/pv_pipeline/interactive_dashboard/index.json",
        },
        "manual_geo_overrides": "configs/manual_station_geo_overrides.csv",
        "notes": [
            "test set is only used for final evaluation",
            "dashboard data is exported after final prediction generation",
            "NRMSE denominator uses station capacity for site metrics and total capacity for city metrics",
        ],
    }
    path = output_root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] manifest written: {path}")
```

验收：

```bash
test -f output/pv_pipeline/manifest.json
python -m json.tool output/pv_pipeline/manifest.json | head -80
```

---

## 七、补充经纬度验证

新增或修改：

```text
scripts/posttrain_validation.py
```

增加检查项：

```text
GEO1: S115/S116 不得缺 latitude/longitude
GEO2: 手工覆盖经纬度必须在连云港合理范围内
GEO3: geo_confidence 不得为空
GEO4: 如果 confidence=low，报告中必须提示该站点坐标仍需人工复核
```

连云港大致范围校验：

```python
def in_lianyungang(lat, lon):
    return 33.9 <= lat <= 35.2 and 118.4 <= lon <= 119.9
```

如果 S115/S116 仍缺坐标，直接 FAIL。

---

## 八、重训验证命令

完成上述修改后，执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round52_full_pipeline.log

python scripts/posttrain_validation.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round52_posttrain_validation.log

python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round52_dashboard_check.log
```

检查是否还有 FAIL：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|FileNotFound|KeyError|ValueError" \
  output/pv_pipeline/logs/round52_full_pipeline.log \
  output/pv_pipeline/logs/round52_posttrain_validation.log \
  output/pv_pipeline/logs/round52_dashboard_check.log || true
```

---

## 九、检查 S115/S116 经纬度是否生效

执行：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

targets = {"S115", "S116"}

for p in Path("output/pv_pipeline").rglob("*station*.pkl"):
    try:
        df = pd.read_pickle(p)
    except Exception:
        continue
    if "station_id" not in df.columns:
        continue
    hit = df[df["station_id"].astype(str).isin(targets)]
    if len(hit):
        print("\n====", p, "====")
        cols = [c for c in [
            "station_id", "station_name", "capacity_mw",
            "latitude", "longitude", "geo_source", "geo_confidence", "geo_note"
        ] if c in hit.columns]
        print(hit[cols].to_string(index=False))

for p in Path("output/pv_pipeline").rglob("*.csv"):
    if "site_metrics" not in p.name and "station" not in p.name:
        continue
    try:
        df = pd.read_csv(p)
    except Exception:
        continue
    if "station_id" not in df.columns:
        continue
    hit = df[df["station_id"].astype(str).isin(targets)]
    if len(hit):
        print("\n====", p, "====")
        cols = [c for c in [
            "station_id", "station_name", "capacity_mw",
            "latitude", "longitude", "geo_source", "geo_confidence",
            "nrmse_percent", "mae_mw", "rmse_mw"
        ] if c in hit.columns]
        print(hit[cols].to_string(index=False))
PY
```

要求：

- S115/S116 的 `latitude/longitude` 非空。
- 经纬度在连云港范围内。
- `geo_source/geo_confidence` 非空。

---

## 十、检查指标变化

重训后查看：

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

说明：

- 补齐经纬度后，S115/S116 的空间特征和气象匹配会更合理，但不保证 NRMSE 立刻显著下降。
- 如果误差仍高，应继续检查容量映射、功率数据异常、限电/遮挡、并网/停运时段，而不是继续盲目调模型。

---

## 十一、启动可视化页面

```bash
python -m http.server 8060
```

访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

检查：

1. 页面不显示旧数据警告。
2. 全市曲线正常。
3. 单站点曲线正常。
4. S115/S116 可以正常展示。
5. 典型站点表中不再提示 S115/S116 缺经纬度。
6. 逐小时预测结果表读取最新 `hourly_nrmse_consistent.csv`。

---

## 十二、生成 Round52 报告

新增：

```text
docs/Round52_主流程闭环与S115_S116经纬度补齐报告.md
```

模板：

```markdown
# Round52 主流程闭环与 S115/S116 经纬度补齐报告

## 1. 本轮目标

## 2. 修改文件

## 3. S115/S116 经纬度来源

| station_id | station_name | address | latitude | longitude | source | confidence | note |
|---|---|---|---:|---:|---|---|---|

## 4. run_full_pipeline.py 闭环情况

- 是否包含 Stage 01/02：
- 是否一键跑通：
- 是否生成 manifest：

## 5. 最终产物文件名统一情况

## 6. posttrain_validation 结果

## 7. dashboard 校验结果

## 8. S115/S116 指标变化

## 9. 当前仍需注意的问题
```

---

## 十三、验收标准

本轮必须满足：

```text
[PASS] run_full_pipeline.py 一条命令完整跑通
[PASS] Stage 01/02 已纳入主入口
[PASS] manifest.json 自动生成
[PASS] 正式最终文件名不再依赖 round36/round46
[PASS] S115/S116 经纬度非空
[PASS] S115/S116 经纬度有来源、地址、置信度说明
[PASS] posttrain_validation 无 FAIL
[PASS] dashboard_prediction_values 无 FAIL
[PASS] 可视化数据晚于最终预测文件
```

如果 S115/S116 经纬度只能定位到乡镇或注册地址，允许通过，但报告必须标注 `confidence=low/medium`，并说明后续应由甲方或运维台账确认精确场区坐标。

