"""
compute_hourly_nrmse_consistent.py
================================
用统一口径重新计算逐小时站点 NRMSE。

口径（Round46确立，必须保持）：
  1. 测试集 split == "test"，小时 6-19
  2. 对每个 (site_id, hour) 分别计算 RMSE / capacity_mw × 100%
  3. 同一 hour 下，对所有站点的 NRMSE 取平均
  4. 城市 NRMSE 按全市同一小时总功率聚合后计算

这是训练后自动收口链路的核心一步。

此脚本是 round46_recompute_hourly_nrmse_consistent.py 的通用命名版本，
功能完全相同。round46 版本保留作为兼容性引用。

输出：
  - round46_site_hour_nrmse_consistent.csv   （站点×小时粒度的详细指标）
  - round46_hourly_nrmse_consistent.csv      （小时粒度的汇总指标）
  - interactive_dashboard/hourly_prediction_summary.json  （dashboard 直接读取）
"""

import sys
from pathlib import Path

# 实际调用 round46 版本（通用命名作为入口，round46 版本作为实现）
_script_dir = Path(__file__).parent.resolve()
_wrapper = _script_dir / "round46_recompute_hourly_nrmse_consistent.py"

if not _wrapper.exists():
    raise FileNotFoundError(
        f"compute_hourly_nrmse_consistent.py 依赖 "
        f"round46_recompute_hourly_nrmse_consistent.py，但后者不存在。"
    )

# 将本脚本的参数透传给 round46 版本执行
if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, str(_wrapper)] + sys.argv[1:],
        cwd=str(_script_dir.parent),
    )
    sys.exit(result.returncode)
