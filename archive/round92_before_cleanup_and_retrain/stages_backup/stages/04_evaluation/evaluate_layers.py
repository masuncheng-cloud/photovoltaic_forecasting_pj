from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths


def main():
    parser = build_parser('Evaluate layer metrics for pipeline v1.5.1')
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)
    inv = pd.read_csv(paths.metrics / 'inverse_metrics.csv')
    blend = pd.read_csv(paths.metrics / 'irradiance_blend_metrics.csv')
    # 优先读 v159 版本，否则 fallback
    dist_path = paths.metrics / 'distributed_metrics_v159.csv'
    if not dist_path.exists():
        dist_path = paths.metrics / 'distributed_metrics.csv'
    dist = pd.read_csv(dist_path)
    rows = []
    if not inv.empty:
        t = inv[inv['split'] == 'test'].iloc[0]
        rows.append({'stage': 'ERA5→集中式反演辐照', 'rmse': float(t['irr_rmse']), 'nrmse': float(t['irr_nrmse']), 'corr': float(t.get('irr_corr', np.nan))})
    if not blend.empty:
        t = blend[blend['split'] == 'test'].iloc[0]
        rows.append({'stage': '集中式反演辐照→全站点辐照融合', 'rmse': float(t['rmse_blend']), 'nrmse': float(t['nrmse_blend']), 'corr': np.nan})
    if not dist.empty:
        t = dist[dist['split'] == 'test'].iloc[0]
        rows.append({'stage': '全站点辐照融合→分布式功率估计(站点级)', 'rmse': float(t['rmse']), 'nrmse': float(t['nrmse']), 'corr': float(t.get('corr', np.nan))})
    out = pd.DataFrame(rows)
    out.to_csv(paths.metrics / 'layer_metrics_summary.csv', index=False, encoding='utf-8-sig')
    print(out)


if __name__ == '__main__':
    main()
