# Cursor执行方案：Round95 彻底收口可视化读数、清理冗余并干净重训

## 一、本轮目标

本轮不要再围绕某一个旧 `metadata.json` 或浏览器缓存做零散修补。  
目标是把项目重新整理成一个清晰、可复现、可交付的闭环：

```text
1. 只保留一个正式输出目录：output/pv_pipeline
2. 只保留一个正式可视化页面：stages/05_visualization/interactive_forecast_dashboard.html
3. 所有训练阶段先写入临时新目录，验证通过后才覆盖 output/pv_pipeline
4. 可视化页面只读取 output/pv_pipeline/interactive_dashboard
5. 旧 round 输出、旧 dashboard 页面、旧临时脚本统一归档，不混在正式流程里
6. 完整重训一遍，确保训练、评估、可视化、报告都来自同一次最新结果
```

本轮完成后，页面不应再出现：

```text
canonical
2026-06-03
旧 Round36 / Round68 / Round94_旧目录
```

---

## 二、执行前准备

进入项目根目录：

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj
pwd
git status --short
```

如果你是在云服务器 Cursor 中执行，则进入云服务器项目目录，例如：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
pwd
git status --short
```

后续命令统一假设当前目录就是项目根目录。

---

## 三、创建本轮工作分支

```bash
git checkout -b fix/round95-clean-retrain-dashboard-closure
```

如果分支已经存在：

```bash
git checkout fix/round95-clean-retrain-dashboard-closure
```

---

## 四、先做当前状态快照

不要直接删除旧文件。先完整归档，后续确认没问题再删除归档外的残留。

```bash
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_ROOT="archive/round95_before_cleanup_${STAMP}"
mkdir -p "$ARCHIVE_ROOT"

python3 - <<'PY'
from pathlib import Path
import json

root = Path.cwd()
snapshot = {
    "project_root": str(root),
    "output_dirs": sorted([p.name for p in (root / "output").glob("*")]) if (root / "output").exists() else [],
    "dashboard_pages": sorted([p.name for p in (root / "stages/05_visualization").glob("interactive_forecast_dashboard*.html")]) if (root / "stages/05_visualization").exists() else [],
    "script_round_files": sorted([p.name for p in (root / "scripts").glob("*round*")]) if (root / "scripts").exists() else [],
}
Path("archive").mkdir(exist_ok=True)
Path("archive/round95_current_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(snapshot, ensure_ascii=False, indent=2))
PY

cp archive/round95_current_snapshot.json "$ARCHIVE_ROOT/"
```

---

## 五、彻底定位旧版本来源

### 5.1 全项目搜索旧版本标记

```bash
grep -RIn --exclude-dir=.git --exclude-dir=archive \
  -E "canonical|2026-06-03|Round36|Round68 final|pv_pipeline_round94_3|interactive_forecast_dashboard_round94" \
  . > "$ARCHIVE_ROOT/round95_old_marker_search.txt" || true

sed -n '1,200p' "$ARCHIVE_ROOT/round95_old_marker_search.txt"
```

### 5.2 判断哪些旧标记允许存在

允许存在的位置：

```text
archive/
docs/历史报告
CHANGELOG.md
```

不允许存在的位置：

```text
stages/05_visualization/interactive_forecast_dashboard.html
scripts/export_interactive_dashboard_data.py
scripts/update_dashboard_after_training.py
output/pv_pipeline/interactive_dashboard/*.json
run_full_pipeline.py
```

如果不允许位置出现 `canonical`、`2026-06-03`、旧 round 字样，必须修掉。

---

## 六、统一正式输出目录

从现在开始，正式结果只有：

```text
output/pv_pipeline
```

不要再让页面读取：

```text
output/pv_pipeline_round94_3_era5_expanded_clean_20260604_225618
output/pv_pipeline_round*
output/pv_pipeline_fresh*
```

### 6.1 归档旧输出目录

保留正式目录 `output/pv_pipeline`，其他旧 round 输出先移动到归档。

```bash
mkdir -p "$ARCHIVE_ROOT/output_old_rounds"

find output -maxdepth 1 -type d \
  \( -name "pv_pipeline_round*" -o -name "pv_pipeline_fresh*" -o -name "pv_pipeline_*candidate*" -o -name "pv_pipeline_*path_test*" \) \
  -print > "$ARCHIVE_ROOT/output_dirs_to_archive.txt"

while IFS= read -r d; do
  [ -z "$d" ] && continue
  echo "[archive output] $d"
  mv "$d" "$ARCHIVE_ROOT/output_old_rounds/"
done < "$ARCHIVE_ROOT/output_dirs_to_archive.txt"
```

说明：如果你明确要保留某个目录，比如旧的最佳结果目录，可以先复制到 `archive/round95_before_cleanup_*/output_old_rounds/`，不要留在 `output/` 根目录干扰脚本。

### 6.2 确保 `output/pv_pipeline` 是真实目录，不是符号链接

```bash
if [ -L output/pv_pipeline ]; then
  TARGET="$(readlink output/pv_pipeline)"
  rm output/pv_pipeline
  mkdir -p output/pv_pipeline
  echo "[INFO] removed symlink output/pv_pipeline -> $TARGET"
fi

mkdir -p output/pv_pipeline
ls -ld output/pv_pipeline
```

为什么不要符号链接：  
符号链接在 zip、GitHub、Cursor 云服务器和本地浏览器服务之间容易断，之前页面读旧结果和 404 的问题，很大一部分就是输出目录别名混乱导致的。

---

## 七、统一可视化页面入口

正式页面只保留：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 7.1 归档旧 dashboard 页面

```bash
mkdir -p "$ARCHIVE_ROOT/dashboard_old_pages"

find stages/05_visualization -maxdepth 1 -type f \
  \( -name "interactive_forecast_dashboard_round*.html" -o -name "*broken_backup*.html" -o -name "*backup*.html" \) \
  -print > "$ARCHIVE_ROOT/dashboard_pages_to_archive.txt"

while IFS= read -r f; do
  [ -z "$f" ] && continue
  echo "[archive dashboard page] $f"
  mv "$f" "$ARCHIVE_ROOT/dashboard_old_pages/"
done < "$ARCHIVE_ROOT/dashboard_pages_to_archive.txt"
```

### 7.2 修复正式页面数据路径

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

要求：

```javascript
const DATA_ROOT = "../../output/pv_pipeline/interactive_dashboard";
```

或如果你使用项目根目录 HTTP 服务，也可以用：

```javascript
const DATA_ROOT = "/output/pv_pipeline/interactive_dashboard";
```

二选一即可。  
推荐保留相对路径 `../../output/pv_pipeline/interactive_dashboard`，因为当前页面路径就在 `stages/05_visualization/`。

同时必须满足：

```text
1. 不存在跳转到 interactive_forecast_dashboard_round94.html
2. 不存在硬编码 canonical
3. 不存在硬编码 2026-06-03
4. 不从 localStorage/sessionStorage 读取 metadata
5. fetch JSON 必须带 cache bust
```

检查：

```bash
grep -n "interactive_forecast_dashboard_round94\\|canonical\\|2026-06-03\\|location.replace\\|localStorage.*metadata\\|sessionStorage.*metadata" \
  stages/05_visualization/interactive_forecast_dashboard.html || true
```

如果有命中，修掉。

### 7.3 fetch JSON 必须禁用缓存

确保 HTML 中的 JSON 加载函数类似：

```javascript
async function fetchJSON(relativePath) {
  const sep = relativePath.includes("?") ? "&" : "?";
  const url = `${DATA_ROOT}/${relativePath}${sep}v=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`加载失败: ${res.status} ${url}`);
  return await res.json();
}
```

---

## 八、统一训练主流程输出策略

本轮必须修复成：

```text
训练先写临时目录 -> 验证临时目录 -> 验证通过 -> 覆盖 output/pv_pipeline -> 导出 dashboard -> 再验证正式目录
```

不要让任何阶段在训练中途直接写 `output/pv_pipeline`。

### 8.1 检查硬编码输出路径

```bash
grep -RIn --exclude-dir=.git --exclude-dir=archive \
  -E "output/pv_pipeline|pv_pipeline_round|pv_pipeline_fresh" \
  scripts stages src run_full_pipeline.py config configs \
  > "$ARCHIVE_ROOT/output_path_hardcode_scan.txt" || true

sed -n '1,240p' "$ARCHIVE_ROOT/output_path_hardcode_scan.txt"
```

处理原则：

```text
1. run_full_pipeline.py 可以有默认 output/pv_pipeline，但必须允许 --output-root 覆盖。
2. 子脚本不允许无视 --output-root 直接写 output/pv_pipeline。
3. dashboard HTML 可以读 output/pv_pipeline，因为这是正式结果入口。
4. docs 里出现旧路径无所谓。
```

如果某个训练脚本硬编码写入 `output/pv_pipeline`，必须增加 `--output-root` 参数或从环境变量读取：

```python
parser.add_argument("--output-root", default="output/pv_pipeline")
```

所有输出路径都从 `args.output_root` 派生。

---

## 九、清理冗余脚本和结果文件

### 9.1 归档临时 round 脚本

把明显的历史修复脚本归档，不放在正式 `scripts/` 根目录中干扰。

```bash
mkdir -p "$ARCHIVE_ROOT/scripts_round_legacy"

find scripts -maxdepth 1 -type f \
  \( -name "*round[0-9]*.py" -o -name "diagnose_round*.py" -o -name "check_*round*.py" -o -name "apply_round*.py" \) \
  -print > "$ARCHIVE_ROOT/scripts_to_archive.txt"

while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    *run_full_pipeline.py|*export_interactive_dashboard_data.py|*posttrain_validation.py|*dashboard_regression_check.py|*check_dashboard_prediction_values.py)
      echo "[keep official] $f"
      ;;
    *)
      echo "[archive script] $f"
      mv "$f" "$ARCHIVE_ROOT/scripts_round_legacy/"
      ;;
  esac
done < "$ARCHIVE_ROOT/scripts_to_archive.txt"
```

注意：如果某些 round 脚本仍被主流程调用，不能归档。归档后马上跑：

```bash
python3 run_full_pipeline.py --help
```

如果主流程报找不到某个脚本，说明它仍是正式依赖，要恢复：

```bash
mv "$ARCHIVE_ROOT/scripts_round_legacy/<脚本名>" scripts/
```

### 9.2 清理 metrics 中旧 round CSV

正式 `output/pv_pipeline/metrics` 不应堆满历史 round 文件。先归档：

```bash
mkdir -p "$ARCHIVE_ROOT/metrics_old_round_files"

if [ -d output/pv_pipeline/metrics ]; then
  find output/pv_pipeline/metrics -maxdepth 1 -type f \
    \( -name "round*.csv" -o -name "*round*.csv" -o -name "*compare*.csv" -o -name "*rollback*.csv" -o -name "*candidate*.csv" \) \
    -print > "$ARCHIVE_ROOT/metrics_to_archive.txt"

  while IFS= read -r f; do
    [ -z "$f" ] && continue
    echo "[archive metric] $f"
    mv "$f" "$ARCHIVE_ROOT/metrics_old_round_files/"
  done < "$ARCHIVE_ROOT/metrics_to_archive.txt"
fi
```

### 9.3 清理 output 根目录旧残留

检查：

```bash
find output -maxdepth 1 -mindepth 1 -print | sort
```

正式允许保留：

```text
output/pv_pipeline
```

其他历史输出都应在 `archive/round95_before_cleanup_*/output_old_rounds/`。

---

## 十、检查 ERA5 数据

你的新 ERA5 数据应在项目内：

```text
data/2023/data_stream-oper_stepType-accum.nc
data/2023/data_stream-oper_stepType-instant.nc
data/2024/data_stream-oper_stepType-accum.nc
data/2024/data_stream-oper_stepType-instant.nc
data/2025/data_stream-oper_stepType-accum.nc
data/2025/data_stream-oper_stepType-instant.nc
```

执行：

```bash
python3 scripts/check_era5_inputs.py --data-root data
```

要求：

```text
2023/2024/2025 文件都存在
ERA5 范围覆盖连云港
S115/S116 不再缺经纬度或气象特征
```

如果 `check_era5_inputs.py` 不支持 `--data-root`，先修脚本参数。

---

## 十一、创建干净重训目录

```bash
RUN_ID="round95_clean_retrain_$(date +%Y%m%d_%H%M%S)"
FRESH_OUTPUT="output/${RUN_ID}"
mkdir -p "$FRESH_OUTPUT"
echo "$FRESH_OUTPUT"
```

---

## 十二、完整重训

优先使用正式主入口：

```bash
python3 run_full_pipeline.py \
  --data-root data \
  --output-root "$FRESH_OUTPUT"
```

如果当前主入口参数不同，先执行：

```bash
python3 run_full_pipeline.py --help
```

然后按实际参数补齐，但必须保证：

```text
1. 输入数据来自 data/
2. 输出全部写入 $FRESH_OUTPUT
3. 不允许任何阶段写 output/pv_pipeline
```

训练过程中另开终端监控是否污染正式目录：

```bash
find output/pv_pipeline -type f -newer "$ARCHIVE_ROOT/round95_current_snapshot.json" | head
```

如果训练中途发现 `output/pv_pipeline` 被写入，立即停止训练，修硬编码路径。

---

## 十三、验证临时训练结果

训练完成后，对 `$FRESH_OUTPUT` 验证：

```bash
python3 scripts/posttrain_validation.py --output-root "$FRESH_OUTPUT"
python3 scripts/check_dashboard_prediction_values.py --output-root "$FRESH_OUTPUT"
python3 scripts/dashboard_regression_check.py --output-root "$FRESH_OUTPUT"
```

要求：

```text
posttrain_validation.py: FAIL=0
check_dashboard_prediction_values.py: PASS
dashboard_regression_check.py: PASS
```

再检查核心结果文件：

```bash
python3 - <<PY
from pathlib import Path
import json

out = Path("$FRESH_OUTPUT")
required = [
    "predictions/distributed_predictions_final_full.pkl",
    "predictions/distributed_predictions_final_eval.pkl",
    "interactive_dashboard/metadata.json",
    "interactive_dashboard/index.json",
    "interactive_dashboard/city_series.json",
    "interactive_dashboard/site_series",
    "metrics",
    "docs",
]

for rel in required:
    p = out / rel
    print(rel, "exists=", p.exists())
    if not p.exists():
        raise SystemExit(f"missing {rel}")

m = json.loads((out / "interactive_dashboard/metadata.json").read_text(encoding="utf-8"))
print("metadata:", m)
text = json.dumps(m, ensure_ascii=False)
if "canonical" in text or "2026-06-03" in text:
    raise SystemExit("metadata still old")
PY
```

---

## 十四、采用本次训练结果为正式结果

只有第十三步全部通过，才覆盖正式目录。

```bash
ADOPT_STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$ARCHIVE_ROOT/formal_output_before_adopt"

if [ -d output/pv_pipeline ]; then
  mv output/pv_pipeline "$ARCHIVE_ROOT/formal_output_before_adopt/pv_pipeline_${ADOPT_STAMP}"
fi

mkdir -p output
cp -a "$FRESH_OUTPUT" output/pv_pipeline
```

不要使用符号链接。  
正式结果必须是真实目录：

```bash
test -d output/pv_pipeline
test ! -L output/pv_pipeline
```

---

## 十五、重新导出正式可视化数据

```bash
python3 scripts/export_interactive_dashboard_data.py --output-root output/pv_pipeline
```

验证：

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path("output/pv_pipeline/interactive_dashboard/metadata.json")
m = json.loads(p.read_text(encoding="utf-8"))
for k in ["round", "data_version", "training_round", "dashboard_refresh_round", "exported_at", "generated_at", "prediction_column", "include_future"]:
    print(k, "=", m.get(k))

text = json.dumps(m, ensure_ascii=False)
if "canonical" in text or "2026-06-03" in text:
    raise SystemExit("[FAIL] 正式 dashboard metadata 仍是旧版本")

print("[PASS] 正式 dashboard metadata 是本次新结果")
PY
```

---

## 十六、启动可视化页面

不要再使用 8070。  
如果本机 8070 被 Cursor 占用，固定用 8095。

```bash
lsof -nP -iTCP:8095 -sTCP:LISTEN || true
```

如果 8095 有旧进程，先停止。

启动：

```bash
python3 scripts/serve_dashboard_no_cache.py --host 127.0.0.1 --port 8095 --directory "$(pwd)"
```

如果脚本不存在：

```bash
python3 -m http.server 8095 --bind 127.0.0.1
```

浏览器访问：

```text
http://127.0.0.1:8095/stages/05_visualization/interactive_forecast_dashboard.html?v=round95
```

---

## 十七、HTTP 验证页面读的是正式结果

另开终端执行：

```bash
curl -s "http://127.0.0.1:8095/output/pv_pipeline/interactive_dashboard/metadata.json?v=round95_$(date +%s)" \
  | python3 -m json.tool | head -100
```

必须不是：

```text
canonical
2026-06-03
```

检查页面 HTML：

```bash
curl -s "http://127.0.0.1:8095/stages/05_visualization/interactive_forecast_dashboard.html?v=round95_$(date +%s)" \
  | grep -E "canonical|2026-06-03|interactive_forecast_dashboard_round94" || true
```

要求没有输出。

---

## 十八、最终训练闭环检查

执行：

```bash
python3 scripts/posttrain_validation.py --output-root output/pv_pipeline
python3 scripts/check_dashboard_prediction_values.py --output-root output/pv_pipeline
python3 scripts/dashboard_regression_check.py --output-root output/pv_pipeline
```

再执行结构检查：

```bash
python3 scripts/audit_training_project_structure.py || true
python3 scripts/audit_training_metric_contract.py --output-root output/pv_pipeline || true
```

如果后两个脚本不存在或参数不支持，不要强行失败，但要在报告里说明。

---

## 十九、生成 Round95 报告

新建：

```text
docs/Round95_彻底收口可视化读数_清理冗余并干净重训报告.md
```

报告必须包含：

1. 本轮项目根目录。
2. 旧输出目录归档位置。
3. 旧 dashboard 页面归档位置。
4. 旧 round 脚本归档位置。
5. 正式输出目录是否为真实目录，不是符号链接。
6. 本次完整重训输出目录 `$FRESH_OUTPUT`。
7. 是否发现训练阶段污染 `output/pv_pipeline`。
8. 采用正式结果前的验证结果。
9. 采用正式结果后的验证结果。
10. Dashboard metadata 的 round/data_version/exported_at。
11. 可视化启动端口和访问地址。
12. 页面是否仍出现 canonical/2026-06-03。
13. 当前主要指标摘要：站点平均 NRMSE、城市 NRMSE、逐小时 10-14 结果。
14. 如果指标比 Round94_3 明显变差，必须说明是否回退。

---

## 二十、如果本次重训效果变差，如何处理

如果本次干净重训的核心指标明显差于 Round94_3，不要硬采用。

处理方式：

```bash
mv output/pv_pipeline "$ARCHIVE_ROOT/formal_output_bad_round95_$(date +%Y%m%d_%H%M%S)"
cp -a "$ARCHIVE_ROOT/formal_output_before_adopt"/pv_pipeline_* output/pv_pipeline
python3 scripts/export_interactive_dashboard_data.py --output-root output/pv_pipeline
```

然后报告中说明：

```text
Round95 训练链路已跑通，但指标不如当前最优，因此正式结果回退。
```

不要为了“新训练”而采用更差结果。

---

## 二十一、验收标准

本轮结束后必须满足：

```text
1. output 根目录下只有一个正式结果目录 output/pv_pipeline，旧 round 输出已归档。
2. stages/05_visualization 下只有一个正式 dashboard 页面 interactive_forecast_dashboard.html。
3. output/pv_pipeline 是真实目录，不是符号链接。
4. 完整训练从临时目录开始，不污染正式目录。
5. 验证通过后才采用正式结果。
6. 可视化页面 metadata 不再显示 canonical。
7. 可视化页面 metadata 不再显示 2026-06-03。
8. 浏览器访问 8095 页面可以正常展示曲线和表格。
9. posttrain_validation.py FAIL=0。
10. dashboard 数据一致性检查 PASS。
```

