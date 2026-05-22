# Cursor + GitHub 协作完整方案（云服务器版）

## 一、目标

你的项目现在主要在 Cursor 连接的云服务器上运行，本地 Mac 没有代码。后续建议统一改成：

```text
GitHub public 仓库 = 代码主仓库
云服务器 Cursor = 开发、训练、生成结果的运行环境
Codex = 读取 GitHub 代码 + 读取你提交的轻量结果文件，给出分析和下一步修复方案
```

这样以后不需要反复上传完整 zip。

仓库地址：

```text
https://github.com/masuncheng-cloud/photovoltaic_forecasting_pj
```

---

## 二、云服务器首次 clone 项目

在 Cursor 云服务器终端执行：

```bash
cd /root/autodl-tmp
git clone https://github.com/masuncheng-cloud/photovoltaic_forecasting_pj.git
cd photovoltaic_forecasting_pj
```

如果提示目录已存在：

```bash
cd /root/autodl-tmp/photovoltaic_forecasting_pj
git status
git pull
```

---

## 三、推荐目录结构

建议项目保持如下结构：

```text
photovoltaic_forecasting_pj/
├── src/
├── scripts/
├── stages/
├── configs/
├── docs/
│   ├── 训练记录_xxx.md
│   ├── 当前结果_vs_周二基准对比.md
│   └── 修复说明_xxx.md
├── output/
│   └── pv_pipeline/
│       ├── metrics/
│       │   ├── *.csv
│       │   └── *.json
│       └── docs/
│           └── *.md
├── 光伏功率预测项目.md
├── README.md
└── .gitignore
```

---

## 四、哪些文件提交到 GitHub

### 4.1 建议提交

提交代码：

```text
src/
scripts/
stages/
configs/
requirements.txt
README.md
```

提交轻量结果：

```text
docs/*.md
output/pv_pipeline/docs/*.md
output/pv_pipeline/metrics/*.csv
output/pv_pipeline/metrics/*.json
光伏功率预测项目.md
```

这些文件我后续可以直接从 GitHub 查看，判断代码和结果是否一致。

### 4.2 不建议提交

不要提交大文件：

```text
*.zip
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/models/*.pkl
output/pv_pipeline/figures_dashboard/
data/
*.parquet
*.h5
*.joblib
```

原因：

- pkl/model/zip 太大，GitHub 不适合存；
- 大文件会导致 push 很慢，甚至失败；
- 模型和中间表可在云服务器重新生成。

---

## 五、配置 `.gitignore`

在项目根目录检查 `.gitignore`，建议至少包含：

```gitignore
# Python
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/

# OS
.DS_Store

# Env
.env
.venv/
venv/

# Data and large artifacts
data/
*.zip
*.tar
*.tar.gz
*.7z

# Large pipeline outputs
output/pv_pipeline/tables/
output/pv_pipeline/models/
output/pv_pipeline/figures_dashboard/
output/pv_pipeline/figures/

# Keep lightweight metrics/docs
!output/
!output/pv_pipeline/
!output/pv_pipeline/metrics/
!output/pv_pipeline/metrics/*.csv
!output/pv_pipeline/metrics/*.json
!output/pv_pipeline/docs/
!output/pv_pipeline/docs/*.md

# Logs
*.log
```

如果某些 CSV 特别大，也不要提交。

---

## 六、每次 Cursor 修改后的标准流程

### 6.1 查看改动

```bash
cd /root/autodl-tmp/photovoltaic_forecasting_pj
git status
git diff
```

### 6.2 运行后处理或训练

如果只改后处理：

```bash
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_chinese_metrics.py
python scripts/compare_with_week2_reference.py
python scripts/check_pipeline_consistency.py
```

如果要跑完整跳过训练流程：

```bash
python scripts/train_fixed.py --skip-training --data-root data --output-root output/pv_pipeline
```

如果确认需要完整训练：

```bash
python scripts/train_fixed.py --data-root data --output-root output/pv_pipeline
```

### 6.3 生成或更新报告

建议每次运行后至少更新：

```text
光伏功率预测项目.md
docs/训练记录_日期_主题.md
output/pv_pipeline/docs/当前最终结果摘要.md
output/pv_pipeline/metrics/当前结果_vs_周二基准_整体对比.csv
output/pv_pipeline/metrics/当前结果_vs_周二基准_逐小时NRMSE对比.csv
output/pv_pipeline/metrics/final_version_selection_by_hour.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
```

### 6.4 添加文件

推荐只添加代码、docs、metrics：

```bash
git add src scripts stages configs README.md requirements.txt .gitignore
git add docs
git add 光伏功率预测项目.md
git add output/pv_pipeline/docs
git add output/pv_pipeline/metrics
```

查看将要提交的文件：

```bash
git status
```

如果发现 `.pkl`、模型、zip 被加入，立刻取消：

```bash
git restore --staged output/pv_pipeline/tables
git restore --staged output/pv_pipeline/models
git restore --staged "*.zip"
```

### 6.5 提交

```bash
git commit -m "fix pv forecasting metrics and final selection"
```

建议 commit message 写清楚主题，例如：

```bash
git commit -m "fix final selection to avoid test leakage"
git commit -m "update round4 metrics report"
git commit -m "add week2 reference comparison"
```

### 6.6 推送到 GitHub

```bash
git push
```

如果首次 push 分支：

```bash
git push -u origin main
```

---

## 七、如果 GitHub push 失败

### 7.1 没有权限

如果报：

```text
Authentication failed
```

建议在云服务器配置 GitHub token 或 SSH。

HTTPS token 方式：

```bash
git remote set-url origin https://github.com/masuncheng-cloud/photovoltaic_forecasting_pj.git
```

push 时用户名填 GitHub 用户名，密码填 GitHub Personal Access Token。

SSH 方式：

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
cat ~/.ssh/id_ed25519.pub
```

把输出的公钥添加到 GitHub：

```text
GitHub -> Settings -> SSH and GPG keys -> New SSH key
```

然后改 remote：

```bash
git remote set-url origin git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git
```

测试：

```bash
ssh -T git@github.com
```

### 7.2 文件太大

如果报：

```text
File ... is larger than 100 MB
```

说明误提交了大文件。

取消暂存：

```bash
git restore --staged path/to/large_file
```

如果已经 commit 了但没 push：

```bash
git reset --soft HEAD~1
git restore --staged path/to/large_file
git commit -m "fix commit without large artifacts"
```

然后确认 `.gitignore` 已排除大文件。

---

## 八、以后给 Codex 分析时怎么说

以后你可以直接说：

```text
看 GitHub 最新代码：
https://github.com/masuncheng-cloud/photovoltaic_forecasting_pj

重点看 docs/训练记录_xxx.md 和 光伏功率预测项目.md，
分析和周二基准相比还有什么问题。
```

如果你已经把结果 CSV 和报告也 push 到 GitHub，我就能直接分析，不需要 zip。

如果结果文件没有 push，只能分析代码，不能准确判断训练结果。

---

## 九、建议每轮必须提交的最小结果集

每轮 Cursor 运行后，至少提交这些轻量文件：

```text
光伏功率预测项目.md
docs/训练记录_本轮.md
output/pv_pipeline/metrics/final_version_selection_by_hour.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/metrics/当前结果_vs_周二基准_整体对比.csv
output/pv_pipeline/metrics/当前结果_vs_周二基准_逐小时NRMSE对比.csv
output/pv_pipeline/docs/当前最终结果摘要.md
```

这样我可以判断：

- 当前最终选择了哪些版本；
- 整体 MAE/RMSE/ratio/bias 是否达标；
- 逐小时 NRMSE 是否改善；
- 当前报告是否和真实结果一致；
- 是否已经接近或超过周二基准。

---

## 十、云服务器完整操作模板

每轮可以直接复制下面这段执行：

```bash
cd /root/autodl-tmp/photovoltaic_forecasting_pj

# 1. 拉取 GitHub 最新代码
git pull

# 2. 查看状态
git status

# 3. 运行后处理
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_chinese_metrics.py
python scripts/compare_with_week2_reference.py
python scripts/check_pipeline_consistency.py

# 4. 可选：运行 skip-training 总流程
python scripts/train_fixed.py --skip-training --data-root data --output-root output/pv_pipeline

# 5. 查看核心结果
cat output/pv_pipeline/metrics/当前结果_vs_周二基准_整体对比.csv
cat output/pv_pipeline/metrics/final_version_selection_by_hour.csv

# 6. 添加轻量文件
git add src scripts stages configs README.md requirements.txt .gitignore
git add docs
git add 光伏功率预测项目.md
git add output/pv_pipeline/docs
git add output/pv_pipeline/metrics

# 7. 确认没有误加大文件
git status

# 8. 提交并推送
git commit -m "update pv forecasting pipeline and metrics"
git push
```

如果 `git commit` 提示 nothing to commit，说明没有新的文件变化，可以直接结束。

---

## 十一、重要提醒

不要把下面文件提交到 GitHub：

```text
*.zip
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/models/*.pkl
data/
```

如果确实需要保存大文件，建议单独用：

- 云服务器磁盘；
- 对象存储；
- 百度网盘/阿里云盘；
- Git LFS（不建议当前阶段使用，容易把仓库搞复杂）。

当前阶段最稳的是：

```text
GitHub 存代码 + 轻量 CSV/MD
云服务器存数据 + pkl + 模型
```

