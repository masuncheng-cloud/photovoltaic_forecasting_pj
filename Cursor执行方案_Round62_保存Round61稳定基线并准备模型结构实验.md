# Cursor 执行方案 Round62：保存 Round61 稳定基线，并准备模型结构实验

## 目标

当前 Round61 是稳定版本：

- 城市总量精度基本回到 Round58 水平；
- 变差超过 +1pp 的站点数为 0；
- 可视化、诊断和评估链路基本稳定；
- 后处理校准空间已经接近上限。

本轮目标：

1. 将 Round61 固化为 GitHub 可回退基线。
2. 创建清晰的 Git tag 和 baseline manifest。
3. 生成 Round61 baseline 文件清单。
4. 新建模型结构实验分支。
5. 准备下一阶段“分场景残差模型 + 发电状态分类器”的实验设计文档。
6. 暂不直接改模型训练代码。

---

## 一、进入项目目录并检查 Git 状态

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

git status
git branch --show-current
git remote -v
```

确认 remote 指向：

```text
git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git
```

如果 remote 不存在或不是该地址，执行：

```bash
git remote remove origin || true
git remote add origin git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git
git remote -v
```

---

## 二、确认 Round61 当前结果有效

先跑轻量验证：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round62_audit_before_commit.log
```

检查：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|FileNotFound|KeyError|ValueError" \
  output/pv_pipeline/logs/round62_audit_before_commit.log || true
```

注意：

- 如果只有 C16 manifest hash 自动同步类 WARN，可以继续。
- 如果存在真实 FAIL，不要提交，先修。

---

## 三、修正 Round61 报告中的明显矛盾

修改：

```text
docs/Round61_城市总量校准与站点稳定性保护报告.md
```

或项目实际报告路径。

把这类表述：

```text
posttrain_validation 无 FAIL
36项 32PASS 1FAIL 3WARN
C16 FAIL 为预期
```

改成更严谨的：

```text
posttrain_validation 存在 1 个 C16 manifest hash 自动同步相关告警/失败项，已确认不影响预测结果和 dashboard 一致性；后续需将 C16 归类为 WARN 或修复 hash 同步逻辑。
```

如果代码已经把 C16 修为 WARN，则报告写：

```text
posttrain_validation 无真实 FAIL，仅有 manifest 时间/hash 同步类 WARN。
```

不要在报告中同时写“无 FAIL”和“1 FAIL”。

---

## 四、生成 Round61 baseline manifest

新增脚本：

```text
scripts/create_round61_baseline_manifest.py
```

功能：

- 收集当前正式代码版本；
- 收集核心产物路径；
- 计算关键文件 SHA256；
- 写出 baseline manifest。

输出：

```text
output/pv_pipeline/baselines/round61/round61_baseline_manifest.json
output/pv_pipeline/baselines/round61/round61_baseline_files.csv
docs/Round61_稳定基线说明.md
```

脚本参考：

```python
from pathlib import Path
import hashlib
import json
import subprocess
from datetime import datetime
import pandas as pd

ROOT = Path(".")
BASE = ROOT / "output/pv_pipeline/baselines/round61"
BASE.mkdir(parents=True, exist_ok=True)

FILES = [
    "configs/pipeline.yaml",
    "configs/site_quality_policy.yaml",
    "configs/manual_station_geo_overrides.csv",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
    "output/pv_pipeline/metrics/round61_compare_summary.csv",
    "output/pv_pipeline/metrics/round61_compare_hourly.csv",
    "output/pv_pipeline/metrics/round61_compare_site.csv",
    "output/pv_pipeline/manifest.json",
    "docs/Round61_城市总量校准与站点稳定性保护报告.md",
]

def sha256(path):
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def git(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except Exception as e:
        return f"ERROR: {e}"

rows = []
for f in FILES:
    p = ROOT / f
    rows.append({
        "path": f,
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else None,
        "sha256": sha256(p) if p.exists() else None,
    })

df = pd.DataFrame(rows)
df.to_csv(BASE / "round61_baseline_files.csv", index=False, encoding="utf-8-sig")

manifest = {
    "baseline": "round61",
    "created_at": datetime.now().isoformat(timespec="seconds"),
    "git_branch": git("git branch --show-current"),
    "git_commit": git("git rev-parse HEAD"),
    "git_status_short": git("git status --short"),
    "final_prediction_column": "power_pred_final",
    "eval_scope": {
        "split": "test",
        "hours": "6-19",
        "exclude_future": True,
        "nrmse_site_denominator": "station capacity_mw",
        "nrmse_city_denominator": "sum participating station capacity_mw",
    },
    "key_result_summary": {
        "city_nrmse_6_19": "3.9531%",
        "city_nrmse_10_14": "6.2359%",
        "site_mean_nrmse_6_19": "11.4095%",
        "bias_6_19": "+1.42%",
        "worse_than_1pp_sites": 0,
    },
    "files": rows,
    "restore_note": "Use git checkout round61-stable-20260601 and restore artifacts listed in round61_baseline_files.csv if later experiments degrade results.",
}

(BASE / "round61_baseline_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

doc = """# Round61 稳定基线说明

## 基线说明

Round61 是当前稳定版本。该版本的特点是：城市总量精度基本回到 Round58 水平，同时保留了站点级恶化保护机制，变差超过 +1pp 的站点数为 0。

## 关键指标

| 指标 | Round61 |
|---|---:|
| city_nrmse_6_19 | 3.9531% |
| city_nrmse_10_14 | 6.2359% |
| site_mean_nrmse_6_19 | 11.4095% |
| bias_6_19 | +1.42% |
| 变差 > +1pp 站点数 | 0 |

## 回退方式

如果后续模型结构实验导致结果恶化，可回退到 Git tag：

```bash
git checkout round61-stable-20260601
```

同时按照 `output/pv_pipeline/baselines/round61/round61_baseline_files.csv` 恢复对应产物。
"""

(ROOT / "docs/Round61_稳定基线说明.md").write_text(doc, encoding="utf-8")
print("[OK] Round61 baseline manifest written")
```

执行：

```bash
python scripts/create_round61_baseline_manifest.py
```

---

## 五、复制关键产物到 Round61 baseline 目录

```bash
mkdir -p output/pv_pipeline/baselines/round61

cp output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
   output/pv_pipeline/baselines/round61/distributed_predictions_final_full.pkl

cp output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
   output/pv_pipeline/baselines/round61/distributed_predictions_final_eval.pkl

cp output/pv_pipeline/metrics/hourly_nrmse_consistent.csv \
   output/pv_pipeline/baselines/round61/hourly_nrmse_consistent.csv

cp output/pv_pipeline/metrics/site_metrics_consistent.csv \
   output/pv_pipeline/baselines/round61/site_metrics_consistent.csv

cp output/pv_pipeline/manifest.json \
   output/pv_pipeline/baselines/round61/manifest.json

cp output/pv_pipeline/metrics/round61_compare_summary.csv \
   output/pv_pipeline/baselines/round61/round61_compare_summary.csv || true

cp output/pv_pipeline/metrics/round61_compare_hourly.csv \
   output/pv_pipeline/baselines/round61/round61_compare_hourly.csv || true

cp output/pv_pipeline/metrics/round61_compare_site.csv \
   output/pv_pipeline/baselines/round61/round61_compare_site.csv || true
```

重新生成 manifest，确保 hash 覆盖 baseline 文件：

```bash
python scripts/create_round61_baseline_manifest.py
```

---

## 六、检查 .gitignore，避免提交大型 pkl

查看：

```bash
cat .gitignore || true
```

如果没有忽略 pkl/parquet/joblib/model 大文件，追加：

```bash
cat >> .gitignore <<'EOF'

# large generated artifacts
output/**/*.pkl
output/**/*.parquet
output/**/*.joblib
output/**/*.model
output/**/*.bin
output/**/*.npy
output/**/*.npz
EOF
```

注意：

- 大型 pkl 不建议提交 GitHub。
- 但 baseline manifest、CSV、报告、配置、脚本要提交。

确认不会提交 pkl：

```bash
git status --short | grep -E "\\.pkl|\\.parquet|\\.joblib|\\.npy|\\.npz" || true
```

如果发现 pkl 被 Git 跟踪，先不要强制删除历史，至少本次不要新增大文件。

---

## 七、Git 提交 Round61 稳定基线

查看变更：

```bash
git status --short
```

添加应提交的文件：

```bash
git add \
  configs \
  scripts \
  docs \
  stages/05_visualization \
  output/pv_pipeline/metrics/*.csv \
  output/pv_pipeline/baselines/round61/*.csv \
  output/pv_pipeline/baselines/round61/*.json \
  output/pv_pipeline/manifest.json \
  .gitignore
```

如果某些路径不存在，Git 会报错；可分批 add：

```bash
git add configs scripts docs stages/05_visualization .gitignore
git add output/pv_pipeline/metrics/*.csv || true
git add output/pv_pipeline/baselines/round61/*.csv || true
git add output/pv_pipeline/baselines/round61/*.json || true
git add output/pv_pipeline/manifest.json || true
```

再次确认没有大文件：

```bash
git status --short
git diff --cached --stat
git diff --cached --name-only | grep -E "\\.pkl|\\.parquet|\\.joblib|\\.npy|\\.npz" && echo "ERROR: large artifact staged" && exit 1 || true
```

提交：

```bash
git commit -m "chore: save round61 stable baseline"
```

---

## 八、打 Git tag 并推送

打 tag：

```bash
git tag -a round61-stable-20260601 -m "Round61 stable baseline before model-structure experiments"
```

推送：

```bash
git push origin HEAD
git push origin round61-stable-20260601
```

验证：

```bash
git log --oneline -5
git tag --list "round61*"
```

---

## 九、创建模型结构实验分支

```bash
git checkout -b experiment/model-structure-round62
git push -u origin experiment/model-structure-round62
```

后续模型结构实验全部在该分支进行，不直接污染 `main` 的 Round61 稳定版本。

---

## 十、准备模型结构实验设计文档

新增：

```text
docs/Round62_模型结构实验设计.md
```

内容：

```markdown
# Round62 模型结构实验设计

## 1. 为什么进入模型结构层

Round59-Round61 的校准主要修正系统性偏差，但提升幅度有限。Round61 已经接近校准层上限，继续调整校准参数容易在城市总量和站点稳定性之间来回摇摆。

## 2. 当前主要误差模式

| 问题 | 证据 | 可能原因 |
|---|---|---|
| 7 点低估 | bias 仍偏负 | 弱光启动阶段建模不足 |
| 17 点低估 | bias 仍偏负 | 傍晚下降阶段建模不足 |
| 10-14 高估 | bias 仍偏正 | 强辐照/峰值阶段过估 |
| low 场景低估 | pred/actual 偏低 | 弱辐照特征不足 |
| 部分站点长期偏差 | S012/S032/S053 等 | 容量/映射/站点差异 |

## 3. 实验方向

### 3.1 发电状态分类器

目标：先判断该小时是否有效发电，再预测功率。

输出：

```text
active / weak / inactive
```

### 3.2 分场景残差模型

保留现有预测作为基线：

```text
P_final = P_base + residual_correction
```

按场景拆分：

```text
dawn: 6-8
day: 9-16
dusk: 17-19
low irradiance
clear peak
```

### 3.3 站点特性增强

加入：

```text
station historical PR
capacity bucket
zero ratio
positive sample count
geo confidence
long-term bias
```

## 4. 实验边界

- 不使用 test 调参。
- Round61 作为固定 baseline。
- 新模型若变差，自动回退 Round61。
- 先做 offline candidate，不直接覆盖正式结果。

## 5. 验收指标

| 指标 | 要求 |
|---|---|
| site_mean_nrmse_6_19 | 优于 Round61 或不高于 +0.1pp |
| city_nrmse_6_19 | 不高于 Round61 +0.1pp |
| 10-14 city_nrmse | 不高于 Round61 |
| 7/17 bias_abs | 下降 |
| 变差 > +1pp 站点数 | 0 |

## 6. 风险

1. 数据质量限制：异常 0 值、停运、限电无法靠模型完全解决。
2. 辐照特征限制：没有地面实测辐照，局地云和遮挡难以完全建模。
3. 季节分布漂移：valid 与 test 季节不同。
4. 站点异质性：缺少屋顶类型、倾角、朝向等结构化信息。

## 7. 下一步

Round63 开始实现 offline 分场景 residual candidate，不覆盖 Round61 正式结果。
```

提交实验设计文档：

```bash
git add docs/Round62_模型结构实验设计.md
git commit -m "docs: add round62 model structure experiment design"
git push
```

---

## 十一、生成 Round62 执行报告

新增：

```text
docs/Round62_保存Round61稳定基线并准备模型结构实验报告.md
```

内容：

```markdown
# Round62 保存 Round61 稳定基线并准备模型结构实验报告

## 1. 本轮目标

## 2. Round61 验证结果

## 3. Git 提交信息

| 项目 | 值 |
|---|---|
| commit |  |
| tag | round61-stable-20260601 |
| branch |  |

## 4. baseline 文件清单

## 5. 是否提交大型产物

## 6. 实验分支

## 7. 模型结构实验设计摘要

## 8. 回退方式

```bash
git checkout round61-stable-20260601
```

## 9. 后续建议
```

提交：

```bash
git add docs/Round62_保存Round61稳定基线并准备模型结构实验报告.md
git commit -m "docs: record round62 baseline save report"
git push
```

---

## 十二、验收标准

```text
[PASS] Round61 audit-only 无真实 FAIL
[PASS] Round61 报告矛盾已修正
[PASS] round61_baseline_manifest.json 已生成
[PASS] round61_baseline_files.csv 已生成
[PASS] 未提交大型 pkl/parquet/joblib/npy 文件
[PASS] Git commit 已完成
[PASS] Git tag round61-stable-20260601 已推送
[PASS] experiment/model-structure-round62 分支已创建
[PASS] Round62 模型结构实验设计文档已提交
[PASS] 回退方式明确
```

